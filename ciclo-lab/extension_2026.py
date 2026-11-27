"""M01-known replication in a separate, previously partly explored 2026 period.
Frozen coefficients fitted on 2021-23 only. No 2024-25 strategy data.
A development extension, NOT independent validation or release.
"""
import argparse,json,tempfile,hashlib,io,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,bars,atr,align,lag
from regime_router import regimes,candidates
from ridge_router import features,fit_predict
from derivative_screen import load,derivative_features
from hourly_futures import make_outcomes,FEES
from boost_futures import nonlinear
from hurdle_futures import estimate
from portfolio_screen import votes
from mixed_portfolio import route
from validation_rehearsal import scoped_spot,HORIZONS,utc,replay
from latency_audit import delayed
from validation_core import calendar_report
from datetime import date
import derivatives_dataset as acquisition

START="2026-04-01";END="2026-10-01";FIT_CUT="2024-01-01"
def load_scoped_flow(root,d):
    root=Path(root); manifest=json.loads((root/"manifest.json").read_text())
    out=[]
    for item in manifest["files"]:
        raw=(root/item["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item["sha256"]:raise ValueError("hash mismatch")
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names=[n for n in z.namelist() if n.endswith(".csv")]
            if len(names)!=1:raise ValueError("invalid archive")
            with z.open(names[0]) as f:
                x=pd.read_csv(f,header=None,usecols=[0,5,6,9],dtype=str)
        x=x[~x[0].str.lower().isin(["open_time","opentime"])]
        t=pd.to_numeric(x[0]).astype("int64"); t=t.where(t<10**14,t//1000)
        ct=pd.to_numeric(x[6]).astype("int64");ct=ct.where(ct<10**14,ct//1000)
        valid=ct==t+59999
        v=x.loc[valid,5].astype(float).to_numpy();b=x.loc[valid,9].astype(float).to_numpy()
        if not np.isfinite(b).all() or (b<0).any() or (b>v+1e-8*np.maximum(1,v)).any():raise ValueError("invalid taker buy volume")
        out.append(pd.Series(b,index=pd.to_datetime(t[valid].to_numpy(),unit="ms",utc=True)))
    a=pd.concat(out)
    if not a.index.equals(d.index):raise ValueError("flow timestamps mismatch")
    return d.assign(buy=a)


def scope_2026(root,dest):
    root=Path(root).resolve();dest=Path(dest)
    source=json.loads((root/"manifest.json").read_text())
    if source["dataset_version"]!="1.1" or source["errors"]:raise ValueError("unverified source")
    files=[f for f in source["files"] if f["start"]>="2026-01-01" and f["end_exclusive"]<=END]
    if not files or files[0]["start"]!="2026-01-01" or files[-1]["end_exclusive"]!=END:raise ValueError("missing 2026 coverage")
    for a,b in zip(files,files[1:]):
        if a["end_exclusive"]!=b["start"]:raise ValueError("archive gap")
    for f in files:
        name=f["file"]
        if Path(name).name!=name:raise ValueError("invalid path")
        (dest/name).symlink_to(root/name)
    m=dict(dataset_version="1.1",errors=[],files=files,rows=sum(f["rows"] for f in files),expected=sum(f["expected"] for f in files))
    (dest/"manifest.json").write_text(json.dumps(m))
    return dict(files=len(files),rows=m["rows"],sha256=hashlib.sha256((dest/"manifest.json").read_bytes()).hexdigest())

def prepare(root,derivatives,development):
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
    if not development:eligible&=m.index>=utc(START)
    x=features(d,m,reg,s);x["atr1_rel"]=m.atr1/m.close
    x["return4h"]=m.close/lag(m,"close",48)-1;x["return24h"]=m.close/lag(m,"close",288)-1
    x=x.loc[eligible]
    ys={}
    for name,(h,stop) in HORIZONS.items():
        ex=m.assign(atr1=m.atr1*(stop/2.5))
        ys[name]={k:make_outcomes(ex,eligible,perp,mark,funding,h,*v) for k,v in FEES.items()}
    return x,ys,m,perp,mark,funding

def frozen(train,test,y,window,method):
    assert list(train.columns)==list(test.columns)
    cut=utc(FIT_CUT)
    a=y.loc[(y.index<cut)&(y.available<=cut.value)]
    if window:a=a.loc[a.index>=cut-pd.Timedelta(days=window)]
    if len(a)<300:raise ValueError("insufficient training")
    assert a.index.isin(train.index).all() and (test.index>=utc(START)).all()
    xx=train.loc[a.index];yy=a.R.to_numpy()
    p=estimate(xx,test,yy,"tree")[0] if method=="hurdle" else method(xx,test,yy)
    return pd.Series(p,index=test.index)

def signals(train,ys,test,m):
    y=ys["4h"]["stress"];xh=train.loc[train.index.minute==0];th=test.loc[test.index.minute==0];yh=y.loc[y.index.isin(xh.index)]
    p01=frozen(train,test,y,None,"hurdle")
    g01=frozen(xh,th,yh,None,nonlinear)
    e60=(frozen(xh,th,yh,None,fit_predict)+g01)/2
    e15=(frozen(train,test,y,365,fit_predict)+frozen(train,test,y,365,nonlinear))/2
    v4=votes({"P01":p01>=.05,"G01":g01>=.05,"E60":e60>=0.,"E15":e15>=.05})
    x1=frozen(train,test,ys["2h15"]["stress"],None,"hurdle")>=0
    y2=ys["2h25"]["stress"]
    x2=(frozen(train,test,y2,None,fit_predict)+frozen(train,test,y2,None,nonlinear))/2>=0
    r=route(v4,x1,x2,"four_hour_priority")
    return r.loc[m.trend4h.notna().reindex(r.index).fillna(False)]

def delayed_tables(r,m,perp,mark,funding,minutes,cost):
    shift=pd.Timedelta(minutes=minutes-1);out={}
    for name,(h,stop) in HORIZONS.items():
        ix=r.index[r==name]
        original=m.loc[ix,["segment","atr1"]].copy()
        original["atr1"]*=stop/2.5;original.index+=shift
        mask=pd.Series(True,index=original.index)
        out[name]={cost:make_outcomes(original,mask,perp,mark,funding,h,*FEES[cost])}
    shifted=r.copy();shifted.index+=shift
    return replay(shifted,out,cost,start=START,end=END)

def selftest():
    from validation_rehearsal import selftest as test
    test()
    with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
        root=Path(a)
        files=[dict(file="reserved.zip",start="2024-01-01",end_exclusive="2026-01-01",rows=1,expected=1),dict(file="dev26.zip",start="2026-01-01",end_exclusive=END,rows=2,expected=2)]
        (root/"manifest.json").write_text(json.dumps(dict(dataset_version="1.1",errors=[],files=files)))
        (root/"dev26.zip").write_bytes(b"test")
        q=scope_2026(root,b);assert q["files"]==1 and not (Path(b)/"reserved.zip").exists()
    print("2026 development scope excludes reserved archive PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--acquire",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    if a.selftest:return
    if a.acquire:
        # Keep downloader unchanged; only the explicitly allowed range changes.
        import sys
        acquisition.START=date(2026,1,1);acquisition.END=date(2026,10,1)
        sys.argv=[sys.argv[0]]
        acquisition.main()
        path=Path("lab-derivatives/manifest.json");meta=json.loads(path.read_text())
        meta["period"]="2026-01-01 to 2026-10-01 exclusive, development extension"
        assert all(f["start"]>="2026-01-01" and f["end_exclusive"]<=END for f in meta["files"])
        path.write_text(json.dumps(meta,indent=2))
        if any(v["verified"]!=v["files"] for v in meta["summary"].values()):raise SystemExit("2026 archive incomplete")
        return
    with tempfile.TemporaryDirectory() as a0,tempfile.TemporaryDirectory() as b0:
        q0=scoped_spot(a.dataset,a0);q1=scope_2026(a.dataset,b0)
        train,y,_,_,_,_=prepare(a0,a.derivatives,True)
        test,z,m,perp,mark,funding=prepare(b0,a.extension,False)
    r=signals(train,y,test,m)
    print("EXTENSION_SCOPE="+json.dumps(dict(development=q0,extension=q1,trainingRows=len(train),testRows=len(test),signals=len(r),routes=r.value_counts().to_dict())),flush=True)
    results={}
    for delay in [1,5,15]:
        results[str(delay)]={}
        for cost in FEES:
            q=replay(r,z,cost,start=START,end=END) if delay==1 else delayed_tables(r,m,perp,mark,funding,delay,cost)
            results[str(delay)][cost]=q
            print("EXTENSION="+json.dumps(dict(delay=delay,cost=cost,n=q["n"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],dd=q["dd"],years=q["years"])),flush=True)
    Path("lab-extension-2026.json").write_text(json.dumps(dict(period="2026-04-01 to 2026-10-01 exclusive, final-day embargo",results=results,limitations="M01-known predictors fitted once with labels available by 2024-01-01, rolling branch uses prior 365d as of that cutoff. No refit in 2026, 2026 Jan-Mar warmup only; deliberately tests persistence after a long gap, not ordinary live retraining. 2026 previously partly explored, only six months, CI descriptive. No 2024-25 market archive parsed or evaluated. No release or live orders."),indent=2))
if __name__=="__main__":main()
