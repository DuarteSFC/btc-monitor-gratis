"""CF01: fixed cross-asset settled funding divergence, development only."""
import argparse,hashlib,json
from pathlib import Path
from datetime import date
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from derivatives_dataset import fetch,normalize,monthnext
from ca01_relative_strength import MONTHS,controls
from derivative_screen import load
from market_frame import segments,bars,atr,lag
from hourly_futures import make_outcomes,FEES
from validation_rehearsal import replay,utc

def acquire(month):
    a=date.fromisoformat(month+"-01");b=monthnext(a)
    url="https://data.binance.vision/data/futures/um/monthly/fundingRate/ETHUSDT/ETHUSDT-fundingRate-"+month+".zip"
    raw=fetch(url);sha=hashlib.sha256(raw).hexdigest()
    if sha!=fetch(url+".CHECKSUM").decode().split()[0].lower():raise ValueError("checksum "+month)
    rows,q=normalize("funding",raw,a,b)
    if q["duplicates"] or q["conflict_timestamps"] or q["invalid"]:raise ValueError("funding integrity "+month)
    x=pd.DataFrame([v for t,v in rows],columns=["interval_hours","rate"],index=pd.to_datetime([t for t,v in rows],unit="ms",utc=True))
    return x,dict(month=month,source=url,sha256=sha,**q)

def joint(b,e):
    def one(x,name):
        a=x.copy();a["actual"]=a.index
        a.index=a.index.floor("min")
        if a.index.has_duplicates:raise ValueError("duplicate settlement minute")
        return a.rename(columns={k:name+"_"+k for k in a.columns})
    a=one(b,"btc").join(one(e,"eth"),how="inner").sort_index()
    a=a.loc[a.btc_interval_hours.eq(8)&a.eth_interval_hours.eq(8)]
    a["diff"]=a.btc_rate-a.eth_rate
    prior=a["diff"].reindex(a.index-pd.Timedelta(hours=24)).to_numpy()
    contiguous=np.ones(len(a),dtype=bool)
    for n in [8,16,24]:contiguous&=(a.index-pd.Timedelta(hours=n)).isin(a.index)
    a["change"]=(a["diff"]-prior).where(contiguous)
    a["observed"]=a.btc_actual.where(a.btc_actual>=a.eth_actual,a.eth_actual)
    return a

def signals(h,a,delay):
    q=a[["btc_rate","diff","change","observed"]].copy()
    q.index=pd.DatetimeIndex(q.observed)+pd.Timedelta(minutes=delay)
    z=q.reindex(h.index,method="ffill",tolerance=pd.Timedelta(hours=8)-pd.Timedelta(nanoseconds=1))
    four=h.close/lag(h,"close",4)-1
    one=h.close/lag(h,"close")-1
    common=z[["btc_rate","diff","change"]].notna().all(axis=1)&four.notna()&one.notna()&h.atr1.gt(0)
    base=common&four.le(0)&one.gt(0)
    select=base&z.btc_rate.le(0)&z["diff"].le(-.00005)&z.change.le(-.00005)
    return pd.DataFrame(dict(eligible=common,base=base,selected=select),index=h.index)

def selftest():
    from validation_rehearsal import selftest as test
    test()
    t=pd.date_range("2022-01-01",periods=5,freq="8h",tz="UTC")
    b=pd.DataFrame(dict(interval_hours=8,rate=[.0001,.0001,.0001,-.0001,-.0001]),index=t)
    e=pd.DataFrame(dict(interval_hours=8,rate=.0001),index=t+pd.Timedelta(seconds=10))
    a=joint(b,e)
    assert a.change.iloc[:3].isna().all() and abs(a.change.iloc[3]+.0002)<1e-12
    assert joint(b.drop(t[1]),e).change.isna().all()
    i=pd.date_range(t[0],t[-1]+pd.Timedelta(hours=8),freq="h",tz="UTC")
    h=pd.DataFrame(dict(close=100.,segment=1,atr1=1.),index=i)
    h.loc[t[3]-pd.Timedelta(hours=4),"close"]=101.
    h.loc[t[3]-pd.Timedelta(hours=1),"close"]=99.
    h.loc[t[3]+pd.Timedelta(hours=1),"close"]=100.1
    h.loc[t[3]-pd.Timedelta(hours=3),"close"]=101.
    s=signals(h,a,30)
    assert not s.eligible.loc[t[3]] and s.selected.loc[t[3]+pd.Timedelta(hours=1)]
    e2=e.copy();e2.loc[e2.index>=t[4],"rate"]=1.
    pd.testing.assert_frame_equal(s.loc[:t[4]],signals(h,joint(b,e2),30).loc[:t[4]])
    print("CF01 matched settlement, gap, publication lag and future mutation PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    if a.selftest:return
    with ThreadPoolExecutor(max_workers=6) as pool:x=list(pool.map(acquire,MONTHS))
    eth=pd.concat([q[0] for q in x]).sort_index();manifest=[q[1] for q in x]
    assert not eth.index.has_duplicates
    print("CF_DATA="+json.dumps(dict(files=len(x),rows=len(eth),archives=manifest)),flush=True)
    results={}
    for name,root,start,end,warm in [("2022-23",a.derivatives,"2022-01-01","2024-01-01","2021-01-01"),("2026",a.extension,"2026-04-01","2026-10-01","2026-01-01")]:
        p,mark,funding=[load(root,k) for k in ["perp","mark","funding"]]
        assert p.index.min()>=utc(warm) and p.index.max()<utc(end)
        h=bars(segments(p.assign(quote=p.volume*p.close)),60)
        h["atr1"]=atr(h)*1.2
        e=eth.loc[(eth.index>=utc(warm))&(eth.index<utc(end))]
        a0=joint(funding,e)
        out={}
        for lagmin in [30,60]:
            f=signals(h,a0,lagmin)
            f=f.loc[(f.index>=utc(start))&(f.index<utc(end)-pd.Timedelta(days=1))]
            base=f.index[f.base];selected=f.index[f.selected]
            print("CF_SCOPE="+json.dumps(dict(period=name,lag=lagmin,jointSettlements=len(a0),eligible=int(f.eligible.sum()),baseSignals=len(base),signals=len(selected))),flush=True)
            out[str(lagmin)]={}
            for delay in ([1,5,15] if lagmin==30 else [1]):
                shift=pd.Timedelta(minutes=delay-1);m=h.loc[base,["atr1","segment"]].copy();m.index+=shift
                out[str(lagmin)][str(delay)]={}
                for cost in (FEES if lagmin==30 else ["stress"]):
                    y=make_outcomes(m,pd.Series(True,index=m.index),p,mark,funding,720,*FEES[cost])
                    out[str(lagmin)][str(delay)][cost]={}
                    for policy,ix in [("base",base),("CF01",selected)]:
                        r=pd.Series("12h",index=ix+shift,dtype="object")
                        q=replay(r,{"12h":{cost:y}},cost,start=start,end=end)
                        out[str(lagmin)][str(delay)][cost][policy]=q
                        print("CF_RESULT="+json.dumps(dict(period=name,lag=lagmin,policy=policy,delay=delay,cost=cost,n=q["n"],signals=q["signals"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],years=q["years"])),flush=True)
                    if lagmin==30 and delay==1 and cost=="stress":
                        c=controls(base,selected,y,out[str(lagmin)][str(delay)][cost]["CF01"]);out["controls"]=c
                        print("CF_CONTROL="+json.dumps(dict(period=name,**{k:v for k,v in c.items() if k!="draws"})),flush=True)
        results[name]=out
    Path("lab-cf01.json").write_text(json.dumps(dict(archives=manifest,results=results,limitations="One fixed relative settled funding hypothesis, reused development only. Availability lags assumed not measured, irregular schedules excluded. Funding proxy does not establish actual positions. Approximate controls, no independent validation or orders."),indent=2))
if __name__=="__main__":main()
