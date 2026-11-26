"""CICLO LAB derivatives incremental-value experiment, 2021 training, 2022-23 eval.
All model variants use identical candidate universe and stress labels. No live orders.
"""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,lag,segments
from flow_families import load_flow
from regime_router import regimes,candidates
from ridge_router import features,labels,fit_predict
from new_families import run
from frequency_screen import trade_audit

THRESHOLDS=[0.,.05,.10]
def load(root,kind):
    root=Path(root);manifest=json.loads((root/"manifest.json").read_text())
    out=[]
    for f in manifest["files"]:
        if f["kind"]!=kind or f["status"]!="ok":continue
        p=root/f["file"]
        if hashlib.sha256(p.read_bytes()).hexdigest()!=f["file_sha256"]:raise ValueError("derivatives digest mismatch")
        x=pd.read_csv(p)
        if len(x)!=f["rows"]:raise ValueError("row mismatch")
        x.index=pd.to_datetime(x.pop("time_ms"),unit="ms",utc=True)
        out.append(x)
    a=pd.concat(out).sort_index()
    if a.index.has_duplicates:raise ValueError("duplicate derivative timestamp")
    return a

def aligned(source,index,delay,tolerance):
    # Observations visible only after a conservative delay; missing samples not filled indefinitely.
    a=source.copy();a.index+=pd.Timedelta(minutes=delay)
    return a.reindex(index,method="ffill",tolerance=pd.Timedelta(minutes=tolerance))

def derivative_features(m,perp,mark,metrics,funding,metric_delay=15):
    i=m.index
    p=aligned(perp[["close"]],i,1,0).close
    mk=aligned(mark[["close"]],i,1,0).close
    q=metrics.copy()
    oi=q.sum_open_interest
    for n in [15,60]:
        prior=oi.reindex(oi.index-pd.Timedelta(minutes=n)).to_numpy()
        q["oi_change"+str(n)]=oi/prior-1
    # Snapshots: actual exchange publication timestamp unavailable; delay sensitivity mandatory.
    f=aligned(q,i,metric_delay,0)
    # Settled funding: never use future funding rates.
    fr=aligned(funding[["rate"]],i,5,480).rate
    x=pd.DataFrame(index=i)
    x["basis"]=p/m.close-1
    x["mark_basis"]=mk/m.close-1
    x["mark_perp_gap"]=mk/p-1
    x["oi_change15"]=f.oi_change15
    x["oi_change60"]=f.oi_change60
    x["funding"]=fr
    for c in ["count_long_short_ratio","sum_taker_long_short_vol_ratio","count_toptrader_long_short_ratio","sum_toptrader_long_short_ratio"]:
        x[c]=np.log(f[c].where(f[c]>0))
    x["price_oi"]=x.oi_change60*m.ret30
    x["funding_basis"]=x.funding*x.basis
    return x.replace([np.inf,-np.inf],np.nan)

def predict(x,y):
    # Expand quarterly using only outcomes fully available by cutoff.
    dates=pd.date_range("2022-01-01","2024-01-01",freq="QS",tz="UTC")
    out=[]
    for cut,end in zip(dates[:-1],dates[1:]):
        train=y.loc[(y.index<cut)&(y.label_available<=cut)]
        test=x.loc[(x.index>=cut)&(x.index<end)]
        if len(train)<200:raise ValueError("insufficient labels")
        if len(test):out.append(pd.Series(fit_predict(x.loc[train.index],test,train.R.to_numpy()),index=test.index))
    return pd.concat(out)

def selftest():
    idx=pd.date_range("2021-01-01",periods=5,freq="5min",tz="UTC")
    a=pd.DataFrame({"value":[1.,2.,3.,4.,5.]},index=idx)
    b=aligned(a,idx,15,0)
    assert b.iloc[:3].isna().all().all() and b.iloc[3,0]==1
    c=a.copy();c.iloc[2:]=100
    pd.testing.assert_frame_equal(b,aligned(c,idx,15,0))
    assert aligned(a.drop(idx[1]),idx,15,0).iloc[4].isna().all()
    print("Derivatives alignment: delay, causality and missing sample tests PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")]
    d=load_flow(a.dataset,d);m=signal_frames(d);reg=regimes(d,m);s=candidates(d,m)
    union=pd.Series(False,index=m.index)
    for v in s.values():union|=v
    union&=m.index>=pd.Timestamp("2021-01-01",tz="UTC")
    base=features(d,m,reg,s).loc[union]
    perp,mark,metrics,funding=[load(a.derivatives,k) for k in ["perp","mark","metrics","funding"]]
    x15=derivative_features(m,perp,mark,metrics,funding,15).loc[union]
    x30=derivative_features(m,perp,mark,metrics,funding,30).loc[union]
    # Require observable core derivative values at both delays; fair same-universe baseline.
    core=["basis","oi_change15","oi_change60","funding"]
    eligible=x15[core].notna().all(axis=1)&x30[core].notna().all(axis=1)
    base=base.loc[eligible];x15=x15.loc[eligible];x30=x30.loc[eligible]
    mask=pd.Series(m.index.isin(base.index),index=m.index);y=labels(d,m,mask)
    models={"spot_matched":base,"derivatives_15m":base.join(x15),"derivatives_30m":base.join(x30)}
    preds={k:predict(v,y) for k,v in models.items()}
    results={}
    for name,pred in preds.items():
        for th in THRESHOLDS:
            pick=pd.Series(m.index.isin(pred.index[pred>=th]),index=m.index)
            q=run(d,m,pick);stress=run(d,m,pick,fee=.0008,slip=.0004);audit=trade_audit(d,m,pick,.0008,.0004)
            assert audit["n"]==stress["n"]
            if audit["n"]:assert abs(audit["mean"]-stress["conservativeMeanR"])<1e-8
            ci=audit["ci"]
            passed=bool(q["n"]>=150 and stress["n"]>=150 and q["unknown"]==0 and stress["unknown"]==0 and ci and ci[0]>0 and q["conservativeMeanR"]>=.05 and q["profitFactor"] is not None and q["profitFactor"]>=1.15)
            key=f"{name}:{th:.2f}"
            results[key]=dict(normal=q,stress=stress,audit=audit,screenPass=passed)
            print("DERIVATIVE_SCREEN="+json.dumps(dict(key=key,n=q["n"],normal=q["conservativeMeanR"],stress=stress["conservativeMeanR"],pf=q["profitFactor"],equity=q["equityEnd"],ci=ci,hit1=audit["hitRate"],lead=audit["medianLead"],unknown=audit["unknown"],passed=passed)),flush=True)
    # No holdout accessed, and PnL uses spot execution proxy rather than derivative settlement.
    Path("lab-derivative-screen.json").write_text(json.dumps(dict(period="2022-2023 development",eligible=int(eligible.sum()),candidateCount=len(eligible),featureCoverage=x15.notna().mean().to_dict(),results=results,limitations="Funding is predictor only, not cash flow. Metrics delay 15/30m assumed, publication unverified. 9 correlated variants, bootstrap unadjusted; audit includes empty months from 2021. No direct liquidation data. Same matched candidate universe, spot execution proxy."),indent=2))
if __name__=="__main__":main()
