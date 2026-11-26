"""CICLO LAB frequency/anticipation screen. Development only, 2021-23.
Chronological quarterly refits, purged targets, fixed grid, block-bootstrap
diagnostics (not independent confirmation). No orders or production imports.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,segments
from flow_families import load_flow
from regime_router import regimes,candidates
from ridge_router import features,labels,fit_predict
from new_families import run

THRESHOLDS=[-.02,0.,.03,.06,.10]
NS=60_000_000_000
def expanded(x):
    # Fixed nonlinear interactions, no feature selection using evaluation outcomes.
    z=x.copy()
    for a,b in [("rsi","return30"),("atr_rel","imbalance"),("volume_log","imbalance"),
                ("return60","ema_gap"),("rsi_change","close_pos"),("atr_rel","return30")]:
        z[a+"*"+b]=x[a]*x[b]
    for a in ["rsi","return30","return60","imbalance","atr_rel"]:z[a+"^2"]=x[a]**2
    return z

def predict(x,y,quarterly):
    dates=pd.date_range("2021-01-01","2024-01-01",freq="QS" if quarterly else "YS",tz="UTC")
    out=[]
    for cut,end in zip(dates[:-1],dates[1:]):
        train=y.loc[(y.index<cut)&(y.label_available<=cut)]
        test=x.loc[(x.index>=cut)&(x.index<end)]
        if len(train)<200:raise ValueError("insufficient labels")
        if len(test):out.append(pd.Series(fit_predict(x.loc[train.index],test,train.R.to_numpy()),index=test.index))
    return pd.concat(out)

def trade_audit(d,m,mask,fee,slip):
    t=d.index.as_unit("ns").asi8;v=d[["open","high","low","close"]].to_numpy();sg=d.segment.to_numpy()
    last=-1;rr=[];unknown=0
    for dt,f in m.loc[mask].iterrows():
        et=dt.value+NS
        if et<=last or et+239*NS>t[-1]:continue
        k=int(np.searchsorted(t,et))
        if k>=len(t) or t[k]!=et or sg[k]!=f.segment:continue
        z=v[k:k+240];ts=t[k:k+240]
        raw=z[0,0];entry=raw*(1+slip);stop=entry-4*f.atr15
        if not 0<stop<entry:continue
        risk=entry*(1+fee)-stop*(1-slip)*(1-fee)
        target=(entry*(1+fee)+2*risk)/((1-slip)*(1-fee))
        gaps=np.flatnonzero((ts!=et+np.arange(len(ts))*NS)|(sg[k:k+240]!=f.segment))
        gap=int(gaps[0]) if len(gaps) else len(z)
        hits=np.flatnonzero((z[:gap,2]<=stop)|(z[:gap,1]>=target))
        if len(hits):
            j=int(hits[0]);out=min(z[j,0],stop) if z[j,2]<=stop else target
        elif gap<len(z):
            j=gap;out=0.;unknown+=1
        else:j=len(z)-1;out=z[j,3]
        last=int(ts[j]+NS)
        R=(out*(1-slip)*(1-fee)-entry*(1+fee))/risk
        # First +1% from entry quote before -1%, within trade lifetime; stop-first on ties.
        # This is conditional on selected entries, not recall of all market moves.
        path=z[:min(j+1,gap)]
        up=np.flatnonzero(path[:,1]>=raw*1.01);dn=np.flatnonzero(path[:,2]<=raw*.99)
        success=bool(len(up) and (not len(dn) or up[0]<dn[0]))
        # Exit candle ordering unknown: do not claim milestone if stop/target exit occurs in that candle.
        if success and len(hits) and up[0]>=j:success=False
        rr.append(dict(time=dt.isoformat(),R=float(R),hit1=success,lead=int(up[0]+1) if success else None))
    if not rr:return dict(n=0,unknown=0,mean=None,ci=None,hitRate=None,medianLead=None,records=[])
    f=pd.DataFrame(rr);f["month"]=pd.to_datetime(f.time,utc=True).dt.strftime("%Y-%m")
    blocks=f.groupby("month").R.agg(["sum","count"])
    # Resample calendar months including empty months in the evaluation period.
    months=pd.period_range("2021-01","2023-12",freq="M").astype(str)
    blocks=blocks.reindex(months,fill_value=0)
    rng=np.random.default_rng(20261126);i=rng.integers(0,len(blocks),size=(2000,len(blocks)))
    sums=blocks["sum"].to_numpy()[i].sum(1);counts=blocks["count"].to_numpy()[i].sum(1)
    boots=sums[counts>0]/counts[counts>0]
    return dict(n=len(f),unknown=unknown,mean=float(f.R.mean()),ci=np.quantile(boots,[.025,.975]).tolist(),
        hitRate=float(f.hit1.mean()),medianLead=float(f.loc[f.hit1,"lead"].median()) if f.hit1.any() else None,records=rr)

def selftest():
    from ridge_router import selftest as rtest
    rtest()
    idx=pd.date_range("2021-01-01",periods=300,freq="min",tz="UTC")
    d=segments(pd.DataFrame(dict(open=100.,high=100.1,low=99.9,close=100.,volume=1.,quote=100.),index=idx))
    m=pd.DataFrame(dict(atr15=[1.],segment=[1],trend4h=[True]),index=pd.DatetimeIndex([idx[5]]))
    mask=pd.Series(True,index=m.index);a=trade_audit(d,m,mask,.0008,.0004)
    q=run(d,m,mask,fee=.0008,slip=.0004)
    assert a["n"]==q["n"] and abs(a["mean"]-q["conservativeMeanR"])<1e-10
    d.loc[idx[16],"high"]=101.5
    a=trade_audit(d,m,mask,.0008,.0004)
    assert a["hitRate"]==1 and a["medianLead"]==11
    d.loc[idx[16],"low"]=98.5
    assert trade_audit(d,m,mask,.0008,.0004)["hitRate"]==0
    print("Trade audit, replay parity, milestone and stop-first tests PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")]
    d=load_flow(a.dataset,d);m=signal_frames(d);reg=regimes(d,m);s=candidates(d,m)
    union=pd.Series(False,index=m.index)
    for v in s.values():union|=v
    x=features(d,m,reg,s).loc[union];y=labels(d,m,union)
    variants={"annual_linear":predict(x,y,False),"quarterly_linear":predict(x,y,True),"quarterly_interactions":predict(expanded(x),y,True)}
    results={}
    for name,pred in variants.items():
        for th in THRESHOLDS:
            mask=pd.Series(m.index.isin(pred.index[pred>=th]),index=m.index)
            q=run(d,m,mask);stress=run(d,m,mask,fee=.0008,slip=.0004);audit=trade_audit(d,m,mask,.0008,.0004)
            assert audit["n"]==stress["n"]
            if audit["n"]:assert abs(audit["mean"]-stress["conservativeMeanR"])<1e-8
            ci=audit["ci"]
            years=sum(1 for yr,v in stress["years"].items() if yr!="2020" and v["n"]>=25 and v["conservativeMeanR"] is not None and v["conservativeMeanR"]>0)
            passed=bool(q["n"]>=150 and stress["n"]>=150 and audit["unknown"]==0 and q["unknown"]==0 and ci and ci[0]>0 and q["conservativeMeanR"]>=.05 and q["profitFactor"] is not None and q["profitFactor"]>=1.15 and years>=2)
            key=f"{name}:{th:.2f}"
            results[key]=dict(normal=q,stress=stress,audit=audit,screenPass=passed)
            print("SCREEN="+json.dumps(dict(key=key,n=q["n"],normal=q["conservativeMeanR"],stress=stress["conservativeMeanR"],pf=q["profitFactor"],equity=q["equityEnd"],ci=ci,hit1=audit["hitRate"],lead=audit["medianLead"],unknown=audit["unknown"],passed=passed)),flush=True)
    Path("lab-frequency-screen.json").write_text(json.dumps(dict(period="2021-2023 previously inspected development",thresholds=THRESHOLDS,results=results,limitations="15 correlated variants; bootstrap intervals unadjusted for selection and not proof; month blocks approximate dependence; spot proxy, funding absent; milestone conditional on executed positions, no market-wide recall; unknown regimes allowed as explicit feature; no holdout accessed."),indent=2))
if __name__=="__main__":main()
