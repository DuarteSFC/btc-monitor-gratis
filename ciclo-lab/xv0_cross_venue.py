"""XV0: cross-venue historical hourly candle feasibility only. No strategy."""
import argparse,hashlib,io,json,zipfile,time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
import numpy as np
import pandas as pd
from derivatives_dataset import fetch

WEEKS=["2022-02-08","2022-06-08","2023-02-08","2023-06-08","2026-04-08","2026-07-08"]
PRODUCTS=["BTC-USD","USDT-USD"]
COLS=["open","high","low","close","volume"]
def utc(s):return pd.Timestamp(s,tz="UTC")
def validate(x,start,end):
    if x.index.has_duplicates or not x.index.is_monotonic_increasing:raise ValueError("invalid timestamps")
    if not (x.index==x.index.floor("h")).all():raise ValueError("off grid")
    if not np.isfinite(x[COLS].to_numpy()).all():raise ValueError("nonfinite")
    if ((x.low<=0)|(x.low>x[["open","close"]].min(axis=1))|(x.high<x[["open","close"]].max(axis=1))|(x.volume<0)).any():raise ValueError("bad OHLCV")
    return x.loc[(x.index>=start)&(x.index<end)]
def cb_parse(raw,start,end):
    a=json.loads(raw)
    if not isinstance(a,list) or any(not isinstance(r,list) or len(r)!=6 for r in a):raise ValueError("Coinbase schema")
    q=pd.DataFrame(a,columns=["time","low","high","open","close","volume"])
    q.index=pd.to_datetime(q.pop("time"),unit="s",utc=True)
    return validate(q[COLS].astype(float).sort_index(),start,end)
def coinbase(product,start,end):
    url="https://api.exchange.coinbase.com/products/"+product+"/candles?"+urlencode(dict(start=start.isoformat(),end=end.isoformat(),granularity=3600))
    with urlopen(Request(url,headers={"User-Agent":"CICLO-LAB historical research","Accept":"application/json"}),timeout=30) as r:raw=r.read()
    return cb_parse(raw,start,end),dict(source=url,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
def bn_parse(raw,start,end):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.endswith(".csv")]
        if len(names)!=1:raise ValueError("archive members")
        with z.open(names[0]) as f:q=pd.read_csv(f,header=None,usecols=list(range(7)),dtype=str)
    q=q.loc[~q[0].str.lower().isin(["open_time","opentime"])]
    t=pd.to_numeric(q[0]).astype("int64");ct=pd.to_numeric(q[6]).astype("int64")
    if (t>=10**15).all():unit="us";delta=3600000000
    elif (t<10**15).all():unit="ms";delta=3600000
    else:raise ValueError("mixed timestamp units")
    if not (ct==t+delta-1).all():raise ValueError("bad close time")
    x=q[[1,2,3,4,5]].astype(float);x.columns=COLS
    x.index=pd.to_datetime(t.to_numpy(),unit=unit,utc=True)
    return validate(x,start,end),unit
def binance(start,end):
    month=start.strftime("%Y-%m")
    url="https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-"+month+".zip"
    raw=fetch(url);sha=hashlib.sha256(raw).hexdigest()
    if sha!=fetch(url+".CHECKSUM").decode().split()[0].lower():raise ValueError("checksum")
    x,unit=bn_parse(raw,start,end)
    return x,dict(source=url,sha256=sha,bytes=len(raw),unit=unit)
def compare(b,c,u,start,end):
    ix=pd.date_range(start,end,freq="h",inclusive="left")
    q=pd.DataFrame(dict(binance=b.close,coinbase=c.close,usdtUSD=u.close)).reindex(ix)
    q["rawBps"]=(q.coinbase/q.binance-1)*10000
    q["adjustedBps"]=(q.coinbase/(q.binance*q.usdtUSD)-1)*10000
    q.index+=pd.Timedelta(hours=1)
    def stats(x):
        x=x.dropna()
        return dict(n=len(x),median=float(x.median()),p05=float(x.quantile(.05)),p95=float(x.quantile(.95)),min=float(x.min()),max=float(x.max())) if len(x) else dict(n=0)
    return q,dict(expected=len(ix),binance=len(b),coinbase=len(c),usdt=len(u),joint=int(q.adjustedBps.notna().sum()),raw=stats(q.rawBps),adjusted=stats(q.adjustedBps),usdtDeviationBps=stats((q.usdtUSD-1)*10000))
def selftest():
    t=utc("2022-02-08");end=t+pd.Timedelta(hours=2)
    raw=json.dumps([[int(t.timestamp()),100,102,101,101,2],[int((t+pd.Timedelta(hours=1)).timestamp()),101,103,102,102,3]]).encode()
    c=cb_parse(raw,t,end);b=c.copy();u=c.copy();u[COLS]=1.;u["close"]=1.01
    q,r=compare(b,c,u,t,end)
    assert r["usdt"]==2 and r["usdtDeviationBps"]["n"]==2
    assert r["joint"]==2 and q.rawBps.eq(0).all() and np.allclose(q.adjustedBps,(1/1.01-1)*10000)
    assert compare(b,c,u.iloc[:1],t,end)[1]["joint"]==1
    for scale in [1000,1000000]:
        n=int(t.timestamp())*scale;buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w") as z:z.writestr("a.csv",f"{n},101,102,100,101,2,{n+3600*scale-1}\n")
        x,unit=bn_parse(buf.getvalue(),t,end);assert len(x)==1 and x.index[0]==t
    print("XV0 timestamp units, missing data and USD adjustment PASS",flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");a=p.parse_args();selftest()
    if a.selftest:return
    root=Path("lab-xv0");root.mkdir(exist_ok=True)
    rows=[];errors=[]
    for w in WEEKS:
        start=utc(w);end=start+pd.Timedelta(days=7)
        try:
            b,bm=binance(start,end)
            c,cm=coinbase("BTC-USD",start,end);time.sleep(.4)
            u,um=coinbase("USDT-USD",start,end);time.sleep(.4)
            q,r=compare(b,c,u,start,end)
            out=root/(w+".csv");q.to_csv(out)
            r.update(week=w,sources=[bm,cm,um],file=out.name,fileSHA256=hashlib.sha256(out.read_bytes()).hexdigest())
            rows.append(r);print("XV_WEEK="+json.dumps(r),flush=True)
        except Exception as e:
            errors.append(dict(week=w,error=str(e)));print("XV_ERROR="+json.dumps(errors[-1]),flush=True)
    feasible=len(rows)==6 and not errors and all(r["joint"]/r["expected"]>=.95 for r in rows)
    d=dict(weeks=WEEKS,results=rows,errors=errors,feasible=feasible,limitations="Coinbase response digest is internal provenance, not published checksum. Hourly close premium proxy, not synchronized executable quotes or measured arrival. No return outcomes evaluated, no reserved periods.")
    (root/"manifest.json").write_text(json.dumps(d,indent=2))
    print("XV_SUMMARY="+json.dumps(dict(weeks=len(rows),joint=sum(x["joint"] for x in rows),expected=1008,errors=errors,feasible=feasible)),flush=True)
    if not feasible:raise SystemExit("XV0 source feasibility failed")
if __name__=="__main__":main()
