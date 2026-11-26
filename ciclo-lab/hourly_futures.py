"""Hourly decision grid, multi-horizon expected-return research on BTCUSDT perpetual.
Development only. No live orders, leverage or production imports.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,bars,atr,align,lag,segments
from flow_families import load_flow
from regime_router import regimes,candidates
from ridge_router import features,fit_predict
from derivative_screen import load,derivative_features

NS=60_000_000_000
HORIZONS=[240,720,1440]
FEES={"normal":(.0005,.0002),"stress":(.0008,.0004)}
THRESHOLD=.10
def outcome(t,v,sg,dt,seg,atr1,h,fee,slip,ft,fr,fp,fallback):
    et=dt.value+NS;k=int(np.searchsorted(t,et))
    if k>=len(t) or t[k]!=et or k+h>len(t):return None
    if t[k+h-1]!=et+(h-1)*NS or sg[k+h-1]!=sg[k]:return None
    raw=v[k,0];entry=raw*(1+slip);stop=entry-2.5*atr1
    if not 0<stop<entry:return None
    risk=entry*(1+fee)-stop*(1-slip)*(1-fee)
    z=v[k:k+h];hits=np.flatnonzero(z[:,2]<=stop)
    j=int(hits[0]) if len(hits) else h-1
    out=min(z[j,0],stop) if len(hits) else z[j,3]
    exit_open=t[k+j];exit_close=exit_open+NS
    a=int(np.searchsorted(ft,et,side="left"));b=int(np.searchsorted(ft,exit_close,side="left"))
    rate=fr[a:b];prices=fp[a:b];times=ft[a:b]
    if not np.isfinite(prices).all():return None
    # Charge positive settlement when holding at any point in the exit minute;
    # only credit negative funding when unambiguously held before exit minute.
    charge=rate*prices
    charge=np.where((times>=exit_open)&(charge<0)&bool(len(hits)),0.,charge)
    funding=float(charge.sum())
    net=out*(1-slip)*(1-fee)-entry*(1+fee)-funding
    return dict(R=float(net/risk),riskFraction=float(risk/(entry*(1+fee))),
        fundingR=float(funding/risk),exit=int(exit_close),available=int(t[k+h-1]+NS),
        fallback=int(fallback[a:b].sum()),reason="stop" if len(hits) else "timeout")
def make_outcomes(m,eligible,perp,mark,funding,h,fee,slip):
    t=perp.index.as_unit("ns").asi8;v=perp[["open","high","low","close"]].to_numpy()
    sg=np.cumsum(np.r_[True,np.diff(t)!=NS])
    ft=funding.index.as_unit("ns").asi8;fr=funding.rate.to_numpy()
    # Last completed mark candle at settlement. If absent, use last completed
    # perpetual candle as explicitly counted approximation, not forward-filled mark.
    prior=funding.index.floor("min")-pd.Timedelta(minutes=1)
    mk=mark.close.reindex(prior).to_numpy();px=perp.close.reindex(prior).to_numpy()
    fallback=~np.isfinite(mk);fp=np.where(fallback,px,mk)
    rows=[]
    for dt,f in m.loc[eligible,["segment","atr1"]].iterrows():
        if dt.value+(h+1)*NS>t[-1]+NS:continue
        r=outcome(t,v,sg,dt,f.segment,f.atr1,h,fee,slip,ft,fr,fp,fallback)
        if r is not None:rows.append(dict(time=dt,**r))
    return pd.DataFrame(rows).set_index("time") if rows else pd.DataFrame(columns=["R","riskFraction","fundingR","exit","available","fallback","reason"],index=pd.DatetimeIndex([],tz="UTC"))
def predict(x,y):
    out=[]
    for cut in pd.date_range("2022-01-01","2023-10-01",freq="QS",tz="UTC"):
        end=cut+pd.offsets.QuarterBegin(startingMonth=1)
        train=y.loc[(y.index<cut)&(y.available<=cut.value)]
        test=x.loc[(x.index>=cut)&(x.index<end)]
        if len(train)<200:raise ValueError("insufficient training")
        if len(test):out.append(pd.Series(fit_predict(x.loc[train.index],test,train.R.to_numpy()),index=test.index))
    return pd.concat(out)
def evaluate(pred,y,threshold):
    equity=peak=10000.;dd=0.;last=-1;records=[];unknown=0
    for dt in pred.index[pred>=threshold]:
        if dt.value+NS<last:continue
        if dt not in y.index:
            # Unknown outcome, no fabricated PnL. Count and fail gate.
            unknown+=1;last=dt.value+(1441)*NS;continue
        q=y.loc[dt]
        qtyrisk=min(.0025*equity,equity*q.riskFraction)
        pnl=qtyrisk*q.R
        equity=max(0.,equity+pnl);peak=max(peak,equity);dd=max(dd,(peak-equity)/peak)
        last=int(q.exit);records.append(dict(time=dt.isoformat(),R=float(q.R),fundingR=float(q.fundingR),fallback=int(q.fallback),pnl=float(pnl)))
    n=len(records)
    if not n:return dict(n=0,unknown=unknown,mean=None,pf=None,win=None,equity=equity,dd=dd,ci=None,years={},fundingR=None,fallback=0,records=[])
    f=pd.DataFrame(records);r=f.R.to_numpy();loss=-r[r<0].sum()
    times=pd.to_datetime(f.time,utc=True);f["month"]=times.dt.strftime("%Y-%m")
    b=f.groupby("month").R.agg(["sum","count"]).reindex(pd.period_range("2022-01","2023-12",freq="M").astype(str),fill_value=0)
    rng=np.random.default_rng(20261126);i=rng.integers(0,len(b),size=(2000,len(b)))
    a=b["sum"].to_numpy()[i].sum(1);c=b["count"].to_numpy()[i].sum(1)
    ci=np.quantile(a[c>0]/c[c>0],[.025,.975]).tolist()
    years={str(k):dict(n=len(g),mean=float(g.R.mean())) for k,g in f.groupby(times.dt.year)}
    return dict(n=n,unknown=unknown,mean=float(r.mean()),pf=float(r[r>0].sum()/loss) if loss else None,win=float((r>0).mean()),equity=equity,dd=dd,ci=ci,years=years,fundingR=float(f.fundingR.sum()),fallback=int(f.fallback.sum()),records=records)
def selftest():
    idx=pd.date_range("2022-01-01",periods=300,freq="min",tz="UTC")
    t=idx.as_unit("ns").asi8;v=np.tile([100.,100.1,99.9,100.],(len(t),1));sg=np.ones(len(t))
    ft=np.array([t[30]]);fr=np.array([.001]);fp=np.array([100.]);fb=np.array([False])
    a=outcome(t,v,sg,idx[5],1,1.,240,.0005,.0002,ft,fr,fp,fb)
    assert a["R"]<0 and a["fundingR"]>0 and a["available"]==t[246]
    z=v.copy();z[10,2]=95.
    b=outcome(t,z,sg,idx[5],1,1.,240,.0005,.0002,ft,fr,fp,fb)
    assert abs(b["R"]+1)<1e-8 and b["fundingR"]==0 and b["reason"]=="stop"
    print("Hourly futures outcome, funding cashflow, stop and label availability PASS",flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")];d=load_flow(a.dataset,d)
    m=signal_frames(d);reg=regimes(d,m);s=candidates(d,m)
    h=bars(d,60);h["a"]=atr(h);m["atr1"]=align(h,m,"a")
    p,mark,metrics,funding=[load(a.derivatives,k) for k in ["perp","mark","metrics","funding"]]
    deriv=derivative_features(m,p,mark,metrics,funding,30)
    eligible=(m.index.minute==0)&(m.index.year>=2021)&m.atr1.notna()&(m.atr1>0)&deriv[["basis","oi_change15","oi_change60","funding"]].notna().all(axis=1)
    # End-of-data embargo defined before seeing results, same across horizons.
    eligible&=m.index<pd.Timestamp("2023-12-31",tz="UTC")
    x=features(d,m,reg,s);x["atr1_rel"]=m.atr1/m.close
    x["return4h"]=m.close/lag(m,"close",48)-1;x["return24h"]=m.close/lag(m,"close",288)-1
    x=x.loc[eligible];xx=x.join(deriv.loc[eligible])
    results={}
    for horizon in HORIZONS:
        y={k:make_outcomes(m,eligible,p,mark,funding,horizon,*v) for k,v in FEES.items()}
        for name,f in [("spot_features",x),("derivatives_features",xx)]:
            pred=predict(f,y["stress"])
            normal=evaluate(pred,y["normal"],THRESHOLD);stress=evaluate(pred,y["stress"],THRESHOLD)
            passed=bool(normal["n"]>=150 and stress["n"]>=150 and not normal["unknown"] and not stress["unknown"] and normal["mean"]>=.05 and normal["pf"] is not None and normal["pf"]>=1.15 and stress["ci"][0]>0 and len(stress["years"])==2 and all(v["n"]>=30 and v["mean"]>0 for v in stress["years"].values()))
            key=f"{name}:{horizon}"
            results[key]=dict(normal=normal,stress=stress,screenPass=passed)
            print("HOURLY="+json.dumps(dict(key=key,n=normal["n"],mean=normal["mean"],pf=normal["pf"],win=normal["win"],equity=normal["equity"],stress=stress["mean"],ci=stress["ci"],unknown=stress["unknown"],fundingR=stress["fundingR"],markFallback=stress["fallback"],passed=passed)),flush=True)
    Path("lab-hourly-futures.json").write_text(json.dumps(dict(period="2022-2023 development",eligible=int(eligible.sum()),horizons=HORIZONS,threshold=THRESHOLD,results=results,limitations="Six correlated experiments, not independent validation. No leverage; 2.5 ATR1h stop and time exit, no TP. Funding cashflow uses last completed mark (perpetual close fallback counted); 30m metric delay assumed. Unknown outcomes counted and fail gate; equity shown excludes unknown PnL. Full-horizon observation required even if stop earlier. Fees and slippage assumptions, no liquidation model; bootstrap unadjusted. No 2024-25 data accessed."),indent=2))
if __name__=="__main__":main()
