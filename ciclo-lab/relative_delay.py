"""Delay-aware multi-horizon portfolios, moderate dispersion penalty.
Development 2022-23 only. Fixed hypotheses; no holdout, leverage or orders.
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
from robust_delay import replay,DELAYS

HORIZONS={"2h":(120,1.5),"4h":(240,2.5)}
WINDOWS=["expanding","365d"]
THRESHOLDS=[0.,.025]
NTEST=4*3

def target(tables):
    r=pd.concat({k:v.R for k,v in tables.items()},axis=1).dropna()
    a=pd.concat({k:v.available for k,v in tables.items()},axis=1).loc[r.index]
    assert a.notna().all().all()
    # Less restrictive than the minimum of hypothetical execution results.
    # No actual latency distribution is assumed.
    return pd.DataFrame(dict(R=r.mean(axis=1)-.5*r.std(axis=1,ddof=0),available=a.max(axis=1).astype("int64")),index=r.index)

def execution_tables(m,eligible,perp,mark,funding):
    out={}
    original=m.loc[eligible,["segment","atr1"]]
    for name,(horizon,stop) in HORIZONS.items():
        out[name]={}
        for delay in DELAYS:
            shift=pd.Timedelta(minutes=delay-1)
            z=original.copy();z["atr1"]*=stop/2.5;z.index=z.index+shift
            mask=pd.Series(True,index=z.index)
            out[name][delay]={}
            for cost,args in FEES.items():
                q=make_outcomes(z,mask,perp,mark,funding,horizon,*args)
                q.index=q.index-shift
                out[name][delay][cost]=q
    return out

def select(preds,threshold):
    p=pd.concat(preds,axis=1).sort_index()
    assert p.notna().all().all()
    # Deterministic tie break: first column, 2h. One proposed route per time.
    winners=p.idxmax(axis=1)
    return winners.loc[p.max(axis=1)>=threshold]

def portfolio(routes,ys,delay,cost):
    selected=[]
    for name in HORIZONS:
        ix=routes.index[routes==name]
        y=ys[name][delay][cost]
        selected.append(y.loc[y.index.isin(ix)])
    y=pd.concat(selected).sort_index()
    assert not y.index.has_duplicates
    return replay(pd.Series(1.,index=routes.index),y,1.,delay)

def lower(result):
    if not result["records"]:return None,0
    f=pd.DataFrame(result["records"]);f["month"]=pd.to_datetime(f.time,utc=True).dt.strftime("%Y-%m")
    b=f.groupby("month").R.agg(["sum","count"]);active=len(b)
    if active<12:return None,active
    b=b.reindex(pd.period_range("2022-01","2023-12",freq="M").astype(str),fill_value=0)
    rng=np.random.default_rng(20261126);i=rng.integers(0,len(b),size=(30000,len(b)))
    a=b["sum"].to_numpy()[i].sum(1);c=b["count"].to_numpy()[i].sum(1)
    return float(np.quantile(a[c>0]/c[c>0],.05/NTEST)),active

# Causal context normalization. Quantiles calculated from previous
# 30 complete calendar days of eligible scores, not future outcomes.
# Absolute floor prevents trading predicted material losses.
NTEST=12
def gate_scores(p,fraction):
    # Score history includes all eligible prediction times. Shift one decision
    # before quantile estimation, so the current observation is not used.
    q=p.rolling("30D",min_periods=1000,closed="left").quantile(1-fraction)
    return (p>=q)&(p>=-.025)&q.notna()
def selftest():
    from moderate_delay import selftest as test
    test()
    i=pd.date_range("2022-01-01",periods=3000,freq="15min",tz="UTC")
    p=pd.Series(np.sin(np.arange(len(i))/20)*.1,index=i)
    z=p.copy();z.iloc[2000:]=99
    pd.testing.assert_series_equal(gate_scores(p,.02).iloc[:2000],gate_scores(z,.02).iloc[:2000])
    assert not gate_scores(p,.02).iloc[:1000].any()
    print("Causal score normalization, warmup and future mutation PASS",flush=True)
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
    labels={k:target({i:v[i]["stress"] for i in DELAYS}) for k,v in ys.items()}
    # A single rolling-year predictor family; fixed variants of relative score
    # cutoff, selected without looking at each day's future price.
    preds={k:(predictions(x,y,"365d",fit_predict)+predictions(x,y,"365d",nonlinear))/2 for k,y in labels.items()}
    p=pd.concat(preds,axis=1).sort_index()
    best=p.max(axis=1)
    results={}
    for frac in [.01,.02,.05]:
        allowed=gate_scores(best,frac)
        r=p.idxmax(axis=1).loc[allowed]
        out={}
        for delay in DELAYS:
            out[str(delay)]={}
            for cost in FEES:
                q=portfolio(r,ys,delay,cost);lo,active=lower(q) if cost=="stress" else (None,None)
                row=dict(fraction=frac,delay=delay,cost=cost,n=q["n"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],adjustedLower=lo,activeMonths=active,unknown=q["unknown"],years=q["years"])
                print("RELATIVE="+json.dumps(row),flush=True)
                out[str(delay)][cost]=dict(summary=row,full=q)
        results[str(frac)]=out
    Path("lab-relative-delay.json").write_text(json.dumps(dict(period="2022-2023 development",results=results,limitations="18 replays. 30D trailing prediction quantile with 1000-score warmup, current excluded. Minimum expected score -.025 R; abstention possible. No guarantee of target signal frequency. 12-comparison conservative bound covers this batch only, not global search. All rules development-adaptive; no independent validation or release, no orders."),indent=2))
if __name__=="__main__":main()
