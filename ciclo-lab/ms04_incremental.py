"""MS04: paired price versus microstructure ridge models, no optimization."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from ms1_dataset import WEEKS,DATES
from ms01_absorption import read_week,market,selftest as base_test
from derivative_screen import load
from ridge_router import fit_predict
from hourly_futures import make_outcomes,FEES
from validation_rehearsal import replay,utc

THRESHOLD=.10
def features(a):
    cols=["open","high","low","close","volume","buyVolume","aggregates","buyAggregates","maxAggregate"]
    g=a[cols].resample("5min",closed="right",label="right")
    z=g.agg(dict(open="first",high="max",low="min",close="last",volume="sum",buyVolume="sum",aggregates="sum",buyAggregates="sum",maxAggregate="max"))
    complete=g.count().eq(60).all(axis=1)
    z=z.where(complete)
    x=pd.DataFrame(index=z.index);u=pd.DataFrame(index=z.index)
    for n in [1,3,6,12]:
        x[f"ret{n}"]=z.close/z.open.shift(n-1)-1
    x["range5"]=(z.high-z.low)/z.close
    x["range60"]=(z.high.rolling(12,min_periods=12).max()-z.low.rolling(12,min_periods=12).min())/z.close
    x["closeLocation"]=(z.close-z.low)/(z.high-z.low).replace(0,np.nan)
    x["relVolume"]=z.volume/z.volume.shift(1).rolling(11,min_periods=11).median().replace(0,np.nan)
    for n in [1,3,12]:
        s=z[["volume","buyVolume","aggregates","buyAggregates"]].rolling(n,min_periods=n).sum()
        sell=s.volume-s.buyVolume;sc=s.aggregates-s.buyAggregates
        u[f"volumeImb{n}"]=2*s.buyVolume/s.volume.replace(0,np.nan)-1
        u[f"countImb{n}"]=2*s.buyAggregates/s.aggregates.replace(0,np.nan)-1
        u[f"sizeRatio{n}"]=np.log((s.buyVolume/s.buyAggregates.where(s.buyAggregates>0))/(sell.where(sell>0)/sc.where(sc>0)))
    u["maxAggShare"]=z.maxAggregate/z.volume.replace(0,np.nan)
    sq=(a.volume**2).resample("5min",closed="right",label="right").sum(min_count=60)
    u["concentration"]=sq/z.volume.pow(2).replace(0,np.nan)
    rr=np.log(a.close/a.open)
    u["vol5s"]=np.sqrt((rr**2).resample("5min",closed="right",label="right").sum(min_count=60))
    ok=complete.rolling(12,min_periods=12).sum().eq(12)&(z.index.minute%15==0)
    return z.loc[ok,"close"],x.loc[ok].replace([np.inf,-np.inf],np.nan),u.loc[ok].replace([np.inf,-np.inf],np.nan)

def tables(m,p,mark,funding,delay,cost):
    z=m.copy();z["atr1"]/=.6;z.index+=pd.Timedelta(minutes=delay-1)
    return make_outcomes(z,pd.Series(True,index=z.index),p,mark,funding,240,*FEES[cost])

def evaluate_forecasts(pred,y):
    known=pred.join(y[["R"]],how="inner").dropna()
    rows={}
    for col in ["price","micro"]:
        a=known[col];r=known.R
        rows[col]=dict(n=len(a),mse=float(((a-r)**2).mean()),mae=float((a-r).abs().mean()),spearman=float(a.corr(r,method="spearman")) if len(a)>1 and a.nunique()>1 and r.nunique()>1 else None)
    delta=((known.micro-known.R)**2-(known.price-known.R)**2)
    day=delta.groupby(delta.index.floor("D")).mean()
    return dict(models=rows,dayMeanMSEDelta=float(day.mean()),daysMicroBetter=int((day<0).sum()),days=len(day))

def selftest():
    base_test()
    i=pd.date_range("2022-01-01 00:00:05",periods=60*24,freq="5s",tz="UTC")
    a=pd.DataFrame(dict(open=100.,high=100.1,low=99.9,close=100.,volume=1.,buyVolume=.6,aggregates=10.,buyAggregates=4.,maxAggregate=.1),index=i)
    z,x,u=features(a)
    assert len(x)>0 and abs(u.iloc[-1].volumeImb1-.2)<1e-10
    cut=i[900]
    b=a.copy();b.loc[b.index>cut,"buyVolume"]=.9
    _,xx,uu=features(b)
    pd.testing.assert_frame_equal(x.loc[:cut],xx.loc[:cut]);pd.testing.assert_frame_equal(u.loc[:cut],uu.loc[:cut])
    b=a.copy();b.iloc[100,:]=np.nan
    assert features(b)[1].index.min()>x.index.min()
    print("MS04 matched support, size and flow features, future mutation PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    if a.selftest:return
    root=Path(a.dataset);meta=json.loads((root/"manifest.json").read_text())
    assert meta["dates"]==DATES and meta["weeks"]==WEEKS and meta["verified"]==70 and not meta["errors"]
    items={r["day"]:r for r in meta["results"]};assert set(items)==set(DATES)
    old=[load(a.derivatives,k) for k in ["perp","mark","funding"]]
    new=[load(a.extension,k) for k in ["perp","mark","funding"]]
    assert old[0].index.max()<utc("2024-01-01") and new[0].index.min()>=utc("2026-01-01")
    trainx=[];trainu=[];trainy=[];records={};folds=[]
    for week in WEEKS:
        p,mark,funding=old if week<"2024" else new
        d,_=read_week(root,items,week,p)
        close,x,u=features(d)
        ix=x.index[x.index<utc(week)+pd.Timedelta(days=7,hours=-4,minutes=-30)]
        m=market(p,ix)
        ix=m.index[m.atr1.notna()&m.atr1.gt(0)&m.segment.notna()]
        m=m.loc[ix];x=x.loc[ix];u=u.loc[ix]
        x["atrRel"]=m.atr1/.6/close.loc[ix]
        # Missing numerical features handled only by train-derived medians.
        y=tables(m,p,mark,funding,1,"stress")
        if week>="2023":
            xx=pd.concat(trainx);uu=pd.concat(trainu);yy=pd.concat(trainy)
            good=yy.index[(yy.index<utc(week))&(yy.available<=utc(week).value)]
            assert len(good)>=300 and good.isin(xx.index).all()
            pr=pd.Series(fit_predict(xx.loc[good],x,yy.loc[good].R.to_numpy()),index=ix)
            pm=pd.Series(fit_predict(xx.join(uu).loc[good],x.join(u),yy.loc[good].R.to_numpy()),index=ix)
            pred=pd.DataFrame(dict(price=pr,micro=pm))
            q=evaluate_forecasts(pred,y)
            fold=dict(week=week,train=len(good),test=len(ix),known=len(y),priceSignals=int((pr>=THRESHOLD).sum()),microSignals=int((pm>=THRESHOLD).sum()),forecast=q)
            folds.append(fold);print("MS04_FOLD="+json.dumps(fold),flush=True)
            records[week]=dict(pred=pred,m=m,y=y)
        trainx.append(x);trainu.append(u);trainy.append(y)
    results={}
    for name,weeks,(p,mark,funding),start,end in [("2023",WEEKS[4:8],old,"2023-01-01","2024-01-01"),("2026",WEEKS[8:],new,"2026-04-01","2026-10-01")]:
        pred=pd.concat([records[w]["pred"] for w in weeks]);m=pd.concat([records[w]["m"] for w in weeks]);y=pd.concat([records[w]["y"] for w in weeks])
        forecast=evaluate_forecasts(pred,y)
        print("MS04_FORECAST="+json.dumps(dict(period=name,**forecast)),flush=True)
        out={}
        for policy in ["price","micro"]:
            ix=pred.index[pred[policy]>=THRESHOLD];out[policy]={}
            for delay in [1,5,15]:
                out[policy][str(delay)]={}
                for cost in FEES:
                    yy=tables(m.loc[ix],p,mark,funding,delay,cost)
                    r=pd.Series("4h",index=ix+pd.Timedelta(minutes=delay-1),dtype="object")
                    q=replay(r,{"4h":{cost:yy}},cost,start=start,end=end)
                    out[policy][str(delay)][cost]=q
                    print("MS04_RESULT="+json.dumps(dict(period=name,policy=policy,delay=delay,cost=cost,n=q["n"],signals=q["signals"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"])),flush=True)
        results[name]=dict(forecast=forecast,policies=out)
    Path("lab-ms04.json").write_text(json.dumps(dict(folds=folds,results=results,limitations="Six test weeks only, reused development, overlapping labels. No threshold tuning, common support and purged expanding training, descriptive forecast loss and simulated portfolio. 24 replays, no independent significance, no release."),indent=2))
if __name__=="__main__":main()
