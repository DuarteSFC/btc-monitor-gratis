"""Phase-2 execution audit using archived development trades only.
No new model fitting, holdout data or live orders.
"""
import argparse,json,tempfile
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,bars,atr,align
from derivative_screen import load
from hourly_futures import outcome,FEES,NS
from validation_rehearsal import scoped_spot,HORIZONS,START,END

def settlement_arrays(perp,mark,funding):
    ft=funding.index.as_unit("ns").asi8
    fr=funding.rate.to_numpy()
    prior=funding.index.floor("min")-pd.Timedelta(minutes=1)
    mk=mark.close.reindex(prior).to_numpy();px=perp.close.reindex(prior).to_numpy()
    fb=~np.isfinite(mk);fp=np.where(fb,px,mk)
    return ft,fr,fp,fb

def funding_coverage(f):
    # Inspect settled funding intervals; tolerate 60 seconds of timestamp jitter.
    # This diagnoses archive support, not exact exchange publication/settlement.
    t=f.index.as_unit("ns").asi8
    hours=f.interval_hours.to_numpy(dtype=float)
    dif=np.diff(t)/NS/60
    a=np.abs(dif-hours[:-1]);b=np.abs(dif-hours[1:])
    bad=np.flatnonzero(np.minimum(a,b)>1/60)
    return dict(settlements=len(f),first=str(f.index[0]),last=str(f.index[-1]),intervalHours=sorted(set(hours.tolist())),inconsistentIntervals=len(bad),examples=[dict(start=str(f.index[i]),end=str(f.index[i+1]),gapHours=float(dif[i])) for i in bad[:10]])

def update_path(peak,dd,high,low,close):
    # Conservative high-before-low ordering within each minute; both extremes
    # can occur after the actual stop in the last minute. A proxy, not a bound.
    for h,l,c in zip(high,low,close):
        peak=max(peak,float(h),float(c))
        dd=max(dd,(peak-min(float(l),float(c)))/peak)
    return peak,dd

def audit(records,m,perp,mark,funding,cost):
    fee,slip=FEES[cost]
    t=perp.index.as_unit("ns").asi8;v=perp[["open","high","low","close"]].to_numpy()
    sg=np.cumsum(np.r_[True,np.diff(t)!=NS])
    mv=mark[["high","low","close"]].reindex(perp.index).to_numpy()
    ft,fr,fp,fb=settlement_arrays(perp,mark,funding)
    equity=10000.;closed_peak=close_peak=trade_peak=mark_peak=equity
    closed_dd=close_dd=trade_dd=mark_dd=0.
    missing_mark_minutes=fallback_count=0;total_funding=0.;last=-1;results=[]
    for r in records:
        dt=pd.Timestamp(r["time"]);h,stop=HORIZONS[r["route"]]
        atr1=float(m.at[dt,"atr1"])*stop/2.5
        et=dt.value+NS;k=int(np.searchsorted(t,et))
        assert et>=last
        q=outcome(t,v,sg,dt,0,atr1,h,fee,slip,ft,fr,fp,fb)
        if q is None:raise ValueError("archive trade cannot be reconstructed")
        np.testing.assert_allclose([q["R"],q["fundingR"]],[r["R"],r["fundingR"]],rtol=1e-10,atol=1e-10)
        assert q["exit"]==r["exit"] and q["fallback"]==r["fallback"]
        j=int(np.searchsorted(t,q["exit"]));assert j>k
        entry=v[k,0]*(1+slip);risk_per_unit=q["riskFraction"]*entry*(1+fee)
        qty=min(.0025*equity,equity*q["riskFraction"])/risk_per_unit
        pnl=qty*risk_per_unit*q["R"];np.testing.assert_allclose(pnl,r["pnl"],rtol=1e-10,atol=1e-10)
        # Reconstruct realized funding charged in the original outcome.
        a=int(np.searchsorted(ft,et,side="left"));b=int(np.searchsorted(ft,q["exit"],side="left"))
        charge=fr[a:b]*fp[a:b]
        charge=np.where((ft[a:b]>=t[j-1])&(charge<0)&(q["reason"]=="stop"),0.,charge)
        np.testing.assert_allclose(charge.sum()/risk_per_unit,q["fundingR"],rtol=1e-10,atol=1e-10)
        cash=np.zeros(j-k);neg=np.zeros(j-k)
        for time,value in zip(ft[a:b],charge):
            idx=int(np.searchsorted(t[k:j],time,side="right")-1)
            assert 0<=idx<len(cash)
            cash[idx]+=value
            if value<0:neg[idx]+=value
        cum=np.cumsum(cash)
        # For extremes, credit negative funding only at minute end;
        # positive funding charged from minute start.
        extreme_funding=cum-neg
        def net(price,fund):return equity+qty*(price*(1-slip)*(1-fee)-entry*(1+fee)-fund)
        close=net(v[k:j,3],cum);close[-1]=equity+pnl
        # The last minute high/low may not precede the stop; explicitly proxy.
        high=net(v[k:j,1],extreme_funding);low=net(v[k:j,2],extreme_funding)
        close_peak,close_dd=update_path(close_peak,close_dd,close,close,close)
        trade_peak,trade_dd=update_path(trade_peak,trade_dd,high,low,close)
        mark_part=mv[k:j];missing=~np.isfinite(mark_part).all(axis=1)
        missing_mark_minutes+=int(missing.sum())
        # Only for a descriptive mixed proxy; report fallback count.
        mark_part=np.where(missing[:,None],v[k:j][:,[1,2,3]],mark_part)
        mh=net(mark_part[:,0],extreme_funding);ml=net(mark_part[:,1],extreme_funding);mc=net(mark_part[:,2],cum);mc[-1]=equity+pnl
        mark_peak,mark_dd=update_path(mark_peak,mark_dd,mh,ml,mc)
        total_funding+=float(qty*charge.sum());fallback_count+=int(q["fallback"])
        results.append(dict(time=r["time"],route=r["route"],minutes=j-k,netFunding=float(qty*charge.sum()),pnl=pnl,exit=q["exit"]))
        equity+=pnl;last=q["exit"];closed_peak=max(closed_peak,equity);closed_dd=max(closed_dd,(closed_peak-equity)/closed_peak)
    return dict(n=len(records),equity=equity,closedDD=closed_dd,minuteCloseDD=close_dd,tradeExtremeDD=trade_dd,markExtremeDD=mark_dd,markFallbackMinutes=missing_mark_minutes,fundingFallbackSettlements=fallback_count,netFunding=total_funding,records=results)

def selftest():
    from validation_rehearsal import selftest as test
    test()
    p,d=update_path(100.,0.,[105.,102.],[98.,95.],[102.,100.])
    assert p==105 and abs(d-10/105)<1e-12
    i=pd.date_range("2022-01-01",periods=3,freq="8h",tz="UTC")
    f=pd.DataFrame(dict(interval_hours=8,rate=.0001),index=i)
    assert funding_coverage(f)["inconsistentIntervals"]==0 and funding_coverage(f.drop(i[1]))["inconsistentIntervals"]==1
    print("Intraminute drawdown ordering and funding interval diagnostics PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");a=p.parse_args()
    selftest()
    if a.selftest:return
    q=json.loads(Path("audit-rehearsal/lab-validation-rehearsal.json").read_text())
    assert q["holdoutLocked"]
    with tempfile.TemporaryDirectory() as tmp:
        scope=scoped_spot(a.dataset,tmp);d=load_minutes(tmp)
    assert scope==q["scope"]
    manifest=json.loads((Path(a.derivatives)/"manifest.json").read_text())
    assert all(f["end_exclusive"]<=END for f in manifest["files"])
    m=signal_frames(d);h=bars(d,60);h["a"]=atr(h);m["atr1"]=align(h,m,"a")
    perp,mark,funding=[load(a.derivatives,k) for k in ["perp","mark","funding"]]
    coverage=funding_coverage(funding);print("FUNDING_COVERAGE="+json.dumps(coverage),flush=True)
    results={}
    for cost in FEES:
        r=q["results"][cost];z=audit(r["records"],m,perp,mark,funding,cost)
        assert z["n"]==r["n"]==180
        np.testing.assert_allclose([z["equity"],z["closedDD"]],[r["equity"],r["dd"]],rtol=1e-10,atol=1e-10)
        assert z["minuteCloseDD"]+1e-12>=z["closedDD"] and z["tradeExtremeDD"]+1e-12>=z["minuteCloseDD"]
        results[cost]=z;print("PATH_RISK="+json.dumps(dict(cost=cost,**{k:v for k,v in z.items() if k!="records"})),flush=True)
    Path("lab-path-risk.json").write_text(json.dumps(dict(scope=scope,fundingCoverage=coverage,results=results,limitations="Development only. Original fills and funding reconstructed exactly within numerical tolerance. Minute-close marked-to-exit equity uses hypothetical fees/slippage; last minute uses realized exit. High-before-low extrema include full exit minute, possibly prices after stop; descriptive conservative proxy, not a guaranteed bound or actual exchange path. Mark missing minutes use traded extrema and are counted. No ticks, depth, liquidation or exact settlement price. Funding interval checks do not prove complete cashflow. No candidate approval."),indent=2))
if __name__=="__main__":main()
