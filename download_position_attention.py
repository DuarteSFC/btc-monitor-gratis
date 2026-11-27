"""Download official daily USD-M futures metrics; preserve timestamp provenance and gaps."""
import calendar,csv,hashlib,io,json,math,re,sys,time,urllib.request,urllib.error,zipfile
from pathlib import Path
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
ROOT="https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/"
MONTHS=[f"2025-{m:02}" for m in [1,2,3,4,5,10,11,12]]+[f"2026-{m:02}" for m in [1,2,3]]
OUT=Path(sys.argv[1])
OUT.mkdir(parents=True,exist_ok=True)
FIELDS=["sum_open_interest","count_toptrader_long_short_ratio","sum_toptrader_long_short_ratio","count_long_short_ratio"]
def get(url,limit):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url,timeout=25) as r:
                body=r.read(limit+1)
            if len(body)>limit: raise ValueError("archive size limit")
            return body
        except urllib.error.HTTPError as e:
            if e.code==404: return None
            if attempt==2: raise
        except (OSError,TimeoutError):
            if attempt==2: raise
        time.sleep(2**attempt)
def daily(day):
    name=f"BTCUSDT-metrics-{day.date().isoformat()}.zip"
    check=get(ROOT+name+".CHECKSUM",4096)
    if check is None: return (day,[],0,"checksum unavailable")
    sha=check.decode("ascii").split()[0].lower()
    if not re.fullmatch(r"[a-f0-9]{64}",sha): raise ValueError("bad checksum")
    raw=get(ROOT+name,2_000_000)
    if raw is None:return (day,[],0,"archive unavailable")
    if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError("checksum mismatch: "+name)
    rows=[];bad=0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members=[n for n in z.infolist() if not n.is_dir()]
        if len(members)!=1 or members[0].file_size>3_000_000:raise ValueError("unexpected archive")
        with z.open(members[0]) as src:
            reader=csv.DictReader(io.TextIOWrapper(src,encoding="utf-8-sig"))
            if not set(["create_time","symbol",*FIELDS]).issubset(reader.fieldnames or []):raise ValueError("unexpected metrics schema")
            for r in reader:
                try:
                    ts=datetime.fromisoformat(r["create_time"].replace("Z","+00:00"))
                    if ts.tzinfo is None:ts=ts.replace(tzinfo=timezone.utc)
                    t=int(ts.timestamp()*1000)
                    vals=tuple(float(r[f]) for f in FIELDS)
                    if r["symbol"]!="BTCUSDT" or t%300000 or not day<=ts<=day+timedelta(days=1) or not all(math.isfinite(v) and v>0 for v in vals):
                        raise ValueError("invalid row")
                    rows.append((t,*vals))
                except (ValueError,TypeError,KeyError,OverflowError):
                    bad+=1
    return (day,rows,bad,None)
days=[]
for month in MONTHS:
    y,m=map(int,month.split("-"))
    days.extend(datetime(y,m,d,tzinfo=timezone.utc) for d in range(1,calendar.monthrange(y,m)[1]+1))
allrows={};conflicts=set();stats={m:{"days":0,"missing":0,"badRows":0,"verifiedRows":0} for m in MONTHS}
with ThreadPoolExecutor(max_workers=6) as pool:
    for day,rows,bad,err in pool.map(daily,days):
        a=stats[day.strftime("%Y-%m")];a["days"]+=1;a["missing"]+=int(err is not None);a["badRows"]+=bad;a["verifiedRows"]+=len(rows)
        for t,*vals in rows:
            vals=tuple(vals)
            if t in allrows and allrows[t]!=vals:conflicts.add(t)
            else:allrows[t]=vals
with (OUT/"metrics.csv").open("w",newline="") as f:
    w=csv.writer(f)
    for t in sorted(allrows):
        if t not in conflicts:w.writerow((t,*allrows[t]))
print(json.dumps({"archiveDays":len(days),"uniqueRows":len(allrows)-len(conflicts),"conflictingTimestampsDropped":len(conflicts),"months":stats},indent=2),flush=True)
if len(allrows)-len(conflicts)<len(days)*288*.9:raise ValueError("less than 90 percent overall archive coverage")
