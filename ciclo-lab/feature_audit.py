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
# These are forensic diagnostics, not optimized trading policies.
def frame(d):
    m=signal_frames(d);reg=regimes(d,m);s=candidates(d,m)
    h=bars(d,60);h["a"]=atr(h);m["atr1"]=align(h,m,"a")
    x=features(d,m,reg,s);x["atr1_rel"]=m.atr1/m.close
    x["return4h"]=m.close/lag(m,"close",48)-1;x["return24h"]=m.close/lag(m,"close",288)-1
    return m,reg,x
def prefix_check(d,full,cuts):
    results=[]
    for cut in cuts:
        m,reg,x=frame(d.loc[d.index<cut])
        expected=full.loc[full.index<=cut]
        pd.testing.assert_index_equal(x.index,expected.index)
        pd.testing.assert_frame_equal(x,expected,check_exact=False,rtol=1e-10,atol=1e-12)
        results.append(dict(cut=str(cut),rows=len(x),columns=len(x.columns)))
    return results
def classify(m,x,reg,d):
    starts=d.index.to_series().groupby(d.segment,sort=False).first()
    start=m.segment.map(starts)
    age=(m.index.to_series()-start).dt.total_seconds()/3600
    return pd.DataFrame(dict(ageBand=pd.cut(age,[-np.inf,24,168,800,1440,np.inf],labels=["0-24h","1-7d","7-33d","33-60d","60d+"]).astype("string"),knownTrend=m.trend4h.notna(),regime=reg,complete=x.notna().all(axis=1),year=m.index.year),index=m.index)
def breakdown(q,context):
    f=pd.DataFrame(q["records"])
    if f.empty:return []
    f.index=pd.to_datetime(f.time,utc=True)
    f=f.join(context)
    if f.year.isna().any():raise ValueError("unmatched decision time")
    rows=[]
    for name in ["ageBand","knownTrend","regime","complete","year"]:
        for v,g in f.groupby([name,"year"] if name!="year" else ["year"],dropna=False):
            rows.append(dict(dimension=name,group=str(v),n=len(g),meanR=float(g.R.mean()),pnl=float(g.pnl.sum())))
    return rows
def selftest():
    from mixed_portfolio import selftest as test
    test()
    from market_frame import segments
    i=pd.date_range("2022-01-01",periods=60*72,freq="min",tz="UTC")
    rng=np.random.default_rng(42);c=100+np.cumsum(rng.normal(0,.01,len(i)));o=np.r_[c[0],c[:-1]];v=rng.uniform(1,10,len(i))
    d=segments(pd.DataFrame(dict(open=o,high=np.maximum(o,c)+.05,low=np.minimum(o,c)-.05,close=c,volume=v,quote=c*v,buy=v*.55),index=i).drop(i[100]))
    m,reg,x=frame(d);r=prefix_check(d,x,[i[2000],i[3000]])
    assert len(r)==2 and len(classify(m,x,reg,d))==len(m)
    print("Full feature prefix invariance and segment-age mapping PASS",flush=True)
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
    mm,rr,full=frame(d)
    pd.testing.assert_frame_equal(x,full.loc[x.index],check_exact=False,rtol=1e-10,atol=1e-12)
    cuts=[pd.Timestamp(t,tz="UTC") for t in ["2021-12-31 12:00","2022-06-15 12:00","2023-06-15 12:00"]]
    prefixes=prefix_check(d,full,cuts)
    print("CAUSAL_PREFIX="+json.dumps(prefixes),flush=True)
    ctx=classify(mm,full,rr,d)
    policies={"C01":pd.Series("4h",index=v4.index[v4>=1]),"M01":route(v4,x1,x2,"four_hour_priority")}
    results={}
    for name,r in policies.items():
        normal=replay(r,ys,"normal");stress=replay(r,ys,"stress")
        summary=dict(n=stress["n"],mean=stress["mean"],equity=stress["equity"],breakdown=breakdown(stress,ctx))
        print("GAP_DIAG="+json.dumps(dict(policy=name,**summary)),flush=True)
        filters={"known_trend":ctx.knownTrend,"known_regime":ctx.regime!="unknown","complete_features":ctx.complete}
        diagnostics={}
        for fname,mask in filters.items():
            z=r.loc[mask.reindex(r.index).fillna(False)]
            a=replay(z,ys,"normal");b=replay(z,ys,"stress")
            row=dict(policy=name,filter=fname,n=a["n"],mean=a["mean"],stressN=b["n"],stress=b["mean"],unknown=b["unknown"],years=b["years"],ci=b["ci"])
            diagnostics[fname]=dict(summary=row,normal=a,stress=b)
            print("GAP_ABLATION="+json.dumps(row),flush=True)
        results[name]=dict(baseline=summary,diagnostics=diagnostics)
    Path("lab-feature-audit.json").write_text(json.dumps(dict(prefixChecks=prefixes,results=results,limitations="Retrospective diagnostic only, full price/volume features tested for prefix invariance at three cutoffs; not proof of all availability timestamps. Fixed original signals; removing unknown contexts changes portfolio overlap, no retraining. OI publication times still assumed, derivative availability gate not independently verified. Not holdout or release."),indent=2))
if __name__=="__main__":main()
