"""Calendar-independent validation primitives. No holdout data access.
Only synthetic tests and parity on archived development trades in this workflow.
"""
import argparse,json,math
from pathlib import Path
import numpy as np
import pandas as pd

def utc(t):
    x=pd.Timestamp(t)
    return x.tz_localize("UTC") if x.tzinfo is None else x.tz_convert("UTC")
def chronological_folds(x,y,start,end,window=None):
    """Yield each quarter's training labels fully observable at refit."""
    start,end=utc(start),utc(end)
    if start>=end or start!=start.normalize() or end!=end.normalize():raise ValueError("invalid period")
    if start.day!=1 or end.day!=1 or start.month not in [1,4,7,10] or end.month not in [1,4,7,10]:raise ValueError("quarter boundaries required")
    if x.index.has_duplicates or y.index.has_duplicates or not x.index.is_monotonic_increasing or not y.index.is_monotonic_increasing:raise ValueError("unique chronological index required")
    if not y.index.isin(x.index).all() or y.available.isna().any():raise ValueError("invalid label index/availability")
    if (y.available.to_numpy()<y.index.as_unit("ns").asi8).any():raise ValueError("outcome before signal")
    dates=pd.date_range(start,end,freq="QS")
    for cut,nxt in zip(dates[:-1],dates[1:]):
        mask=(y.index<cut)&(y.available<=cut.value)
        if window is not None:mask&=y.index>=cut-pd.Timedelta(days=window)
        train=y.loc[mask];test=x.loc[(x.index>=cut)&(x.index<nxt)]
        yield cut,nxt,train,test
def calendar_report(records,start,end,initial=10000.,seed=20261126):
    start,end=utc(start),utc(end)
    if start>=end or start.day!=1 or end.day!=1:raise ValueError("month boundary period required")
    periods=pd.period_range(start.strftime("%Y-%m"),(end-pd.Timedelta(days=1)).strftime("%Y-%m"),freq="M").astype(str)
    if not records:return dict(n=0,mean=None,pf=None,win=None,equity=initial,dd=0.,ci=None,lower95=None,years={},months=[])
    f=pd.DataFrame(records);t=pd.to_datetime(f.time,utc=True)
    if not t.is_monotonic_increasing or t.duplicated().any() or ((t<start)|(t>=end)).any():raise ValueError("out-of-period or duplicate trades")
    r=f.R.to_numpy(dtype=float);p=f.pnl.to_numpy(dtype=float)
    if not np.isfinite(r).all() or not np.isfinite(p).all():raise ValueError("nonfinite outcome")
    eq=np.r_[initial,initial+np.cumsum(p)];peak=np.maximum.accumulate(eq)
    loss=-r[r<0].sum()
    b=f.assign(month=t.dt.strftime("%Y-%m")).groupby("month").agg(net=("pnl","sum"),n=("R","size"),r=("R","sum")).reindex(periods,fill_value=0)
    rng=np.random.default_rng(seed)
    i=rng.integers(0,len(b),size=(2000,len(b)))
    a=b.r.to_numpy()[i].sum(1);c=b.n.to_numpy()[i].sum(1)
    ci=np.quantile(a[c>0]/c[c>0],[.025,.975]).tolist()
    # Report one-sided lower bound across 1 and 3 month circular blocks;
    # prespecified conservative minimum. Small calendar support explicitly flagged.
    lows={}
    for block in [1,3]:
        rng=np.random.default_rng(seed+block)
        j=rng.integers(0,len(b),size=(30000,math.ceil(len(b)/block)))
        k=((j[:,:,None]+np.arange(block))%len(b)).reshape(30000,-1)[:,:len(b)]
        a=b.r.to_numpy()[k].sum(1);c=b.n.to_numpy()[k].sum(1)
        lows[str(block)]=float(np.quantile(a[c>0]/c[c>0],.05)) if (c>0).any() else None
    years={str(k):dict(n=len(g),mean=float(g.R.mean()),returnFraction=float(g.pnl.sum()/initial)) for k,g in f.groupby(t.dt.year)}
    active=int((b.n>0).sum())
    return dict(n=len(r),mean=float(r.mean()),pf=float(r[r>0].sum()/loss) if loss else None,win=float((r>0).mean()),equity=float(eq[-1]),dd=float(np.max((peak-eq)/peak)),ci=ci,lower95=min(lows.values()) if active>=12 and len(b)>=24 else None,blockLower=lows,years=years,activeMonths=active,months=[dict(month=k,trades=int(v.n),netR=float(v.r),returnFraction=float(v.net/initial)) for k,v in b.iterrows()])
def selftest():
    i=pd.date_range("2023-01-01","2025-01-01",freq="D",inclusive="left",tz="UTC")
    x=pd.DataFrame({"a":np.arange(len(i))},index=i)
    y=pd.DataFrame({"R":.1,"available":i.as_unit("ns").asi8+2*86400*10**9},index=i)
    folds=list(chronological_folds(x,y,"2024-01-01","2025-01-01",365))
    assert len(folds)==4
    for cut,nxt,tr,te in folds:
        assert (tr.index<cut).all() and (tr.available<=cut.value).all() and (tr.index>=cut-pd.Timedelta(days=365)).all()
        assert (te.index>=cut).all() and (te.index<nxt).all()
        assert cut-pd.Timedelta(days=1) not in tr.index
    q=[dict(time="2024-01-01T00:00:00Z",R=.1,pnl=10),dict(time="2025-01-01T00:00:00Z",R=-.2,pnl=-20)]
    z=calendar_report(q,"2024-01-01","2026-01-01")
    assert z["n"]==2 and z["equity"]==9990 and len(z["months"])==24 and z["lower95"] is None
    print("Synthetic quarter purge, rolling history, 2024-25 calendar and low-support guard PASS",flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");a=p.parse_args();selftest()
    if a.selftest:return
    q=json.loads(Path("audit-portfolio/lab-portfolio-screen.json").read_text())["results"]
    out={}
    for name,v in q.items():
        for cost in ["normal","stress"]:
            r=v[cost]
            z=calendar_report(r["records"],"2022-01-01","2024-01-01")
            for key in ["n","mean","pf","win","equity","dd","ci"]:
                if r[key] is None:assert z[key] is None
                else:np.testing.assert_allclose(z[key],r[key],rtol=1e-10,atol=1e-10)
            out[name+":"+cost]=dict(n=z["n"],mean=z["mean"],equity=z["equity"],ci=z["ci"],lower95=z["lower95"],activeMonths=z["activeMonths"])
    print("VALIDATION_CORE="+json.dumps(out),flush=True)
    Path("lab-validation-core.json").write_text(json.dumps(dict(developmentParity=out,limitations="No holdout inputs opened, downloaded or evaluated; only synthetic dates and prior 2022-23 archived records. Reusable calendar statistics and temporal folds, not a complete candidate-specific holdout runner, not approval. Closed-trade drawdown only; intratrade drawdown and full execution parity still required."),indent=2))
if __name__=="__main__":main()
