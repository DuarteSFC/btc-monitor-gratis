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
def selftest():
    from portfolio_screen import selftest as test
    test()
    i=pd.date_range("2022-01-01",periods=3,freq="15min",tz="UTC")
    v=pd.Series([1,0,2],index=i);x1=pd.Series([True,True,False],index=i);x2=pd.Series([True,False,True],index=i)
    assert route(v,x1,x2,"four_hour_priority").tolist()==["4h","2h15","4h"]
    assert route(v,x1,x2,"two_hour_priority").tolist()==["2h15","2h15","2h25"]
    assert route(v,x1,x2,"confirmed").tolist()==["2h15","4h"]
    a=route(v,x1,x2,"four_hour_priority")
    z=pd.DataFrame(dict(month="2022-01",session=0,trend="up",vol=0),index=i)
    assert control(a,z,42).value_counts().to_dict()==a.value_counts().to_dict()
    print("Mixed horizon routing and stratified randomized signal count parity PASS",flush=True)
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
    strata=pd.DataFrame(dict(month=mi.index.strftime("%Y-%m"),session=mi.index.hour//6,trend=mi.trend4h.astype("string").fillna("unknown"),vol=pd.cut(mi.atr1/mi.close,[-np.inf,.002,.005,.01,np.inf],labels=False)),index=mi.index)
    results={}
    for mode in MODES:
        r=route(v4,x1,x2,mode)
        assert r.index.isin(strata.index).all()
        normal=replay(r,ys,"normal");stress=replay(r,ys,"stress")
        lo,active=lower(stress)
        ctl=[]
        for seed in SEEDS:
            z=control(r,strata,seed);q=replay(z,ys,"stress")
            ctl.append(dict(seed=seed,n=q["n"],mean=q["mean"],unknown=q["unknown"]))
        validctl=[z["mean"] for z in ctl if z["mean"] is not None and not z["unknown"]]
        beat=len(validctl)==len(SEEDS) and stress["mean"] is not None and stress["mean"]>max(validctl)
        passed=bool(normal["n"]>=150 and stress["n"]>=150 and not normal["unknown"] and not stress["unknown"] and normal["mean"]>=.05 and normal["pf"] is not None and normal["pf"]>=1.15 and lo is not None and lo>0 and len(stress["years"])==2 and all(t["n"]>=30 and t["mean"]>0 for t in stress["years"].values()) and beat)
        row=dict(policy=mode,n=normal["n"],stressN=stress["n"],mean=normal["mean"],pf=normal["pf"],win=normal["win"],equity=normal["equity"],stress=stress["mean"],ci=stress["ci"],adjustedLower=lo,activeMonths=active,unknown=stress["unknown"],years=stress["years"],signalCounts=r.value_counts().to_dict(),controls=ctl,beatsControls=beat,passed=passed)
        results[mode]=dict(summary=row,normal=normal,stress=stress)
        print("MIXED="+json.dumps(row),flush=True)
    Path("lab-mixed-portfolio.json").write_text(json.dumps(dict(period="2022-2023 development",results=results,limitations="Six economic replays and 15 stress controls; candidates selected on development. Matched random by month/session/trend/ATR, signal count and horizon mix, not guaranteed executed trade count. Three policies; adjusted bound only within these policies. Shared funding proxy; one position; unknown exit locks 24h conservatively; no holdout or leverage."),indent=2))
if __name__=="__main__":main()
