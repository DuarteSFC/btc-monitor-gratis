"""Nonlinear four-hour futures models. Frozen development grid, no holdout or orders."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from market_frame import load_minutes,signal_frames,bars,atr,align,lag
from flow_families import load_flow
from regime_router import regimes,candidates
from ridge_router import features,fit_predict
from derivative_screen import load,derivative_features
from hourly_futures import make_outcomes,evaluate,FEES

THRESHOLDS=[.05,.10]
def nonlinear(train,test,y):
    # Explicit shallow trees and large leaves; no internal random validation.
    counts=pd.Series(1.,index=train.index).groupby(train.index.floor("D")).transform("sum").to_numpy()
    w=1/counts;w=w/w.mean()
    model=HistGradientBoostingRegressor(loss="squared_error",max_iter=100,learning_rate=.05,max_leaf_nodes=7,min_samples_leaf=150,l2_regularization=10.,early_stopping=False,random_state=42)
    model.fit(train.to_numpy(dtype=float),y,sample_weight=w)
    return model.predict(test.to_numpy(dtype=float))
def predict(x,y,method):
    out=[]
    for cut in pd.date_range("2022-01-01","2023-10-01",freq="QS",tz="UTC"):
        end=cut+pd.offsets.QuarterBegin(startingMonth=1)
        train=y.loc[(y.index<cut)&(y.available<=cut.value)]
        test=x.loc[(x.index>=cut)&(x.index<end)]
        if len(train)<300:raise ValueError("insufficient training")
        if len(test):
            pred=method(x.loc[train.index],test,train.R.to_numpy())
            out.append(pd.Series(pred,index=test.index))
    return pd.concat(out)
def selftest():
    from hourly_futures import selftest as test
    test()
    idx=pd.date_range("2021-01-01",periods=1200,freq="h",tz="UTC")
    x=pd.DataFrame({"a":np.linspace(-2,2,len(idx)),"b":np.sin(np.arange(len(idx)))},index=idx)
    x.loc[idx[::20],"b"]=np.nan
    y=x.a.to_numpy()**2
    p=nonlinear(x.iloc[:1000],x.iloc[1000:],y[:1000])
    assert len(p)==200 and np.isfinite(p).all()
    # Deterministic output and support for missing features.
    np.testing.assert_allclose(p,nonlinear(x.iloc[:1000],x.iloc[1000:],y[:1000]))
    print("Nonlinear regression, missing features and deterministic fit PASS",flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")];d=load_flow(a.dataset,d)
    m=signal_frames(d);reg=regimes(d,m);s=candidates(d,m)
    h=bars(d,60);h["a"]=atr(h);m["atr1"]=align(h,m,"a")
    perp,mark,metrics,funding=[load(a.derivatives,k) for k in ["perp","mark","metrics","funding"]]
    deriv=derivative_features(m,perp,mark,metrics,funding,30)
    eligible=(m.index.minute==0)&(m.index.year>=2021)&m.atr1.notna()&(m.atr1>0)&deriv[["basis","oi_change15","oi_change60","funding"]].notna().all(axis=1)&(m.index<pd.Timestamp("2023-12-31",tz="UTC"))
    x=features(d,m,reg,s);x["atr1_rel"]=m.atr1/m.close
    x["return4h"]=m.close/lag(m,"close",48)-1;x["return24h"]=m.close/lag(m,"close",288)-1
    x=x.loc[eligible];xx=x.join(deriv.loc[eligible])
    y={k:make_outcomes(m,eligible,perp,mark,funding,240,*v) for k,v in FEES.items()}
    results={}
    for feature_name,f in [("spot",x),("derivatives",xx)]:
        for method_name,method in [("ridge",fit_predict),("boost",nonlinear)]:
            pred=predict(f,y["stress"],method)
            for th in THRESHOLDS:
                normal=evaluate(pred,y["normal"],th);stress=evaluate(pred,y["stress"],th)
                passed=bool(normal["n"]>=150 and stress["n"]>=150 and not normal["unknown"] and not stress["unknown"] and normal["mean"]>=.05 and normal["pf"] is not None and normal["pf"]>=1.15 and stress["ci"][0]>0 and len(stress["years"])==2 and all(v["n"]>=30 and v["mean"]>0 for v in stress["years"].values()))
                key=f"{feature_name}:{method_name}:{th:.2f}"
                results[key]=dict(normal=normal,stress=stress,screenPass=passed)
                print("BOOST_SCREEN="+json.dumps(dict(key=key,n=normal["n"],mean=normal["mean"],pf=normal["pf"],win=normal["win"],equity=normal["equity"],stress=stress["mean"],ci=stress["ci"],unknown=stress["unknown"],passed=passed)),flush=True)
    Path("lab-boost-futures.json").write_text(json.dumps(dict(period="2022-2023 development only",models=results,limitations="Eight correlated configurations; 4h selected after v0.4 development findings. Same hourly grid, futures execution and funding assumptions. 30m metrics delay assumed. No leverage. CI unadjusted exploratory. No independent holdout used."),indent=2))
if __name__=="__main__":main()
