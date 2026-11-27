"""EV07: bounded incremental forecasting audit on admitted futures data."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from event_adaptive import merged,selftest as data_test
from market_frame import segments,bars,atr,lag
from hourly_futures import make_outcomes,FEES,NS
from validation_rehearsal import replay,utc

H=720
PRICE=['r1','r4','r24','r168','atrRel','regime4','regime24']
FULL=PRICE+['funding','regimeFunding']

def frame(p,funding):
    h=bars(segments(p.assign(quote=p.volume*p.close)),60)
    h['atr1']=atr(h);a=h.atr1/h.close
    f=pd.DataFrame(index=h.index)
    for n in (1,4,24,168):f[f'r{n}']=(h.close/lag(h,'close',n)-1)/a
    f['atrRel']=a;sign=np.sign(f.r168)
    f['regime4']=sign*f.r4;f['regime24']=sign*f.r24
    r=funding.rate.copy();r.index+=pd.Timedelta(minutes=15)
    f['funding']=r.reindex(h.index,method='ffill',tolerance=pd.Timedelta(hours=8))
    f['regimeFunding']=sign*f.funding
    f=f.replace([np.inf,-np.inf],np.nan).dropna()
    return h,f.loc[f.atrRel>=.004,FULL]

def fit(x,y,cut,end):
    tr=y.loc[(y.index<cut)&(y.available<=cut.value)]
    te=x.loc[(x.index>=cut)&(x.index<end)]
    assert len(tr)>=1000 and not te.empty and tr.index.isin(x.index).all()
    pred=pd.DataFrame(index=te.index)
    pred['mean']=float(tr.R.mean())
    for name,cols in [('price',PRICE),('full',FULL)]:
        model=make_pipeline(StandardScaler(),Ridge(alpha=100.))
        model.fit(x.loc[tr.index,cols],tr.R)
        pred[name]=model.predict(te[cols])
    return pred,len(tr)

def scores(pred,y):
    known=pred.index.intersection(y.index)
    known=known[(known.hour%12==0)&(known.minute==0)]
    actual=y.loc[known,'R'];out={}
    for key in pred.columns:
        q=pred.loc[known,key]
        mse=float(((q-actual)**2).mean()) if len(q) else None
        rank=float(q.rank().corr(actual.rank())) if len(q)>1 and q.nunique()>1 and actual.nunique()>1 else None
        out[key]=dict(mse=mse,rank=rank if rank is not None and np.isfinite(rank) else None)
    return dict(n=len(known),expected=int(((pred.index.hour%12==0)&(pred.index.minute==0)).sum()),models=out)

def selftest():
    data_test()
    i=pd.date_range('2020-01-01',periods=12*1440,freq='min',tz='UTC')
    px=100+np.arange(len(i))*.002
    p=pd.DataFrame(dict(open=px,high=px+.5,low=px-.5,close=px,volume=1.),index=i)
    funding=pd.DataFrame(dict(rate=-.001),index=i[::480]);h,x=frame(p,funding);assert not x.empty
    cut=i[10*1440];q=p.copy();q.loc[q.index>=cut,['open','high','low','close']]*=2
    g=funding.copy();g.loc[g.index>=cut,'rate']=.001
    _,xx=frame(q,g);pd.testing.assert_frame_equal(x.loc[:cut],xx.loc[:cut])
    t=pd.date_range('2020-01-01',periods=1300,freq='h',tz='UTC')
    rng=np.random.default_rng(27);x=pd.DataFrame(rng.normal(size=(len(t),len(FULL))),index=t,columns=FULL)
    y=pd.DataFrame(dict(R=x.r4,available=t.asi8+721*NS),index=t)
    cut=t[1200];pred,n=fit(x,y,cut,t[-1]);assert n==1188
    y.loc[y.available>cut.value,'R']=1e6
    p2,n2=fit(x,y,cut,t[-1]);pd.testing.assert_frame_equal(pred,p2);assert n==n2
    print('EV07 causal frame and full-horizon label purge PASS',flush=True)

def main():
    a=argparse.ArgumentParser();a.add_argument('--selftest',action='store_true');a.add_argument('--derivatives');a.add_argument('--extension');a.add_argument('--extra');a=a.parse_args();selftest()
    if a.selftest:return
    scopes=[('2020-23',[Path(a.extra)/'early',a.derivatives],'2020-01-01','2020-02-01','2024-01-01'),('2026',[a.extension,Path(a.extra)/'recent'],'2026-01-01','2026-02-01','2026-11-01')]
    cache={};xs=[];ys=[]
    for name,roots,warm,start,end in scopes:
        p,mark,funding,report=merged(roots,warm,end);h,x=frame(p,funding)
        x=x.loc[(x.index>=utc(start))&(x.index<utc(end)-pd.Timedelta(days=2))]
        for row in report:
            if not row['admitted']:
                month=utc(row['month']);x=x.loc[~((x.index>=month-pd.Timedelta(days=2))&(x.index<month+pd.offsets.MonthBegin(1)))]
        m=h.loc[x.index,['atr1','segment']]
        y=make_outcomes(m,pd.Series(True,index=m.index),p,mark,funding,H,*FEES['stress'])
        xs.append(x);ys.append(y);cache[name]=(p,mark,funding,h,report)
        print('EV07_DATA='+json.dumps(dict(period=name,eligible=len(x),known=len(y))),flush=True)
    x=pd.concat(xs);y=pd.concat(ys);results={}
    assert x.index.is_unique and y.index.is_unique
    for name,_,warm,start,end in scopes:
        cuts=(list(pd.date_range('2021-01-01','2023-10-01',freq='QS',tz='UTC')) if name=='2020-23' else [utc('2026-02-01'),utc('2026-04-01'),utc('2026-07-01'),utc('2026-10-01')])+[utc(end)]
        folds=[];preds=[]
        for cut,nxt in zip(cuts[:-1],cuts[1:]):
            pred,n=fit(x,y,cut,nxt);preds.append(pred)
            folds.append(dict(cut=cut.isoformat(),train=n,**scores(pred,y)))
        pred=pd.concat(preds);chosen=pred.index[pred.full>=.10]
        diag=scores(pred,y)
        print('EV07_FORECAST='+json.dumps(dict(period=name,decisions=len(pred),selected=len(chosen),sparse=diag,folds=folds)),flush=True)
        p,mark,funding,h,report=cache[name];econ={}
        for delay in (1,5,15):
            shift=pd.Timedelta(minutes=delay-1);universe=pred.index if delay==1 else chosen
            m=h.loc[universe,['atr1','segment']].copy();m.index+=shift
            for cost,params in FEES.items():
                labels=make_outcomes(m,pd.Series(True,index=m.index),p,mark,funding,H,*params)
                policies=[('EV07',chosen)]+([('base',pred.index)] if delay==1 else [])
                for policy,ix in policies:
                    r=replay(pd.Series('12h',index=ix+shift,dtype='object'),{'12h':{cost:labels}},cost,start=cuts[0],end=end)
                    econ[f'{delay}:{cost}:{policy}']=r
                    print('EV07_RESULT='+json.dumps(dict(period=name,delay=delay,cost=cost,policy=policy,**{k:r[k] for k in ('n','mean','pf','equity','ci','dd','unknown','years','signals','skipped')})),flush=True)
        results[name]=dict(coverage=report,forecast=diag,folds=folds,economic=econ)
    Path('lab-ev07.json').write_text(json.dumps(dict(results=results,limitations='Development only; sparse forecast grid reduces overlap but does not confer independence. No holdout or orders.'),indent=2))
if __name__=='__main__':main()
