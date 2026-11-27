"""MS01: fixed shock-response hypothesis, no fitted models or threshold search."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from ms1_dataset import WEEKS,DATES
from derivative_screen import load
from market_frame import segments,bars,atr,align
from hourly_futures import make_outcomes,FEES,NS
from validation_rehearsal import replay,utc

def quality(a,ref):
    b=a.resample("1min",closed="left",label="left").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
    b=b.reindex(ref.index)
    v=(b.volume-ref.volume).abs()/ref.volume.where(ref.volume>0)
    p=(b[["open","high","low","close"]]-ref[["open","high","low","close"]]).abs()/ref[["open","high","low","close"]]
    return v.le(.01)&p.max(axis=1).le(.001)&b.notna().all(axis=1)

def read_week(root,items,week,perp):
    start=utc(week);end=start+pd.Timedelta(days=7)
    frames=[];good=bad=0
    for date in pd.date_range(start,end,freq="D",inclusive="left"):
        name=date.strftime("%Y-%m-%d");f=items[name];path=root/f["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest()!=f["fileSHA256"]:raise ValueError("5s digest mismatch")
        a=pd.read_csv(path,compression="gzip")
        a.index=pd.to_datetime(a.pop("openUtc"),utc=True)
        if len(a)!=f["bins"] or a.index.has_duplicates or not a.index.is_monotonic_increasing:raise ValueError("bad bins")
        if ((a.index<date)|(a.index>=date+pd.Timedelta(days=1))).any():raise ValueError("unexpected date")
        ref=perp.loc[(perp.index>=date)&(perp.index<date+pd.Timedelta(days=1))]
        ok=quality(a,ref);good+=int(ok.sum());bad+=int((~ok).sum())
        a=a.loc[ok.reindex(a.index.floor("min")).fillna(False).to_numpy()]
        frames.append(a)
    a=pd.concat(frames).reindex(pd.date_range(start,end,freq="5s",inclusive="left"))
    a.index+=pd.Timedelta(seconds=5)
    return a,dict(week=week,goodMinutes=good,excludedMinutes=bad,completeBins=int(a.close.notna().sum()))

def conditions(a):
    # Index = close timestamp of each 5s bin. No future-derived features.
    # Require all 12 bins in shock and all 3 bins in recovery.
    vol=a.volume.rolling(12,min_periods=12).sum()
    buy=a.buyVolume.rolling(12,min_periods=12).sum()
    ret=a.close/a.open.shift(11)-1
    v=vol.shift(3);sell=1-buy.shift(3)/v.where(v>0);r=ret.shift(3)
    vbase=vol.shift(15).rolling(360,min_periods=360).median()
    rbase=ret.abs().shift(15).rolling(360,min_periods=360).median()
    rv=a.volume.rolling(3,min_periods=3).sum()
    rb=a.buyVolume.rolling(3,min_periods=3).sum()/rv.where(rv>0)
    rr=a.close/a.open.shift(2)-1
    complete=vol.notna()&v.notna()&vbase.gt(0)&rbase.gt(0)&rb.notna()&r.notna()&rr.notna()
    base=complete&(v>=2*vbase)&(sell>=.65)&(rb>=.60)&(rr>0)
    limited=(r>=-rbase)&(r<=0)
    return pd.DataFrame(dict(complete=complete,base=base,selected=base&limited,shockReturn=r,shockSell=sell,shockVolumeRatio=v/vbase,recoveryBuy=rb),index=a.index)

def market(perp,ix):
    d=segments(perp.assign(quote=perp.volume*perp.close))
    h=bars(d,60);h["a"]=atr(h)
    m=pd.DataFrame(index=ix)
    m["segment"]=d.segment.reindex(ix-pd.Timedelta(minutes=1)).to_numpy()
    m["atr1"]=align(h,m,"a")*.6
    return m

def tables(m,perp,mark,funding,delay,cost):
    shift=pd.Timedelta(minutes=delay-1)
    z=m.copy();z.index+=shift
    return make_outcomes(z,pd.Series(True,index=z.index),perp,mark,funding,120,*FEES[cost])

def fast(index,lookup):
    eq=10000.;last=-1;rs=[];unknown=0
    for dt in index:
        if dt+NS<last:continue
        if dt not in lookup:unknown+=1;last=dt+1441*NS;continue
        r,f,e=lookup[dt];eq+=min(.0025*eq,eq*f)*r;last=e;rs.append(r)
    return dict(n=len(rs),mean=float(np.mean(rs)) if rs else None,equity=eq,unknown=unknown)

def controls(base,selected,y,observed):
    z=pd.DataFrame(dict(day=base.strftime("%Y-%m-%d"),session=base.hour//6),index=base)
    groups=[]
    for _,g in z.groupby(["day","session"]):
        n=int(g.index.isin(selected).sum())
        if n:groups.append((g.index.as_unit("ns").asi8,n))
    assert sum(n for _,n in groups)==len(selected)
    lookup={t.value:(v.R,v.riskFraction,int(v.exit)) for t,v in y.iterrows()}
    orig=fast(selected.as_unit("ns").asi8,lookup)
    assert orig["n"]==observed["n"] and orig["unknown"]==observed["unknown"]
    np.testing.assert_allclose(orig["equity"],observed["equity"],rtol=1e-10,atol=1e-10)
    rng=np.random.default_rng(20261127);out=[]
    for _ in range(199):
        t=np.sort(np.concatenate([rng.choice(ix,size=n,replace=False) for ix,n in groups])) if groups else np.array([],dtype=np.int64)
        out.append(fast(t,lookup))
    valid=[q for q in out if q["mean"] is not None and not q["unknown"]]
    movable=sum(len(ix)>n for ix,n in groups)
    p=(1+sum(q["mean"]>=observed["mean"] for q in valid))/200 if len(valid)==199 and observed["mean"] is not None and not observed["unknown"] and movable else None
    return dict(draws=out,valid=len(valid),movableStrata=movable,totalStrata=len(groups),medianMean=float(np.median([q["mean"] for q in valid])) if valid else None,pRelative=p)

def selftest():
    from microstructure_probe import selftest as test
    test()
    i=pd.date_range("2022-01-01",periods=1000,freq="5s",tz="UTC")
    a=pd.DataFrame(dict(open=100.,close=100.01,volume=1.,buyVolume=.5),index=i)
    a.loc[i[686]:i[697],["volume","buyVolume"]]=[4.,.4]
    a.loc[i[697],"close"]=99.995
    a.loc[i[698]:i[700],["buyVolume","close"]]=[.9,100.02]
    z=conditions(a);assert bool(z.loc[i[700],"selected"]);b=a.copy();b.loc[i[800]:,"volume"]=100.
    pd.testing.assert_frame_equal(z.iloc[:800],conditions(b).iloc[:800])
    b=a.copy();b.loc[i[500],["volume","buyVolume","close","open"]]=np.nan
    assert not conditions(b).complete.iloc[500:516].any() and not bool(conditions(b).loc[i[700],"selected"])
    t=pd.date_range("2022-01-01",periods=2,freq="min",tz="UTC")
    q=pd.DataFrame(dict(open=[100.,100.],high=[100.,100.],low=[100.,100.],close=[100.,100.],volume=[12.,12.]),index=t)
    bb=pd.DataFrame(dict(open=100.,high=100.,low=100.,close=100.,volume=1.),index=pd.date_range(t[0],periods=24,freq="5s"))
    assert quality(bb,q).all()
    bb.iloc[0,bb.columns.get_loc("volume")]=2.
    assert quality(bb,q).tolist()==[False,True]
    print("MS01 causal shock/recovery, missing-bin and quality-filter tests PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    if a.selftest:return
    root=Path(a.dataset);meta=json.loads((root/"manifest.json").read_text())
    assert meta["dates"]==DATES and meta["weeks"]==WEEKS and meta["verified"]==70 and not meta["errors"]
    items={r["day"]:r for r in meta["results"]};assert set(items)==set(DATES)
    results={}
    for name,weeks,deriv,start,end in [("2022-23",WEEKS[:8],a.derivatives,"2022-01-01","2024-01-01"),("2026",WEEKS[8:],a.extension,"2026-04-01","2026-10-01")]:
        perp,mark,funding=[load(deriv,k) for k in ["perp","mark","funding"]]
        assert perp.index.max()<utc(end) and perp.index.min()>=utc("2021-01-01" if name=="2022-23" else "2026-01-01")
        base=[];selected=[];audit=[]
        for week in weeks:
            d,q=read_week(root,items,week,perp)
            f=conditions(d)
            f=f.loc[(f.index.second==0)&(f.index<utc(week)+pd.Timedelta(days=7,hours=-4))]
            base.append(f.index[f.base]);selected.append(f.index[f.selected])
            q.update(completeDecisions=int(f.complete.sum()),baseSignals=int(f.base.sum()),selected=int(f.selected.sum()))
            audit.append(q);print("MS01_WEEK="+json.dumps(q),flush=True)
        ix=base[0].append(base[1:]);s=selected[0].append(selected[1:])
        m=market(perp,ix)
        eligible=m.atr1.notna()&m.atr1.gt(0)&m.segment.notna()
        m=m.loc[eligible];ix=m.index;s=s.intersection(ix)
        summary=dict(period=name,baseSignals=len(ix),signals=len(s),weeks=len(weeks))
        print("MS01_SCOPE="+json.dumps(summary),flush=True)
        out={}
        for delay in [1,5,15]:
            out[str(delay)]={}
            for cost in FEES:
                y=tables(m if delay==1 and cost=="stress" else m.loc[s],perp,mark,funding,delay,cost)
                r=pd.Series("2h15",index=s+pd.Timedelta(minutes=delay-1),dtype="object")
                q=replay(r,{"2h15":{cost:y}},cost,start=start,end=end)
                out[str(delay)][cost]=q
                print("MS01_RESULT="+json.dumps(dict(period=name,delay=delay,cost=cost,n=q["n"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],years=q["years"])),flush=True)
                if delay==1 and cost=="stress":
                    b=replay(pd.Series("2h15",index=ix,dtype="object"),{"2h15":{cost:y}},cost,start=start,end=end)
                    c=controls(ix,s,y,q)
                    out["base"]=b;out["controls"]=c
                    print("MS01_CONTROL="+json.dumps(dict(period=name,baseN=b["n"],baseMean=b["mean"],baseUnknown=b["unknown"],**{k:v for k,v in c.items() if k!="draws"})),flush=True)
        results[name]=dict(scope=summary,weekAudit=audit,results=out)
    Path("lab-ms01.json").write_text(json.dumps(dict(results=results,limitations="Ten fixed calendar weeks only. 5s event-time aggregate executions, not orders/depth, retrospective minute quality filter. 120m outcome, 1.5 ATR1h futures, 1/5/15m hypothetical execution. Matched timing controls approximate, only day/session; no multiple-testing significance or independent validation. No holdout or release."),indent=2))
if __name__=="__main__":main()
