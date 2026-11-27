"""Public spot archive only. Verify each ZIP and every timestamp before research."""
import math, calendar, csv, hashlib, io, re, sys, time, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path
MARKET=sys.argv[2] if len(sys.argv)>2 else "spot"
if MARKET not in ("spot","futures/um"): raise ValueError("unsupported market")
ROOT=f"https://data.binance.vision/data/{MARKET}/monthly/klines/BTCUSDT/1m/"
MONTHS=[f"{y}-{m:02}" for y in [2022,2023] for m in range(1,13)]+[f"2026-{m:02}" for m in range(1,10)]
OUT=Path(sys.argv[1] if len(sys.argv)>1 and sys.argv[1]!="--selftest" else "/tmp/tactical-flow")
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
def clean_rows(source,start,expected):
    rows={}
    conflicts=set()
    stats={"invalid":0,"duplicates":0,"conflicts":0,"outOfOrder":0,"examples":[]}
    prev=-1
    for row in source:
        if row and row[0].lower() in ("open_time","open time"):continue
        try:
            if len(row)!=12:raise ValueError("columns")
            t=millis(row[0]); end=millis(row[6])
            if not start<=t<start+expected*60000 or t%60000 or end!=t+59999:raise ValueError("time")
            vals=tuple(float(row[i]) for i in [1,2,3,4,5,7,8,10])
            o,h,l,c,v,q,n,buy=vals
            if not all(math.isfinite(x) for x in vals) or l<=0 or h<max(o,c) or l>min(o,c) or min(v,q,n,buy)<0 or not n.is_integer() or buy>q+1e-6:raise ValueError("values")
        except (ValueError,TypeError,OverflowError):
            stats["invalid"]+=1
            if len(stats["examples"])<5:stats["examples"].append(row[:1])
            continue
        if t<prev:stats["outOfOrder"]+=1
        prev=t
        if t in conflicts:continue
        if t in rows:
            if rows[t][0]==vals:stats["duplicates"]+=1
            else:
                conflicts.add(t);del rows[t];stats["conflicts"]+=1
            continue
        rows[t]=(vals,[t,*row[1:6],row[7],row[8],row[10]])
    return [rows[t][1] for t in sorted(rows)],stats
def selftest():
    def row(t,price=100):
        return [str(t),str(price),str(price+1),str(price-1),str(price),"1",str(t+59999),"100","1","0.5","50","0"]
    s=1600000020000
    a,st=clean_rows([row(s+60000),row(s),row(s),row(s+120000),row(s+120000,101),row(s+180001),row(s+240000)],s,5)
    assert [r[0] for r in a]==[s,s+60000,s+240000]
    assert st["duplicates"]==1 and st["conflicts"]==1 and st["invalid"]==1 and st["outOfOrder"]==1
    print("Archive selftest passed: identical duplicate, conflicting duplicate, out-of-order, invalid minute, no fabricated rows.",flush=True)
if "--selftest" in sys.argv:
    selftest()
    sys.exit(0)
for month in MONTHS:
    name=f"BTCUSDT-1m-{month}.zip"
    checksum=get(ROOT+name+".CHECKSUM",4096).decode("ascii").split()[0].lower()
    if not re.fullmatch(r"[a-f0-9]{64}",checksum):raise ValueError("bad checksum format")
    data=get(ROOT+name,20_000_000)
    if hashlib.sha256(data).hexdigest()!=checksum:raise ValueError("checksum mismatch: "+month)
    y,m=map(int,month.split("-"))
    start=int(datetime(y,m,1,tzinfo=timezone.utc).timestamp()*1000)
    expected=calendar.monthrange(y,m)[1]*1440
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members=[n for n in z.infolist() if not n.is_dir()]
        if len(members)!=1 or members[0].file_size>40_000_000:raise ValueError("unexpected archive")
        with z.open(members[0]) as src:
            rows,stats=clean_rows(csv.reader(io.TextIOWrapper(src,encoding="utf-8-sig")),start,expected)
    print(f"{MARKET} {month}: {len(rows)}/{expected} minutes; SHA256 verified; quality={stats}",flush=True)
    if len(rows)<expected*.99:raise ValueError("coverage below 99 percent: "+month)
    with (OUT/(month+".csv")).open("w",newline="") as out:
        csv.writer(out).writerows(rows)
