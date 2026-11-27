"""XV01: fixed cross-venue premium dislocation, development only."""
import argparse,hashlib,json,time
from pathlib import Path
import numpy as np
import pandas as pd

SCOPES=[("2022-23","2021-01-01","2022-01-01","2024-01-01"),("2026","2026-01-01","2026-04-01","2026-10-01")]
PREMIUM_START={"2022-23":"2021-06-01","2026":"2026-01-01"}
def utc(s):return pd.Timestamp(s,tz="UTC")
def scores(p):
    p=p.asfreq("h")
    past=p.shift(1).rolling(168,min_periods=168)
    sd=past.std(ddof=0)
    return (p-past.mean())/sd.where(sd>1e-10)
def signals(h,z,lag_hours):
    v=z.copy();v.index+=pd.Timedelta(hours=lag_hours)
    v=v.reindex(h.index)
    prev=h.groupby("segment").close.shift(1)
    prior=h.groupby("segment").close.shift(4)
    eligible=v.notna()&prev.notna()&prior.notna()&h.atr1.gt(0)
    base=eligible&h.close.gt(prev)&h.close.le(prior)
    return pd.DataFrame(dict(eligible=eligible,base=base,selected=base&v.ge(2)),index=h.index)
def selftest():
    i=pd.date_range("2022-01-01",periods=210,freq="h",tz="UTC")
    p=pd.Series(np.sin(np.arange(len(i))),index=i);p.iloc[180]=4
    z=scores(p);assert z.iloc[:168].isna().all() and z.iloc[180]>2
    q=p.copy();q.iloc[181:]=100
    pd.testing.assert_series_equal(z.loc[:i[180]],scores(q).loc[:i[180]])
    assert pd.isna(scores(p.drop(i[100])).loc[i[180]])
    h=pd.DataFrame(dict(close=100.,segment=1,atr1=1.),index=i);h.loc[i[177],"close"]=101;h.loc[i[180],"close"]=99
    assert signals(h,z,1).selected.loc[i[181]] and not signals(h,z,2).selected.loc[i[181]]
    print("XV01 prior-only normalization, gaps and delayed availability PASS",flush=True)
def acquire(start,end):
    from xv0_cross_venue import binance,coinbase,compare
    parts=[];manifest=[]
    for month in pd.date_range(start,end,freq="MS",inclusive="left",tz="UTC"):
        stop=month+pd.offsets.MonthBegin(1)
        b,bm=binance(month,stop)
        chunks=[];sources=[bm]
        for left in pd.date_range(month,stop,freq="12D",inclusive="left"):
            right=min(left+pd.Timedelta(days=12),stop)
            c,cm=coinbase("BTC-USD",left,right);time.sleep(.35)
            u,um=coinbase("USDT-USD",left,right);time.sleep(.35)
            q,r=compare(b.loc[(b.index>=left)&(b.index<right)],c,u,left,right)
            chunks.append(q);sources.extend([cm,um])
        q=pd.concat(chunks);expected=pd.date_range(month+pd.Timedelta(hours=1),stop,freq="h")
        pd.testing.assert_index_equal(q.index,expected,check_names=False)
        valid=int(q.adjustedBps.notna().sum())
        row=dict(month=month.strftime("%Y-%m"),expected=len(q),joint=valid,binance=int(q.binance.notna().sum()),coinbase=int(q.coinbase.notna().sum()),usdt=int(q.usdtUSD.notna().sum()),sources=sources)
        print("XV01_MONTH="+json.dumps({k:v for k,v in row.items() if k!="sources"}),flush=True)
        if valid/len(q)<.95:raise ValueError(f"incomplete month {month}: {valid}/{len(q)} joint observations")
        manifest.append(row);parts.append(q.adjustedBps)
    p=pd.concat(parts);assert p.index.is_unique and p.index.is_monotonic_increasing
    return p,manifest
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args();selftest()
    if a.selftest:return
    from derivative_screen import load
    from market_frame import segments,bars,atr
    from hourly_futures import make_outcomes,FEES
    from validation_rehearsal import replay
    from ca01_relative_strength import controls
    results={};provenance={}
    for (name,warm,start,end),root in zip(SCOPES,[a.derivatives,a.extension]):
        premium_start=PREMIUM_START[name]
        assert utc(premium_start)+pd.Timedelta(days=8)<utc(start)
        p,manifest=acquire(premium_start,end);z=scores(p);provenance[name]=manifest
        print("XV01_DATA="+json.dumps(dict(period=name,months=len(manifest),expected=len(p),joint=int(p.notna().sum()),scoreHours=int(z.notna().sum()))),flush=True)
        btc,mark,funding=[load(root,k) for k in ["perp","mark","funding"]]
        assert btc.index.min()>=utc(warm) and btc.index.max()<utc(end)
        h=bars(segments(btc.assign(quote=btc.volume*btc.close)),60);h["atr1"]=atr(h)*1.2
        out={}
        for lag in [1,2]:
            f=signals(h,z,lag);f=f.loc[(f.index>=utc(start))&(f.index<utc(end)-pd.Timedelta(days=1))]
            base=f.index[f.base];selected=f.index[f.selected]
            print("XV01_SCOPE="+json.dumps(dict(period=name,lag=lag,eligible=int(f.eligible.sum()),baseSignals=len(base),signals=len(selected))),flush=True)
            out[str(lag)]={}
            for delay in ([1,5,15] if lag==1 else [1]):
                shift=pd.Timedelta(minutes=delay-1);m=h.loc[base,["atr1","segment"]].copy();m.index+=shift
                out[str(lag)][str(delay)]={}
                for cost in (FEES if lag==1 else ["stress"]):
                    y=make_outcomes(m,pd.Series(True,index=m.index),btc,mark,funding,720,*FEES[cost]);out[str(lag)][str(delay)][cost]={}
                    for policy,ix in [("base",base),("XV01",selected)]:
                        r=pd.Series("12h",index=ix+shift,dtype="object");q=replay(r,{"12h":{cost:y}},cost,start=start,end=end)
                        out[str(lag)][str(delay)][cost][policy]=q
                        print("XV01_RESULT="+json.dumps(dict(period=name,lag=lag,policy=policy,delay=delay,cost=cost,n=q["n"],signals=q["signals"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],years=q["years"])),flush=True)
                    if lag==1 and delay==1 and cost=="stress":
                        c=controls(base,selected,y,out[str(lag)][str(delay)][cost]["XV01"]);out["controls"]=c
                        print("XV01_CONTROL="+json.dumps(dict(period=name,**{k:v for k,v in c.items() if k!="draws"})),flush=True)
        results[name]=out
    Path("lab-xv01.json").write_text(json.dumps(dict(provenance=provenance,results=results,limitations="Completed hourly close proxy, assumed receipt delay, no executable quote reconstruction; reused development only, approximate controls, no holdout or orders."),indent=2))
if __name__=="__main__":main()
