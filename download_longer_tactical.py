"""Public spot archive only. Verify each ZIP and every timestamp before research."""
import calendar, csv, hashlib, io, re, sys, time, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path
MARKET=sys.argv[2] if len(sys.argv)>2 else "spot"
if MARKET not in ("spot","futures/um"): raise ValueError("unsupported market")
ROOT=f"https://data.binance.vision/data/{MARKET}/monthly/klines/BTCUSDT/1m/"
MONTHS=[f"2024-{m:02}" for m in range(1,13)]+[f"2026-{m:02}" for m in [7,8,9]]
OUT=Path(sys.argv[1] if len(sys.argv)>1 else "/tmp/tactical-flow")
OUT.mkdir(parents=True,exist_ok=True)
def get(url,limit):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url,timeout=35) as r:
                body=r.read(limit+1)
            if len(body)>limit: raise ValueError("archive size limit")
            return body
        except Exception:
            if attempt==2: raise
            time.sleep(2**attempt)
def millis(s):
    v=int(s)
    return v//1000 if v>=10**15 else v
for month in MONTHS:
    name=f"BTCUSDT-1m-{month}.zip"
    checksum=get(ROOT+name+".CHECKSUM",4096).decode("ascii").split()[0].lower()
    if not re.fullmatch(r"[a-f0-9]{64}",checksum): raise ValueError("bad checksum format")
    data=get(ROOT+name,20_000_000)
    if hashlib.sha256(data).hexdigest()!=checksum: raise ValueError("checksum mismatch: "+month)
    y,m=map(int,month.split("-"))
    start=int(datetime(y,m,1,tzinfo=timezone.utc).timestamp()*1000)
    expected=calendar.monthrange(y,m)[1]*1440
    count=0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members=[n for n in z.infolist() if not n.is_dir()]
        if len(members)!=1 or members[0].file_size>40_000_000: raise ValueError("unexpected archive")
        with z.open(members[0]) as src, (OUT/(month+".csv")).open("w",newline="") as out:
            w=csv.writer(out)
            for row in csv.reader(io.TextIOWrapper(src,encoding="utf-8-sig")):
                if not count and row and row[0].lower() in ("open_time","open time"): continue
                if len(row)!=12: raise ValueError("unexpected archive columns")
                t=millis(row[0]); end=millis(row[6])
                if t!=start+count*60000 or end!=t+59999: raise ValueError("gap or invalid close: "+month)
                # Retain exact public source quantities. Validation of finite ranges is in JS.
                w.writerow([t,*row[1:6],row[7],row[8],row[10]])
                count+=1
    if count!=expected: raise ValueError("incomplete month: "+month)
    print(f"{MARKET} {month}: {count} contiguous minutes, SHA256 verified",flush=True)
