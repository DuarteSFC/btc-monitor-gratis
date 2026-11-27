"""MS01 incremental decision audit, no PnL and no tuning.
Compare a causal bounded buffer with full batch calculations, and diagnose
sensitivity to availability of the independent minute reconciliation.
"""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from derivative_screen import load
from ms01_absorption import conditions,quality,selftest as base_test

# Max feature dependency = 15 shift + 359 median history + 11 return/volume history.
BUFFER=386
def point(a):
    if len(a)!=BUFFER or not (a.index.to_series().diff().iloc[1:]==pd.Timedelta(seconds=5)).all():raise ValueError("incomplete clock")
    v=a.volume.to_numpy();b=a.buyVolume.to_numpy();o=a.open.to_numpy();c=a.close.to_numpy()
    if not np.isfinite(np.r_[v,b,o,c]).all() or (v<=0).any() or (b<0).any() or (b>v+1e-8*np.maximum(1,v)).any() or (o<=0).any() or (c<=0).any():
        return (False,False,False)
    vv=np.lib.stride_tricks.sliding_window_view(v,12).sum(axis=1)
    ret=c[11:]/o[:-11]-1
    vb=np.median(vv[:-15]);rb=np.median(np.abs(ret[:-15]))
    shock=v[-15:-3].sum();rec=v[-3:].sum()
    if min(vb,rb,shock,rec)<=0:return (False,False,False)
    sr=c[-4]/o[-15]-1
    base=shock>=2*vb and 1-b[-15:-3].sum()/shock>=.65 and b[-3:].sum()/rec>=.60 and c[-1]/o[-3]>1
    return (True,bool(base),bool(base and -rb<=sr<=0))

def sample(a):
    f=conditions(a);ix=np.flatnonzero(a.index.second==0)
    # Check every eligible decision once, not just three prefix cutoffs.
    for i in ix[ix>=BUFFER-1]:
        z=point(a.iloc[i-BUFFER+1:i+1])
        q=tuple(bool(f.iloc[i][k]) for k in ["complete","base","selected"])
        if z!=q:raise AssertionError((str(a.index[i]),z,q))
    return f.loc[f.index.second==0],int((ix>=BUFFER-1).sum())

def selftest():
    base_test()
    i=pd.date_range("2022-01-01",periods=1000,freq="5s",tz="UTC")
    rng=np.random.default_rng(42)
    a=pd.DataFrame(dict(open=100.,close=100.+rng.normal(0,.01,len(i)),volume=1.,buyVolume=.5),index=i)
    f,n=sample(a);assert n>0
    a.iloc[500,0]=np.nan
    # All features must be available; compare after an explicit all-column gap.
    a.iloc[500,:]=np.nan;sample(a)
    print("Bounded buffer and independent scalar decision parity PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    if a.selftest:return
    root=Path("audit-ms0");meta=json.loads((root/"manifest.json").read_text())
    assert meta["verified"]==6 and not meta["errors"]
    old=load(a.derivatives,"perp");new=load(a.extension,"perp")
    assert old.index.max()<pd.Timestamp("2024-01-01",tz="UTC") and new.index.min()>=pd.Timestamp("2026-01-01",tz="UTC")
    perp=pd.concat([old,new]);out=[]
    for f in meta["results"]:
        day=pd.Timestamp(f["day"],tz="UTC");end=day+pd.Timedelta(days=1)
        path=root/f["file"];assert hashlib.sha256(path.read_bytes()).hexdigest()==f["fileSHA256"]
        x=pd.read_csv(path,compression="gzip");x.index=pd.to_datetime(x.pop("openUtc"),utc=True)
        ref=perp.loc[(perp.index>=day)&(perp.index<end)]
        good=quality(x,ref)
        grid=pd.date_range(day,end,freq="5s",inclusive="left")
        raw=x.reindex(grid);filtered=x.loc[good.reindex(x.index.floor("min")).fillna(False).to_numpy()].reindex(grid)
        for z in [raw,filtered]:z.index+=pd.Timedelta(seconds=5)
        fr,nr=sample(raw);fq,nq=sample(filtered)
        # Full same-minute source quality can only be used after that minute.
        # An alternative requires prior-minute quality but not the current
        # minute's reconciliation. Compare flags only, no returns or tuning.
        raw_selected=fr.selected;filtered_selected=fq.selected
        q=dict(day=f["day"],rawComplete=int(fr.complete.sum()),filteredComplete=int(fq.complete.sum()),rawSignals=int(raw_selected.sum()),filteredSignals=int(filtered_selected.sum()),sameSignals=int((raw_selected&filtered_selected).sum()),rawOnly=int((raw_selected&~filtered_selected).sum()),filteredOnly=int((filtered_selected&~raw_selected).sum()),pointChecks=nr+nq)
        out.append(q);print("MS_STREAM="+json.dumps(q),flush=True)
    Path("lab-ms-stream.json").write_text(json.dumps(dict(results=out,limitations="Six diagnostic days, independent scalar calculation with 386 completed 5s bins; raw versus reconciled decisions, no PnL. Raw event-time stream assumes complete ordered arrivals, not measured network latency. Actual live message capture and reconciliation publication delay unverified."),indent=2))
if __name__=="__main__":main()
