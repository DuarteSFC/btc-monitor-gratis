"""CICLO LAB: frozen multi-model portfolio screen, development 2022-23.
Combine already archived strategies, not independent evidence. No live orders.
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

# Fixed strategies preserved in EVIDENCE before this portfolio experiment.
# P01, G01, and batch 60m expanding ensemble; additional rolling ensemble.
NAMES=["P01","G01","E60","E15"]
POLICIES=["union","two_votes","three_votes"]
def votes(preds):
    # No forward fill: only new completed signals at the same decision time.
    v=pd.concat(preds,axis=1).fillna(False).astype(bool)
    return v.sum(axis=1).sort_index()
def lower(result):
    if not result["records"]:return None,0
    f=pd.DataFrame(result["records"]);f["month"]=pd.to_datetime(f.time,utc=True).dt.strftime("%Y-%m")
    b=f.groupby("month").R.agg(["sum","count"]);active=len(b)
    if active<12:return None,active
    b=b.reindex(pd.period_range("2022-01","2023-12",freq="M").astype(str),fill_value=0)
    rng=np.random.default_rng(20261126);i=rng.integers(0,len(b),size=(30000,len(b)))
    a=b["sum"].to_numpy()[i].sum(1);c=b["count"].to_numpy()[i].sum(1)
    return float(np.quantile(a[c>0]/c[c>0],.05/3)),active
def selftest():
    from hurdle_futures import selftest as test
    test()
    idx=pd.date_range("2022-01-01",periods=3,freq="15min",tz="UTC")
    a=pd.Series([True,False,True],index=idx)
    b=pd.Series([True],index=idx[:1])
    v=votes({"a":a,"b":b})
    assert v.tolist()==[2,0,1] and lower({"records":[]})==(None,0)
    print("Portfolio simultaneous votes, no carry-forward and confidence guard PASS",flush=True)
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
    y=ys["stress"];xh=x.loc[x.index.minute==0];yh=y.loc[y.index.isin(xh.index)]
    p01=hurdle_predict(x,y,"expanding","tree").score
    g01=predictions(xh,yh,"expanding",nonlinear)
    e60=(predictions(xh,yh,"expanding",fit_predict)+g01)/2
    e15=(predictions(x,y,"365d",fit_predict)+predictions(x,y,"365d",nonlinear))/2
    signals={"P01":p01>=.05,"G01":g01>=.05,"E60":e60>=0.,"E15":e15>=.05}
    v=votes(signals);results={};individual={}
    for name,p in signals.items():
        normal=evaluate(p.astype(float),ys["normal"],1.);stress=evaluate(p.astype(float),ys["stress"],1.)
        individual[name]=dict(n=normal["n"],mean=normal["mean"],stress=stress["mean"])
    print("PORT_INDIVIDUAL="+json.dumps(individual),flush=True)
    for count,name in enumerate(POLICIES,1):
        normal=evaluate(v.astype(float),ys["normal"],float(count))
        stress=evaluate(v.astype(float),ys["stress"],float(count))
        lo,active=lower(stress)
        passed=bool(normal["n"]>=150 and stress["n"]>=150 and not normal["unknown"] and not stress["unknown"] and normal["mean"]>=.05 and normal["pf"] is not None and normal["pf"]>=1.15 and lo is not None and lo>0 and len(stress["years"])==2 and all(t["n"]>=30 and t["mean"]>0 for t in stress["years"].values()))
        row=dict(policy=name,n=normal["n"],stressN=stress["n"],mean=normal["mean"],pf=normal["pf"],win=normal["win"],equity=normal["equity"],stress=stress["mean"],ci=stress["ci"],adjustedLower=lo,activeMonths=active,unknown=stress["unknown"],passed=passed)
        results[name]=dict(summary=row,normal=normal,stress=stress)
        print("PORT="+json.dumps(row),flush=True)
    Path("lab-portfolio-screen.json").write_text(json.dumps(dict(period="2022-2023 development",individual=individual,signals={k:int(p.sum()) for k,p in signals.items()},votes=v.value_counts().to_dict(),results=results,limitations="Models selected after inspecting development; not independent. Votes may share features and labels; no assumption of independence. One position, same 4h futures execution and funding approximation. Three policies, multiplicity adjustment only within these policies. No holdout accessed."),indent=2))
if __name__=="__main__":main()
