"""EV06: synchronized spot/perp discount, directional decomposition; research only."""
import argparse,json,tempfile
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,segments,bars,atr,lag
from event_adaptive import merged,selftest as data_test
from hourly_futures import make_outcomes,FEES,NS
from validation_rehearsal import replay,utc

H=720

def spot_scope(root,start,end):
    root=Path(root).resolve()
    assert (start,end) in [('2020-01-01','2024-01-01'),('2026-01-01','2026-11-01')]
    m=json.loads((root/'manifest.json').read_text())
    assert m['dataset_version']=='1.1' and not m['errors']
    files=sorted([f for f in m['files'] if f['start']>=start and f['end_exclusive']<=end],key=lambda f:f['start'])
    assert files and files[0]['start']==start and files[-1]['end_exclusive']==end
    assert all(a['end_exclusive']==b['start'] for a,b in zip(files,files[1:]))
    with tempfile.TemporaryDirectory() as tmp:
        dest=Path(tmp)
        for f in files:
            assert Path(f['file']).name==f['file']
            (dest/f['file']).symlink_to(root/f['file'])
        restricted=dict(m,files=files,start=start,end_exclusive=end,rows=sum(f['rows'] for f in files),expected=sum(f['expected'] for f in files))
        (dest/'manifest.json').write_text(json.dumps(restricted))
        return load_minutes(dest)

def conditions(p,spot):
    h=bars(segments(p.assign(quote=p.volume*p.close)),60)
    s=bars(spot,60);h['atr1']=atr(h)
    spot_close=s.close.reindex(h.index)
    ret=(s.close/lag(s,'close')-1).reindex(h.index)
    basis=h.close/spot_close-1
    eligible=basis.notna()&ret.notna()&h.atr1.ge(.004*h.close)
    selected=eligible&basis.le(-.003)&ret.gt(0)
    return h,pd.DataFrame(dict(eligible=eligible,selected=selected,basis=basis,spotRet=ret),index=h.index)

def direction(p,spot,ix):
    def path(d):
        t=d.index.as_unit('ns').asi8
        k=np.searchsorted(t,ix.as_unit('ns').asi8+NS)
        a=np.minimum(k,len(t)-1);b=np.minimum(k+H-1,len(t)-1)
        good=(k+H<=len(t))&(t[a]==ix.as_unit('ns').asi8+NS)&(t[b]-t[a]==(H-1)*NS)
        ret=np.log(d.close.to_numpy()[b]/d.open.to_numpy()[a])
        return ret,good
    a,aa=path(p);b,bb=path(spot);ok=aa&bb
    x=a[ok];y=b[ok];z=x-y
    return dict(decisions=len(ix),known=int(ok.sum()),perpLogBps=float(x.mean()*1e4) if len(x) else None,spotLogBps=float(y.mean()*1e4) if len(y) else None,basisChangeLogBps=float(z.mean()*1e4) if len(z) else None)

def selftest():
    data_test()
    i=pd.date_range('2020-01-01',periods=3*1440,freq='min',tz='UTC')
    x=100+np.arange(len(i))*.002
    s=segments(pd.DataFrame(dict(open=x,high=x+.5,low=x-.5,close=x,volume=1.,quote=x),index=i))
    p=s.copy();p[['open','high','low','close']]*=.995
    h,f=conditions(p,s);assert f.selected.any()
    cut=i[1500];q=s.copy();q.loc[q.index>=cut,['open','high','low','close']]*=2
    _,g=conditions(p,q);pd.testing.assert_frame_equal(f.loc[:cut],g.loc[:cut])
    r=direction(p,s,pd.DatetimeIndex([i[100]]))
    assert r['known']==1 and abs(r['basisChangeLogBps'])<1e-8
    assert direction(p,s.drop(i[110]),pd.DatetimeIndex([i[100]]))['known']==0
    print('EV06 synchronized scope, causal features and directional identity PASS',flush=True)

def main():
    a=argparse.ArgumentParser();a.add_argument('--selftest',action='store_true');a.add_argument('--dataset');a.add_argument('--derivatives');a.add_argument('--extension');a.add_argument('--extra');a=a.parse_args();selftest()
    if a.selftest:return
    scopes=[('2020-23',[Path(a.extra)/'early',a.derivatives],'2020-01-01','2020-02-01','2024-01-01'),('2026',[a.extension,Path(a.extra)/'recent'],'2026-01-01','2026-02-01','2026-11-01')]
    results={}
    for name,roots,warm,start,end in scopes:
        p,mark,funding,report=merged(roots,warm,end);spot=spot_scope(a.dataset,warm,end)
        h,f=conditions(p,spot);f=f.loc[(f.index>=utc(start))&(f.index<utc(end)-pd.Timedelta(days=2))]
        for row in report:
            if not row['admitted']:
                month=utc(row['month']);f=f.loc[~((f.index>=month-pd.Timedelta(days=2))&(f.index<month+pd.offsets.MonthBegin(1)))]
        base=f.index[f.eligible];selected=f.index[f.selected]
        diagnostic={k:direction(p,spot,ix) for k,ix in [('base',base),('EV06',selected)]}
        print('EV06_SCOPE='+json.dumps(dict(period=name,diagnostic=diagnostic)),flush=True)
        result={}
        for delay in (1,5,15):
            shift=pd.Timedelta(minutes=delay-1);universe=base if delay==1 else selected
            m=h.loc[universe,['atr1','segment']].copy();m.index+=shift
            for cost,params in FEES.items():
                y=make_outcomes(m,pd.Series(True,index=m.index),p,mark,funding,H,*params)
                policies=[('EV06',selected)]+([('base',base)] if delay==1 else [])
                for policy,ix in policies:
                    r=replay(pd.Series('12h',index=ix+shift,dtype='object'),{'12h':{cost:y}},cost,start=start,end=end)
                    result[f'{delay}:{cost}:{policy}']=r
                    print('EV06_RESULT='+json.dumps(dict(period=name,delay=delay,cost=cost,policy=policy,**{k:r[k] for k in ('n','mean','pf','equity','ci','dd','unknown','years','signals','skipped')})),flush=True)
        results[name]=dict(coverage=report,diagnostic=diagnostic,economic=result)
    Path('lab-ev06.json').write_text(json.dumps(dict(results=results,limitations='Development only. Unstopped log-return identity descriptive, not executable arbitrage. No holdout or orders.'),indent=2))
if __name__=='__main__':main()
