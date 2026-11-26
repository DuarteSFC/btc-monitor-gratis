"""Batch screen: 108 configurations, 216 cost replays, development only.
Shared label generation; fixed grid before this run. No orders/production.
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

GRIDS=[15,30,60]
WINDOWS=["expanding","365d"]
THRESHOLDS=[0.,.025,.05,.075,.10,.15]
NTEST=108
def predictions(x,y,window,method):
    out=[]
    for cut in pd.date_range("2022-01-01","2023-10-01",freq="QS",tz="UTC"):
        end=cut+pd.offsets.QuarterBegin(startingMonth=1)
        valid=(y.index<cut)&(y.available<=cut.value)
        if window=="365d":valid&=y.index>=cut-pd.Timedelta(days=365)
        train=y.loc[valid];test=x.loc[(x.index>=cut)&(x.index<end)]
        if len(train)<300:raise ValueError("insufficient training")
        if len(test):out.append(pd.Series(method(x.loc[train.index],test,train.R.to_numpy()),index=test.index))
    return pd.concat(out)

def adjusted_ci(result):
    # Bonferroni-adjusted one-sided monthly bootstrap lower bound.
    # Exploratory, not valid independent evidence: historic experiments also selected this grid.
    if not result["records"]:return None,0
    f=pd.DataFrame(result["records"]);f["month"]=pd.to_datetime(f.time,utc=True).dt.strftime("%Y-%m")
    b=f.groupby("month").R.agg(["sum","count"])
    active=len(b)
    if active<12:return None,active
    b=b.reindex(pd.period_range("2022-01","2023-12",freq="M").astype(str),fill_value=0)
    rng=np.random.default_rng(20261126)
    i=rng.integers(0,len(b),size=(30000,len(b)))
    a=b["sum"].to_numpy()[i].sum(1);c=b["count"].to_numpy()[i].sum(1)
    return float(np.quantile(a[c>0]/c[c>0],.05/NTEST)),active

def selftest():
    from boost_futures import selftest as test
    test()
    r={"records":[{"time":"2022-01-01T00:00:00Z","R":1.}]}
    assert adjusted_ci(r)==(None,1)
    r={"records":[{"time":str(t),"R":.2} for t in pd.date_range("2022-01-01",periods=24,freq="MS",tz="UTC")]}
    low,n=adjusted_ci(r);assert n==24 and abs(low-.2)<1e-10
    assert len(GRIDS)*len(WINDOWS)*3*len(THRESHOLDS)==NTEST
    print("Multiplicity screen, active-month guard and configuration count PASS",flush=True)
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
    ys={k:make_outcomes(m,eligible,perp,mark,funding,240,*v) for k,v in FEES.items()}
    results={}
    for grid in GRIDS:
        xx=x.loc[x.index.minute%grid==0]
        yy={k:y.loc[y.index.isin(xx.index)] for k,y in ys.items()}
        for window in WINDOWS:
            preds={"ridge":predictions(xx,yy["stress"],window,fit_predict),"boost":predictions(xx,yy["stress"],window,nonlinear)}
            preds["ensemble"]=(preds["ridge"]+preds["boost"])/2
            for name,pred in preds.items():
                for th in THRESHOLDS:
                    normal=evaluate(pred,yy["normal"],th);stress=evaluate(pred,yy["stress"],th)
                    lower,active=adjusted_ci(stress)
                    passed=bool(normal["n"]>=150 and stress["n"]>=150 and not normal["unknown"] and not stress["unknown"] and normal["mean"]>=.05 and normal["pf"] is not None and normal["pf"]>=1.15 and lower is not None and lower>0 and len(stress["years"])==2 and all(v["n"]>=30 and v["mean"]>0 for v in stress["years"].values()))
                    key=f"{grid}:{window}:{name}:{th:.3f}"
                    row=dict(key=key,n=normal["n"],stressN=stress["n"],mean=normal["mean"],pf=normal["pf"],win=normal["win"],equity=normal["equity"],stress=stress["mean"],ci=stress["ci"],adjustedLower=lower,activeMonths=active,unknown=stress["unknown"],passed=passed)
                    results[key]=dict(summary=row,normal=normal,stress=stress)
                    print("BATCH="+json.dumps(row),flush=True)
    assert len(results)==NTEST
    Path("lab-batch-futures.json").write_text(json.dumps(dict(period="2022-2023 development only",models=results,limitations="108 correlated configurations, 216 cost replays; same 4h futures exits and funding; no leverage. One-sided monthly bootstrap lower bound adjusted for 108 configurations only, not prior experiments or data-dependent grid choices. Only 24 calendar blocks; not independent validation. Unknown PnL not fabricated and fails gate."),indent=2))
    print("BATCH_DONE="+json.dumps(dict(configs=len(results),positiveBoth=sum(1 for v in results.values() if v["summary"]["mean"] is not None and v["summary"]["stress"] is not None and v["summary"]["mean"]>0 and v["summary"]["stress"]>0),passes=sum(v["summary"]["passed"] for v in results.values()))),flush=True)
if __name__=="__main__":main()
