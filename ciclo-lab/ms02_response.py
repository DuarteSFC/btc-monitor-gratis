"""MS02: directional attribution of frozen MS01 events, not a trading policy."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from ms1_dataset import WEEKS,DATES
from ms01_absorption import read_week,conditions,market,selftest as base_test
from derivative_screen import load
from validation_rehearsal import utc

HORIZONS=[1,5,15,30,60,120]
def paths(perp,ix):
    # All results from next minute open, with complete 120-minute path.
    t=perp.index.as_unit("ns").asi8
    ns=60_000_000_000
    k=np.searchsorted(t,ix.as_unit("ns").asi8+ns)
    good=(k+119<len(t))
    k=k[good];ix=ix[good]
    good=(t[k]==ix.as_unit("ns").asi8+ns)&(t[k+119]==t[k]+119*ns)
    k=k[good];ix=ix[good]
    v=perp[["open","high","low","close"]].to_numpy()
    a=v[k,0]
    z=k[:,None]+np.arange(120)[None,:]
    high=v[z,1]/a[:,None]-1;low=v[z,2]/a[:,None]-1
    close=v[z,3]/a[:,None]-1
    out=pd.DataFrame(index=ix)
    for h in HORIZONS:
        out["r"+str(h)]=close[:,h-1]
        out["mfe"+str(h)]=high[:,:h].max(axis=1)
        out["mae"+str(h)]=low[:,:h].min(axis=1)
        u=high[:,:h]>=.0024;d=low[:,:h]<=-.0024
        up=np.where(u.any(axis=1),u.argmax(axis=1)+1,h+1)
        dn=np.where(d.any(axis=1),d.argmax(axis=1)+1,h+1)
        out["first"+str(h)]=np.where((up==dn)&(up<=h),"ambiguous",np.where(up<dn,"up",np.where(dn<up,"down","neither")))
        out["upTime"+str(h)]=np.where(up<=h,up,np.nan)
    return out

def summary(q,h):
    r=q["r"+str(h)]
    if not len(r):return dict(n=0)
    first=q["first"+str(h)]
    u=q.loc[first=="up","upTime"+str(h)]
    return dict(n=len(r),meanBps=float(r.mean()*1e4),medianBps=float(r.median()*1e4),positive=float((r>0).mean()),meanLess14Bps=float(r.mean()*1e4-14),meanLess24Bps=float(r.mean()*1e4-24),mfeMeanBps=float(q["mfe"+str(h)].mean()*1e4),maeMeanBps=float(q["mae"+str(h)].mean()*1e4),first={k:int((first==k).sum()) for k in ["up","down","ambiguous","neither"]},medianUpMinutes=float(u.median()) if len(u) else None)

def matched(q,h,control):
    z=q.assign(day=q.index.strftime("%Y-%m-%d"),session=q.index.hour//6)
    dif=[];weights=[]
    for _,g in z.groupby(["day","session"]):
        a=g.loc[g.selected,"r"+str(h)]
        b=g.loc[control(g),"r"+str(h)]
        if len(a) and len(b):
            dif.append(float(a.mean()-b.mean())*1e4);weights.append(len(a))
    return dict(matchedSelected=int(sum(weights)),strata=len(weights),differenceBps=float(np.average(dif,weights=weights)) if weights else None)

def selftest():
    base_test()
    i=pd.date_range("2022-01-01",periods=122,freq="min",tz="UTC")
    v=pd.DataFrame(dict(open=100.,high=100.1,low=99.9,close=100.),index=i)
    v.loc[i[1],["high","low","close"]]=[100.5,99.5,100.3]
    q=paths(v,i[:1])
    assert len(q)==1 and q.iloc[0].first1=="ambiguous"
    assert abs(q.iloc[0].r1-.003)<1e-12
    assert paths(v.drop(i[2]),i[:1]).empty
    print("MS02 next-minute entry, complete path and ambiguous crossing PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    if a.selftest:return
    root=Path(a.dataset);meta=json.loads((root/"manifest.json").read_text())
    assert meta["dates"]==DATES and meta["weeks"]==WEEKS and meta["verified"]==70 and not meta["errors"]
    items={r["day"]:r for r in meta["results"]};assert set(items)==set(DATES)
    results={}
    for name,weeks,deriv,end in [("2022-23",WEEKS[:8],a.derivatives,"2024-01-01"),("2026",WEEKS[8:],a.extension,"2026-10-01")]:
        perp=load(deriv,"perp");assert perp.index.max()<utc(end) and perp.index.min()>=utc("2021-01-01" if name=="2022-23" else "2026-01-01")
        frames=[];missing=0
        for week in weeks:
            d,_=read_week(root,items,week,perp)
            f=conditions(d);f=f.loc[(f.index.second==0)&(f.index<utc(week)+pd.Timedelta(days=7,hours=-4))&f.complete]
            m=market(perp,f.index);f=f.loc[m.atr1.notna()&m.atr1.gt(0)&m.segment.notna()]
            y=paths(perp,f.index);missing+=len(f)-len(y)
            z=y.join(f[["base","selected"]]);z["week"]=week;frames.append(z)
        q=pd.concat(frames);assert not q.index.has_duplicates
        n=int(q.selected.sum());assert n==(101 if name=="2022-23" else 33)
        assert int(q.base.sum())==(715 if name=="2022-23" else 209)
        rows=[]
        for h in HORIZONS:
            s=summary(q.loc[q.selected],h)
            b=summary(q.loc[q.base&~q.selected],h)
            allq=summary(q.loc[~q.selected],h)
            m=matched(q,h,lambda g:g.base&~g.selected)
            c=matched(q,h,lambda g:~g.selected)
            perweek=[dict(week=w,selected=summary(g.loc[g.selected],h),rejectedBase=summary(g.loc[g.base&~g.selected],h)) for w,g in q.groupby("week")]
            row=dict(period=name,horizon=h,selected=s,rejectedBase=b,otherEligible=allq,matchedBase=m,matchedAll=c,weeks=perweek)
            rows.append(row)
            print("MS02="+json.dumps({k:v for k,v in row.items() if k!="weeks"}),flush=True)
        results[name]=dict(missingPaths=missing,rows=rows)
    Path("lab-ms02.json").write_text(json.dumps(dict(results=results,limitations="Diagnostic only: overlapping forward returns, no stop/funding/sizing, same 70 days already used for failed MS01. Same day/session comparisons approximate, excludes selected from controls. Six horizons descriptive, no selection or independent significance. No holdout or release."),indent=2))
if __name__=="__main__":main()
