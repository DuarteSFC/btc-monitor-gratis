"""Development-only diagnostic of B03: sensitivity, causal regimes and solvent equity.
No validation-period data, live orders, or production imports.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,segments

NS=60_000_000_000
START=10000.
RISK=.0025

def replay(d,m,stop_atr,horizon,fee,slip):
    t=d.index.as_unit("ns").asi8
    x=d[["open","high","low","close"]].to_numpy()
    sg=d.segment.to_numpy()
    mask=m.b03 & m.atr15.notna() & (m.atr15>0)
    equity=peak=START; dd=0.; last=-1; records=[]; skips=0
    for dt,f in m.loc[mask].iterrows():
        et=dt.value+NS
        if et<=last: continue
        if et+(horizon-1)*NS>t[-1]: continue
        k=int(np.searchsorted(t,et))
        if k>=len(t) or t[k]!=et or sg[k]!=f.segment:
            skips+=1; continue
        raw=x[k,0]; entry=raw*(1+slip); stop=entry-stop_atr*f.atr15
        if not 0<stop<entry or equity<=0: continue
        risk=entry*(1+fee)-stop*(1-slip)*(1-fee)
        target=(entry*(1+fee)+2*risk)/((1-slip)*(1-fee))
        qty=min(equity*RISK/risk,equity/(entry*(1+fee)))
        end=min(k+horizon,len(t))
        ts=t[k:end]; z=x[k:end]
        bad=np.flatnonzero((ts!=et+np.arange(len(ts))*NS)|(sg[k:end]!=f.segment))
        gap=int(bad[0]) if len(bad) else len(z)
        hits=np.flatnonzero((z[:gap,2]<=stop)|(z[:gap,1]>=target))
        if len(hits):
            j=int(hits[0]); o,h,l,c=z[j]
            if l<=stop: out=min(o,stop); reason="stop"
            else: out=target; reason="target"
        elif gap<len(z):
            j=gap; out=0.; reason="unknown_gap"
        else:
            j=len(z)-1; out=z[j,3]; reason="timeout"
        last=int(t[k+j]+NS)
        net=out*(1-slip)*(1-fee)-entry*(1+fee)
        gross=out-raw
        pnl=net*qty
        equity=max(0.,equity+pnl)
        peak=max(peak,equity); dd=max(dd,(peak-equity)/peak)
        regime="unknown" if pd.isna(f.trend4h) else ("up" if f.trend4h else "down")
        records.append(dict(year=dt.year,regime=regime,reason=reason,R=float(net/risk),grossR=float(gross/risk),costR=float((gross-net)/risk),pnl=float(pnl)))
    def stats(rr):
        r=np.array([v["R"] for v in rr if v["reason"]!="unknown_gap"])
        allr=np.array([v["R"] for v in rr])
        loss=-r[r<0].sum()
        return dict(n=len(rr),known=len(r),unknown=len(rr)-len(r),win=float((r>0).sum()/len(rr)) if rr else None,meanR=float(r.mean()) if len(r) else None,conservativeMeanR=float(allr.mean()) if rr else None,profitFactor=float(r[r>0].sum()/loss) if loss else None,grossMeanR=float(np.mean([v["grossR"] for v in rr if v["reason"]!="unknown_gap"])) if len(r) else None,costMeanR=float(np.mean([v["costR"] for v in rr if v["reason"]!="unknown_gap"])) if len(r) else None)
    return dict(stopATR=stop_atr,horizonMinutes=horizon,fee=fee,slippage=slip,**stats(records),equityEnd=equity,closedDrawdownConservative=dd,missingEntry=skips,years={str(y):stats([v for v in records if v["year"]==y]) for y in range(2020,2024)},regimes={g:stats([v for v in records if v["regime"]==g]) for g in ["up","down","unknown"]})

def selftest():
    idx=pd.date_range("2020-01-01",periods=300,freq="min",tz="UTC")
    d=segments(pd.DataFrame({"open":100.,"high":100.1,"low":99.9,"close":100.,"volume":1.,"quote":100.},index=idx))
    m=pd.DataFrame({"b03":[True],"atr15":[1.],"segment":[1],"trend4h":[True]},index=pd.DatetimeIndex([idx[5]]))
    a=replay(d,m,1.5,240,.0005,.0002)
    assert a["n"]==1 and a["meanR"]<0 and a["equityEnd"]<START
    d1=d.copy();d1.loc[idx[6],["low","high"]]=[97.,110.]
    a=replay(d1,m,1.5,240,.0005,.0002)
    assert abs(a["meanR"]+1)<1e-8
    d1=d.copy();d1.loc[idx[6],"high"]=110.
    a=replay(d1,m,1.5,240,.0005,.0002)
    assert abs(a["meanR"]-2)<1e-8
    a=replay(segments(d.drop(idx[9])),m,1.5,240,.0005,.0002)
    assert a["unknown"]==1 and a["meanR"] is None and 0<=a["equityEnd"]<=START
    print("B03 diagnostic selftest PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset)
    d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")]
    m=signal_frames(d)
    results=[]
    for s in [1.5,2.5,4.0]:
        for h in [240,720,1440]:
            for fee,slip in [(0.,0.),(.0005,.0002),(.0008,.0004)]:
                q=replay(d,m,s,h,fee,slip);results.append(q)
                print(json.dumps({k:v for k,v in q.items() if k not in ["years","regimes"]}),flush=True)
    report=dict(period="2020-2023 only",model="B03 exploratory sensitivity",configs=len(results),results=results,limitations="Not a validation; 27 correlated configurations; spot proxy, no funding, no mark-to-market DD. Zero costs change target geometry, not an identical-trades cost counterfactual. Unknown exits charged total spot notional loss; resolved metrics descriptive. Compounded risk capped by equity.")
    Path("lab-b03-diagnostic.json").write_text(json.dumps(report,indent=2))
    print("B03_DIAGNOSTIC="+json.dumps(report),flush=True)
if __name__=="__main__":main()
