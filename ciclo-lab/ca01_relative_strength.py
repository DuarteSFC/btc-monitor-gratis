"""CA01: fixed ETH relative-strength/BTC pullback hypothesis. Development only."""
import argparse,hashlib,io,json,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from derivatives_dataset import fetch
from derivative_screen import load
from market_frame import segments,bars,atr,ema,lag
from hourly_futures import make_outcomes,FEES
from validation_rehearsal import replay,utc
from ms01_absorption import fast

BASE="https://data.binance.vision/data/futures/um/monthly/klines/ETHUSDT/1h/"
MONTHS=[f"{y}-{m:02d}" for y in [2021,2022,2023] for m in range(1,13)]+[f"2026-{m:02d}" for m in range(1,10)]
def parse(raw,month):
    start=utc(month+"-01");end=start+pd.offsets.MonthBegin(1)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.endswith(".csv")]
        if len(names)!=1:raise ValueError("archive schema")
        with z.open(names[0]) as f:q=pd.read_csv(f,header=None,usecols=[0,1,2,3,4,5,6],dtype=str)
    q=q.loc[~q[0].str.lower().isin(["open_time","opentime"])]
    t=pd.to_numeric(q[0]).astype("int64");ct=pd.to_numeric(q[6]).astype("int64")
    if not (ct==t+3599999).all():raise ValueError("invalid closed timestamp")
    x=q[[1,2,3,4,5]].astype(float);x.columns=["open","high","low","close","volume"]
    x.index=pd.to_datetime(t.to_numpy(),unit="ms",utc=True)
    expected=pd.date_range(start,end,freq="h",inclusive="left")
    pd.testing.assert_index_equal(x.index,expected,check_names=False)
    if not np.isfinite(x.to_numpy()).all() or ((x.low<=0)|(x.low>x[["open","close"]].min(axis=1))|(x.high<x[["open","close"]].max(axis=1))|(x.volume<0)).any():raise ValueError("invalid OHLCV")
    x.index+=pd.Timedelta(hours=1)
    return x

def acquire(month):
    url=BASE+"ETHUSDT-1h-"+month+".zip";raw=fetch(url);sha=hashlib.sha256(raw).hexdigest()
    if sha!=fetch(url+".CHECKSUM").decode().split()[0].lower():raise ValueError("checksum "+month)
    x=parse(raw,month)
    return x,dict(month=month,source=url,sha256=sha,rows=len(x))

def conditions(h,e):
    e=e.copy()
    # Gap segments reset at nonconsecutive hourly closes.
    e["segment"]=e.index.to_series().diff().ne(pd.Timedelta(hours=1)).cumsum().to_numpy()
    er=e.close/lag(e,"close",4)-1
    br=h.close/lag(h,"close",4)-1
    one=h.close/lag(h,"close")-1
    a=ema(h,48);b=ema(h,168)
    er=er.reindex(h.index)
    common=a.notna()&b.notna()&br.notna()&one.notna()&er.notna()&h.atr1.notna()&h.atr1.gt(0)
    base=common&h.close.gt(b)&a.gt(b)&br.le(0)&one.gt(0)
    return pd.DataFrame(dict(eligible=common,base=base,selected=base&er.ge(.01)&(er-br).ge(.005)),index=h.index)

def controls(base,selected,y,observed):
    z=pd.DataFrame(dict(month=base.strftime("%Y-%m"),session=base.hour//6),index=base)
    groups=[]
    for _,g in z.groupby(["month","session"]):
        n=int(g.index.isin(selected).sum())
        if n:groups.append((g.index.as_unit("ns").asi8,n))
    assert sum(n for _,n in groups)==len(selected)
    lookup={t.value:(v.R,v.riskFraction,int(v.exit)) for t,v in y.iterrows()}
    orig=fast(selected.as_unit("ns").asi8,lookup)
    assert orig["n"]==observed["n"] and orig["unknown"]==observed["unknown"]
    np.testing.assert_allclose(orig["equity"],observed["equity"],rtol=1e-10,atol=1e-10)
    rng=np.random.default_rng(20261127);out=[]
    for _ in range(199):
        t=np.sort(np.concatenate([rng.choice(ix,size=n,replace=False) for ix,n in groups])) if groups else np.array([],dtype=np.int64)
        out.append(fast(t,lookup))
    valid=[q for q in out if q["mean"] is not None and not q["unknown"]]
    movable=sum(len(ix)>n for ix,n in groups)
    p=(1+sum(q["mean"]>=observed["mean"] for q in valid))/200 if len(valid)==199 and observed["mean"] is not None and not observed["unknown"] and movable else None
    return dict(draws=out,valid=len(valid),movableStrata=movable,totalStrata=len(groups),medianMean=float(np.median([q["mean"] for q in valid])) if valid else None,pRelative=p)

def selftest():
    from validation_rehearsal import selftest as test
    test()
    t=pd.date_range("2022-01-01","2022-02-01",freq="h",inclusive="left",tz="UTC")
    ms=t.asi8//1000000;b=io.BytesIO()
    with zipfile.ZipFile(b,"w") as z:z.writestr("a.csv","\n".join(f"{u},100,101,99,100,10,{u+3599999}" for u in ms))
    e=parse(b.getvalue(),"2022-01");assert len(e)==744 and e.index[0]==t[0]+pd.Timedelta(hours=1)
    h=e.assign(segment=1,atr1=1.);h.close=100+np.arange(len(h))*.1
    j=250;h.loc[h.index[j-4:j+1],"close"]=[125.2,125.0,124.9,124.8,125.0]
    e.loc[e.index[j],"close"]=102.
    q=conditions(h,e);assert q.selected.iloc[j]
    h2=h.copy();h2.loc[h2.index[j+1]:,"close"]=1000.
    pd.testing.assert_frame_equal(q.iloc[:j+1],conditions(h2,e).iloc[:j+1])
    print("CA01 verified hourly closure, positive cross-asset event and future mutation PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args();selftest()
    if a.selftest:return
    with ThreadPoolExecutor(max_workers=6) as pool:
        x=list(pool.map(acquire,MONTHS))
    eth=pd.concat([q[0] for q in x]);manifest=[q[1] for q in x];assert not eth.index.has_duplicates and eth.index.is_monotonic_increasing
    print("CA_DATA="+json.dumps(dict(files=len(x),rows=len(eth),archives=manifest)),flush=True)
    results={}
    for name,root,start,end,warm in [("2022-23",a.derivatives,"2022-01-01","2024-01-01","2021-01-01"),("2026",a.extension,"2026-04-01","2026-10-01","2026-01-01")]:
        p,mark,funding=[load(root,k) for k in ["perp","mark","funding"]]
        assert p.index.min()>=utc(warm) and p.index.max()<utc(end)
        h=bars(segments(p.assign(quote=p.volume*p.close)),60)
        h["atr1"]=atr(h)*1.2
        e=eth.loc[(eth.index>utc(warm))&(eth.index<=utc(end))]
        f=conditions(h,e)
        f=f.loc[(f.index>=utc(start))&(f.index<utc(end)-pd.Timedelta(days=1))]
        base=f.index[f.base];selected=f.index[f.selected]
        print("CA_SCOPE="+json.dumps(dict(period=name,eligible=int(f.eligible.sum()),baseSignals=len(base),signals=len(selected))),flush=True)
        out={}
        for delay in [1,5,15]:
            out[str(delay)]={}
            shift=pd.Timedelta(minutes=delay-1)
            m=h.loc[base,["atr1","segment"]].copy();m.index+=shift
            for cost in FEES:
                y=make_outcomes(m,pd.Series(True,index=m.index),p,mark,funding,720,*FEES[cost])
                out[str(delay)][cost]={}
                for policy,ix in [("base",base),("CA01",selected)]:
                    r=pd.Series("12h",index=ix+shift,dtype="object")
                    q=replay(r,{"12h":{cost:y}},cost,start=start,end=end)
                    out[str(delay)][cost][policy]=q
                    print("CA_RESULT="+json.dumps(dict(period=name,policy=policy,delay=delay,cost=cost,n=q["n"],signals=q["signals"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],years=q["years"])),flush=True)
                if delay==1 and cost=="stress":
                    c=controls(base,selected,y,out[str(delay)][cost]["CA01"]);out["controls"]=c
                    print("CA_CONTROL="+json.dumps(dict(period=name,**{k:v for k,v in c.items() if k!="draws"})),flush=True)
        results[name]=out
    Path("lab-ca01.json").write_text(json.dumps(dict(archives=manifest,results=results,limitations="One fixed cross-asset risk-appetite hypothesis, 12h execution, no model fitting. ETH hourly bars assume availability after closure, no measured real-time delay; 2026 already explored; approximate matched controls, not independent validation or proof of edge. No holdout or orders."),indent=2))
if __name__=="__main__":main()
