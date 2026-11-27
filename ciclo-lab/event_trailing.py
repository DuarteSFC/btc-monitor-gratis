"""EV05: settled funding resilience and causal trailing stop. Research only."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from event_adaptive import merged,selftest as data_test
from market_frame import segments,bars,atr,lag
from hourly_futures import make_outcomes,FEES,NS
from validation_rehearsal import replay,utc

H=1440

def conditions(p,funding):
    h=bars(segments(p.assign(quote=p.volume*p.close)),60)
    h['atr1']=atr(h);prior=lag(h,'close',4)
    r=funding.rate.copy();r.index+=pd.Timedelta(minutes=15)
    known=r.reindex(h.index,method='ffill',tolerance=pd.Timedelta(hours=8))
    eligible=prior.notna()&known.notna()&h.atr1.ge(.004*h.close)
    return h,pd.DataFrame(dict(eligible=eligible,selected=eligible&known.lt(0)&h.close.gt(prior)),index=h.index)

def trail(z,entry,distance):
    peak=np.r_[entry,np.maximum.accumulate(z[:-1,1])]
    stop=np.where(peak>=entry+2*distance,np.maximum(entry-distance,peak-distance),entry-distance)
    hits=np.flatnonzero(z[:,2]<=stop)
    j=int(hits[0]) if len(hits) else len(z)-1
    return j,min(z[j,0],stop[j]) if len(hits) else z[j,3],bool(len(hits))

def outcomes(m,p,mark,funding,fee,slip):
    t=p.index.as_unit('ns').asi8;v=p[['open','high','low','close']].to_numpy()
    ft=funding.index.as_unit('ns').asi8;fr=funding.rate.to_numpy()
    prior=funding.index.floor('min')-pd.Timedelta(minutes=1)
    mk=mark.close.reindex(prior).to_numpy();px=p.close.reindex(prior).to_numpy()
    fallback=~np.isfinite(mk);fp=np.where(fallback,px,mk);rows=[]
    for dt,a in m.atr1.items():
        et=dt.value+NS;k=int(np.searchsorted(t,et))
        if k+H>len(t) or t[k]!=et or t[k+H-1]!=et+(H-1)*NS:continue
        entry=v[k,0]*(1+slip);distance=2.5*a;stop=entry-distance
        if not 0<stop<entry:continue
        risk=entry*(1+fee)-stop*(1-slip)*(1-fee)
        j,out,hit=trail(v[k:k+H],entry,distance);exit_open=t[k+j];exit_close=exit_open+NS
        left=np.searchsorted(ft,et);right=np.searchsorted(ft,exit_close)
        if not np.isfinite(fp[left:right]).all():continue
        charge=fr[left:right]*fp[left:right]
        charge=np.where((ft[left:right]>=exit_open)&(charge<0)&hit,0.,charge)
        paid=float(charge.sum());net=out*(1-slip)*(1-fee)-entry*(1+fee)-paid
        rows.append(dict(time=dt,R=net/risk,riskFraction=risk/(entry*(1+fee)),fundingR=paid/risk,
            fallback=int(fallback[left:right].sum()),exit=exit_close,available=t[k+H-1]+NS,reason='stop' if hit else 'timeout'))
    return pd.DataFrame(rows).set_index('time') if rows else pd.DataFrame(columns=['R','riskFraction','fundingR','fallback','exit','available','reason'],index=pd.DatetimeIndex([],tz='UTC'))

def selftest():
    data_test()
    z=np.array([[100.,106.,99.,105.],[105.,108.,104.,107.],[107.,108.,101.,102.]])
    assert trail(z,100.,2.)==(2,106.,True)
    z[0,2]=97.;assert trail(z,100.,2.)==(0,98.,True)
    z[0,2]=99.;z[1,0]=101.;z[1,2]=100.;assert trail(z,100.,2.)==(1,101.,True)
    i=pd.date_range('2020-01-01',periods=3*1440,freq='min',tz='UTC')
    v=100+np.arange(len(i))*.001
    p=pd.DataFrame(dict(open=v,high=v+.5,low=v-.5,close=v,volume=1.),index=i)
    f=pd.DataFrame(dict(rate=-.001),index=i[::480]);h,q=conditions(p,f)
    f2=f.copy();cut=i[1440];f2.loc[f2.index>=cut,'rate']=.001
    _,q2=conditions(p,f2);pd.testing.assert_frame_equal(q.loc[:cut],q2.loc[:cut])
    print('EV05 causal stop, gap fill, funding visibility PASS',flush=True)

def main():
    a=argparse.ArgumentParser();a.add_argument('--selftest',action='store_true');a.add_argument('--derivatives');a.add_argument('--extension');a.add_argument('--extra');a=a.parse_args();selftest()
    if a.selftest:return
    scopes=[('2020-23',[Path(a.extra)/'early',a.derivatives],'2020-01-01','2020-02-01','2024-01-01'),('2026',[a.extension,Path(a.extra)/'recent'],'2026-01-01','2026-02-01','2026-11-01')]
    results={}
    for name,roots,warm,start,end in scopes:
        p,mark,funding,report=merged(roots,warm,end);h,f=conditions(p,funding)
        f=f.loc[(f.index>=utc(start))&(f.index<utc(end)-pd.Timedelta(days=2))]
        for row in report:
            if not row['admitted']:
                month=utc(row['month']);f=f.loc[~((f.index>=month-pd.Timedelta(days=2))&(f.index<month+pd.offsets.MonthBegin(1)))]
        base=f.index[f.eligible];selected=f.index[f.selected]
        print('EV05_SCOPE='+json.dumps(dict(period=name,eligible=len(base),selected=len(selected))),flush=True)
        result={}
        for delay in (1,5,15):
            shift=pd.Timedelta(minutes=delay-1);universe=base if delay==1 else selected
            m=h.loc[universe,['atr1','segment']].copy();m.index+=shift
            for cost,params in FEES.items():
                y=outcomes(m,p,mark,funding,*params)
                sm=m.loc[selected+shift];static=make_outcomes(sm,pd.Series(True,index=sm.index),p,mark,funding,H,*params)
                policies=[('EV05',selected,y),('static',selected,static)]+([('base',base,y)] if delay==1 else [])
                for policy,ix,labels in policies:
                    r=replay(pd.Series('24h',index=ix+shift,dtype='object'),{'24h':{cost:labels}},cost,start=start,end=end)
                    result[f'{delay}:{cost}:{policy}']=r
                    print('EV05_RESULT='+json.dumps(dict(period=name,delay=delay,cost=cost,policy=policy,**{k:r[k] for k in ('n','mean','pf','equity','ci','dd','unknown','years','signals','skipped')})),flush=True)
        results[name]=dict(coverage=report,economic=result)
    Path('lab-ev05.json').write_text(json.dumps(dict(results=results,limitations='Development diagnostic only. Trailing update uses earlier completed minutes; intraminute execution approximate. No holdout or orders.'),indent=2))
if __name__=='__main__':main()
