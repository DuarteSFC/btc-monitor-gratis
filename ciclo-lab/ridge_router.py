"""CICLO LAB: regularized expected-return model on candidate events.
Development only: expanding chronological folds, 2021-23. No trading.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,lag,rolling,segments
from flow_families import load_flow
from regime_router import regimes,candidates
from new_families import run

NS=60_000_000_000
H=240
FEE=.0008
SLIP=.0004
STOP=4.
THRESHOLD=.10
ALPHA=20.

def features(d,m,reg,signals):
    v=m.volume/lag(m,"vol20")
    x=pd.DataFrame(index=m.index)
    x["rsi"]=m.rsi/100
    x["rsi_change"]=(m.rsi-lag(m,"rsi"))/100
    x["return30"]=m.ret30
    x["return60"]=m.close/lag(m,"close",12)-1
    x["atr_rel"]=m.atr15/m.close
    x["volume_log"]=np.log(v.where(v>0))
    x["close_pos"]=(m.close-m.low)/(m.high-m.low).replace(0,np.nan)
    x["ema_gap"]=m.close/m.ema20_1h-1
    taker=d.buy.resample("5min",label="right",closed="left",origin="epoch").sum().reindex(m.index)
    x["imbalance"]=(2*taker-m.volume)/m.volume.where(m.volume>0)
    x["hour_sin"]=np.sin(2*np.pi*m.index.hour/24)
    x["hour_cos"]=np.cos(2*np.pi*m.index.hour/24)
    for k in ["up","down","range","shock","unknown"]:x["reg_"+k]=(reg==k).astype(float)
    for k,v in signals.items():x["sig_"+k]=v.astype(float)
    return x.replace([np.inf,-np.inf],np.nan)

def labels(d,m,mask):
    """Stress-cost net R; each candidate hypothetical, overlaps allowed in training.
    Label only when entire outcome is observable; no training across cutoffs.
    """
    t=d.index.as_unit("ns").asi8;v=d[["open","high","low","close"]].to_numpy();sg=d.segment.to_numpy()
    rows=[]
    for dt,f in m.loc[mask].iterrows():
        et=dt.value+NS;k=int(np.searchsorted(t,et))
        if k>=len(t) or t[k]!=et or sg[k]!=f.segment or k+H>len(t):continue
        z=v[k:k+H];ts=t[k:k+H]
        if ts[-1]!=et+(H-1)*NS or sg[k+H-1]!=f.segment:continue
        entry=z[0,0]*(1+SLIP);stop=entry-STOP*f.atr15
        if not 0<stop<entry:continue
        risk=entry*(1+FEE)-stop*(1-SLIP)*(1-FEE)
        target=(entry*(1+FEE)+2*risk)/((1-SLIP)*(1-FEE))
        hits=np.flatnonzero((z[:,2]<=stop)|(z[:,1]>=target))
        if len(hits):
            j=int(hits[0]);out=min(z[j,0],stop) if z[j,2]<=stop else target
        else:j=H-1;out=z[j,3]
        R=(out*(1-SLIP)*(1-FEE)-entry*(1+FEE))/risk
        rows.append((dt,pd.Timestamp(int(ts[-1]+NS),unit="ns",tz="UTC"),float(R)))
    return pd.DataFrame(rows,columns=["signal","label_available","R"]).set_index("signal")

def fit_predict(train,test,y):
    # Train-only median imputation, scaling, clipping; ridge with unpenalized intercept.
    a=train.to_numpy(dtype=float);b=test.to_numpy(dtype=float)
    med=np.array([np.median(c[np.isfinite(c)]) if np.isfinite(c).any() else 0. for c in a.T])
    a=np.where(np.isfinite(a),a,med);b=np.where(np.isfinite(b),b,med)
    mu=a.mean(0);sd=a.std(0);sd=np.where(sd>1e-10,sd,1.)
    a=np.clip((a-mu)/sd,-6,6);b=np.clip((b-mu)/sd,-6,6)
    a=np.c_[np.ones(len(a)),a];b=np.c_[np.ones(len(b)),b]
    # Equal weight per UTC day to limit clusters of overlapping labels.
    count=pd.Series(1.,index=train.index).groupby(train.index.floor("D")).transform("sum").to_numpy()
    w=1/count;w=w/w.mean()
    penalty=np.eye(a.shape[1])*ALPHA;penalty[0,0]=0
    beta=np.linalg.solve(a.T@(w[:,None]*a)+penalty,a.T@(w*y))
    return b@beta

def selftest():
    idx=pd.date_range("2020-01-01",periods=300,freq="min",tz="UTC")
    d=segments(pd.DataFrame(dict(open=100.,high=100.1,low=99.9,close=100.,volume=1.,quote=100.),index=idx))
    m=pd.DataFrame(dict(atr15=[1.],segment=[1]),index=pd.DatetimeIndex([idx[5]]))
    mask=pd.Series(True,index=m.index);z=labels(d,m,mask)
    assert len(z)==1 and z.iloc[0].R<0 and z.iloc[0].label_available==idx[246]
    assert labels(segments(d.drop(idx[9])),m,mask).empty
    x=pd.DataFrame({"a":np.arange(100.),"b":np.nan},index=idx[:100])
    p=fit_predict(x.iloc[:80],x.iloc[80:],np.arange(80.)/80)
    assert np.isfinite(p).all() and p[-1]>p[0]
    print("Ridge labels, gap exclusion, availability and train-only scaling PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")]
    d=load_flow(a.dataset,d);m=signal_frames(d);reg=regimes(d,m);s=candidates(d,m)
    union=pd.Series(False,index=m.index)
    for v in s.values():union|=v
    x=features(d,m,reg,s).loc[union]
    y=labels(d,m,union)
    selected=pd.Series(False,index=m.index);folds={}
    for year in [2021,2022,2023]:
        cut=pd.Timestamp(f"{year}-01-01",tz="UTC");end=pd.Timestamp(f"{year+1}-01-01",tz="UTC")
        train=y.loc[(y.index<cut)&(y.label_available<=cut)]
        test=x.loc[(x.index>=cut)&(x.index<end)]
        if len(train)<200:raise ValueError("insufficient training labels")
        pred=fit_predict(x.loc[train.index],test,train.R.to_numpy())
        picks=test.index[pred>=THRESHOLD]
        selected.loc[picks]=True
        dd=d.loc[d.index<end];mm=m.loc[m.index<end]
        mask=pd.Series(mm.index.isin(picks),index=mm.index)
        q=run(dd,mm,mask);stress=run(dd,mm,mask,fee=FEE,slip=SLIP)
        folds[str(year)]=dict(train=len(train),test=len(test),signals=len(picks),normal=q,stress=stress)
        print("RIDGE_FOLD="+json.dumps(dict(year=year,train=len(train),test=len(test),signals=len(picks),n=q["n"],mean=q["conservativeMeanR"],stress=stress["conservativeMeanR"],equity=q["equityEnd"])),flush=True)
    normal=run(d,m,selected);stress=run(d,m,selected,fee=FEE,slip=SLIP)
    report=dict(period="2021-2023 development walk-forward",threshold=THRESHOLD,alpha=ALPHA,features=list(x.columns),folds=folds,normal=normal,stress=stress,limitations="Ridge predicts expected stress-cost R, not calibrated win probability. Candidate labels overlap, day-weighted; missing-data labels excluded from training but evaluation trades penalized by existing simulator. Already inspected development years; not independent. Spot proxy, no funding. No trade if predicted R below threshold. Hyperparameters fixed for this run, not preregistered independent test.")
    Path("lab-ridge-router.json").write_text(json.dumps(report,indent=2))
    print("RIDGE="+json.dumps({k:v for k,v in report.items() if k!="folds"}),flush=True)
if __name__=="__main__":main()
