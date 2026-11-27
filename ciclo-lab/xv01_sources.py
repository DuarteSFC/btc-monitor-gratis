"""XV01 source repair: verified raw archives only; no fabricated timestamps or prices."""
import hashlib,io,zipfile,json,time
from urllib.error import HTTPError,URLError
import numpy as np
import pandas as pd

COLS=["open","high","low","close","volume"]
def parse(raw,start,end,minutes=60):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.endswith(".csv")]
        if len(names)!=1:raise ValueError("archive schema")
        with z.open(names[0]) as f:q=pd.read_csv(f,header=None,usecols=list(range(7)),dtype=str)
    q=q.loc[~q[0].str.lower().isin(["open_time","opentime"])].copy()
    t=pd.to_numeric(q[0],errors="coerce");ct=pd.to_numeric(q[6],errors="coerce")
    valid_ts=t.notna()&(t%1==0)
    if not valid_ts.any():raise ValueError("no valid timestamp")
    if (t[valid_ts]>=10**15).all():unit="us";scale=1000000
    elif (t[valid_ts]<10**15).all():unit="ms";scale=1000
    else:raise ValueError("mixed timestamp units")
    delta=minutes*60*scale
    aligned=valid_ts&(t%delta==0)
    close_ok=ct.eq(t+delta-1)
    x=q[[1,2,3,4,5]].apply(pd.to_numeric,errors="coerce");x.columns=COLS
    prices=np.isfinite(x).all(axis=1)&x.low.gt(0)&x.low.le(x[["open","close"]].min(axis=1))&x.high.ge(x[["open","close"]].max(axis=1))&x.volume.ge(0)
    dup=t.duplicated(keep=False)&valid_ts
    keep=aligned&close_ok&prices&~dup
    x=x.loc[keep].copy()
    x.index=pd.to_datetime(t.loc[keep].astype("int64").to_numpy(),unit=unit,utc=True)
    x=x.sort_index();outside=int(((x.index<start)|(x.index>=end)).sum())
    x=x.loc[(x.index>=start)&(x.index<end)]
    audit=dict(rows=int(len(q)),valid=int(len(x)),unit=unit,badOpen=int((~aligned).sum()),badClose=int((aligned&~close_ok).sum()),badOHLCV=int((~prices).sum()),duplicateRows=int(dup.sum()),outside=outside,invalidExamples=[dict(open=str(a),close=str(b)) for a,b in zip(q.loc[~keep,0].head(5),q.loc[~keep,6].head(5))])
    return x,audit

def hourly(x):
    g=x.resample("h",closed="left",label="left")
    y=g.agg(dict(open="first",high="max",low="min",close="last",volume="sum"))
    return y.loc[g.close.count().eq(60)]

def fetch_verified(url,start,end,minutes):
    from derivatives_dataset import fetch
    raw=fetch(url);digest=hashlib.sha256(raw).hexdigest()
    if digest!=fetch(url+".CHECKSUM").decode().split()[0].lower():raise ValueError("checksum "+url)
    x,audit=parse(raw,start,end,minutes)
    return x,dict(source=url,sha256=digest,bytes=len(raw),**audit)

def merge_verified(x,d,missing):
    overlap=x.index.intersection(d.index)
    if len(overlap) and not np.allclose(x.loc[overlap,COLS],d.loc[overlap,COLS],rtol=1e-8,atol=1e-8):
        raise ValueError("daily/monthly conflict")
    add=d.loc[d.index.intersection(missing)]
    return pd.concat([x,add]).sort_index(),int(len(add))

def binance(start,end):
    prefix="https://data.binance.vision/data/spot/"
    month=start.strftime("%Y-%m")
    x,audit=fetch_verified(prefix+"monthly/klines/BTCUSDT/1h/BTCUSDT-1h-"+month+".zip",start,end,60)
    expected=pd.date_range(start,end,freq="h",inclusive="left")
    repairs=[]
    for day in expected.difference(x.index).floor("D").unique():
        stop=day+pd.Timedelta(days=1)
        for resolution,minutes in [("1h",60),("1m",1)]:
            missing=expected.difference(x.index)
            if not ((missing>=day)&(missing<stop)).any():break
            url=prefix+f"daily/klines/BTCUSDT/{resolution}/BTCUSDT-{resolution}-"+day.strftime("%Y-%m-%d")+".zip"
            try:
                d,r=fetch_verified(url,day,stop,minutes)
                if minutes==1:d=hourly(d)
                x,n=merge_verified(x,d,missing)
                repairs.append(dict(**r,recovered=n))
            except Exception as e:
                repairs.append(dict(source=url,error=str(e),recovered=0))
    assert x.index.is_unique and x.index.is_monotonic_increasing
    audit.update(repairs=repairs,remainingMissing=int(len(expected.difference(x.index))),recovered=int(len(x)-audit["valid"]))
    print("XV01_BINANCE_AUDIT="+json.dumps(dict(month=month,**audit)),flush=True)
    return x,audit

def coinbase(product,start,end):
    from xv0_cross_venue import coinbase as request
    for attempt in range(4):
        try:return request(product,start,end)
        except HTTPError as e:
            if e.code not in [429,500,502,503,504] or attempt==3:raise
        except (URLError,TimeoutError,ConnectionError):
            if attempt==3:raise
        time.sleep(2**attempt)

def selftest():
    t=pd.Timestamp("2021-08-01",tz="UTC");end=t+pd.Timedelta(hours=4)
    for scale in [1000,1000000]:
        n=int(t.timestamp())*scale;delta=3600*scale
        def row(i,close):return f"{n+i*delta},100,102,99,101,2,{close}"
        lines=[row(0,n+delta-1),row(1,n+2*delta-2),row(2,n+3*delta-1),row(2,n+3*delta-1),row(3,n+4*delta-1)]
        b=io.BytesIO()
        with zipfile.ZipFile(b,"w") as z:z.writestr("a.csv","\n".join(lines))
        x,a=parse(b.getvalue(),t,end)
        assert len(x)==2 and a["badClose"]==1 and a["duplicateRows"]==2
        assert list(x.index)==[t,t+pd.Timedelta(hours=3)]
    i=pd.date_range(t,periods=120,freq="min")
    d=pd.DataFrame(dict(open=100.,high=102.,low=99.,close=101.,volume=2.),index=i)
    h=hourly(d);assert len(h)==2 and h.volume.eq(120.).all()
    assert len(hourly(d.drop(i[10])))==1
    merged,n=merge_verified(h.iloc[:1],h,h.index[1:]);assert n==1 and merged.equals(h)
    bad=h.copy();bad.iloc[0,0]=99.
    try:merge_verified(h.iloc[:1],bad,h.index[1:])
    except ValueError:pass
    else:raise AssertionError("conflicting repair accepted")
    print("XV01 source validation: invalid closes, duplicate timestamps, complete-minute reconstruction and conflict rejection PASS",flush=True)
if __name__=="__main__":selftest()
