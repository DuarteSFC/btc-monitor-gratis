"""EV01: event-first diagnostics and one fixed economic rule; development only."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import segments,bars,atr,rsi,ema,lag,rolling,align
from derivative_screen import load
from hourly_futures import FEES,NS
from validation_rehearsal import replay,utc

TARGETS=[.01,.02,.03,.05]
HORIZONS=[120,240,720,1440,2880]

def features(d):
    m=bars(d,15); h=bars(d,60); q=bars(d,240)
    h['a']=atr(h)/h.close
    q['trend']=(ema(q,20)>ema(q,60)).astype(float).where(ema(q,60).notna())
    return pd.DataFrame(dict(ret4=m.close/lag(m,'close',16)-1,
        ret1=m.close/lag(m,'close',4)-1,rsi=rsi(m),
        atr=align(h,m,'a'),vol=m.volume/lag(m.assign(avg=rolling(m,'volume',96,lambda r:r.mean())),'avg'),
        trend=align(q,m,'trend')),index=m.index).replace([np.inf,-np.inf],np.nan).dropna()

def first(mask):
    return np.where(mask.any(axis=1),mask.argmax(axis=1),mask.shape[1])

def paths(p,index):
    t=p.index.as_unit('ns').asi8
    v=p[['open','high','low','close']].to_numpy()
    k=np.searchsorted(t,index.as_unit('ns').asi8+NS)
    ok=k+2880<=len(t)
    safe=np.minimum(k,len(t)-1);end=np.minimum(k+2879,len(t)-1)
    ok &= (t[safe]==index.as_unit('ns').asi8+NS)&(t[end]-t[safe]==2879*NS)
    idx=index[ok];k=k[ok];out={}
    for target in TARGETS:
        ups=[];downs=[]
        for a in range(0,len(k),256):
            j=k[a:a+256];ii=j[:,None]+np.arange(2880)[None,:];price=v[j,0,None]
            ups.append(first(v[ii,1]>=price*(1+target)))
            downs.append(first(v[ii,2]<=price*(1-target/2)))
        out[target]=(np.concatenate(ups),np.concatenate(downs)) if len(k) else (np.array([],dtype=int),np.array([],dtype=int))
    return idx,k,out

def classification(u,d,h):
    return np.where((d<h)&(d<=u),-1,np.where((u<h)&(u<d),1,0))

def describe(a,u):
    n=len(a);hit=a==1
    return dict(n=n,up=int(hit.sum()),down=int((a==-1).sum()),timeout=int((a==0).sum()),
        upRate=float(hit.mean()) if n else None,medianLeadMin=float(np.median(u[hit]+1)) if hit.any() else None)

def strata(f):
    return {'ret4neg':f.ret4<0,'ret4nonneg':f.ret4>=0,'rsiLow':f.rsi<40,
        'rsiMid':f.rsi.between(40,60),'rsiHigh':f.rsi>60,'ret1pos':f.ret1>0,'ret1nonpos':f.ret1<=0,
        'atrHigh':f.atr>=.01,'atrLow':f.atr<.01,'volHigh':f.vol>=1.5,'volLow':f.vol<1.5,
        'trendUp':f.trend==1,'trendOther':f.trend==0,'EV01':(f.ret4<0)&(f.ret1>0)&(f.rsi<60)}

def outcomes(p,mark,funding,idx,k,u,d,cost):
    fee,slip=FEES[cost]
    v=p[['open','high','low','close']].to_numpy();t=p.index.as_unit('ns').asi8
    cl=classification(u,d,720);j=np.where(cl==1,u,np.where(cl==-1,d,719));q=k+j
    raw=v[k,0];entry=raw*(1+slip);stop=raw*.99
    out=np.where(cl==1,raw*1.02,np.where(cl==-1,np.minimum(stop,v[q,0]),v[q,3]))
    risk=entry*(1+fee)-stop*(1-slip)*(1-fee)
    ft=funding.index.as_unit('ns').asi8;prior=funding.index.floor('min')-pd.Timedelta(minutes=1)
    mp=mark.close.reindex(prior).to_numpy();pp=p.close.reindex(prior).to_numpy();fallback=~np.isfinite(mp)
    px=np.where(fallback,pp,mp);rates=funding.rate.to_numpy()
    charge=px*rates;valid=np.isfinite(charge);charge=np.where(valid,charge,0.)
    def sums(arr,a,b):
        pre=np.r_[0,np.cumsum(arr)];return pre[b]-pre[a]
    left=np.searchsorted(ft,t[k],side='left');right=np.searchsorted(ft,t[q]+NS,side='left')
    # No credit for negative settlement in uncertain stop/target exit minute.
    rneg=np.where(cl!=0,np.searchsorted(ft,t[q],side='left'),right)
    fundingPaid=sums(np.maximum(charge,0),left,right)+sums(np.minimum(charge,0),left,rneg)
    known=(sums(~valid,left,right)==0)&(risk>0)
    net=out*(1-slip)*(1-fee)-entry*(1+fee)-fundingPaid
    z=pd.DataFrame(dict(R=net/risk,riskFraction=risk/(entry*(1+fee)),fundingR=fundingPaid/risk,
        fallback=sums(fallback,left,right),exit=t[q]+NS,available=t[k+719]+NS),index=idx)
    return z.loc[known]

def selftest():
    from validation_rehearsal import selftest as test
    test()
    a=np.array([[False,True,True],[False,False,False],[True,False,False]])
    np.testing.assert_array_equal(first(a),[1,3,0])
    np.testing.assert_array_equal(classification(np.array([1,1,3,3]),np.array([2,1,2,3]),3),[1,-1,-1,0])
    i=pd.date_range('2021-01-01',periods=3000,freq='min',tz='UTC')
    p=pd.DataFrame(dict(open=100.,high=100.,low=100.,close=100.),index=i)
    p.loc[i[3],'high']=103.;p.loc[i[3],'low']=98.
    idx,k,events=paths(p,i[[0,1,2999]])
    assert len(idx)==2 and classification(*events[.02],720).tolist()==[-1,-1]
    assert len(paths(p.drop(i[9]),i[[0]])[0])==0
    f=pd.DataFrame(dict(rate=[.001]),index=i[[2]])
    z=outcomes(p,p,f,idx,k,*events[.02],'normal')
    assert len(z)==2 and (z.R<-1).all()
    print('EV01 first passage, conservative ties, gaps, funding and stop PASS',flush=True)

def main():
    a=argparse.ArgumentParser();a.add_argument('--selftest',action='store_true');a.add_argument('--derivatives');a.add_argument('--extension');a=a.parse_args();selftest()
    if a.selftest:return
    result={}
    for name,root,warm,start,end in [('2021-23',a.derivatives,'2021-01-01','2021-02-01','2024-01-01'),('2026',a.extension,'2026-01-01','2026-02-01','2026-10-01')]:
        p,mark,funding=[load(root,k) for k in ('perp','mark','funding')]
        assert p.index.min()>=utc(warm) and p.index.max()<utc(end)
        f=features(segments(p.assign(quote=p.volume*p.close)))
        f=f.loc[(f.index>=utc(start))&(f.index<utc(end)-pd.Timedelta(days=3))]
        idx,k,events=paths(p,f.index);g=f.loc[idx];u,d=events[.02];cl=classification(u,d,720)
        print('EV01_SCOPE='+json.dumps(dict(period=name,featureDecisions=len(f),known=len(g),missing=len(f)-len(g))),flush=True)
        tab={}
        for target,(up,down) in events.items():
            for h in HORIZONS:
                key=f'{target}:{h}';v=classification(up,down,h);hour=idx.minute==0
                tab[key]={'15m':describe(v,up),'1h':describe(v[hour],up[hour])}
                print('EV01_EVENT='+json.dumps(dict(period=name,target=target,horizon=h,**tab[key])),flush=True)
        groups={key:describe(cl[mask],u[mask]) for key,mask in strata(g).items()}
        groups['EV01']['decisionRecall']=groups['EV01']['up']/int((cl==1).sum()) if (cl==1).any() else None
        years={str(y):describe(cl[idx.year==y],u[idx.year==y]) for y in np.unique(idx.year)}
        sparse=(idx.hour%12==0)&(idx.minute==0)
        print('EV01_PRIMARY='+json.dumps(dict(period=name,base=describe(cl,u),strata=groups,years=years,sparse=describe(cl[sparse],u[sparse]))),flush=True)
        economic={}
        for cost in FEES:
            y=outcomes(p,mark,funding,idx,k,u,d,cost);economic[cost]={}
            for policy,ix in [('base',f.index),('EV01',f.index[strata(f)['EV01']])]:
                q=replay(pd.Series('12h',index=ix,dtype='object'),{'12h':{cost:y}},cost,start=start,end=end)
                economic[cost][policy]=q
                print('EV01_ECON='+json.dumps(dict(period=name,cost=cost,policy=policy,**{k:q[k] for k in ('n','mean','pf','equity','ci','dd','unknown','years','signals','skipped')})),flush=True)
        result[name]=dict(featureDecisions=len(f),known=len(g),events=tab,strata=groups,years=years,sparse=describe(cl[sparse],u[sparse]),economic=economic)
    Path('lab-ev01.json').write_text(json.dumps(dict(results=result,limitations='Overlapping hypothetical decisions; 12h spaced sample sensitivity; fixed economic rule, unknowns fail gate, development reused; no independent evidence or orders.'),indent=2))
if __name__=='__main__':main()
