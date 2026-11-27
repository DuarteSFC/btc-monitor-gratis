"""CM01: fixed spot/perpetual taker-flow divergence hypothesis.
Development only. No model fitting, no 2024-25 market reads, no orders.
"""
import argparse,json,tempfile,hashlib,io,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,bars,atr,align
from derivative_screen import load
from hourly_futures import make_outcomes,FEES,NS
from validation_rehearsal import scoped_spot,replay,utc
from extension_2026 import scope_2026,load_scoped_flow
from derivatives_dataset import fetch

def extract(raw,expected):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.endswith(".csv")]
        if len(names)!=1:raise ValueError("unexpected archive")
        with z.open(names[0]) as f:
            q=pd.read_csv(f,header=None,usecols=[0,5,6,9],dtype=str)
    q=q.loc[~q[0].str.lower().isin(["open_time","opentime"])]
    t=pd.to_numeric(q[0]).astype("int64");ct=pd.to_numeric(q[6]).astype("int64")
    t=t.where(t<10**14,t//1000);ct=ct.where(ct<10**14,ct//1000)
    valid=ct==t+59999
    a=pd.DataFrame(dict(volume=q.loc[valid,5].astype(float).to_numpy(),buy=q.loc[valid,9].astype(float).to_numpy()),index=pd.to_datetime(t[valid].to_numpy(),unit="ms",utc=True))
    a=a.loc[a.index.isin(expected.index)]
    if not np.isfinite(a.to_numpy()).all() or (a.buy<0).any() or (a.buy>a.volume+1e-8*np.maximum(1,a.volume)).any():raise ValueError("invalid taker quantity")
    if a.index.has_duplicates:
        different=a.groupby(level=0).nunique().max(axis=1)>1
        if different.any():raise ValueError("conflicting raw flow")
        a=a.loc[~a.index.duplicated()]
    a=a.sort_index()
    pd.testing.assert_index_equal(a.index,expected.index,check_names=False)
    np.testing.assert_allclose(a.volume,expected.volume,rtol=1e-10,atol=1e-10)
    return a.buy

def perp_flow(root,perp):
    meta=json.loads((Path(root)/"manifest.json").read_text())
    files=[f for f in meta["files"] if f["kind"]=="perp"]
    if not files or any(f["status"]!="ok" for f in files):raise ValueError("unverified futures archive")
    def one(f):
        raw=fetch(f["url"])
        if hashlib.sha256(raw).hexdigest()!=f["source_sha256"]:raise ValueError("source archive digest mismatch")
        expected=perp.loc[(perp.index>=utc(f["start"]))&(perp.index<utc(f["end_exclusive"]))]
        return extract(raw,expected)
    with ThreadPoolExecutor(max_workers=4) as pool:
        a=pd.concat(list(pool.map(one,files))).sort_index()
    pd.testing.assert_index_equal(a.index,perp.index,check_names=False)
    return a,len(files)

def conditions(d,perp,buy,m,start,end):
    q=bars(d,15)
    spot_buy=d.buy.resample("15min",closed="left",label="right",origin="epoch").sum().reindex(q.index)
    p=perp.assign(buy=buy).resample("15min",closed="left",label="right",origin="epoch").agg({"volume":["sum","count"],"buy":"sum"})
    p.columns=["volume","n","buy"]
    ps=((2*p.buy-p.volume)/p.volume.where(p.volume>0)).where(p.n==15)
    ss=(2*spot_buy-q.volume)/q.volume.where(q.volume>0)
    mi=m.loc[m.index.intersection(q.index)]
    ss=ss.reindex(mi.index);ps=ps.reindex(mi.index);q=q.reindex(mi.index)
    base=(ss>=.10)&ps.notna()&(q.close>q.open)&(q.close>=(q.high+q.low)/2)&mi.trend4h.notna()&mi.atr1.notna()&(mi.atr1>0)&(mi.index>=utc(start))&(mi.index<utc(end)-pd.Timedelta(days=1))
    selected=base&(ps<=-.15)
    return mi.loc[base],mi.index[selected]

def outcomes(index,m,perp,mark,funding,delay,cost):
    shift=pd.Timedelta(minutes=delay-1)
    x=m.loc[index,["segment","atr1"]].copy();x.index+=shift
    return make_outcomes(x,pd.Series(True,index=x.index),perp,mark,funding,240,*FEES[cost])

def fast(index,y):
    # Same position sizing/overlap/unknown locks as rehearsal; no bootstrap
    # inside placebo loops. Verify parity on the observed path.
    eq=10000.;last=-1;rs=[];unknown=0
    lookup={t.value:(v.R,v.riskFraction,int(v.exit)) for t,v in y.iterrows()}
    for t in index:
        dt=t.value
        if dt+NS<last:continue
        if dt not in lookup:unknown+=1;last=dt+1441*NS;continue
        r,f,e=lookup[dt];eq+=min(.0025*eq,eq*f)*r;last=e;rs.append(r)
    return dict(n=len(rs),mean=float(np.mean(rs)) if rs else None,equity=eq,unknown=unknown)

def controls(base,selected,y,observed):
    z=pd.DataFrame(dict(month=base.index.strftime("%Y-%m"),session=base.index.hour//6,trend=base.trend4h.astype("string"),vol=pd.cut(base.atr1/base.close,[-np.inf,.002,.005,.01,np.inf],labels=False)),index=base.index)
    groups=[]
    for _,g in z.groupby(["month","session","trend","vol"],dropna=False):
        n=int(g.index.isin(selected).sum())
        if n:groups.append((g.index.as_unit("ns").asi8,n))
    assert sum(n for _,n in groups)==len(selected)
    rng=np.random.default_rng(20261127);out=[]
    for _ in range(199):
        t=np.sort(np.concatenate([rng.choice(ix,size=n,replace=False) for ix,n in groups])) if groups else np.array([],dtype=np.int64)
        out.append(fast(pd.to_datetime(t,unit="ns",utc=True),y))
    valid=[q for q in out if q["mean"] is not None and not q["unknown"]]
    p=(1+sum(q["mean"]>=observed["mean"] for q in valid))/(len(valid)+1) if len(valid)==199 and observed["mean"] is not None and not observed["unknown"] else None
    return dict(draws=out,valid=len(valid),medianMean=float(np.median([q["mean"] for q in valid])) if valid else None,pRelative=p)

def run(spot,deriv,start,end):
    d=load_scoped_flow(spot,load_minutes(spot))
    allowed_end="2024-01-01" if start.startswith("2022") else "2026-10-01"
    assert d.index.max()<utc(allowed_end)
    meta=json.loads((Path(deriv)/"manifest.json").read_text())
    assert all(f["end_exclusive"]<=allowed_end and f["start"]>=("2021-01-01" if start.startswith("2022") else "2026-01-01") for f in meta["files"])
    perp,mark,funding=[load(deriv,k) for k in ["perp","mark","funding"]]
    buy,nfiles=perp_flow(deriv,perp)
    m=signal_frames(d);h=bars(d,60);h["a"]=atr(h);m["atr1"]=align(h,m,"a")
    base,ix=conditions(d,perp,buy,m,start,end)
    print("CM_SCOPE="+json.dumps(dict(start=start,end=end,archives=nfiles,flowRows=len(buy),baseSignals=len(base),selected=len(ix))),flush=True)
    results={}
    for delay in [1,5,15]:
        results[str(delay)]={}
        for cost in FEES:
            # At 1m stress retain the full base outcome table for conditional controls.
            index=base.index if delay==1 and cost=="stress" else ix
            y=outcomes(index,m,perp,mark,funding,delay,cost)
            r=pd.Series("4h",index=ix+pd.Timedelta(minutes=delay-1),dtype="object")
            q=replay(r,{"4h":{cost:y}},cost,start=start,end=end)
            results[str(delay)][cost]=q
            print("CM_RESULT="+json.dumps(dict(start=start,delay=delay,cost=cost,n=q["n"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],years=q["years"])),flush=True)
            if delay==1 and cost=="stress":
                a=fast(ix,y);assert a["n"]==q["n"] and a["unknown"]==q["unknown"]
                np.testing.assert_allclose(a["equity"],q["equity"],rtol=1e-10,atol=1e-10)
                ctl=controls(base,ix,y,q);results["controls"]=ctl
                print("CM_CONTROL="+json.dumps(dict(start=start,**{k:v for k,v in ctl.items() if k!="draws"})),flush=True)
    return results

def selftest():
    from validation_rehearsal import selftest as test
    test()
    t=pd.date_range("2022-01-01",periods=3,freq="min",tz="UTC")
    ms=t.asi8//1000000
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w") as z:
        z.writestr("a.csv","\n".join(f"{u},100,101,99,100,10,{u+59999},0,1,6,0,0" for u in ms))
    q=extract(b.getvalue(),pd.DataFrame({"volume":10.},index=pd.to_datetime(ms,unit="ms",utc=True)))
    assert q.tolist()==[6.,6.,6.]
    y=pd.DataFrame(dict(R=[.1,.2,-.1],riskFraction=.01,exit=t.asi8+3*NS),index=t)
    a=fast(t,y);assert a["n"]==2
    print("Cross-market raw-flow checksum schema, volume parity and overlap selftest PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    if a.selftest:return
    with tempfile.TemporaryDirectory() as d0,tempfile.TemporaryDirectory() as d1:
        scoped_spot(a.dataset,d0);scope_2026(a.dataset,d1)
        results={"2022-23":run(d0,a.derivatives,"2022-01-01","2024-01-01"),"2026":run(d1,a.extension,"2026-04-01","2026-10-01")}
    Path("lab-cross-market.json").write_text(json.dumps(dict(results=results,limitations="One fixed non-trained hypothesis. Source hashes matched to archived futures candles, not order book/actual liquidation data. Conditional random timing comparison approximate; no absolute selection adjustment or independent validation. 2026 partly explored. No holdout or production."),indent=2))
if __name__=="__main__":main()
