"""Train against adverse entry delays rather than optimize one exact fill.
Predeclared development experiment. No holdout, leverage or orders.
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

DELAYS=[1,5,15]
THRESHOLDS=[0.,.05]
def robust_labels(tables):
    # All labels indexed by original signal time. Require every execution
    # scenario and make the target available only after the latest horizon.
    r=pd.concat({k:v.R for k,v in tables.items()},axis=1).dropna()
    a=pd.concat({k:v.available for k,v in tables.items()},axis=1).loc[r.index]
    assert a.notna().all().all()
    return pd.DataFrame(dict(R=r.min(axis=1),available=a.max(axis=1).astype("int64")),index=r.index)

def execution_tables(m,eligible,perp,mark,funding):
    out={}
    original=m.loc[eligible,["segment","atr1"]]
    for delay in DELAYS:
        shift=pd.Timedelta(minutes=delay-1)
        z=original.copy();z.index=z.index+shift
        mask=pd.Series(True,index=z.index)
        out[delay]={}
        for cost,args in FEES.items():
            q=make_outcomes(z,mask,perp,mark,funding,240,*args)
            q.index=q.index-shift
            out[delay][cost]=q
    return out

def replay(pred,y,threshold,delay):
    shift=pd.Timedelta(minutes=delay-1)
    p=pred.copy();p.index=p.index+shift
    z=y.copy();z.index=z.index+shift
    return evaluate(p,z,threshold)

def selftest():
    from hurdle_futures import selftest as test
    test()
    i=pd.date_range("2022-01-01",periods=3,freq="15min",tz="UTC")
    a=pd.DataFrame(dict(R=[.2,.3,.4],available=i.asi8+300*60_000_000_000),index=i)
    b=a.copy();b.R=[.1,.5,-.4];b.available+=60_000_000_000
    c=robust_labels({1:a,5:b.iloc[:2],15:b})
    assert c.R.tolist()==[.1,.3] and c.available.tolist()==b.available.iloc[:2].tolist()
    print("Robust target worst-case, complete scenario coverage and latest availability PASS",flush=True)

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
    ys=execution_tables(m,eligible,perp,mark,funding)
    y=robust_labels({k:ys[k]["stress"] for k in DELAYS})
    assert y.index.isin(x.index).all()
    print("ROBUST_LABELS="+json.dumps(dict(candidates=len(x),complete=len(y),positive=float((y.R>0).mean()))),flush=True)
    preds={"ensemble":(predictions(x,y,"expanding",fit_predict)+predictions(x,y,"expanding",nonlinear))/2,"hurdle":hurdle_predict(x,y,"expanding","tree").score}
    results={}
    for name,pred in preds.items():
        for th in THRESHOLDS:
            key=f"{name}:{th:.2f}";out={}
            for delay in DELAYS:
                out[str(delay)]={}
                for cost in FEES:
                    q=replay(pred,ys[delay][cost],th,delay)
                    row=dict(key=key,delay=delay,cost=cost,n=q["n"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],years=q["years"])
                    print("ROBUST="+json.dumps(row),flush=True)
                    out[str(delay)][cost]=q
            # This is deliberately a screen, not an adjusted test or release gate.
            stress=[v["stress"] for v in out.values()]
            viable=all(v["n"]>=150 and not v["unknown"] and v["mean"] is not None and v["mean"]>0 for v in stress)
            results[key]=dict(scenarios=out,passesDelayScreen=viable)
            print("ROBUST_SUMMARY="+json.dumps(dict(key=key,passesDelayScreen=viable)),flush=True)
    Path("lab-robust-delay.json").write_text(json.dumps(dict(period="2022-2023 development",labels=len(y),results=results,limitations="24 replays; target is minimum per-trade net R across three hypothetical stress fills, not expected actual fill. Horizon starts after each delayed entry. Common label support; evaluation includes unknowns. Quarterly chronological training; selected development hypothesis after latency audit. No adjusted significance, no independent validation, no live trading."),indent=2))
if __name__=="__main__":main()
