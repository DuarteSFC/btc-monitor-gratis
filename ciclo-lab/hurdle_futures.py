"""Two-stage expected return: separately estimate probability and size of gain/loss.
Development 2022-23; identical futures execution, funding, and hourly/15m labels.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from market_frame import load_minutes,signal_frames,bars,atr,align,lag
from flow_families import load_flow
from regime_router import regimes,candidates
from ridge_router import features,fit_predict
from derivative_screen import load,derivative_features
from hourly_futures import make_outcomes,evaluate,FEES
from boost_futures import nonlinear

THRESHOLDS=[0.,.05,.10]
NTEST=24
def weights(index):
    counts=pd.Series(1.,index=index).groupby(index.floor("D")).transform("sum").to_numpy()
    w=1/counts
    return w/w.mean()
def estimate(train,test,y,method):
    wins=y>0
    if min(wins.sum(),(~wins).sum())<100:raise ValueError("insufficient outcomes by class")
    a=train.to_numpy(dtype=float);b=test.to_numpy(dtype=float)
    w=weights(train.index)
    if method=="linear":
        imp=SimpleImputer(strategy="median",keep_empty_features=True)
        a=imp.fit_transform(a);b=imp.transform(b)
        scale=StandardScaler();a=np.clip(scale.fit_transform(a),-6,6);b=np.clip(scale.transform(b),-6,6)
        model=LogisticRegression(C=.05,max_iter=500,random_state=42)
        reg=fit_predict
    else:
        model=HistGradientBoostingClassifier(max_iter=100,learning_rate=.05,max_leaf_nodes=7,min_samples_leaf=150,l2_regularization=10.,early_stopping=False,random_state=42)
        reg=nonlinear
    model.fit(a,wins,sample_weight=w)
    prob=model.predict_proba(b)[:,1]
    # Conditional mean estimates are constrained to their correct sign and
    # clipped to observed training range, never test outcomes.
    gain=np.clip(reg(train.iloc[wins],test,y[wins]),0,float(y[wins].max()))
    loss=np.clip(reg(train.iloc[~wins],test,-y[~wins]),0,float((-y[~wins]).max()))
    score=prob*gain-(1-prob)*loss
    return score,prob,gain,loss
def predict(x,y,window,method):
    out=[]
    for cut in pd.date_range("2022-01-01","2023-10-01",freq="QS",tz="UTC"):
        end=cut+pd.offsets.QuarterBegin(startingMonth=1)
        valid=(y.index<cut)&(y.available<=cut.value)
        if window=="365d":valid&=y.index>=cut-pd.Timedelta(days=365)
        train=y.loc[valid];test=x.loc[(x.index>=cut)&(x.index<end)]
        if len(train)<300:raise ValueError("insufficient training")
        if len(test):
            score,prob,gain,loss=estimate(x.loc[train.index],test,train.R.to_numpy(),method)
            baseline=float(np.average(train.R>0,weights=weights(train.index)))
            out.append(pd.DataFrame(dict(score=score,prob=prob,gain=gain,loss=loss,baseline=baseline),index=test.index))
    return pd.concat(out)
def audit(pred,y):
    a=pred.join(y[["R"]]).dropna()
    if a.empty:return {}
    obs=(a.R>0).astype(float)
    a=a.assign(obs=obs,bin=pd.qcut(a.prob,5,duplicates="drop"))
    return dict(n=len(a),brier=float(((a.prob-obs)**2).mean()),baselineBrier=float(((a.baseline-obs)**2).mean()),rankCorrelation=float(a.score.rank().corr(a.R.rank())),bins=[dict(n=len(g),predicted=float(g.prob.mean()),observed=float(g.obs.mean()),meanR=float(g.R.mean())) for _,g in a.groupby("bin",observed=True)])
def lower_bound(result):
    if not result["records"]:return None,0
    f=pd.DataFrame(result["records"]);f["month"]=pd.to_datetime(f.time,utc=True).dt.strftime("%Y-%m")
    b=f.groupby("month").R.agg(["sum","count"]);active=len(b)
    if active<12:return None,active
    b=b.reindex(pd.period_range("2022-01","2023-12",freq="M").astype(str),fill_value=0)
    rng=np.random.default_rng(20261126);i=rng.integers(0,len(b),size=(30000,len(b)))
    a=b["sum"].to_numpy()[i].sum(1);c=b["count"].to_numpy()[i].sum(1)
    return float(np.quantile(a[c>0]/c[c>0],.05/NTEST)),active
def selftest():
    from boost_futures import selftest as test
    test()
    idx=pd.date_range("2021-01-01",periods=1200,freq="h",tz="UTC")
    rng=np.random.default_rng(42);x=pd.DataFrame(dict(a=rng.normal(size=len(idx)),b=rng.normal(size=len(idx))),index=idx)
    x.loc[idx[::20],"b"]=np.nan;y=x.a.to_numpy()+rng.normal(size=len(idx))
    for method in ["linear","tree"]:
        s,p,g,l=estimate(x.iloc[:1000],x.iloc[1000:],y[:1000],method)
        assert np.isfinite(s).all() and ((0<=p)&(p<=1)).all() and (g>=0).all() and (l>=0).all()
        np.testing.assert_allclose(s,p*g-(1-p)*l)
    assert lower_bound({"records":[]})==(None,0)
    print("Two-stage probabilities, conditional sizes, expected-return identity and empty guard PASS",flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")];d=load_flow(a.dataset,d)
    m=signal_frames(d);reg=regimes(d,m);s=candidates(d,m)
    h=bars(d,60);h["a"]=atr(h);m["atr1"]=align(h,m,"a")
    perp,mark,metrics,funding=[load(a.derivatives,k) for k in ["perp","mark","metrics","funding"]]
    deriv=derivative_features(m,perp,mark,metrics,funding,30)
    eligible=(m.index.minute%15==0)&(m.index.year>=2021)&m.atr1.notna()&(m.atr1>0)&deriv[["basis","oi_change15","oi_change60","funding"]].notna().all(axis=1)&(m.index<pd.Timestamp("2023-12-31",tz="UTC"))
    x=features(d,m,reg,s);x["atr1_rel"]=m.atr1/m.close
    x["return4h"]=m.close/lag(m,"close",48)-1;x["return24h"]=m.close/lag(m,"close",288)-1
    x=x.loc[eligible]
    ys={k:make_outcomes(m,eligible,perp,mark,funding,240,*v) for k,v in FEES.items()}
    results={};audits={}
    for grid in [15,60]:
        xx=x.loc[x.index.minute%grid==0];yy={k:y.loc[y.index.isin(xx.index)] for k,y in ys.items()}
        for window in ["expanding","365d"]:
            for method in ["linear","tree"]:
                pred=predict(xx,yy["stress"],window,method);key0=f"{grid}:{window}:{method}"
                audits[key0]=audit(pred,yy["stress"])
                print("PROB_AUDIT="+json.dumps(dict(key=key0,**audits[key0])),flush=True)
                for th in THRESHOLDS:
                    normal=evaluate(pred.score,yy["normal"],th);stress=evaluate(pred.score,yy["stress"],th)
                    low,active=lower_bound(stress)
                    passed=bool(normal["n"]>=150 and stress["n"]>=150 and not normal["unknown"] and not stress["unknown"] and normal["mean"]>=.05 and normal["pf"] is not None and normal["pf"]>=1.15 and low is not None and low>0 and len(stress["years"])==2 and all(v["n"]>=30 and v["mean"]>0 for v in stress["years"].values()))
                    key=f"{key0}:{th:.2f}"
                    row=dict(key=key,n=normal["n"],stressN=stress["n"],mean=normal["mean"],pf=normal["pf"],win=normal["win"],equity=normal["equity"],stress=stress["mean"],ci=stress["ci"],adjustedLower=low,activeMonths=active,unknown=stress["unknown"],passed=passed)
                    results[key]=dict(summary=row,normal=normal,stress=stress)
                    print("HURDLE="+json.dumps(row),flush=True)
    assert len(results)==NTEST
    Path("lab-hurdle-futures.json").write_text(json.dumps(dict(period="2022-2023 development only",models=results,audits=audits,limitations="24 correlated configurations, 48 cost replays. Probability of positive stress-cost R, not future price direction; Brier descriptive on overlapping labels. No post-fit calibration. Bonferroni only this batch, monthly bootstrap approximate. Same futures exit and funding assumptions. No leverage, holdout untouched."),indent=2))
    print("HURDLE_DONE="+json.dumps(dict(configs=len(results),positiveBoth=sum(1 for v in results.values() if v["summary"]["mean"] is not None and v["summary"]["stress"] is not None and v["summary"]["mean"]>0 and v["summary"]["stress"]>0),passes=sum(v["summary"]["passed"] for v in results.values()))),flush=True)
if __name__=="__main__":main()
