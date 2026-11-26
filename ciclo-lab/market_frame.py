"""CICLO LAB research: validated minute data and causal B02-B06 signals.
No production imports, trading, or network access. Research definitions v0.1.
"""
import argparse, csv, hashlib, io, json, zipfile
from pathlib import Path
import numpy as np
import pandas as pd

OHLCV = ["open","high","low","close","volume","quote"]
MINUTE = 60000

def load_minutes(root):
    root = Path(root)
    manifest = json.loads((root/"manifest.json").read_text())
    if manifest["dataset_version"] != "1.1" or manifest["errors"]:
        raise ValueError("dataset not certified; use v1.1 manifest without file errors")
    frames = []
    for item in manifest["files"]:
        path = root/item["file"]
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("checksum mismatch: "+path.name)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if n.endswith(".csv")]
            if len(names)!=1: raise ValueError("unexpected archive")
            with z.open(names[0]) as f:
                x = pd.read_csv(f, header=None, usecols=[0,1,2,3,4,5,6,7], dtype=str)
        x=x[~x[0].str.lower().isin(["open_time","opentime"])]
        t=pd.to_numeric(x[0],errors="raise").astype("int64")
        if ((t>=10**14)&(t%1000!=0)).any(): raise ValueError("nonintegral open time")
        t=t.where(t<10**14,t//1000)
        ct=pd.to_numeric(x[6],errors="raise").astype("int64")
        ct=ct.where(ct<10**14,ct//1000)
        start=pd.Timestamp(item["start"],tz="UTC").value//10**6
        end=pd.Timestamp(item["end_exclusive"],tz="UTC").value//10**6
        if ((t<start)|(t>=end)|(t%MINUTE!=0)).any() or not t.is_monotonic_increasing or t.duplicated().any():
            raise ValueError("invalid minute timestamps")
        valid=ct==t+MINUTE-1
        if int((~valid).sum())!=item["rejected_close_time"] or int(valid.sum())!=item["rows"]:
            raise ValueError("manifest row mismatch")
        y=x.loc[valid,[1,2,3,4,5,7]].astype(float)
        y.columns=OHLCV
        y.index=pd.to_datetime(t[valid].to_numpy(),unit="ms",utc=True)
        if not np.isfinite(y.to_numpy()).all() or ((y.volume<0)|(y.quote<0)|(y.low<=0)|(y.low>y[["open","close"]].min(axis=1))|(y.high<y[["open","close"]].max(axis=1))).any():
            raise ValueError("invalid prices or volume")
        frames.append(y)
    d=pd.concat(frames)
    if len(d)!=manifest["rows"] or not d.index.is_monotonic_increasing or d.index.has_duplicates:
        raise ValueError("dataset mismatch")
    return segments(d)

def segments(d):
    d=d.copy()
    d["segment"]=d.index.to_series().diff().ne(pd.Timedelta(minutes=1)).cumsum().to_numpy()
    return d

def bars(d,n):
    # Minute timestamps are OPEN times; resampled index is the CLOSE boundary.
    r=d.resample(f"{n}min",label="right",closed="left",origin="epoch")
    b=r.agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum","quote":"sum","segment":["first","last"]})
    b.columns=OHLCV+["segment","last_segment"]
    counts=r["close"].count()
    b=b.loc[(counts==n)&(b.segment==b.last_segment)].drop(columns="last_segment")
    b["segment"]=b.segment.astype("int64")
    return b

def group_apply(b,col,fn):
    return b.groupby("segment",sort=False)[col].transform(fn)
def lag(b,col,n=1):
    return b.groupby("segment",sort=False)[col].shift(n)
def ema(b,n):
    return group_apply(b,"close",lambda x:x.ewm(span=n,adjust=False,min_periods=n).mean())
def rolling(b,col,n,fn):
    return group_apply(b,col,lambda x:fn(x.rolling(n,min_periods=n)))
def wilder(b,col,n):
    # Seed explicitly with simple average of first n finite observations.
    def f(x):
        arr=x.to_numpy(dtype=float);out=np.full(len(arr),np.nan)
        finite=np.flatnonzero(np.isfinite(arr))
        if len(finite)<n:return pd.Series(out,index=x.index)
        i=finite[n-1];out[i]=arr[finite[:n]].mean()
        for k in range(i+1,len(arr)):
            if np.isfinite(arr[k]):out[k]=(out[k-1]*(n-1)+arr[k])/n
        return pd.Series(out,index=x.index)
    return group_apply(b,col,f)
def rsi(b,n=14):
    d=b.close-lag(b,"close")
    b=b.assign(gain=d.clip(lower=0),loss=(-d).clip(lower=0))
    a=wilder(b,"gain",n);z=wilder(b,"loss",n)
    return (100-100/(1+a/z)).where(z!=0,np.where(a==0,50,100))
def atr(b,n=14):
    p=lag(b,"close")
    tr=pd.concat([b.high-b.low,(b.high-p).abs(),(b.low-p).abs()],axis=1).max(axis=1)
    return wilder(b.assign(tr=tr),"tr",n)
def align(source, master, col, exact=False):
    # Only completed higher-timeframe bars, never align across a data gap.
    a=source[[col,"segment"]].reindex(master.index,method=None if exact else "ffill")
    return a[col].where(a.segment==master.segment)
def signal_frames(d):
    m=bars(d,5);q=bars(d,15);h=bars(d,60);k=bars(d,240);day=bars(d,1440)
    k["ema50"]=ema(k,50);k["ema200"]=ema(k,200)
    k["trend"]=(k.ema50>k.ema200).where(k.ema200.notna())
    h["ema20"]=ema(h,20);day["ema50"]=ema(day,50)
    q["ema20"]=ema(q,20);q["atr14"]=atr(q)
    q["prev_high"]=lag(q,"high")
    q["regime"]=align(k,q,"trend")
    q["b02"]=(q.regime==True)&(lag(q,"close")<=lag(q,"ema20"))&(q.close>q.ema20)&(q.close>q.prev_high)
    # B03: 30m return, previous 288 five-minute observations (24h).
    m["ret30"]=m.close/lag(m,"close",6)-1
    m["ret_std"]=rolling(m,"ret30",288,lambda r:r.std(ddof=1))
    m["rsi"]=rsi(m)
    m["b03"]=(m.ret30 < -2*lag(m,"ret_std"))&(lag(m,"rsi")<=30)&(m.rsi>30)
    # Exact aggregate spot VWAP: quote/base volume. Require contiguous data since UTC midnight.
    key=(m.index-pd.Timedelta(nanoseconds=1)).floor("D")
    g=m.groupby(key,sort=False)
    expected=((m.index-key)/pd.Timedelta(minutes=5)).astype(int)
    complete=(g.cumcount().to_numpy()+1)==expected
    m["vwap"]=(g.quote.cumsum()/g.volume.cumsum()).where(complete)
    above=m.close>m.vwap
    prev_same=pd.Series(key,index=m.index).eq(pd.Series(key,index=m.index).shift(1))
    same2=prev_same&prev_same.shift(1,fill_value=False)
    # Two closed bars above VWAP after a cross; not a repeated signal.
    m["b04"]=above&above.shift(1,fill_value=False)&(~above.shift(2,fill_value=False))&same2&m.vwap.shift(2).notna()&(m.segment==m.segment.shift(2))
    mean=rolling(q,"close",20,lambda r:r.mean());std=rolling(q,"close",20,lambda r:r.std(ddof=0))
    q["bandwidth"]=4*std/mean
    q["p20"]=rolling(q,"bandwidth",500,lambda r:r.quantile(.2))
    q["hi20"]=rolling(q,"high",20,lambda r:r.max())
    q["vol20"]=rolling(q,"volume",20,lambda r:r.mean())
    q["b05"]=(lag(q,"bandwidth")<lag(q,"p20",2))&(q.close>lag(q,"hi20"))&(q.volume>=1.5*lag(q,"vol20"))
    m["lo20"]=rolling(m,"low",20,lambda r:r.min());m["vol20"]=rolling(m,"volume",20,lambda r:r.mean())
    low=lag(m,"lo20")
    m["b06"]=(m.low<low)&(m.close>low)&(m.volume>=1.5*lag(m,"vol20"))
    m["b02"]=align(q,m,"b02",exact=True).eq(True)
    m["b05"]=align(q,m,"b05",exact=True).eq(True)
    m["atr15"]=align(q,m,"atr14")
    m["trend4h"]=align(k,m,"trend")
    m["ema20_1h"]=align(h,m,"ema20")
    m["ema50_1d"]=align(day,m,"ema50")
    return m

def selftest():
    idx=pd.date_range("2024-01-01",periods=180,freq="min",tz="UTC")
    d=pd.DataFrame({"open":100.,"high":101.,"low":99.,"close":100.,"volume":1.,"quote":100.},index=idx)
    d=segments(d.drop(idx[7]))
    q=bars(d,15);m=bars(d,5)
    assert pd.Timestamp("2024-01-01 00:15",tz="UTC") not in q.index
    assert pd.Timestamp("2024-01-01 00:10",tz="UTC") not in m.index
    assert q.index[0]==pd.Timestamp("2024-01-01 00:30",tz="UTC")
    q["value"]=np.arange(len(q))
    a=align(q,m,"value")
    assert pd.isna(a.loc[pd.Timestamp("2024-01-01 00:25",tz="UTC")])
    assert a.loc[q.index[0]]==0
    assert pd.isna(align(q,m,"value",exact=True).loc[q.index[0]+pd.Timedelta(minutes=5)])
    # Future prices cannot change an already closed signal frame.
    before=signal_frames(d)
    e=d.copy();e.loc[e.index>=idx[120],["open","high","low","close"]]*=2
    after=signal_frames(e)
    pd.testing.assert_frame_equal(before.loc[:idx[120]],after.loc[:idx[120]])
    assert before.loc[before.index<pd.Timestamp("2024-01-02",tz="UTC"),"vwap"].dropna().shape[0]==1
    print("Causal resampling, gap handling, exact alignment, future mutation: PASS")

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset")
    a=p.parse_args();selftest()
    if a.selftest:return
    d=load_minutes(a.dataset)
    # First development data only. 2024-26 not evaluated by this command.
    d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")]
    m=signal_frames(d)
    cols=["b02","b03","b04","b05","b06"]
    out={"minute_rows":len(d),"complete_5m_bars":len(m),"segments":int(d.segment.nunique()),"signal_counts":{c:int((m[c]&m.atr15.notna()).sum()) for c in cols},"period":"2020-2023 only","status":"signals only; no PnL; B01/B07 pending"}
    print(json.dumps(out))
    Path("lab-frame-summary.json").write_text(json.dumps(out,indent=2))
if __name__=="__main__":main()
