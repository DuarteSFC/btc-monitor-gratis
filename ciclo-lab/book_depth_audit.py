"""BD02: source integrity beyond checksums; no forward-return evaluation."""
import argparse,hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from derivative_screen import load

def read_day(root,item):
    raw=(root/item['file']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==item['sha256']
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.endswith('.csv')]
        assert len(names)==1
        with z.open(names[0]) as f:d=pd.read_csv(f)
    assert list(d)==['timestamp','percentage','depth','notional']
    d['timestamp']=pd.to_datetime(d.timestamp,utc=True)
    assert d.timestamp.dt.strftime('%Y-%m-%d').eq(item['day']).all()
    assert np.isfinite(d[['percentage','depth','notional']].to_numpy()).all()
    assert d.depth.ge(0).all() and d.notional.ge(0).all()
    assert not d.duplicated(['timestamp','percentage']).any()
    assert len(d)==item['rows']
    return d

def frozen(g):
    g=g.sort_values('timestamp')
    same=g[['depth','notional']].eq(g[['depth','notional']].shift()).all(axis=1)
    gap=g.timestamp.diff().gt(pd.Timedelta(seconds=90))
    blocks=(~same|gap).cumsum()
    spans=g.groupby(blocks).timestamp.agg(['min','max'])
    longest=float((spans['max']-spans['min']).dt.total_seconds().max())
    counts=g.groupby(['depth','notional']).size()
    n=len(counts);freq=float(counts.max()/len(g))
    return dict(distinct=n,maxFraction=freq,longestSeconds=longest,frozen=bool(n<10 or freq>=.95 or longest>=1800))

def fresh(d,day):
    q=d.loc[d.percentage.isin([-1.,1.]) & d.depth.gt(0) & d.notional.gt(0)]
    paired=q.groupby('timestamp').percentage.nunique()
    times=pd.DatetimeIndex(paired.index[paired.eq(2)])
    grid=pd.date_range(pd.Timestamp(day,tz='UTC')+pd.Timedelta(minutes=5),periods=288,freq='5min')
    s=pd.Series(1,index=times+pd.Timedelta(seconds=60))
    return int(s.reindex(grid,method='ffill',tolerance=pd.Timedelta(seconds=60)).notna().sum())

def plausibility(g,p,offset):
    t=pd.DatetimeIndex(g.timestamp).floor('min')+pd.Timedelta(hours=offset)
    bars=p.reindex(t)
    ratio=g.notional.to_numpy()/np.where(g.depth.to_numpy()>0,g.depth.to_numpy(),np.nan)
    w=abs(float(g.percentage.iloc[0]))/100+.005
    lo=bars.low.to_numpy();hi=bars.high.to_numpy()
    valid=np.isfinite(ratio)&np.isfinite(lo)&np.isfinite(hi)
    ok=valid&(ratio>=lo*(1-w))&(ratio<=hi*(1+w))
    return dict(known=int(valid.sum()),fraction=float(ok.sum()/len(g)))

def audit(d,p,item):
    day=item['day'];bands={}
    for pct,g in d.groupby('percentage'):
        bands[str(float(pct))]=dict(**frozen(g),price={str(k):plausibility(g,p,k) for k in (-2,-1,0,1,2)})
    required=[bands.get('-1.0'),bands.get('1.0')]
    n=int(d.timestamp.nunique());nf=fresh(d,day)
    reasons=[]
    if n<2736:reasons.append('snapshot_coverage')
    if nf<274:reasons.append('fresh_grid_coverage')
    if item['invalid'] or item['duplicates'] or item['conflicts']:reasons.append('invalid_source')
    if d.loc[d.percentage.isin([-1.,1.]),['depth','notional']].le(0).any().any():reasons.append('nonpositive_inner_depth')
    if any(v is None or v['frozen'] for v in required):reasons.append('frozen_or_missing_inner_band')
    if any(v is None or v['price']['0']['fraction']<.95 for v in required):reasons.append('price_alignment')
    return dict(day=day,snapshots=n,fresh=nf,admitted=not reasons,reasons=reasons,bands=bands)

def selftest():
    t=pd.date_range('2023-01-01',periods=2880,freq='30s',tz='UTC')
    a=pd.DataFrame(dict(timestamp=t,percentage=-1.,depth=np.arange(len(t))+1.,notional=100*(np.arange(len(t))+1.)))
    b=a.assign(percentage=1.,depth=5.,notional=500.)
    assert not frozen(a)['frozen'] and frozen(b)['frozen']
    d=pd.concat([a,b]);assert fresh(d,'2023-01-01')==288
    i=pd.date_range('2023-01-01',periods=1440,freq='min',tz='UTC')
    p=pd.DataFrame(dict(low=99.,high=101.),index=i)
    item=dict(day='2023-01-01',invalid=0,duplicates=0,conflicts=0)
    q=audit(d,p,item);assert not q['admitted'] and q['reasons']==['frozen_or_missing_inner_band']
    print('BD02 frozen band, coverage and price consistency selftest PASS',flush=True)

def main():
    a=argparse.ArgumentParser();a.add_argument('--selftest',action='store_true');a.add_argument('--book');a.add_argument('--derivatives');a.add_argument('--extension');a.add_argument('--extra');a=a.parse_args();selftest()
    if a.selftest:return
    root=Path(a.book);m=json.loads((root/'manifest.json').read_text())
    assert len(m['files'])==42 and all(r['status']=='ok' and r['day'][:4] in ('2023','2026') for r in m['files'])
    p=load(a.derivatives,'perp');assert p.index.max()<pd.Timestamp('2024-01-01',tz='UTC')
    recent=pd.concat([load(a.extension,'perp'),load(Path(a.extra)/'recent','perp')]).sort_index()
    assert recent.index.is_unique and recent.index.min()>=pd.Timestamp('2026-01-01',tz='UTC') and recent.index.max()<pd.Timestamp('2026-11-01',tz='UTC')
    reports=[]
    for item in m['files']:
        d=read_day(root,item);r=audit(d,p if item['day'].startswith('2023') else recent,item)
        reports.append(r);print('BD02_DAY='+json.dumps(r),flush=True)
    summary={str(y):dict(days=sum(r['day'].startswith(str(y)) for r in reports),admitted=sum(r['day'].startswith(str(y)) and r['admitted'] for r in reports),fresh=sum(r['fresh'] for r in reports if r['day'].startswith(str(y)) and r['admitted'])) for y in (2023,2026)}
    Path('lab-bd02.json').write_text(json.dumps(dict(summary=summary,days=reports,limitations='Source audit only. Plausibility is not proof of UTC or live availability. No return outcomes.'),indent=2))
    print('BD02_SUMMARY='+json.dumps(summary),flush=True)
if __name__=='__main__':main()
