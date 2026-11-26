"""Aggressor-side volume research using Binance spot klines, development only."""
import argparse,hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,bars,lag,rolling,align,segments
from new_families import run,control
from b03_entry_filters import gate

def load_flow(root,d):
    root=Path(root); manifest=json.loads((root/"manifest.json").read_text())
    out=[]
    for item in manifest["files"]:
        if item["start"]>="2024-01-01":continue
        raw=(root/item["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item["sha256"]:raise ValueError("hash mismatch")
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names=[n for n in z.namelist() if n.endswith(".csv")]
            if len(names)!=1:raise ValueError("invalid archive")
            with z.open(names[0]) as f:
                x=pd.read_csv(f,header=None,usecols=[0,5,6,9],dtype=str)
        x=x[~x[0].str.lower().isin(["open_time","opentime"])]
        t=pd.to_numeric(x[0]).astype("int64"); t=t.where(t<10**14,t//1000)
        ct=pd.to_numeric(x[6]).astype("int64");ct=ct.where(ct<10**14,ct//1000)
        valid=ct==t+59999
        v=x.loc[valid,5].astype(float).to_numpy();b=x.loc[valid,9].astype(float).to_numpy()
        if not np.isfinite(b).all() or (b<0).any() or (b>v+1e-8*np.maximum(1,v)).any():raise ValueError("invalid taker buy volume")
        out.append(pd.Series(b,index=pd.to_datetime(t[valid].to_numpy(),unit="ms",utc=True)))
    a=pd.concat(out)
    if not a.index.equals(d.index):raise ValueError("flow timestamps mismatch")
    return d.assign(buy=a)

def masks(d,m):
    q=bars(d,15)
    taker=d.buy.resample("15min",label="right",closed="left",origin="epoch").sum().reindex(q.index)
    q["imb"]=(2*taker-q.volume)/q.volume.where(q.volume>0)
    q["v20"]=rolling(q,"volume",20,lambda r:r.mean())
    q["lo24"]=rolling(q,"low",24,lambda r:r.min())
    q["hi24"]=rolling(q,"high",24,lambda r:r.max())
    q["prev_imb"]=lag(q,"imb")
    vol=q.volume/lag(q,"v20")
    rng=q.high-q.low
    closepos=(q.close-q.low)/rng.where(rng>0)
    lo=lag(q,"lo24");hi=lag(q,"hi24")
    q["flow_flip"]=(q.prev_imb<=-.15)&(q.imb>=.15)&(q.close>q.open)&(vol>=1.2)
    q["sell_absorption"]=(q.low<lo)&(q.close>lo)&(closepos>=.65)&(q.imb<=-.1)&(vol>=1.5)
    q["buy_breakout"]=(q.close>hi)&(q.imb>=.2)&(vol>=1.5)
    # Previous three complete bars' signed volume negative, then buying pressure and higher close.
    q["signed"]=2*taker-q.volume
    previous=lag(q.assign(s3=rolling(q,"signed",3,lambda r:r.sum())),"s3")
    q["pressure_reversal"]=(previous<0)&(q.imb>=.25)&(q.close>lag(q,"high"))
    return {k:align(q,m,k,exact=True).eq(True)&m.atr15.notna()&(m.atr15>0) for k in ["flow_flip","sell_absorption","buy_breakout","pressure_reversal"]}

def selftest():
    idx=pd.date_range("2020-01-01",periods=60*72,freq="min",tz="UTC")
    rng=np.random.default_rng(42);c=100+np.cumsum(rng.normal(0,.1,len(idx)));o=np.r_[c[0],c[:-1]];v=rng.uniform(1,10,len(idx))
    d=segments(pd.DataFrame(dict(open=o,high=np.maximum(o,c)+.05,low=np.minimum(o,c)-.05,close=c,volume=v,quote=c*v,buy=v*rng.uniform(0,1,len(idx))),index=idx))
    m=signal_frames(d);before=masks(d,m);cut=idx[3000];e=d.copy();e.loc[e.index>=cut,"buy"]=e.loc[e.index>=cut,"volume"]
    after=masks(e,signal_frames(e))
    for k in before:pd.testing.assert_series_equal(before[k].loc[:cut],after[k].loc[:cut])
    print("Aggressor volume causal tests PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")]
    d=load_flow(a.dataset,d);m=signal_frames(d);results={}
    for name,mask in masks(d,m).items():
        normal=run(d,m,mask);stress=run(d,m,mask,fee=.0008,slip=.0004);neighbor=run(d,m,mask,s=2.5)
        random=[run(d,m,control(m,mask,seed)) for seed in [101,202,303,404,505]]
        ctrl=[v["conservativeMeanR"] for v in random if v["conservativeMeanR"] is not None]
        beats=bool(ctrl and normal["conservativeMeanR"] is not None and normal["conservativeMeanR"]>max(ctrl))
        passes=bool(gate(normal) and stress["conservativeMeanR"] is not None and stress["conservativeMeanR"]>0 and neighbor["conservativeMeanR"] is not None and neighbor["conservativeMeanR"]>0 and beats)
        results[name]=dict(signals=int(mask.sum()),normal=normal,stress=stress,neighbor=neighbor,random=random,beatsAllFive=beats,screenPass=passes)
        print(json.dumps(dict(name=name,signals=int(mask.sum()),n=normal["n"],meanR=normal["meanR"],conservative=normal["conservativeMeanR"],stress=stress["conservativeMeanR"],neighbor=neighbor["conservativeMeanR"],control=ctrl,screenPass=passes)),flush=True)
    report=dict(period="2020-2023 only",models=results,limitations="Binance spot taker buy base volume, sell volume inferred as total minus buy; no order-book, OI, funding or liquidation observations. Four correlated exploratory hypotheses, no significance test, holdout untouched.")
    Path("lab-flow-families.json").write_text(json.dumps(report,indent=2))
    print("FLOW_FAMILIES="+json.dumps(report),flush=True)
if __name__=="__main__":main()
