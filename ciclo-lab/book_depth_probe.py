"""BD01: fixed-date book-depth archive feasibility, no returns or orders."""
import argparse,csv,hashlib,io,json,math,zipfile
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.error import HTTPError
from derivatives_dataset import BASE,fetch

DATES=[date(y,m,d) for y,months in [(2023,range(1,13)),(2026,range(2,11))] for m in months for d in (1,15)]

def stamp(s):
    if s.isdigit():
        n=int(s)
        if n>=10**14:raise ValueError('unsupported precision')
        return datetime.fromtimestamp(n/1000 if n>=10**12 else n,timezone.utc),'epoch'
    t=datetime.fromisoformat(s.replace('Z','+00:00'))
    return (t.replace(tzinfo=timezone.utc),'naive_assumed_UTC') if t.tzinfo is None else (t.astimezone(timezone.utc),'offset')

def inspect(raw,day):
    by=defaultdict(dict);bad=set();invalid=duplicates=conflicts=0;enc=Counter();levels=Counter();examples=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.endswith('.csv')]
        if len(names)!=1:raise ValueError('unexpected archive members')
        with z.open(names[0]) as f:
            r=csv.DictReader(io.TextIOWrapper(f,encoding='utf-8-sig'))
            if r.fieldnames!=['timestamp','percentage','depth','notional']:raise ValueError('unexpected schema '+str(r.fieldnames))
            for row in r:
                try:
                    t,e=stamp(row['timestamp']);p,d,n=map(float,(row['percentage'],row['depth'],row['notional']))
                    if t.date()!=day or not all(map(math.isfinite,(p,d,n))) or p==0 or d<0 or n<0:raise ValueError('invalid level')
                except (ValueError,TypeError,OverflowError,OSError):
                    invalid+=1
                    if len(examples)<5:examples.append(row)
                    continue
                enc[e]+=1;key=(t,p)
                if key in bad:duplicates+=1;continue
                if p in by[t]:
                    duplicates+=1
                    if by[t][p]!=(d,n):conflicts+=1;bad.add(key);del by[t][p]
                else:by[t][p]=(d,n)
    ts=sorted(t for t,v in by.items() if v);paired=mono=0
    for t in ts:
        v=by[t];levels.update(v.keys());paired+=int(-1. in v and 1. in v)
        sides=[sorted((abs(p),v[p][0]) for p in v if p*sign>0) for sign in (-1,1)]
        mono+=int(all(len(a)>=2 and all(x[1]<=y[1] for x,y in zip(a,a[1:])) for a in sides))
    gaps=[(b-a).total_seconds() for a,b in zip(ts,ts[1:])]
    return dict(snapshots=len(ts),rows=sum(levels.values()),invalid=invalid,duplicates=duplicates,conflicts=conflicts,encodings=dict(enc),levels=dict(levels),paired1pct=paired,monotoneBoth=mono,maxGapSec=max(gaps,default=None),gapsOver120s=sum(x>120 for x in gaps),first=ts[0].isoformat() if ts else None,last=ts[-1].isoformat() if ts else None,invalidExamples=examples)

def task(day,root):
    name=f'BTCUSDT-bookDepth-{day}.zip';url=f'{BASE}/daily/bookDepth/BTCUSDT/{name}'
    item=dict(day=str(day),url=url)
    try:
        expected=fetch(url+'.CHECKSUM').decode().split()[0].lower();raw=fetch(url);digest=hashlib.sha256(raw).hexdigest()
        if digest!=expected:raise ValueError('checksum mismatch')
        (root/name).write_bytes(raw);item.update(sha256=digest,file=name)
        item.update(status='ok',**inspect(raw,day))
    except HTTPError as e:item.update(status='missing' if e.code==404 else 'error',error=str(e))
    except Exception as e:item.update(status='error',error=str(e))
    return item

def selftest():
    assert len(DATES)==42 and all(d.year in (2023,2026) for d in DATES)
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('x.csv','timestamp,percentage,depth,notional\n2023-01-01 00:00:00,-1,2,200\n2023-01-01 00:00:00,1,3,300\n2023-01-01 00:00:00,1,4,400\n2023-01-01 00:00:30,-1,2,200\n2023-01-01 00:00:30,1,3,300\n')
    q=inspect(b.getvalue(),DATES[0]);assert q['snapshots']==2 and q['rows']==3 and q['conflicts']==1 and q['paired1pct']==1 and q['maxGapSec']==30
    print('BD01 checksum-source scope, schema and conflict quarantine test PASS',flush=True)

def main():
    a=argparse.ArgumentParser();a.add_argument('--selftest',action='store_true');a=a.parse_args();selftest()
    if a.selftest:return
    root=Path('lab-bd01');root.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=6) as pool:items=list(pool.map(lambda d:task(d,root),DATES))
    for r in items:print('BD01_DAY='+json.dumps(r),flush=True)
    ok=[r for r in items if r['status']=='ok'];summary=dict(requested=len(items),verified=len(ok),missing=sum(r['status']=='missing' for r in items),errors=sum(r['status']=='error' for r in items),snapshots=sum(r['snapshots'] for r in ok),rows=sum(r['rows'] for r in ok),paired1pct=sum(r['paired1pct'] for r in ok))
    (root/'manifest.json').write_text(json.dumps(dict(summary=summary,files=items,limitations='Feasibility only; naive UTC assumption and band semantics not verified; no forecasting or execution.'),indent=2))
    print('BD01_SUMMARY='+json.dumps(summary),flush=True)
    if summary['errors'] or not ok:raise SystemExit('source quality investigation incomplete')
if __name__=='__main__':main()
