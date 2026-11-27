"""EV02: fixed event-label net expectancy model; research only."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from event_lab import features,first,outcomes,selftest as event_test
from market_frame import segments
from derivative_screen import load
from hourly_futures import FEES,NS
from validation_rehearsal import replay,utc

SCOPES=[('2021-23','2021-01-01','2021-02-01','2021-09-01','2024-01-01'),
        ('2026','2026-01-01','2026-02-01','2026-02-01','2026-10-01')]

def paths12(p,index):
    t=p.index.as_unit('ns').asi8
    v=p[['open','high','low']].to_numpy()
    k=np.searchsorted(t,index.as_unit('ns').asi8+NS)
    safe=np.minimum(k,len(t)-1);end=np.minimum(k+719,len(t)-1)
    ok=(k+720<=len(t))&(t[safe]==index.as_unit('ns').asi8+NS)&(t[end]-t[safe]==719*NS)
    idx=index[ok];k=k[ok];up=[];down=[]
    for a in range(0,len(k),512):
        j=k[a:a+512];ii=j[:,None]+np.arange(720)[None,:];price=v[j,0,None]
        up.append(first(v[ii,1]>=price*1.02))
        down.append(first(v[ii,2]<=price*.99))
    return idx,k,np.concatenate(up) if up else np.array([],dtype=int),np.concatenate(down) if down else np.array([],dtype=int)

def train_mask(y,cut):
    return (y.index<cut)&(y.available<=cut.value)

def forecast(x,y,cut,end):
    tr=y.loc[train_mask(y,cut)]
    te=x.loc[(x.index>=cut)&(x.index<end)&(x.index.minute==0)]
    assert len(tr)>=1000 and not te.empty and tr.index.isin(x.index).all()
    m=HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,min_samples_leaf=100,
        learning_rate=.05,l2_regularization=1,random_state=27,early_stopping=False)
    m.fit(x.loc[tr.index],tr.R)
    pred=pd.Series(m.predict(te),index=te.index)
    return pred,float(tr.R.mean()),len(tr)

def selftest():
    event_test()
    i=pd.date_range('2021-01-01',periods=800,freq='min',tz='UTC')
    p=pd.DataFrame(dict(open=100.,high=100.,low=100.),index=i)
    p.loc[i[3],'high']=103.;p.loc[i[4],'low']=98.
    idx,k,u,d=paths12(p,i[[0,799]])
    assert len(idx)==1 and u[0]==2 and d[0]==3
    assert len(paths12(p.drop(i[9]),i[[0]])[0])==0
    y=pd.DataFrame(dict(available=[i[10].value,i[30].value]),index=i[[0,1]])
    assert train_mask(y,i[20]).tolist()==[True,False]
    print('EV02 full path and chronological label purge PASS',flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--selftest',action='store_true');parser.add_argument('--derivatives');parser.add_argument('--extension');a=parser.parse_args();selftest()
    if a.selftest:return
    cache={};xs=[];ys=[]
    for (name,warm,start,evaluation,end),root in zip(SCOPES,[a.derivatives,a.extension]):
        p,mark,funding=[load(root,k) for k in ('perp','mark','funding')]
        assert p.index.min()>=utc(warm) and p.index.max()<utc(end)
        f=features(segments(p.assign(quote=p.volume*p.close)))
        f=f.loc[(f.index>=utc(start))&(f.index<utc(end)-pd.Timedelta(days=3))]
        idx,k,u,d=paths12(p,f.index)
        y=outcomes(p,mark,funding,idx,k,u,d,'stress')
        xs.append(f);ys.append(y);cache[name]=(p,mark,funding,f)
        print('EV02_DATA='+json.dumps(dict(period=name,features=len(f),known=len(y))),flush=True)
    x=pd.concat(xs);y=pd.concat(ys)
    result={}
    for name,warm,start,evaluation,end in SCOPES:
        cuts=([utc('2021-09-01')]+list(pd.date_range('2022-01-01','2023-10-01',freq='QS',tz='UTC')) if name=='2021-23' else [utc('2026-02-01'),utc('2026-04-01'),utc('2026-07-01')])+[utc(end)]
        preds=[];errors=[]
        for cut,nxt in zip(cuts[:-1],cuts[1:]):
            pred,base,n=forecast(x,y,cut,nxt);preds.append(pred)
            known=pred.index.intersection(y.index);actual=y.loc[known,'R']
            errors.append(dict(cut=cut.isoformat(),train=n,test=len(pred),known=len(known),
                mse=float(((pred.loc[known]-actual)**2).mean()),baselineMse=float(((base-actual)**2).mean()),
                rank=float(pred.loc[known].rank().corr(actual.rank()))))
        pred=pd.concat(preds);chosen=pred.index[pred>=.10]
        print('EV02_FORECAST='+json.dumps(dict(period=name,decisions=len(pred),selected=len(chosen),folds=errors)),flush=True)
        p,mark,funding,_=cache[name];econ={}
        for delay in (1,5,15):
            shift=pd.Timedelta(minutes=delay-1)
            universe=pred.index if delay==1 else chosen
            idx,k,u,d=paths12(p,universe+shift)
            econ[str(delay)]={}
            for cost in FEES:
                yy=outcomes(p,mark,funding,idx,k,u,d,cost)
                policies=[('EV02',chosen)]+([('base',pred.index)] if delay==1 else [])
                econ[str(delay)][cost]={}
                for policy,ix in policies:
                    q=replay(pd.Series('12h',index=ix+shift,dtype='object'),{'12h':{cost:yy}},cost,start=evaluation,end=end)
                    econ[str(delay)][cost][policy]=q
                    print('EV02_ECON='+json.dumps(dict(period=name,delay=delay,cost=cost,policy=policy,**{k:q[k] for k in ('n','mean','pf','equity','ci','dd','unknown','years','signals','skipped')})),flush=True)
        result[name]=dict(folds=errors,decisions=len(pred),selected=len(chosen),economic=econ)
    Path('lab-ev02.json').write_text(json.dumps(dict(results=result,limitations='Fixed model, reused development, overlapping training labels, no independent holdout or orders.'),indent=2))
if __name__=='__main__':main()
