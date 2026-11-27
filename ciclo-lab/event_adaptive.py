"""EV04: volatility-normalized directional persistence on expanded futures history."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from derivative_screen import load
from hourly_futures import make_outcomes, FEES, NS
from market_frame import segments, bars, atr, ema, lag, align
from validation_rehearsal import replay, utc


def audit_funding(funding, start, end):
    expected = pd.date_range(utc(start), utc(end), freq='8h', inclusive='left')
    observed = funding.index
    rounded = observed.round('8h')
    assert observed.is_unique and observed.is_monotonic_increasing
    assert (abs(observed-rounded) <= pd.Timedelta(minutes=2)).all()
    pd.testing.assert_index_equal(rounded, expected, check_names=False)
    assert funding.interval_hours.eq(8).all() and np.isfinite(funding.rate).all()


def merged(roots, start, end):
    out = []
    for kind in ('perp', 'mark', 'funding'):
        data = pd.concat([load(r,kind) for r in roots]).sort_index()
        assert data.index.is_unique and data.index.min() >= utc(start) and data.index.max() < utc(end)
        if kind != 'funding':
            for month in pd.date_range(utc(start), utc(end), freq='MS', inclusive='left'):
                stop = month + pd.offsets.MonthBegin(1)
                n = ((data.index >= month) & (data.index < stop)).sum()
                assert n >= .95 * ((stop-month)/pd.Timedelta(minutes=1))
        out.append(data)
    audit_funding(out[2],start,end)
    return out


def conditions(p):
    d=segments(p.assign(quote=p.volume*p.close))
    h=bars(d,60); q=bars(d,240)
    h['atr1']=atr(h)
    q['up']=(ema(q,20)>ema(q,60)).astype(float).where(ema(q,60).notna())
    prior=lag(h,'close',24);trend=align(q,h,'up')
    eligible=prior.notna() & trend.notna() & h.atr1.ge(.004*h.close)
    selected=eligible & (h.close-prior).gt(2*h.atr1) & trend.eq(1)
    return h, pd.DataFrame(dict(eligible=eligible,selected=selected),index=h.index)


def selftest():
    from validation_rehearsal import selftest as replay_test
    replay_test()
    from hourly_futures import selftest as outcome_test
    outcome_test()
    t=pd.date_range('2020-01-01',periods=15*1440,freq='min',tz='UTC')
    px=100+np.arange(len(t))*.003
    p=pd.DataFrame(dict(open=px,high=px+.5,low=px-.5,close=px,volume=1.),index=t)
    h,q=conditions(p);assert q.selected.any()
    cut=t[12*1440]
    p2=p.copy();p2.loc[p2.index>=cut,['open','high','low','close']]*=2
    _,q2=conditions(p2)
    pd.testing.assert_frame_equal(q.loc[:cut],q2.loc[:cut])
    i=pd.date_range('2020-01-01','2020-01-02',freq='8h',inclusive='left',tz='UTC')
    f=pd.DataFrame(dict(interval_hours=8,rate=.0001),index=i+pd.Timedelta(milliseconds=2))
    audit_funding(f,'2020-01-01','2020-01-02')
    try:audit_funding(f.iloc[:-1],'2020-01-01','2020-01-02')
    except AssertionError:pass
    else:raise AssertionError('missing funding accepted')
    print('EV04 causal features, gap-aware engine and funding cadence PASS',flush=True)


def main():
    a=argparse.ArgumentParser();a.add_argument('--selftest',action='store_true');a.add_argument('--derivatives');a.add_argument('--extension');a.add_argument('--extra');a=a.parse_args();selftest()
    if a.selftest:return
    scopes=[('2020-23',[Path(a.extra)/'early',a.derivatives],'2020-01-01','2020-02-01','2024-01-01'),('2026',[a.extension,Path(a.extra)/'recent'],'2026-01-01','2026-02-01','2026-11-01')]
    result={}
    for name,roots,warm,start,end in scopes:
        p,mark,funding=merged(roots,warm,end)
        h,f=conditions(p);f=f.loc[(f.index>=utc(start))&(f.index<utc(end)-pd.Timedelta(days=2))]
        base=f.index[f.eligible];selected=f.index[f.selected]
        print('EV04_SCOPE='+json.dumps(dict(period=name,minutes=len(p),funding=len(funding),eligible=len(base),selected=len(selected))),flush=True)
        out={}
        for delay in (1,5,15):
            shift=pd.Timedelta(minutes=delay-1);universe=base if delay==1 else selected
            m=h.loc[universe,['atr1','segment']].copy();m.index+=shift
            out[str(delay)]={}
            fees=dict(FEES)
            if delay==1:fees['zeroFeeSlip']=(0.,0.)
            for cost,params in fees.items():
                y=make_outcomes(m,pd.Series(True,index=m.index),p,mark,funding,1440,*params)
                out[str(delay)][cost]={}
                policies=[('EV04',selected)]+([('base',base)] if delay==1 else [])
                for policy,ix in policies:
                    r=replay(pd.Series('24h',index=ix+shift,dtype='object'),{'24h':{cost:y}},cost,start=start,end=end)
                    out[str(delay)][cost][policy]=r
                    print('EV04_RESULT='+json.dumps(dict(period=name,delay=delay,cost=cost,policy=policy,**{k:r[k] for k in ('n','mean','pf','equity','ci','dd','unknown','years','signals','skipped')})),flush=True)
        result[name]=out
    Path('lab-ev04.json').write_text(json.dumps(dict(results=result,limitations='Development diagnostic; zeroFeeSlip retains funding and may change stop and overlap. Not fixed-fill friction decomposition. No independent holdout or orders.'),indent=2))
if __name__=='__main__':main()
