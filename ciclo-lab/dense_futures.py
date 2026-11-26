"""15-minute decision grid, 4h futures execution. Development-only.
Compare linear/nonlinear/ensemble using pre-fixed thresholds and rank diagnostics.
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
from boost_futures import nonlinear,predict

THRESHOLDS=[.05,.10]
def rank_audit(pred,y):
    # Descriptive predictive ranking, not a portfolio; overlapping labels.
    known=y.R.reindex(pred.index)
    a=pd.DataFrame({"score":pred,"R":known}).dropna()
    if a.empty:return {}
    a["bin"]=pd.qcut(a.score,5,duplicates="drop")
    bins=[dict(low=float(g.score.min()),high=float(g.score.max()),n=len(g),meanR=float(g.R.mean()),win=float((g.R>0).mean())) for _,g in a.groupby("bin",observed=True)]
    return dict(n=len(a),unknown=int(pred.size-len(a)),rankCorrelation=float(a.score.rank().corr(a.R.rank())),bins=bins)

def selftest():
    from boost_futures import selftest as test
    test()
    idx=pd.date_range("2022-01-01",periods=100,freq="15min",tz="UTC")
    z=pd.Series(np.arange(100.),index=idx)
    a=rank_audit(z,pd.DataFrame({"R":z}))
    assert a["n"]==100 and abs(a["rankCorrelation"]-1)<1e-8 and a["bins"][-1]["meanR"]>a["bins"][0]["meanR"]
    print("Ranking audit and 15m model imports PASS",flush=True)

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
    y={k:make_outcomes(m,eligible,perp,mark,funding,240,*v) for k,v in FEES.items()}
    predictions={"ridge":predict(x,y["stress"],fit_predict),"boost":predict(x,y["stress"],nonlinear)}
    predictions["ensemble"]=(predictions["ridge"]+predictions["boost"])/2
    results={};audits={}
    for name,pred in predictions.items():
        audits[name]=rank_audit(pred,y["stress"])
        print("RANK="+json.dumps(dict(model=name,**audits[name])),flush=True)
        for th in THRESHOLDS:
            normal=evaluate(pred,y["normal"],th);stress=evaluate(pred,y["stress"],th)
            passed=bool(normal["n"]>=150 and stress["n"]>=150 and not normal["unknown"] and not stress["unknown"] and normal["mean"]>=.05 and normal["pf"] is not None and normal["pf"]>=1.15 and stress["ci"][0]>0 and len(stress["years"])==2 and all(v["n"]>=30 and v["mean"]>0 for v in stress["years"].values()))
            key=f"{name}:{th:.2f}"
            results[key]=dict(normal=normal,stress=stress,screenPass=passed)
            print("DENSE="+json.dumps(dict(key=key,n=normal["n"],mean=normal["mean"],pf=normal["pf"],win=normal["win"],equity=normal["equity"],stress=stress["mean"],ci=stress["ci"],unknown=stress["unknown"],passed=passed)),flush=True)
    Path("lab-dense-futures.json").write_text(json.dumps(dict(period="2022-2023 development only",eligible=int(eligible.sum()),models=results,audits=audits,limitations="Six correlated configurations; 15m decision grid, 4h execution; overlapping training labels day-weighted, one position in portfolio. Rank bins descriptive on all hypothetical known outcomes, not deployable trading strategies or independent observations. Same funding assumptions, spot features, derivative coverage gate. No holdout accessed."),indent=2))
if __name__=="__main__":main()
