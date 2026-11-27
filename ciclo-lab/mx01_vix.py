"""MX01: preregistered external VIX context, development only."""
import argparse,hashlib,io,json
from pathlib import Path
import numpy as np
import pandas as pd
from derivatives_dataset import fetch
from derivative_screen import load
from market_frame import segments,bars,atr,lag
from hourly_futures import make_outcomes,FEES
from validation_rehearsal import replay,utc
from ca01_relative_strength import controls

URL="https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
def scoped(raw,start,end):
    a=pd.read_csv(io.BytesIO(raw))
    a.columns=[str(c).strip().upper() for c in a.columns]
    a.index=pd.to_datetime(a.DATE,format="%m/%d/%Y",utc=True)
    a=a.loc[(a.index>=utc(start))&(a.index<utc(end)),["CLOSE"]].sort_index()
    if a.index.has_duplicates or a.empty:raise ValueError("invalid VIX dates")
    a["CLOSE"]=pd.to_numeric(a.CLOSE,errors="raise")
    if not np.isfinite(a.CLOSE).all() or not a.CLOSE.gt(0).all():raise ValueError("invalid VIX closes")
    counts=a.CLOSE.groupby(a.index.strftime("%Y-%m")).size()
    expected=pd.date_range(utc(start),utc(end),freq="MS",inclusive="left").strftime("%Y-%m")
    if not counts.reindex(expected).fillna(0).ge(15).all():raise ValueError("incomplete VIX source: "+str(counts.to_dict()))
    a["prior5"]=a.CLOSE.shift(5)
    return a,counts.to_dict()

def signals(h,a,days):
    q=a.copy();q["observed"]=q.index
    q.index+=pd.Timedelta(days=days)
    z=q.reindex(h.index,method="ffill",tolerance=pd.Timedelta(days=7-days)-pd.Timedelta(nanoseconds=1))
    four=h.close/lag(h,"close",4)-1
    one=h.close/lag(h,"close")-1
    common=z[["CLOSE","prior5"]].notna().all(axis=1)&four.notna()&one.notna()&h.atr1.gt(0)
    base=common&four.le(0)&one.gt(0)
    return pd.DataFrame(dict(eligible=common,base=base,selected=base&z.CLOSE.lt(20)&z.CLOSE.lt(z.prior5)),index=h.index)

def selftest():
    from validation_rehearsal import selftest as test
    test()
    t=pd.date_range("2022-01-03",periods=21,freq="B",tz="UTC")
    raw=("DATE,CLOSE\n"+"\n".join(f"{d.strftime('%m/%d/%Y')},{30-i}" for i,d in enumerate(t) if d.month==1)).encode()
    a,_=scoped(raw,"2022-01-01","2022-02-01")
    k=a.index[12]+pd.Timedelta(days=2)
    i=pd.date_range(k-pd.Timedelta(hours=8),k+pd.Timedelta(hours=8),freq="h",tz="UTC")
    h=pd.DataFrame(dict(close=100.,segment=1,atr1=1.),index=i)
    h.loc[k-pd.Timedelta(hours=4),"close"]=101.
    h.loc[k-pd.Timedelta(hours=1),"close"]=99.
    s=signals(h,a,2)
    assert s.selected.loc[k]
    b=a.copy();b.loc[b.index>k-pd.Timedelta(days=2),"CLOSE"]=99.
    pd.testing.assert_frame_equal(s.loc[:k],signals(h,b,2).loc[:k])
    print("MX01 scoped daily observations, publication embargo and future mutation PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    if a.selftest:return
    raw=fetch(URL);digest=hashlib.sha256(raw).hexdigest()
    results={};source={}
    for name,root,start,end,warm in [("2022-23",a.derivatives,"2022-01-01","2024-01-01","2021-01-01"),("2026",a.extension,"2026-04-01","2026-10-01","2026-01-01")]:
        vix,counts=scoped(raw,warm,end);source[name]=dict(rows=len(vix),monthly=counts)
        print("MX_DATA="+json.dumps(dict(period=name,source=URL,sha256=digest,rows=len(vix),monthly=counts)),flush=True)
        p,mark,funding=[load(root,k) for k in ["perp","mark","funding"]]
        assert p.index.min()>=utc(warm) and p.index.max()<utc(end)
        h=bars(segments(p.assign(quote=p.volume*p.close)),60)
        h["atr1"]=atr(h)*1.2
        out={}
        for days in [2,3]:
            f=signals(h,vix,days)
            f=f.loc[(f.index>=utc(start))&(f.index<utc(end)-pd.Timedelta(days=1))]
            base=f.index[f.base];selected=f.index[f.selected]
            print("MX_SCOPE="+json.dumps(dict(period=name,lagDays=days,eligible=int(f.eligible.sum()),baseSignals=len(base),signals=len(selected))),flush=True)
            out[str(days)]={}
            for delay in ([1,5,15] if days==2 else [1]):
                shift=pd.Timedelta(minutes=delay-1);m=h.loc[base,["atr1","segment"]].copy();m.index+=shift
                out[str(days)][str(delay)]={}
                for cost in (FEES if days==2 else ["stress"]):
                    y=make_outcomes(m,pd.Series(True,index=m.index),p,mark,funding,720,*FEES[cost])
                    out[str(days)][str(delay)][cost]={}
                    for policy,ix in [("base",base),("MX01",selected)]:
                        r=pd.Series("12h",index=ix+shift,dtype="object")
                        q=replay(r,{"12h":{cost:y}},cost,start=start,end=end)
                        out[str(days)][str(delay)][cost][policy]=q
                        print("MX_RESULT="+json.dumps(dict(period=name,lagDays=days,policy=policy,delay=delay,cost=cost,n=q["n"],signals=q["signals"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],years=q["years"])),flush=True)
                    if days==2 and delay==1 and cost=="stress":
                        c=controls(base,selected,y,out[str(days)][str(delay)][cost]["MX01"]);out["controls"]=c
                        print("MX_CONTROL="+json.dumps(dict(period=name,**{k:v for k,v in c.items() if k!="draws"})),flush=True)
        results[name]=out
    Path("lab-mx01.json").write_text(json.dumps(dict(source=dict(url=URL,sha256=digest,scopes=source),results=results,limitations="Cboe daily historical data, no point-in-time vintage guarantee; conservative calendar lag assumed, no measured receipt time. Reused development; controls approximate. No independent validation or orders."),indent=2))
if __name__=="__main__":main()
