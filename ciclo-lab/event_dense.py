"""EV03: early-cycle spot acquisition and nested dense event census."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from event_early_source import acquire,selftest as source_test
from market_frame import segments,bars
from derivative_screen import load
from event_lab import paths,classification,describe,selftest as event_test,TARGETS,HORIZONS
from validation_rehearsal import utc

def census(p,start,end):
    b=bars(segments(p.assign(quote=p.volume*p.close)),5)
    f=b.index[(b.index>=utc(start))&(b.index<utc(end)-pd.Timedelta(days=3))]
    idx,k,events=paths(p,f)
    out={}
    for target,(u,d) in events.items():
        for h in HORIZONS:
            a=classification(u,d,h)
            out[f'{target}:{h}']={}
            for name,mask in [('5m',np.ones(len(idx),dtype=bool)),('15m',idx.minute%15==0),('1h',idx.minute==0),('12h',(idx.hour%12==0)&(idx.minute==0))]:
                out[f'{target}:{h}'][name]=describe(a[mask],u[mask])
    u,d=events[.02];a=classification(u,d,720)
    annual={str(y):{name:describe(a[mask&(idx.year==y)],u[mask&(idx.year==y)]) for name,mask in [('5m',np.ones(len(idx),dtype=bool)),('15m',idx.minute%15==0),('1h',idx.minute==0),('12h',(idx.hour%12==0)&(idx.minute==0))]} for y in np.unique(idx.year)}
    return dict(decisions=len(f),known=len(idx),missing=len(f)-len(idx),events=out,annual=annual)

def selftest():
    event_test();source_test()
    i=pd.date_range('2020-01-01',periods=5*1440,freq='min',tz='UTC')
    p=pd.DataFrame(dict(open=100.,high=100.,low=100.,close=100.,volume=1.),index=i)
    q=census(p,'2020-01-01','2020-01-06')
    z=q['events']['0.02:720']
    assert z['5m']['n']>=z['15m']['n']>=z['1h']['n']>=z['12h']['n']
    assert z['5m']['timeout']==z['5m']['n']
    print('EV03 nested grid test PASS',flush=True)

def main():
    a=argparse.ArgumentParser();a.add_argument('--selftest',action='store_true');a.add_argument('--derivatives');a.add_argument('--extension');a=a.parse_args();selftest()
    if a.selftest:return
    spot,manifest=acquire()
    assert manifest['start']=='2017-09-01' and manifest['end_exclusive']=='2021-01-01'
    assert manifest['rows']+manifest['excludedRows']==manifest['verifiedRows']
    assert manifest['verifiedRows']+manifest['missing']==manifest['expected']
    assert manifest['admittedMonths']+len(manifest['excludedMonths'])==40
    print('EV03_ARCHIVE_TOTAL='+json.dumps({k:v for k,v in manifest.items() if k!='files'}),flush=True)
    result={'spot2017-20':census(spot,'2017-10-01','2021-01-01')}
    del spot
    for name,root,warm,start,end in [('perp2021-23',a.derivatives,'2021-01-01','2021-02-01','2024-01-01'),('perp2026',a.extension,'2026-01-01','2026-02-01','2026-10-01')]:
        p=load(root,'perp')
        assert p.index.min()>=utc(warm) and p.index.max()<utc(end)
        result[name]=census(p,start,end)
        del p
    for name,q in result.items():
        print('EV03_SCOPE='+json.dumps(dict(period=name,decisions=q['decisions'],known=q['known'],missing=q['missing'],annual=q['annual'])),flush=True)
        for key,v in q['events'].items():
            print('EV03_EVENT='+json.dumps(dict(period=name,pair=key,grids=v)),flush=True)
    Path('lab-ev03.json').write_text(json.dumps(dict(archive=manifest,results=result,limitations='Spot vs perpetual distinct instruments; overlapping paths; no strategy, PnL or independent inference.'),indent=2))
if __name__=='__main__':main()
