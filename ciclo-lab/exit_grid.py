"""CICLO LAB: exit geometry research on futures with actual historical funding.
Development only. 54 configurations, 108 cost replays. No orders.
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

HORIZONS=[120,240,480]
STOPS=[1.5,2.5,4.]
THRESHOLDS=[0.,.05,.10]
NTEST=54

def bound(result):
    if not result["records"]:return None,0
    f=pd.DataFrame(result["records"]);f["month"]=pd.to_datetime(f.time,utc=True).dt.strftime("%Y-%m")
    b=f.groupby("month").R.agg(["sum","count"]);active=len(b)
    if active<12:return None,active
    b=b.reindex(pd.period_range("2022-01","2023-12",freq="M").astype(str),fill_value=0)
    rng=np.random.default_rng(20261126);i=rng.integers(0,len(b),size=(30000,len(b)))
    a=b["sum"].to_numpy()[i].sum(1);c=b["count"].to_numpy()[i].sum(1)
    return float(np.quantile(a[c>0]/c[c>0],.05/NTEST)),active

def selftest():
    from hurdle_futures import selftest as test
    test()
    assert len(HORIZONS)*len(STOPS)*len(THRESHOLDS)*2==NTEST
    assert bound({"records":[]})==(None,0)
    print("Exit grid dimensions and confidence guard PASS",flush=True)

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
    results={}
    for horizon in HORIZONS:
        for stop in STOPS:
            # Shared executor fixes stop at 2.5 * atr1. Scale only the execution
            # column; keep the original ATR in predictive features.
            execm=m.assign(atr1=m.atr1*(stop/2.5))
            ys={k:make_outcomes(execm,eligible,perp,mark,funding,horizon,*v) for k,v in FEES.items()}
            pr=predictions(x,ys["stress"],"expanding",fit_predict)
            pb=predictions(x,ys["stress"],"expanding",nonlinear)
            ph=hurdle_predict(x,ys["stress"],"expanding","tree").score
            for name,pred in [("ensemble",(pr+pb)/2),("hurdle_tree",ph)]:
                for th in THRESHOLDS:
                    normal=evaluate(pred,ys["normal"],th);stress=evaluate(pred,ys["stress"],th)
                    low,active=bound(stress)
                    passed=bool(normal["n"]>=150 and stress["n"]>=150 and not normal["unknown"] and not stress["unknown"] and normal["mean"]>=.05 and normal["pf"] is not None and normal["pf"]>=1.15 and low is not None and low>0 and len(stress["years"])==2 and all(v["n"]>=30 and v["mean"]>0 for v in stress["years"].values()))
                    key=f"{horizon}:{stop:.1f}:{name}:{th:.2f}"
                    row=dict(key=key,n=normal["n"],stressN=stress["n"],mean=normal["mean"],pf=normal["pf"],win=normal["win"],equity=normal["equity"],stress=stress["mean"],ci=stress["ci"],adjustedLower=low,activeMonths=active,unknown=stress["unknown"],passed=passed)
                    results[key]=dict(summary=row,normal=normal,stress=stress)
                    print("EXIT_GRID="+json.dumps(row),flush=True)
    assert len(results)==NTEST
    Path("lab-exit-grid.json").write_text(json.dumps(dict(period="2022-2023 development only",models=results,limitations="54 correlated configs, 108 cost replays. Training stress labels regenerated for each stop/horizon. Same 15m grid, spot features with derivative coverage gate. Futures funding approximation and execution assumptions inherited. No leverage. Bonferroni only within batch; monthly bootstrap exploratory. No independent holdout used."),indent=2))
    print("EXIT_DONE="+json.dumps(dict(configs=len(results),positiveBoth=sum(1 for v in results.values() if v["summary"]["mean"] is not None and v["summary"]["stress"] is not None and v["summary"]["mean"]>0 and v["summary"]["stress"]>0),passes=sum(v["summary"]["passed"] for v in results.values()))),flush=True)
if __name__=="__main__":main()
