"""T24: fixed daily trend / four-hour breakout; no optimization."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from derivative_screen import load
from market_frame import segments,bars,atr,ema,lag,rolling,align
from hourly_futures import make_outcomes,FEES
from validation_rehearsal import replay,utc
from ca01_relative_strength import controls

def conditions(d):
    h=bars(d,240);day=bars(d,1440)
    day["e20"]=ema(day,20);day["e60"]=ema(day,60)
    # NaN before warmup, aligned only within continuous minute segment.
    day["up"]=((day.close>day.e20)&(day.e20>day.e60)).astype(float).where(day.e20.notna()&day.e60.notna())
    prior=lag(h.assign(prev=rolling(h,"high",6,lambda x:x.max())),"prev")
    h["atr1"]=atr(h)*.8
    up=align(day,h,"up")
    eligible=h.atr1.gt(0)&prior.notna()&up.notna()
    base=eligible&up.eq(1)
    return h,pd.DataFrame(dict(eligible=eligible,base=base,selected=base&h.close.gt(prior)&h.close.gt(h.open)),index=h.index)

def selftest():
    from validation_rehearsal import selftest as test
    test()
    t=pd.date_range("2022-01-01",periods=75*1440,freq="min",tz="UTC")
    px=100+np.arange(len(t))*.0001
    d=segments(pd.DataFrame(dict(open=px,high=px+.01,low=px-.01,close=px+.001,volume=1.,quote=px),index=t))
    h,q=conditions(d);assert q.selected.any()
    cut=t[70*1440]
    b=d.copy();b.loc[b.index>=cut,["open","high","low","close"]]*=2.
    _,f=conditions(b)
    pd.testing.assert_frame_equal(q.loc[:cut],f.loc[:cut])
    b=d.drop(t[65*1440]);b=segments(b)
    _,f=conditions(b)
    assert not f.loc[cut:,"eligible"].any()
    print("T24 daily closure, gap reset and future mutation PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args();selftest()
    if a.selftest:return
    results={}
    for name,root,start,end,warm in [("2022-23",a.derivatives,"2022-01-01","2024-01-01","2021-01-01"),("2026",a.extension,"2026-04-01","2026-10-01","2026-01-01")]:
        p,mark,funding=[load(root,k) for k in ["perp","mark","funding"]]
        assert p.index.min()>=utc(warm) and p.index.max()<utc(end)
        h,f=conditions(segments(p.assign(quote=p.volume*p.close)))
        f=f.loc[(f.index>=utc(start))&(f.index<utc(end)-pd.Timedelta(days=2))]
        base=f.index[f.base];selected=f.index[f.selected]
        print("T24_SCOPE="+json.dumps(dict(period=name,eligible=int(f.eligible.sum()),baseSignals=len(base),signals=len(selected))),flush=True)
        out={}
        for delay in [1,5,15]:
            out[str(delay)]={};shift=pd.Timedelta(minutes=delay-1)
            m=h.loc[base,["atr1","segment"]].copy();m.index+=shift
            for cost in FEES:
                y=make_outcomes(m,pd.Series(True,index=m.index),p,mark,funding,1440,*FEES[cost])
                out[str(delay)][cost]={}
                for policy,ix in [("base",base),("T24",selected)]:
                    r=pd.Series("24h",index=ix+shift,dtype="object")
                    q=replay(r,{"24h":{cost:y}},cost,start=start,end=end)
                    out[str(delay)][cost][policy]=q
                    print("T24_RESULT="+json.dumps(dict(period=name,policy=policy,delay=delay,cost=cost,n=q["n"],signals=q["signals"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],dd=q["dd"],unknown=q["unknown"],years=q["years"])),flush=True)
                if delay==1 and cost=="stress":
                    c=controls(base,selected,y,out[str(delay)][cost]["T24"]);out["controls"]=c
                    print("T24_CONTROL="+json.dumps(dict(period=name,**{k:v for k,v in c.items() if k!="draws"})),flush=True)
        results[name]=out
    Path("lab-t24.json").write_text(json.dumps(dict(results=results,limitations="One fixed 24h trend-breakout rule, reused development data, same time/regime base and approximate month/session controls; no independent significance, no release or orders."),indent=2))
if __name__=="__main__":main()
