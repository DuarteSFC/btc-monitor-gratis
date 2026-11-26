"""Phase-2 rehearsal. No approved candidate yet, actual holdout locked.
Reproduce M01-known on development using calendar-independent folds and
portfolio accounting. No tuning or production changes.
"""
import argparse,json,tempfile,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,bars,atr,align,lag
from flow_families import load_flow
from regime_router import regimes,candidates
from ridge_router import features,fit_predict
from derivative_screen import load,derivative_features
from hourly_futures import make_outcomes,FEES,NS
from boost_futures import nonlinear
from hurdle_futures import estimate
from portfolio_screen import votes
from mixed_portfolio import route
from validation_core import chronological_folds,calendar_report,utc

START="2022-01-01"
END="2024-01-01"
HORIZONS={"4h":(240,2.5),"2h15":(120,1.5),"2h25":(120,2.5)}
def scoped_spot(root,dest):
    """Only expose archive files ending on/before development cutoff."""
    root=Path(root).resolve();dest=Path(dest)
    manifest=json.loads((root/"manifest.json").read_text())
    if manifest["errors"] or manifest["dataset_version"]!="1.1":raise ValueError("invalid original manifest")
    files=[f for f in manifest["files"] if f["end_exclusive"]<=END]
    if not files or files[0]["start"]!="2020-01-01" or files[-1]["end_exclusive"]!=END:raise ValueError("development coverage")
    for a,b in zip(files,files[1:]):
        if a["end_exclusive"]!=b["start"]:raise ValueError("archive gap")
    for f in files:
        name=f["file"]
        if Path(name).name!=name:raise ValueError("invalid archive path")
        (dest/name).symlink_to(root/name)
    restricted=dict(manifest,files=files,rows=sum(f["rows"] for f in files),expected=sum(f["expected"] for f in files),end_exclusive=END)
    (dest/"manifest.json").write_text(json.dumps(restricted))
    return dict(files=len(files),rows=restricted["rows"],end=END,manifestSHA256=hashlib.sha256((dest/"manifest.json").read_bytes()).hexdigest())

def predict(x,y,window,method,start=START,end=END):
    out=[]
    for cut,nxt,train,test in chronological_folds(x,y,start,end,window):
        if len(train)<300:raise ValueError("insufficient training")
        if len(test):
            xx=x.loc[train.index];yy=train.R.to_numpy()
            score=estimate(xx,test,yy,"tree")[0] if method=="hurdle" else method(xx,test,yy)
            out.append(pd.Series(score,index=test.index))
    return pd.concat(out)

def replay(routes,ys,cost,start=START,end=END):
    if routes.index.has_duplicates or not routes.index.is_monotonic_increasing:raise ValueError("invalid routes")
    if ((routes.index<utc(start))|(routes.index>=utc(end))).any():raise ValueError("route outside period")
    eq=10000.;last=-1;unknown=0;records=[];skipped=0
    for dt,name in routes.items():
        if dt.value+NS<last:skipped+=1;continue
        y=ys[name][cost]
        if dt not in y.index:unknown+=1;last=dt.value+1441*NS;continue
        q=y.loc[dt]
        if int(q.exit)>utc(end).value:raise ValueError("trade exits after evaluation boundary")
        if not np.isfinite([q.R,q.riskFraction]).all() or q.riskFraction<=0:raise ValueError("invalid outcome")
        risk=min(.0025*eq,eq*q.riskFraction)
        pnl=risk*float(q.R)
        if eq+pnl<0:raise ValueError("negative equity")
        eq+=pnl;last=int(q.exit)
        records.append(dict(time=dt.isoformat(),R=float(q.R),pnl=pnl,fundingR=float(q.fundingR),fallback=int(q.fallback),exit=last,route=name))
    assert len(records)+unknown+skipped==len(routes)
    out=calendar_report(records,start,end)
    assert abs(out["equity"]-eq)<1e-8
    return dict(**out,unknown=unknown,skipped=skipped,signals=len(routes),records=records)

def selftest():
    from validation_core import selftest as vc
    from mixed_portfolio import selftest as mp
    vc();mp()
    i=pd.date_range("2022-01-01",periods=3,freq="15min",tz="UTC")
    y=pd.DataFrame(dict(R=[.1,.2,-.1],riskFraction=.01,exit=i.asi8+20*NS,fundingR=0.,fallback=0),index=i)
    z=replay(pd.Series("4h",index=i),{"4h":{"normal":y}},"normal")
    assert z["n"]==2 and z["skipped"]==1 and not z["unknown"]
    a=replay(pd.Series("4h",index=i),{"4h":{"normal":y.iloc[1:]}},"normal")
    assert a["unknown"]==1 and a["n"]==0 and a["skipped"]==2
    # Guard the archive cutoff using dummy files, without reading any reserved data.
    with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
        root=Path(a);files=[dict(file="development.zip",start="2020-01-01",end_exclusive=END,rows=1,expected=1),dict(file="sealed.zip",start=END,end_exclusive="2026-01-01",rows=1,expected=1)]
        (root/"manifest.json").write_text(json.dumps(dict(dataset_version="1.1",errors=[],files=files)))
        (root/"development.zip").write_bytes(b"test")
        q=scoped_spot(root,b);assert q["files"]==1 and not (Path(b)/"sealed.zip").exists()
    print("Phase-2 rehearsal cutoff, temporal folds, portfolio overlap and unknown-outcome guards PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");p.add_argument("--holdout",action="store_true");a=p.parse_args()
    if a.holdout:raise SystemExit("HOLDOUT LOCKED: no candidate has passed development; no data access permitted")
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
    results={k:replay(r,ys,k) for k in FEES}
    expected={"normal":(.10908419512743242,10498.589701532865),"stress":(.05994372299079626,10269.518714374417)}
    for k,q in results.items():
        assert q["n"]==180 and not q["unknown"]
        np.testing.assert_allclose([q["mean"],q["equity"]],expected[k],rtol=1e-10,atol=1e-10)
    summary={k:{i:v for i,v in q.items() if i not in ["records","months"]} for k,q in results.items()}
    print("PHASE2_REHEARSAL="+json.dumps(dict(scope=scope,results=summary,holdoutLocked=True)),flush=True)
    Path("lab-validation-rehearsal.json").write_text(json.dumps(dict(scope=scope,results=results,holdoutLocked=True,limitations="M01-known is a rehearsal reference, not frozen or approved. Actual 2024-25 evaluation disabled before reads. Existing source artifact includes reserved spot archives but scoped loader reads only development files. No intratrade drawdown or final exchange execution parity yet. No orders."),indent=2))
if __name__=="__main__":main()
