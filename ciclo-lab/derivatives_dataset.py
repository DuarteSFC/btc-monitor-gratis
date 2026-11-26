"""Verified derivatives archives for development 2021-23, UTC only.
No account, orders or production dependencies. Raw archives not committed.
"""
import argparse,csv,hashlib,io,json,math,time,urllib.request,urllib.error,zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

BASE="https://data.binance.vision/data/futures/um"
START=date(2021,1,1);END=date(2024,1,1)
COLS=["sum_open_interest","sum_open_interest_value","count_toptrader_long_short_ratio","sum_toptrader_long_short_ratio","count_long_short_ratio","sum_taker_long_short_vol_ratio"]
def ms(d):return int(datetime(d.year,d.month,d.day,tzinfo=timezone.utc).timestamp()*1000)
def monthnext(d):return date(d.year+(d.month==12),d.month%12+1,1)
def fetch(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(url,timeout=25) as r:return r.read()
        except urllib.error.HTTPError as e:
            if e.code==404 or i==2:raise
        except (OSError,TimeoutError):
            if i==2:raise
        time.sleep(2**i)
def rows(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.endswith(".csv")]
        if len(names)!=1:raise ValueError("unexpected archive members")
        with z.open(names[0]) as f:yield from csv.reader(io.TextIOWrapper(f,encoding="utf-8"))
def number(v,allow_empty=False):
    if allow_empty and not v.strip():return None
    n=float(v)
    if not math.isfinite(n):raise ValueError("nonfinite numeric value")
    return n
def normalize(kind,raw,a,b):
    start,end=ms(a),ms(b);seen={};conflicts=set();duplicates=outside=invalid=0
    iterator=iter(rows(raw))
    header=next(iterator,None)
    if not header:raise ValueError("empty archive")
    if kind in ("perp","mark"):
        if header[0]!="open_time":
            from itertools import chain
            iterator=chain([header],iterator)
        for r in iterator:
            try:
                t=int(r[0]);ct=int(r[6]);v=tuple(number(x) for x in r[1:6])
                if not start<=t<end:outside+=1;continue
                o,h,l,c,vol=v
                if t%60000 or ct!=t+59999 or not 0<l<=min(o,c)<=max(o,c)<=h or vol<0:raise ValueError()
            except (ValueError,IndexError):invalid+=1;continue
            if t in seen:
                duplicates+=1
                if seen[t]!=v:conflicts.add(t)
            else:seen[t]=v
    elif kind=="funding":
        if header!=["calc_time","funding_interval_hours","last_funding_rate"]:raise ValueError("funding schema mismatch")
        for r in iterator:
            try:
                t=int(r[0]);v=(int(r[1]),number(r[2]))
                # Preserve actual settlement timestamp. Boundary spillovers ignored here,
                # and reported; each calendar month has its own source.
                if not start<=t<end:outside+=1;continue
                if not 0<v[0]<=24 or abs(v[1])>=1:raise ValueError()
            except (ValueError,IndexError):invalid+=1;continue
            if t in seen:
                duplicates+=1
                if seen[t]!=v:conflicts.add(t)
            else:seen[t]=v
    else:
        expected=["create_time","symbol"]+COLS
        if header!=expected:raise ValueError("metrics schema mismatch")
        for r in iterator:
            try:
                t=int(datetime.fromisoformat(r[0]).replace(tzinfo=timezone.utc).timestamp()*1000)
                if not start<=t<end:outside+=1;continue
                if r[1]!="BTCUSDT" or t%300000:raise ValueError()
                v=tuple(number(x,True) for x in r[2:])
                if len(v)!=6 or v[0] is None or v[0]<=0 or any(x is not None and x<0 for x in v):raise ValueError()
            except (ValueError,IndexError):invalid+=1;continue
            if t in seen:
                duplicates+=1
                if seen[t]!=v:conflicts.add(t)
            else:seen[t]=v
    for t in conflicts:seen.pop(t,None)
    if not seen:raise ValueError("no valid rows")
    expected_count=(end-start)//(60000 if kind in ("perp","mark") else 300000) if kind!="funding" else None
    return sorted(seen.items()),dict(rows=len(seen),expected_grid=expected_count,duplicates=duplicates,conflict_timestamps=len(conflicts),invalid=invalid,outside=outside)
def task(kind,a,b,root):
    day=str(a);month=day[:7]
    if kind in ("perp","mark"):
        group="klines" if kind=="perp" else "markPriceKlines"
        path=f"monthly/{group}/BTCUSDT/1m/BTCUSDT-1m-{month}.zip"
    elif kind=="funding":path=f"monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{month}.zip"
    else:path=f"daily/metrics/BTCUSDT/BTCUSDT-metrics-{day}.zip"
    url=BASE+"/"+path;item=dict(kind=kind,start=day,end_exclusive=str(b),url=url)
    try:
        expected=fetch(url+".CHECKSUM").decode().split()[0].lower()
        raw=fetch(url);digest=hashlib.sha256(raw).hexdigest()
        if digest!=expected:raise ValueError("checksum mismatch")
        data,q=normalize(kind,raw,a,b)
        name=f"{kind}-{day}.csv"
        with (root/name).open("w",newline="") as f:
            w=csv.writer(f);w.writerow(["time_ms"]+({"perp":["open","high","low","close","volume"],"mark":["open","high","low","close","volume"],"funding":["interval_hours","rate"],"metrics":COLS}[kind]))
            w.writerows((t,*v) for t,v in data)
        item.update(status="ok",source_sha256=digest,file=name,file_sha256=hashlib.sha256((root/name).read_bytes()).hexdigest(),**q)
    except Exception as e:item.update(status="error",error=str(e))
    return item
def selftest():
    a=date(2022,1,1);b=a+timedelta(days=1);t=ms(a)
    def zipped(lines):
        x=io.BytesIO()
        with zipfile.ZipFile(x,"w") as z:z.writestr("a.csv",lines)
        return x.getvalue()
    raw=zipped("\n".join(f"{u},100,102,99,101,2,{u+59999},0,1,0,0,0" for u in [t,t,t+60000]))
    r,q=normalize("perp",raw,a,b);assert len(r)==2 and q["duplicates"]==1
    raw=zipped(",".join(["create_time","symbol"]+COLS)+"\n2022-01-01 00:00:00,BTCUSDT,100,10000,,,1,1\n2022-01-01 00:05:00,BTCUSDT,101,10000,,,1,1\n2022-01-01 00:05:00,BTCUSDT,102,10000,,,1,1")
    r,q=normalize("metrics",raw,a,b);assert len(r)==1 and q["conflict_timestamps"]==1 and r[0][1][2] is None
    print("Derivatives schema, duplicate and conflict tests PASS",flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");a=p.parse_args();selftest()
    if a.selftest:return
    root=Path("lab-derivatives");root.mkdir(exist_ok=True)
    jobs=[];d=START
    while d<END:
        e=monthnext(d)
        for k in ["perp","mark","funding"]:jobs.append((k,d,e))
        d=e
    d=START
    while d<END:
        e=d+timedelta(days=1);jobs.append(("metrics",d,e));d=e
    result=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i,r in enumerate(pool.map(lambda x:task(*x,root),jobs)):
            result.append(r)
            if (i+1)%100==0 or r["status"]!="ok":print(json.dumps(dict(processed=i+1,total=len(jobs),last=r if r["status"]!="ok" else r["kind"])),flush=True)
    summary={}
    for k in ["perp","mark","funding","metrics"]:
        allk=[r for r in result if r["kind"]==k];ok=[r for r in allk if r["status"]=="ok"]
        summary[k]=dict(files=len(allk),verified=len(ok),rows=sum(r["rows"] for r in ok),duplicates=sum(r["duplicates"] for r in ok),conflicts=sum(r["conflict_timestamps"] for r in ok),invalid=sum(r["invalid"] for r in ok),outside=sum(r["outside"] for r in ok),errors=[{x:r[x] for x in ["start","error"]} for r in allk if r["status"]!="ok"])
    manifest=dict(version="1.0",period="2021-2023 development only",summary=summary,files=result,policy="No forward filling across unavailable files or conflicting rows. Futures 1m opens/close boundaries; metrics publication time unknown: conservative lag required in experiments; funding actual settlement timestamp retained, not future known rate. Missing files not fabricated.")
    (root/"manifest.json").write_text(json.dumps(manifest,indent=2))
    print("DERIVATIVES_DATASET="+json.dumps(summary),flush=True)
    if any(summary[k]["verified"]==0 for k in summary):raise SystemExit("missing entire source")
if __name__=="__main__":main()
