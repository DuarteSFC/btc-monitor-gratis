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

def selftest():
    from robust_delay import selftest as test
    test()
    i=pd.date_range("2022-01-01",periods=3,freq="15min",tz="UTC")
    a=pd.DataFrame(dict(R=[.2,.3,.4],available=i.asi8+300*60_000_000_000),index=i)
    b=a.copy();b.R=[.1,.5,-.4];b.available+=60_000_000_000
    c=target({1:a,5:b.iloc[:2],15:b})
    np.testing.assert_allclose(c.R.to_numpy(),np.array([.2,.3])+np.array([-.1,.2])*2/3-.5*np.array([.1,.2])*np.sqrt(2)/3)
    assert c.available.tolist()==b.available.iloc[:2].tolist()
    s=select({"2h":pd.Series([.1,-.1,.2],index=i),"4h":pd.Series([.1,-.2,.3],index=i)},0.)
    assert s.tolist()==["2h","4h"] and lower({"records":[]})==(None,0)
    print("Moderate penalty, complete availability, deterministic horizon routing and confidence guard PASS",flush=True)

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
    for k,y in labels.items():
        assert y.index.isin(x.index).all()
        print("MODERATE_LABELS="+json.dumps(dict(horizon=k,n=len(y),positive=float((y.R>0).mean()))),flush=True)
    results={}
    for window in WINDOWS:
        preds={k:(predictions(x,y,window,fit_predict)+predictions(x,y,window,nonlinear))/2 for k,y in labels.items()}
        for th in THRESHOLDS:
            key=f"{window}:{th:.3f}";r=select(preds,th);out={}
            for delay in DELAYS:
                out[str(delay)]={}
                for cost in FEES:
                    q=portfolio(r,ys,delay,cost);lo,active=lower(q) if cost=="stress" else (None,None)
                    row=dict(key=key,delay=delay,cost=cost,n=q["n"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],adjustedLower=lo,activeMonths=active,unknown=q["unknown"],years=q["years"])
                    print("MODERATE="+json.dumps(row),flush=True)
                    out[str(delay)][cost]=dict(summary=row,full=q)
            screen=all(v["stress"]["summary"]["n"]>=150 and not v["stress"]["summary"]["unknown"] and v["stress"]["summary"]["adjustedLower"] is not None and v["stress"]["summary"]["adjustedLower"]>0 and len(v["stress"]["summary"]["years"])==2 and all(t["n"]>=30 and t["mean"]>0 for t in v["stress"]["summary"]["years"].values()) and v["normal"]["summary"]["n"]>=150 and not v["normal"]["summary"]["unknown"] and v["normal"]["summary"]["mean"]>=.05 and v["normal"]["summary"]["pf"] is not None and v["normal"]["summary"]["pf"]>=1.15 for v in out.values())
            results[key]=dict(scenarios=out,passesScreen=screen)
            print("MODERATE_SUMMARY="+json.dumps(dict(key=key,signals=r.value_counts().to_dict(),passesScreen=screen)),flush=True)
    Path("lab-moderate-delay.json").write_text(json.dumps(dict(period="2022-2023 development",labels={k:len(v) for k,v in labels.items()},results=results,limitations="4 portfolios, 24 replays. Target mean of three stress R outcomes minus half their population standard deviation; hypothetical, not observed latency distribution. Quarterly chronological training with latest availability, deterministic one-route choice, one concurrent position. Bonferroni 12 stress comparisons within batch only. Development-adaptive, no independent validation or release, no orders."),indent=2))
if __name__=="__main__":main()
