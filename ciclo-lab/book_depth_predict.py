"""BD03: bounded depth forecasting, no execution or holdout."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge

PRICE=['r5','r60','rv60'];FULL=PRICE+['imb','delta']

def frame(day,d,p):
    start=pd.Timestamp(day,tz='UTC');end=start+pd.Timedelta(days=1)
    grid=pd.date_range(start+pd.Timedelta(minutes=5),end,freq='5min',inclusive='left')
    depth=d.loc[d.percentage.isin([-1.,1.])].pivot(index='timestamp',columns='percentage',values='depth').dropna().sort_index()
    depth=depth.loc[(depth.index>=start)&(depth.index<end)&depth.gt(0).all(axis=1)]
    z=np.log(depth[-1.]/depth[1.]);z.index+=pd.Timedelta(seconds=60)
    imb=z.reindex(grid,method='ffill',tolerance=pd.Timedelta(seconds=60))
    # Explicit minute grid; missing prices remain missing, never imputed.
    minute=pd.date_range(start,end,freq='min',inclusive='left');v=p.reindex(minute)
    close=np.log(v.close);r=close.diff();past=r.rolling(60,min_periods=60)
    # At t only closes of minute t-1 or earlier are available.
    f=pd.DataFrame(dict(r5=close.diff(5).shift(1),r60=close.diff(60).shift(1),rv60=past.std().shift(1))).reindex(grid)
    f['imb']=imb;f['delta']=imb.diff();f['day']=day
    # 60 minute path opens t+1, closes t+60. No future feature access.
    y=(close.shift(-60)-np.log(v.open.shift(-1)))*1e4
    valid=v[['open','high','low','close']].notna().all(axis=1).astype(int).rolling(60,min_periods=60).sum().shift(-60).eq(60)
    f['y']=y.where(valid).reindex(grid)
    f=f.replace([np.inf,-np.inf],np.nan)
    return f.dropna(subset=FULL),int(imb.notna().sum())

def evaluate(train,test):
    tr=train.dropna(subset=['y']);te=test.loc[test.index.minute==0].copy()
    known=te.dropna(subset=['y']).copy();assert len(tr)>=100 and len(known)>=20
    known['mean']=float(tr.y.mean())
    for key,cols in [('price',PRICE),('full',FULL)]:
        model=make_pipeline(StandardScaler(),Ridge(alpha=10.))
        model.fit(tr[cols],tr.y);known[key]=model.predict(known[cols])
    out={}
    for key in ('mean','price','full'):
        x=known[key];rank=x.rank().corr(known.y.rank()) if x.nunique()>1 and known.y.nunique()>1 else None
        out[key]=dict(mse=float(((x-known.y)**2).mean()),rank=float(rank) if rank is not None and np.isfinite(rank) else None)
    diff=(known.price-known.y)**2-(known.full-known.y)**2
    by=known.assign(lossdiff=diff).groupby('day').lossdiff.agg(['sum','count'])
    rng=np.random.default_rng(27);i=rng.integers(0,len(by),size=(5000,len(by)))
    boot=by['sum'].to_numpy()[i].sum(1)/by['count'].to_numpy()[i].sum(1)
    return dict(train=len(tr),dense=len(test),denseKnown=int(test.y.notna().sum()),hourly=len(te),known=len(known),days=len(by),models=out,meanImprovement=float(diff.mean()),ci=np.quantile(boot,[.025,.975]).tolist(),dayStats=by.reset_index().to_dict('records'))

def selftest():
    i=pd.date_range('2023-01-01',periods=1440,freq='min',tz='UTC');px=100+np.arange(len(i))*.002
    p=pd.DataFrame(dict(open=px,high=px+.5,low=px-.5,close=px),index=i)
    t=pd.date_range(i[0],periods=2880,freq='30s');d=pd.concat([pd.DataFrame(dict(timestamp=t,percentage=k,depth=1+np.arange(len(t))*.001*(2 if k<0 else 1))) for k in (-1.,1.)])
    f,n=frame('2023-01-01',d,p);assert n==287 and not f.empty
    cut=i[720];q=p.copy();q.loc[q.index>=cut]*=2
    g,_=frame('2023-01-01',d,q);pd.testing.assert_frame_equal(f.loc[:cut,FULL],g.loc[:cut,FULL])
    z,_=frame('2023-01-01',d,p.drop(i[725]));assert pd.isna(z.loc[cut,'y'])
    assert np.isclose(f.loc[cut,'y'],np.log(px[780]/px[721])*1e4)
    assert f.loc[cut,'imb']==np.log((1+2*1438*.001)/(1+1438*.001))
    print('BD03 causal timing, target and gap tests PASS',flush=True)

def main():
    a=argparse.ArgumentParser();a.add_argument('--selftest',action='store_true');a.add_argument('--book');a.add_argument('--audit');a.add_argument('--derivatives');a.add_argument('--extension');a.add_argument('--extra');a=a.parse_args();selftest()
    if a.selftest:return
    from book_depth_audit import read_day,audit
    from derivative_screen import load
    root=Path(a.book);m=json.loads((root/'manifest.json').read_text());q=json.loads(Path(a.audit).read_text());admitted={r['day']:r for r in q['days'] if r['admitted']}
    assert len(admitted)==33 and sum(k.startswith('2023') for k in admitted)==22
    old=load(a.derivatives,'perp');assert old.index.max()<pd.Timestamp('2024-01-01',tz='UTC')
    recent=pd.concat([load(a.extension,'perp'),load(Path(a.extra)/'recent','perp')]).sort_index();assert recent.index.is_unique and recent.index.min()>=pd.Timestamp('2026-01-01',tz='UTC') and recent.index.max()<pd.Timestamp('2026-11-01',tz='UTC')
    frames={}
    for item in m['files']:
        day=item['day']
        if day not in admitted:continue
        p=old if day.startswith('2023') else recent;d=read_day(root,item);r=audit(d,p,item);assert r['admitted'] and r['fresh']==admitted[day]['fresh']
        f,n=frame(day,d,p);assert n<=r['fresh']
        frames[day]=f;print('BD03_DAY='+json.dumps(dict(day=day,fresh=n,features=len(f),known=int(f.y.notna().sum()))),flush=True)
    assert set(frames)==set(admitted)
    o=sorted(k for k in frames if k.startswith('2023'));r=sorted(k for k in frames if k.startswith('2026'))
    def join(keys):return pd.concat([frames[k] for k in keys]).sort_index()
    result={'2023':evaluate(join(o[:11]),join(o[11:])), '2026':evaluate(join(o),join(r))}
    for name,v in result.items():print('BD03_RESULT='+json.dumps(dict(period=name,**v)),flush=True)
    passed=all(v['meanImprovement']>0 and v['ci'][0]>0 for v in result.values())
    Path('lab-bd03.json').write_text(json.dumps(dict(results=result,screenPass=passed,limitations='Gross log returns, sparse day sample, assumed UTC and receipt lag; no economic or independent release validation.'),indent=2))
    print('BD03_PASS='+str(passed),flush=True)
if __name__=='__main__':main()
