"""M01 2026 retraining experiment. Fixed architecture, no thresholds tuned.
Two distinct predeclared schedules: pooled old + recent and recent only.
Development diagnostics only; 2024-25 remain locked.
"""
import argparse,json,tempfile
from pathlib import Path
import numpy as np
import pandas as pd
from extension_2026 import (scope_2026,load_scoped_flow,scoped_spot,signals,
    delayed_tables,START,END,FIT_CUT,HORIZONS)
from market_frame import load_minutes,signal_frames,bars,atr,align,lag
from regime_router import regimes,candidates
from ridge_router import features,fit_predict
from derivative_screen import load,derivative_features
from hourly_futures import make_outcomes,FEES
from boost_futures import nonlinear
from hurdle_futures import estimate
from portfolio_screen import votes
from mixed_portfolio import route
from validation_rehearsal import replay,utc
from validation_core import chronological_folds

def prepare_recent(root,derivatives,development):
    d=load_scoped_flow(root,load_minutes(root))
    allowed_end=FIT_CUT if development else END
    allowed_start="2020-01-01" if development else "2026-01-01"
    assert d.index.min()>=utc(allowed_start) and d.index.max()<utc(allowed_end)
    meta=json.loads((Path(derivatives)/"manifest.json").read_text())
    assert all(f["end_exclusive"]<=allowed_end and f["start"]>=("2021-01-01" if development else "2026-01-01") for f in meta["files"])
    if any(v["verified"]!=v["files"] for v in meta["summary"].values()):raise ValueError("unverified derivative files")
    m=signal_frames(d);reg=regimes(d,m);s=candidates(d,m)
    h=bars(d,60);h["a"]=atr(h);m["atr1"]=align(h,m,"a")
    perp,mark,metrics,funding=[load(derivatives,k) for k in ["perp","mark","metrics","funding"]]
    deriv=derivative_features(m,perp,mark,metrics,funding,30)
    eligible=(m.index.minute%15==0)&(m.index.year>=2021)&m.atr1.notna()&(m.atr1>0)&deriv[["basis","oi_change15","oi_change60","funding"]].notna().all(axis=1)&(m.index<utc(allowed_end)-pd.Timedelta(days=1))
    x=features(d,m,reg,s);x["atr1_rel"]=m.atr1/m.close
    x["return4h"]=m.close/lag(m,"close",48)-1;x["return24h"]=m.close/lag(m,"close",288)-1
    x=x.loc[eligible]
    ys={}
    for name,(h,stop) in HORIZONS.items():
        ex=m.assign(atr1=m.atr1*(stop/2.5))
        ys[name]={k:make_outcomes(ex,eligible,perp,mark,funding,h,*v) for k,v in FEES.items()}
    return x,ys,m,perp,mark,funding


def fit_fold(x,y,cut,window,method,test):
    valid=(y.index<cut)&(y.available<=cut.value)
    if window:valid&=y.index>=cut-pd.Timedelta(days=window)
    a=y.loc[valid]
    if len(a)<300:raise ValueError("insufficient prior labels")
    assert a.index.isin(x.index).all() and (test.index>=cut).all()
    assert a.available.max()<=cut.value
    if not len(test):return pd.Series(dtype=float,index=test.index)
    xx=x.loc[a.index];yy=a.R.to_numpy()
    p=estimate(xx,test,yy,"tree")[0] if method=="hurdle" else method(xx,test,yy)
    return pd.Series(p,index=test.index)

def adaptive(x,y,m,mode):
    result=[];audits=[]
    for cut in pd.date_range(START,END,freq="QS",inclusive="left",tz="UTC"):
        nxt=cut+pd.offsets.QuarterBegin(startingMonth=1)
        test=x.loc[(x.index>=cut)&(x.index<nxt)]
        train=x.loc[x.index<cut]
        if mode=="recent":train=train.loc[train.index.year==2026]
        assert len(test)>0 and train.index.is_monotonic_increasing
        labels={k:v["stress"].loc[v["stress"].index.isin(train.index)] for k,v in y.items()}
        def fit(name,window,method,hourly=False):
            a=train.loc[train.index.minute==0] if hourly else train
            b=test.loc[test.index.minute==0] if hourly else test
            lab=labels[name].loc[labels[name].index.isin(a.index)]
            return fit_fold(a,lab,cut,window,method,b)
        p01=fit("4h",None,"hurdle")
        g01=fit("4h",None,nonlinear,True)
        e60=(fit("4h",None,fit_predict,True)+g01)/2
        e15=(fit("4h",365,fit_predict)+fit("4h",365,nonlinear))/2
        v4=votes({"P01":p01>=.05,"G01":g01>=.05,"E60":e60>=0.,"E15":e15>=.05})
        x1=fit("2h15",None,"hurdle")>=0
        x2=(fit("2h25",None,fit_predict)+fit("2h25",None,nonlinear))/2>=0
        r=route(v4,x1,x2,"four_hour_priority")
        r=r.loc[m.trend4h.notna().reindex(r.index).fillna(False)]
        assert ((r.index>=cut)&(r.index<nxt)).all()
        result.append(r)
        a=labels["4h"].loc[labels["4h"].available<=cut.value]
        audits.append(dict(cut=str(cut),train=len(a),recentTrain=int((a.index.year==2026).sum()),test=len(test),signals=len(r),lastAvailability=str(pd.Timestamp(int(a.available.max()),tz="UTC"))))
    return pd.concat(result).sort_index(),audits

def selftest():
    from extension_2026 import selftest as test
    test()
    t=pd.date_range("2026-01-01",periods=1000,freq="h",tz="UTC")
    x=pd.DataFrame({"a":np.sin(np.arange(len(t))/20)},index=t)
    y=pd.DataFrame(dict(R=x.a,available=t.asi8+4*3600*10**9),index=t)
    cut=t[800];test=x.loc[x.index>=cut]
    p=fit_fold(x,y,cut,None,fit_predict,test)
    y.loc[y.available>cut.value,"R"]=999.
    np.testing.assert_array_equal(p.to_numpy(),fit_fold(x,y,cut,None,fit_predict,test).to_numpy())
    print("Recent refit availability guard and future-outcome mutation PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    if a.selftest:return
    with tempfile.TemporaryDirectory() as d0,tempfile.TemporaryDirectory() as d1:
        q0=scoped_spot(a.dataset,d0);q1=scope_2026(a.dataset,d1)
        old,oy,_,_,_,_=prepare_recent(d0,a.derivatives,True)
        now,ny,m,perp,mark,funding=prepare_recent(d1,a.extension,False)
    x=pd.concat([old,now]).sort_index();assert not x.index.has_duplicates and list(old.columns)==list(now.columns)
    y={k:{c:pd.concat([oy[k][c],ny[k][c]]).sort_index() for c in FEES} for k in HORIZONS}
    base=signals(old,oy,now.loc[now.index>=utc(START)],m)
    b=replay(base,ny,"stress",start=START,end=END)
    assert b["n"]==30 and abs(b["mean"]+.1118697802208505)<1e-10
    results={}
    for mode in ["pooled","recent"]:
        r,audit=adaptive(x,y,m,mode)
        print("REFIT_FOLDS="+json.dumps(dict(policy=mode,folds=audit)),flush=True)
        out={}
        for delay in [1,5,15]:
            out[str(delay)]={}
            for cost in FEES:
                q=replay(r,ny,cost,start=START,end=END) if delay==1 else delayed_tables(r,m,perp,mark,funding,delay,cost)
                out[str(delay)][cost]=q
                print("REFIT="+json.dumps(dict(policy=mode,delay=delay,cost=cost,n=q["n"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],dd=q["dd"],months=q["months"])),flush=True)
        results[mode]=dict(folds=audit,scenarios=out)
    Path("lab-refit-2026.json").write_text(json.dumps(dict(scope=[q0,q1],baseline=b,results=results,limitations="Two fixed quarterly refit schedules, 12 replays. 2026 Jan-Mar training/warmup and Apr-Sep evaluation; rolling branch 365 days has only available 2026 observations. No 2024-25 strategy data. Recent-only short learning history; pooled expanding discontinuous. Development-adaptive after frozen failure, 6 months only, ordinary descriptive CI, no release."),indent=2))
if __name__=="__main__":main()
