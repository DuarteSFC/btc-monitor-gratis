"""CICLO LAB dataset v1. Public BTCUSDT spot, UTC; no live trading."""
import csv, hashlib, io, json, time, urllib.request, urllib.error, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal
import argparse

BASE="https://data.binance.vision/data/spot"
START=date(2020,1,1)
END=date(2026,11,26)  # exclusive, no partial UTC day
MINUTE=60000

def ms(d):
    return int(datetime(d.year,d.month,d.day,tzinfo=timezone.utc).timestamp()*1000)
def nextmonth(d):
    return date(d.year+(d.month==12), d.month%12+1,1)
def timestamp(v):
    t=int(v)
    if t>=10**14:
        if t%1000: raise ValueError("nonintegral ms")
        t//=1000
    return t
def request(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url,timeout=30) as r: return r.read()
        except urllib.error.HTTPError as e:
            if e.code==404 or attempt==3: raise
        except (OSError,TimeoutError):
            if attempt==3: raise
        time.sleep(2**attempt)
def check(raw,start,end):
    first,last=ms(start),ms(end)
    prev=first-MINUTE; gaps=[]; rows=0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.endswith(".csv")]
        if len(names)!=1: raise ValueError("unexpected zip content")
        with z.open(names[0]) as stream:
            for row in csv.reader(io.TextIOWrapper(stream,encoding="utf-8")):
                if row and row[0].lower() in ("open_time","opentime"): continue
                if len(row)<12: raise ValueError("bad row")
                t=timestamp(row[0])
                if not first<=t<last or t%MINUTE or t<=prev:
                    raise ValueError("duplicate, unordered or out-of-range candle "+str(t))
                if t>prev+MINUTE: gaps.append([prev+MINUTE,t])
                o,h,l,c,v=map(float,row[1:6])
                import math
                if not all(map(math.isfinite,(o,h,l,c,v))) or not (0<l<=min(o,c)<=max(o,c)<=h and v>=0):
                    raise ValueError("invalid OHLCV "+str(t))
                # Closing timestamps are in milliseconds or microseconds.
                ct=int(row[6]); ct=ct//1000 if ct>=10**14 else ct
                if ct!=t+MINUTE-1: raise ValueError("bad close time")
                prev=t;rows+=1
    if prev+MINUTE<last: gaps.append([prev+MINUTE,last])
    if not rows: raise ValueError("empty archive")
    missing=sum((b-a)//MINUTE for a,b in gaps)
    expected=(last-first)//MINUTE
    if rows+missing!=expected: raise ValueError("inconsistent coverage")
    return {"rows":rows,"expected":expected,"missing":missing,"gaps_utc_ms_half_open":gaps}
def one(kind,start,end,root):
    suffix=start.strftime("%Y-%m" if kind=="monthly" else "%Y-%m-%d")
    name="BTCUSDT-1m-"+suffix+".zip"
    url=f"{BASE}/{kind}/klines/BTCUSDT/1m/{name}"
    digest=request(url+".CHECKSUM").decode().split()[0].lower()
    raw=request(url)
    sha=hashlib.sha256(raw).hexdigest()
    if sha!=digest: raise ValueError("checksum mismatch "+name)
    quality=check(raw,start,end)
    p=root/name
    p.write_bytes(raw)
    return {"file":name,"url":url,"sha256":sha,"start":str(start),"end_exclusive":str(end),**quality}
def days(a,b):
    while a<b:
        yield ("daily",a,a+timedelta(days=1))
        a+=timedelta(days=1)
def fetch_window(task,root):
    kind,a,b=task
    try: return [one(kind,a,b,root)]
    except urllib.error.HTTPError as e:
        if kind!="monthly" or e.code!=404: raise
        return [one(k,x,y,root) for k,x,y in days(a,b)]
def selftest():
    a=date(2025,1,1);b=a+timedelta(days=1);t=ms(a)
    def ziprows(ts):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w") as z:
            z.writestr("test.csv","\n".join(f"{x*1000},100,102,99,101,2,{(x+MINUTE)*1000-1},0,1,0,0,0" for x in ts))
        return buf.getvalue()
    valid=range(t,ms(b),MINUTE)
    assert check(ziprows(valid),a,b)["missing"]==0
    assert check(ziprows(list(valid)[:5]+list(valid)[6:]),a,b)["missing"]==1
    for ts in ([t,t],[t+1],[ms(b)]):
        try: check(ziprows(ts),a,b)
        except ValueError: pass
        else: raise AssertionError("accepted invalid timestamps")
    print("dataset selftest PASS",flush=True)
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    selftest()
    if args.selftest:return
    root=Path("lab-dataset");root.mkdir(exist_ok=True)
    tasks=[];a=START
    while nextmonth(a)<=END:
        b=nextmonth(a);tasks.append(("monthly",a,b));a=b
    tasks.extend(days(a,END))
    results=[];errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[(task,pool.submit(fetch_window,task,root)) for task in tasks]
        for task,f in futures:
            try:
                items=f.result();results.extend(items)
                print(json.dumps({"window":str(task[1]),"files":len(items),"rows":sum(r["rows"] for r in items),"missing":sum(r["missing"] for r in items)}),flush=True)
            except Exception as e:
                errors.append({"start":str(task[1]),"end_exclusive":str(task[2]),"error":str(e)})
                print(json.dumps(errors[-1]),flush=True)
    results.sort(key=lambda x:x["start"])
    expected=(ms(END)-ms(START))//MINUTE
    rows=sum(r["rows"] for r in results)
    report={"dataset_version":"1.0","symbol":"BTCUSDT","market":"spot","interval":"1m","timezone":"UTC","start":str(START),"end_exclusive":str(END),"expected":expected,"rows":rows,"missing_total":expected-rows,"missing_in_verified_files":sum(r["missing"] for r in results),"errors":errors,"files":results,"policy":"Never forward-fill missing bars. Any feature or simulated trade spanning a gap must be invalidated."}
    (root/"manifest.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!="files"}),flush=True)
    if errors: raise SystemExit(1)
    if sum(r["expected"] for r in results)!=expected: raise SystemExit("coverage range mismatch")
if __name__=="__main__":main()
