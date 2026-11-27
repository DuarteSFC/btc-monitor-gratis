"""EV03-only spot loader: verified source bytes, quarantine malformed minutes."""
import csv,hashlib,io,zipfile,math
from datetime import date
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import archive_dataset as archive

COLS=['open','high','low','close','volume']
def parse(raw,start,end):
    lo,hi=archive.ms(start),archive.ms(end)
    rows={};bad=set();affected=set();rejected=0;examples=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.endswith('.csv')]
        if len(names)!=1:raise ValueError('unexpected archive')
        with z.open(names[0]) as f:
            for row in csv.reader(io.TextIOWrapper(f,encoding='utf-8')):
                if row and row[0].lower() in ('open_time','opentime'):continue
                t=None
                try:
                    t=archive.timestamp(row[0]);ct=int(row[6]);ct=ct//1000 if ct>=10**14 else ct
                    o,h,l,c,v=map(float,row[1:6])
                    if not lo<=t<hi or t%60000 or ct!=t+59999 or not all(map(math.isfinite,(o,h,l,c,v))) or not (0<l<=min(o,c)<=max(o,c)<=h and v>=0):
                        raise ValueError('invalid candle')
                    if t in rows or t in bad:
                        rows.pop(t,None);bad.add(t);raise ValueError('duplicate minute')
                    rows[t]=(o,h,l,c,v)
                except (ValueError,IndexError,OverflowError):
                    rejected+=1
                    if t is not None and lo<=t<hi:
                        affected.add(pd.Timestamp(t,unit='ms',tz='UTC').date())
                    if len(examples)<10:examples.append(row[:7])
    return rows,affected,rejected,examples

def fetch(kind,start,end):
    suffix=start.strftime('%Y-%m' if kind=='monthly' else '%Y-%m-%d')
    name='BTCUSDT-1m-'+suffix+'.zip'
    url=f'{archive.BASE}/{kind}/klines/BTCUSDT/1m/{name}'
    expected=archive.request(url+'.CHECKSUM').decode().split()[0].lower()
    raw=archive.request(url);digest=hashlib.sha256(raw).hexdigest()
    if digest!=expected:raise ValueError('checksum mismatch '+name)
    rows,affected,rejected,examples=parse(raw,start,end)
    return rows,affected,dict(url=url,sha256=digest,valid=len(rows),rejected=rejected,examples=examples)

def reconcile(rows,daily):
    for t,v in daily.items():
        if t in rows and rows[t]!=v:raise ValueError('conflicting verified candle '+str(t))
    n=sum(t not in rows for t in daily)
    rows.update(daily)
    return n

def recover_day(rows,daily,day):
    lo=archive.ms(day);hi=lo+86400000
    conflicts=[dict(time=t,monthly=rows[t],daily=v) for t,v in daily.items() if t in rows and rows[t]!=v]
    if conflicts:
        removed=[t for t in rows if lo<=t<hi]
        for t in removed:del rows[t]
        return dict(recovered=0,quarantined=True,removed=len(removed),conflictCount=len(conflicts),conflicts=conflicts[:10])
    return dict(recovered=reconcile(rows,daily),quarantined=False,removed=0,conflictCount=0)

def month(start):
    from datetime import timedelta
    from urllib.error import HTTPError
    end=archive.nextmonth(start)
    rows,affected,report=fetch('monthly',start,end)
    report.update(month=str(start),daily=[],recovered=0)
    attempted=set()
    def repair(day):
        attempted.add(day)
        try:
            d,_,r=fetch('daily',day,day+timedelta(days=1))
        except HTTPError as e:
            if e.code!=404:raise
            report['daily'].append(dict(day=str(day),missing=True));return
        q=recover_day(rows,d,day);report['recovered']+=q['recovered'];report['daily'].append(dict(day=str(day),**q,**r))
    for day in sorted(affected):
        repair(day)
    expected=(archive.ms(end)-archive.ms(start))//60000
    if len(rows)/expected<.95:
        counts={}
        for t in rows:
            key=t//86400000
            counts[key]=counts.get(key,0)+1
        day=start
        while day<end:
            if day not in attempted and counts.get(archive.ms(day)//86400000,0)<1440:
                repair(day)
            day+=timedelta(days=1)
    admitted=len(rows)/expected>=.95
    report.update(expected=expected,rows=len(rows),missing=expected-len(rows),admitted=admitted,excludedRows=0 if admitted else len(rows))
    print('EV03_ARCHIVE='+__import__('json').dumps(report),flush=True)
    t=sorted(rows) if admitted else []
    frame=pd.DataFrame([rows[k] for k in t],columns=COLS,index=pd.to_datetime(t,unit='ms',utc=True),dtype=float)
    return frame,report


def acquire():
    months=[];a=date(2017,9,1)
    while a<date(2021,1,1):
        months.append(a);a=archive.nextmonth(a)
    with ThreadPoolExecutor(max_workers=4) as pool:
        result=list(pool.map(month,months))
    reports=[x[1] for x in result]
    p=pd.concat([x[0] for x in result if x[1]['admitted']])
    assert p.index.is_unique and p.index.is_monotonic_increasing
    return p,dict(start='2017-09-01',end_exclusive='2021-01-01',rows=len(p),expected=sum(r['expected'] for r in reports),missing=sum(r['missing'] for r in reports),verifiedRows=sum(r['rows'] for r in reports),excludedRows=sum(r['excludedRows'] for r in reports),admittedMonths=sum(r['admitted'] for r in reports),excludedMonths=[r['month'] for r in reports if not r['admitted']],files=reports)

def selftest():
    from datetime import timedelta
    a=date(2017,12,4);b=a+timedelta(days=1);t=archive.ms(a)
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:
        z.writestr('x.csv','\n'.join(f'{u},100,101,99,100,2,{u+59999},0,0,0,0,0' for u in [t,t+60001,t+120000,t+120000,t+180000]))
    rows,affected,rejected,_=parse(raw.getvalue(),a,b)
    assert sorted(rows)==[t,t+180000] and affected=={a} and rejected==2
    assert reconcile(rows,{t+60000:(100.,101.,99.,100.,2.)})==1
    try:reconcile(rows,{t:(100.,102.,99.,100.,2.)})
    except ValueError:pass
    else:raise AssertionError('conflict accepted')
    rows[t-60000]=(100.,101.,99.,100.,2.)
    q=recover_day(rows,{t:(100.,102.,99.,100.,2.)},a)
    assert q['quarantined'] and q['conflictCount']==1 and q['removed']==3 and list(rows)==[t-60000]
    print('EV03 source quarantine, recovery and conflict tests PASS',flush=True)
