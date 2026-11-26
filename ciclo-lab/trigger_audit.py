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
# Additional execution delay; decision features, trained predictions and
# original ATR remain frozen. No retuning.
DELAYS=[1,5,15,30]
def delayed(routes,m,perp,mark,funding,minutes,cost):
    shift=pd.Timedelta(minutes=minutes-1)
    outcome_tables={}
    for name,horizon,stop in [("4h",240,2.5),("2h15",120,1.5),("2h25",120,2.5)]:
        ix=routes.index[routes==name]
        original=m.loc[ix,["segment","atr1"]].copy()
        original["atr1"]*=stop/2.5
        # make_outcomes expects a minute-aligned decision time and enters one
        # minute later. Index moves, but ATR is from original decision.
        original.index=original.index+shift
        mask=pd.Series(True,index=original.index)
        if len(original):
            outcome_tables[name]={cost:make_outcomes(original,mask,perp,mark,funding,horizon,*FEES[cost])}
        else:
            outcome_tables[name]={cost:pd.DataFrame(columns=["R","riskFraction","exit","available","fundingR","fallback"],index=pd.DatetimeIndex([],tz="UTC"))}
    r=routes.copy();r.index=r.index+shift
    return replay(r,outcome_tables,cost)
# Fixed signal execution audit: trigger price and adverse same-minute fill.
# This is a conservative proxy, not a reconstruction of actual order book fills.
NS=60_000_000_000
def exit_proxy(t,v,mark_low,dt,atr1,h,fee,slip,ft,fr,fp,fb,mode):
    et=dt.value+NS;k=int(np.searchsorted(t,et))
    if k>=len(t) or t[k]!=et or k+h>len(t) or t[k+h-1]!=et+(h-1)*NS:return None
    if np.any(np.diff(t[k:k+h])!=NS):return None
    z=v[k:k+h]
    entry=z[0,0]*(1+slip);stop=entry-2.5*atr1
    if not 0<stop<entry:return None
    risk=entry*(1+fee)-stop*(1-slip)*(1-fee)
    trig=mark_low[k:k+h] if mode=="mark_low" else z[:,2]
    hits=np.flatnonzero(trig<=stop)
    j=int(hits[0]) if len(hits) else h-1
    # Missing mark before or during intended exit means unknown, even if a
    # later mark would have triggered. No fabricated zero PnL.
    if not np.isfinite(trig[:j+1]).all():return None
    out=z[j,2] if len(hits) else z[j,3]
    exit_open=t[k+j];exit_close=exit_open+NS
    a=int(np.searchsorted(ft,et,side="left"));b=int(np.searchsorted(ft,exit_close,side="left"))
    rate=fr[a:b];prices=fp[a:b];times=ft[a:b]
    if not np.isfinite(prices).all():return None
    charge=rate*prices
    charge=np.where((times>=exit_open)&(charge<0)&bool(len(hits)),0.,charge)
    funding=float(charge.sum())
    net=out*(1-slip)*(1-fee)-entry*(1+fee)-funding
    return dict(R=float(net/risk),riskFraction=float(risk/(entry*(1+fee))),fundingR=float(funding/risk),exit=int(exit_close),available=int(t[k+h-1]+NS),fallback=int(fb[a:b].sum()),reason="stop" if len(hits) else "timeout")
def proxy_tables(routes,m,perp,mark,funding,mode,cost):
    fee,slip=FEES[cost]
    t=perp.index.as_unit("ns").asi8
    v=perp[["open","high","low","close"]].to_numpy()
    ml=mark.low.reindex(perp.index).to_numpy()
    ft=funding.index.as_unit("ns").asi8;fr=funding.rate.to_numpy()
    prior=funding.index.floor("min")-pd.Timedelta(minutes=1)
    mk=mark.close.reindex(prior).to_numpy();px=perp.close.reindex(prior).to_numpy()
    fb=~np.isfinite(mk);fp=np.where(fb,px,mk)
    out={}
    for name,h,stop in [("4h",240,2.5),("2h15",120,1.5),("2h25",120,2.5)]:
        rows=[]
        for dt in routes.index[routes==name]:
            q=exit_proxy(t,v,ml,dt,float(m.at[dt,"atr1"])*stop/2.5,h,fee,slip,ft,fr,fp,fb,mode)
            if q is not None:rows.append(dict(time=dt,**q))
        y=pd.DataFrame(rows).set_index("time") if rows else pd.DataFrame(columns=["R","riskFraction","exit","available","fundingR","fallback","reason"],index=pd.DatetimeIndex([],tz="UTC"))
        out[name]={cost:y}
    return out
def selftest():
    from latency_audit import selftest as test
    test()
    i=pd.date_range("2022-01-01",periods=5,freq="min",tz="UTC")
    t=i.as_unit("ns").asi8
    v=np.array([[100,100,100,100],[100,101,99,100],[100,101,95,98],[98,99,97,98],[98,99,97,98]],float)
    mark=np.array([100,99,99,96,98],float)
    no=np.array([],dtype=float)
    a=exit_proxy(t,v,mark,i[0],1.,3,0.,0.,no,no,no,np.array([],dtype=bool),"trade_low")
    b=exit_proxy(t,v,mark,i[0],1.,3,0.,0.,no,no,no,np.array([],dtype=bool),"mark_low")
    assert a["exit"]==t[3] and b["exit"]==t[4] and a["R"]==-2. and b["R"]==-1.2
    mark[1]=np.nan
    assert exit_proxy(t,v,mark,i[0],1.,3,0.,0.,no,no,no,np.array([],dtype=bool),"mark_low") is None
    print("Trigger source, adverse fill, funding and missing mark guard PASS",flush=True)
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
    known=m.trend4h.notna()
    c=pd.Series("4h",index=v4.index[v4>=1]);r=route(v4,x1,x2,"four_hour_priority")
    policies={"C01-known":c.loc[known.reindex(c.index).fillna(False)],"M01-known":r.loc[known.reindex(r.index).fillna(False)]}
    results={}
    for name,r in policies.items():
        out={}
        for cost in FEES:
            base=replay(r,ys,cost)
            if cost=="stress":
                expected=138 if name=="C01-known" else 180
                assert base["n"]==expected
            for mode in ["baseline","trade_low","mark_low"]:
                q=base if mode=="baseline" else replay(r,proxy_tables(r,m,perp,mark,funding,mode,cost),cost)
                row=dict(policy=name,cost=cost,mode=mode,n=q["n"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],years=q["years"])
                print("TRIGGER="+json.dumps(row),flush=True)
                out[cost+":"+mode]=dict(summary=row,full=q)
        results[name]=out
    Path("lab-trigger-audit.json").write_text(json.dumps(dict(period="2022-2023 development",results=results,limitations="12 replays. Frozen original signals with known-trend gate. Baseline traded price stop approximates fill at stop or lower open. Alternative uses trade or mark trigger and traded minute low as adverse fill proxy; not worst possible market fill, no depth/ticks. Missing mark until intended exit -> unknown, equity excludes unknown and must fail gate. No leverage/liquidation modeling, no actual exchange parity, no independent validation."),indent=2))
if __name__=="__main__":main()
