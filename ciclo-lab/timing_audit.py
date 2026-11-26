"""Mixed 2h/4h portfolio, one position, matched random controls.
Development only. All candidates frozen in prior research; no holdout or orders.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,bars,atr,align,lag
from flow_families import load_flow
from regime_router import regimes,candidates
from ridge_router import features,fit_predict
from derivative_screen import load,derivative_features
from hourly_futures import make_outcomes,evaluate,FEES
from boost_futures import nonlinear
from batch_futures import predictions
from hurdle_futures import predict as hurdle_predict
from portfolio_screen import votes

MODES=["four_hour_priority","two_hour_priority","confirmed"]
SEEDS=[101,202,303,404,505]
def route(v4,x1,x2,mode):
    a=pd.concat([v4.rename("v4"),x1.rename("x1"),x2.rename("x2")],axis=1).fillna(0).sort_index()
    out=pd.Series("",index=a.index,dtype="object")
    if mode=="four_hour_priority":
        out.loc[a.x2>0]="2h25";out.loc[a.x1>0]="2h15";out.loc[a.v4>=1]="4h"
    elif mode=="two_hour_priority":
        out.loc[a.v4>=1]="4h";out.loc[a.x2>0]="2h25";out.loc[a.x1>0]="2h15"
    else:
        out.loc[(a.x1>0)&(a.x2>0)]="2h15";out.loc[a.v4>=2]="4h"
    return out.loc[out!=""]
def replay(routes,ys,cost):
    selected=[]
    for name in ["4h","2h15","2h25"]:
        ix=routes.index[routes==name]
        y=ys[name][cost]
        selected.append(y.loc[y.index.isin(ix)])
    y=pd.concat(selected).sort_index()
    assert not y.index.has_duplicates
    return evaluate(pd.Series(1.,index=routes.index),y,1.)
def control(routes,strata,seed):
    rng=np.random.default_rng(seed)
    out=pd.Series("",index=strata.index,dtype="object")
    for _,g in strata.groupby(["month","session","trend","vol"],dropna=False):
        selected=routes.reindex(g.index).dropna()
        n=len(selected)
        if not n:continue
        ix=rng.choice(g.index,size=n,replace=False)
        out.loc[ix]=rng.permutation(selected.to_numpy())
    out=out.loc[out!=""]
    assert out.value_counts().to_dict()==routes.value_counts().to_dict()
    return out
def lower(result):
    if not result["records"]:return None,0
    f=pd.DataFrame(result["records"]);f["month"]=pd.to_datetime(f.time,utc=True).dt.strftime("%Y-%m")
    b=f.groupby("month").R.agg(["sum","count"]);active=len(b)
    if active<12:return None,active
    b=b.reindex(pd.period_range("2022-01","2023-12",freq="M").astype(str),fill_value=0)
    rng=np.random.default_rng(20261126);i=rng.integers(0,len(b),size=(30000,len(b)))
    a=b["sum"].to_numpy()[i].sum(1);c=b["count"].to_numpy()[i].sum(1)
    return float(np.quantile(a[c>0]/c[c>0],.05/len(MODES))),active
N_RANDOM=1999
NS=60_000_000_000
def shift_options(routes,eligible):
    # Circular day offsets within each calendar month. All shifted decisions
    # must be eligible; no future trade outcome is used to choose the offset.
    groups=[];valid=set(eligible.as_unit("ns").asi8.tolist())
    for month,g in routes.groupby(routes.index.strftime("%Y-%m")):
        ts=g.index;days=ts.days_in_month[0];base=ts.as_unit("ns").asi8
        one=1440*NS
        day=(ts.day.to_numpy(dtype=np.int64)-1)
        options=[]
        for k in range(days):
            shift=((day+k)%days-day)*one
            shifted=base+shift
            if all(int(z) in valid for z in shifted):options.append(shifted)
        assert options and np.array_equal(options[0],base)
        groups.append((month,np.stack(options),g.to_numpy()))
    return groups
def prepare(ys):
    return {name:{int(t.value):(float(r.R),float(r.riskFraction),int(r.exit)) for t,r in y["stress"].iterrows()} for name,y in ys.items()}
def fast_replay(times,names,lookup):
    last=-1;equity=10000.;unknown=0;rs=[]
    for i in np.argsort(times):
        t=int(times[i])
        if t+NS<last:continue
        row=lookup[names[i]].get(t)
        if row is None:
            unknown+=1;last=t+1441*NS;continue
        r,risk,exit=row
        equity=max(0.,equity+min(.0025*equity,equity*risk)*r)
        rs.append(r);last=exit
    return dict(n=len(rs),unknown=unknown,mean=float(np.mean(rs)) if rs else None,ret=(equity-10000)/10000)
def test_policy(routes,eligible,ys,lookup,seed):
    actual=replay(routes,ys,"stress")
    t=routes.index.as_unit("ns").asi8;v=routes.to_numpy()
    a=fast_replay(t,v,lookup)
    assert a["n"]==actual["n"] and a["unknown"]==actual["unknown"]
    assert abs(a["mean"]-actual["mean"])<1e-10 and abs(a["ret"]-(actual["equity"]-10000)/10000)<1e-10
    groups=shift_options(routes,eligible);rng=np.random.default_rng(seed)
    draws=[]
    for _ in range(N_RANDOM):
        times=np.concatenate([opts[rng.integers(len(opts))] for _,opts,_ in groups])
        names=np.concatenate([names for _,_,names in groups])
        draws.append(fast_replay(times,names,lookup))
    good=[q for q in draws if not q["unknown"] and q["mean"] is not None]
    # Do not silently discard unknown controls: fail inferential reporting if
    # any random draw has an unknown outcome.
    valid=len(good)==N_RANDOM and a["unknown"]==0
    pmean=(1+sum(q["mean"]>=a["mean"] for q in good))/(1+len(good)) if valid else None
    pret=(1+sum(q["ret"]>=a["ret"] for q in good))/(1+len(good)) if valid else None
    summary=dict(actual=a,draws=N_RANDOM,valid=len(good),months=len(groups),movableMonths=sum(len(opts)>1 for _,opts,_ in groups),options={m:len(opts) for m,opts,_ in groups},pMean=pmean,pReturn=pret,pMeanAdjusted=min(1.,pmean*2) if pmean is not None else None,pReturnAdjusted=min(1.,pret*2) if pret is not None else None,controlMeanQuantiles=np.quantile([q["mean"] for q in good],[.025,.5,.975]).tolist() if good else None,controlReturnQuantiles=np.quantile([q["ret"] for q in good],[.025,.5,.975]).tolist() if good else None,controlNQuantiles=np.quantile([q["n"] for q in good],[.025,.5,.975]).tolist() if good else None)
    return dict(summary=summary,draws=draws)
def selftest():
    from mixed_portfolio import selftest as test
    test()
    i=pd.date_range("2022-01-01",periods=31*24*4,freq="15min",tz="UTC")
    r=pd.Series(["4h","2h15"],index=i[[0,5]])
    g=shift_options(r,i)
    assert len(g)==1 and len(g[0][1])==31 and np.all(g[0][1][:,1]-g[0][1][:,0]==75*NS)
    lookup={"4h":{int(i[0].value):(.2,.01,int(i[16].value))},"2h15":{}}
    q=fast_replay(r.index.as_unit("ns").asi8,r.to_numpy(),lookup)
    assert q["n"]==1 and q["unknown"]==0 and abs(q["ret"]-.0005)<1e-10
    print("Cluster-preserving calendar randomization and fast replay PASS",flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")];d=load_flow(a.dataset,d)
    m=signal_frames(d);reg=regimes(d,m);s=candidates(d,m)
    h=bars(d,60);h["a"]=atr(h);m["atr1"]=align(h,m,"a")
    perp,mark,metrics,funding=[load(a.derivatives,k) for k in ["perp","mark","metrics","funding"]]
    deriv=derivative_features(m,perp,mark,metrics,funding,30)
    eligible=(m.index.minute%15==0)&(m.index.year>=2021)&m.atr1.notna()&(m.atr1>0)&deriv[["basis","oi_change15","oi_change60","funding"]].notna().all(axis=1)&(m.index<pd.Timestamp("2023-12-31",tz="UTC"))
    x=features(d,m,reg,s);x["atr1_rel"]=m.atr1/m.close
    x["return4h"]=m.close/lag(m,"close",48)-1;x["return24h"]=m.close/lag(m,"close",288)-1
    x=x.loc[eligible]
    ys={}
    for name,horizon,stop in [("4h",240,2.5),("2h15",120,1.5),("2h25",120,2.5)]:
        ex=m.assign(atr1=m.atr1*(stop/2.5))
        ys[name]={k:make_outcomes(ex,eligible,perp,mark,funding,horizon,*v) for k,v in FEES.items()}
    y=ys["4h"]["stress"];xh=x.loc[x.index.minute==0];yh=y.loc[y.index.isin(xh.index)]
    p01=hurdle_predict(x,y,"expanding","tree").score
    g01=predictions(xh,yh,"expanding",nonlinear)
    e60=(predictions(xh,yh,"expanding",fit_predict)+g01)/2
    e15=(predictions(x,y,"365d",fit_predict)+predictions(x,y,"365d",nonlinear))/2
    v4=votes({"P01":p01>=.05,"G01":g01>=.05,"E60":e60>=0.,"E15":e15>=.05})
    x1=hurdle_predict(x,ys["2h15"]["stress"],"expanding","tree").score>=0
    y2=ys["2h25"]["stress"]
    x2=(predictions(x,y2,"expanding",fit_predict)+predictions(x,y2,"expanding",nonlinear))/2>=0
    old=evaluate(v4.astype(float),ys["4h"]["normal"],1.)
    oldx=evaluate(x1.astype(float),ys["2h15"]["normal"],1.)
    oldx2=evaluate(x2.astype(float),ys["2h25"]["normal"],1.)
    assert old["n"]==156 and abs(old["mean"]-.07676540904536851)<1e-8
    assert oldx["n"]==109 and abs(oldx["mean"]-.09267658442312403)<1e-8
    assert oldx2["n"]==63 and abs(oldx2["mean"]-.0817391130725489)<1e-8
    print("MIXED_PARITY="+json.dumps(dict(C01=old["n"],X01=oldx["n"],X02=oldx2["n"])),flush=True)
    mi=m.loc[x.index];mi=mi.loc[mi.index.year>=2022]
    lookup=prepare(ys)
    c01=pd.Series("4h",index=v4.index[v4>=1])
    policies={"C01":c01,"M01":route(v4,x1,x2,"four_hour_priority")}
    results={}
    for i,(name,r) in enumerate(policies.items()):
        results[name]=test_policy(r,mi.index,ys,lookup,20261126+i)
        print("TIMING="+json.dumps(dict(policy=name,**results[name]["summary"])),flush=True)
    Path("lab-timing-audit.json").write_text(json.dumps(dict(period="2022-2023 development",results=results,limitations="Conditional circular within-month day rotations preserve signal clock, clustering within days and horizon mix; not exact market regime or executed trade count. Exchangeability not guaranteed, only selected development policies; p-values exploratory, two-policy adjustment only, not global selection correction. No holdout. Same funding approximation; no live orders."),indent=2))
if __name__=="__main__":main()
