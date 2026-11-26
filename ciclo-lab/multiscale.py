"""One predeclared development extension: continuous multiscale context.
No threshold search. Same M01-known portfolio policy and execution; add one
feature group, compare matched dates to baseline. No holdout access.
"""
import argparse,json,tempfile
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,bars,atr,align,lag,rolling,ema,segments
from flow_families import load_flow
from regime_router import regimes,candidates
from ridge_router import features,fit_predict
from derivative_screen import load,derivative_features
from hourly_futures import make_outcomes,FEES
from boost_futures import nonlinear
from portfolio_screen import votes
from mixed_portfolio import route
from validation_rehearsal import scoped_spot,predict,replay,START,END,HORIZONS,utc
from latency_audit import delayed
from statistical_audit import bootstrap,month_stats

def context(d,m):
    out=pd.DataFrame(index=m.index)
    for n in [15,60,240]:
        b=bars(d,n);b["a"]=atr(b);scale=b.a.where(b.a>0)
        hi=lag(b.assign(hi=rolling(b,"high",20,lambda z:z.max())),"hi")
        lo=lag(b.assign(lo=rolling(b,"low",20,lambda z:z.min())),"lo")
        taker=d.buy.resample(f"{n}min",closed="left",label="right",origin="epoch").sum().reindex(b.index)
        b["signed"]=2*taker-b.volume
        v=rolling(b,"volume",3,lambda z:z.sum())
        columns={
            "impulse3":(b.close-lag(b,"close",3))/scale,
            "impulse12":(b.close-lag(b,"close",12))/scale,
            "above_support":(b.close-lo)/scale,
            "below_resistance":(hi-b.close)/scale,
            "ema_distance":(b.close-ema(b,20))/scale,
            "ema_slope":(ema(b,20)-lag(b.assign(e=ema(b,20)),"e",3))/scale,
            "volume_pressure":rolling(b,"signed",3,lambda z:z.sum())/v.where(v>0),
            "volatility_ratio":b.a/lag(b.assign(med=rolling(b,"a",40,lambda z:z.median())),"med").replace(0,np.nan),
        }
        for name,val in columns.items():
            b["feature"]=val.replace([np.inf,-np.inf],np.nan)
            out[f"ctx{n}_{name}"]=align(b,m,"feature")
    return out

def routes(x,ys,m):
    y=ys["4h"]["stress"];xh=x.loc[x.index.minute==0];yh=y.loc[y.index.isin(xh.index)]
    p01=predict(x,y,None,"hurdle")
    g01=predict(xh,yh,None,nonlinear)
    e60=(predict(xh,yh,None,fit_predict)+g01)/2
    e15=(predict(x,y,365,fit_predict)+predict(x,y,365,nonlinear))/2
    v4=votes({"P01":p01>=.05,"G01":g01>=.05,"E60":e60>=0.,"E15":e15>=.05})
    x1=predict(x,ys["2h15"]["stress"],None,"hurdle")>=0
    y2=ys["2h25"]["stress"]
    x2=(predict(x,y2,None,fit_predict)+predict(x,y2,None,nonlinear))/2>=0
    r=route(v4,x1,x2,"four_hour_priority")
    r=r.loc[m.trend4h.notna().reindex(r.index).fillna(False)]

    return r

def lower_bound(q,comparisons):
    # Circular block bootstrap of monthly trade-R totals and counts.
    # Family-size adjustment for enumerated candidates only; not all historic search.
    p,n,r=month_stats(q)
    if (n>0).sum()<12:return None
    rng=np.random.default_rng(20261126)
    bounds={}
    for block in [1,3,6]:
        i=rng.integers(0,24,size=(200000,int(np.ceil(24/block))))
        j=((i[:,:,None]+np.arange(block))%24).reshape(200000,-1)[:,:24]
        count=n[j].sum(1);total=r[j].sum(1)
        bounds[str(block)]=float(np.quantile(total[count>0]/count[count>0],.05/comparisons))
    return bounds

def paired(a,b):
    # Monthly PnL difference: same calendar months, paired bootstrap.
    p=month_stats(a)[0]-month_stats(b)[0]
    z=bootstrap(p[:,None],3)
    return dict(totalDifference=float(p.sum()),pOneSided=float(z["raw"][0]))

def selftest():
    from validation_rehearsal import selftest as test
    test()
    i=pd.date_range("2022-01-01",periods=60*72,freq="min",tz="UTC")
    rng=np.random.default_rng(42);c=100+np.cumsum(rng.normal(0,.01,len(i)));o=np.r_[c[0],c[:-1]];v=rng.uniform(1,10,len(i))
    d=segments(pd.DataFrame(dict(open=o,high=np.maximum(o,c)+.05,low=np.minimum(o,c)-.05,close=c,volume=v,quote=c*v,buy=v*.55),index=i).drop(i[100]))
    m=bars(d,5);a=context(d,m);cut=i[3000];before=d.loc[d.index<cut]
    pd.testing.assert_frame_equal(a.loc[:cut],context(before,bars(before,5)),check_exact=False,rtol=1e-10,atol=1e-12)
    assert a.shape[1]==24
    print("Multiscale context: 24 features, completed-bar prefix invariance PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");a=p.parse_args()
    selftest()
    if a.selftest:return
    with tempfile.TemporaryDirectory() as tmp:
        scope=scoped_spot(a.dataset,tmp)
        d=load_flow(tmp,load_minutes(tmp))
    assert d.index.max()<utc(END)
    manifest=json.loads((Path(a.derivatives)/"manifest.json").read_text())
    assert all(f["end_exclusive"]<=END for f in manifest["files"])
    m=signal_frames(d);reg=regimes(d,m);s=candidates(d,m)
    h=bars(d,60);h["a"]=atr(h);m["atr1"]=align(h,m,"a")
    perp,mark,metrics,funding=[load(a.derivatives,k) for k in ["perp","mark","metrics","funding"]]
    deriv=derivative_features(m,perp,mark,metrics,funding,30)
    eligible=(m.index.minute%15==0)&(m.index.year>=2021)&m.atr1.notna()&(m.atr1>0)&deriv[["basis","oi_change15","oi_change60","funding"]].notna().all(axis=1)&(m.index<utc(END)-pd.Timedelta(days=1))
    x=features(d,m,reg,s);x["atr1_rel"]=m.atr1/m.close
    x["return4h"]=m.close/lag(m,"close",48)-1;x["return24h"]=m.close/lag(m,"close",288)-1
    x=x.loc[eligible]
    ys={}
    for name,(h,stop) in HORIZONS.items():
        ex=m.assign(atr1=m.atr1*(stop/2.5))
        ys[name]={k:make_outcomes(ex,eligible,perp,mark,funding,h,*v) for k,v in FEES.items()}

    base=routes(x,ys,m)
    reference={k:replay(base,ys,k) for k in FEES}
    assert reference["stress"]["n"]==180 and abs(reference["stress"]["mean"]-.05994372299079626)<1e-10
    extra=context(d,m).loc[x.index]
    assert len(set(extra.columns)&set(x.columns))==0
    augmented=routes(x.join(extra),ys,m)
    results={}
    for name,r in [("M01-known",base),("MC01",augmented)]:
        out={}
        for delay in [1,5,15]:
            out[str(delay)]={}
            for cost in FEES:
                q=replay(r,ys,cost) if delay==1 else delayed(r,m,perp,mark,funding,delay,cost)
                out[str(delay)][cost]=q
                print("MULTISCALE="+json.dumps(dict(policy=name,delay=delay,cost=cost,n=q["n"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],years=q["years"])),flush=True)
        results[name]=out
    # 189 earlier configs + 3 final known-trend policies + one new policy.
    # Include three endpoints per policy conservatively for this diagnostic.
    comparisons=193*3
    bounds={}
    for delay in [1,5,15]:
        q=results["MC01"][str(delay)]["stress"]
        bounds[str(delay)]=lower_bound(q,comparisons)
    delta=paired(results["MC01"]["1"]["stress"],reference["stress"])
    summary=dict(comparisons=comparisons,adjustedBounds=bounds,pairedMonthlyImprovement=delta,holdoutLocked=True)
    print("MULTISCALE_STAT="+json.dumps(summary),flush=True)
    Path("lab-multiscale.json").write_text(json.dumps(dict(scope=scope,results=results,summary=summary,limitations="One new feature-group hypothesis, no threshold search. Prior selection and incomplete historic search family still limit significance. Bonferroni reference count 579 covers 193 named policies times three delay endpoints, not all historical experiments; 24 months only. Paired PnL comparison descriptive. No holdout or release."),indent=2))
if __name__=="__main__":main()
