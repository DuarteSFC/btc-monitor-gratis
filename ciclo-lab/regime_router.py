"""CICLO LAB regime router, development-only expanding walk-forward.
No future data in training; no orders. Evaluation years 2021-23 are already
researched development data, not an independent holdout.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,bars,ema,atr,align,rolling,lag,segments
from new_families import families,run
from flow_families import load_flow,masks as flow_masks
from b03_entry_filters import hypotheses
from b03_diagnostic import replay

REGIMES=["up","down","range","shock"]
def regimes(d,m):
    k=bars(d,240)
    k["spread"]=(ema(k,50)-ema(k,200))/atr(k).replace(0,np.nan)
    s=align(k,m,"spread")
    x=m.assign(relatr=m.atr15/m.close)
    med=lag(x.assign(med=rolling(x,"relatr",2016,lambda r:r.median())),"med")
    z=pd.Series("unknown",index=m.index)
    valid=s.notna()&med.notna()&(med>0)&x.relatr.notna()
    z.loc[valid]="range"
    z.loc[valid&(s>1)]="up";z.loc[valid&(s< -1)]="down"
    z.loc[valid&(x.relatr>=1.5*med)]="shock"
    return z

def candidates(d,m):
    out={"b03_recovery":hypotheses(m)["down_recovery"],"b02":m.b02,"b05":m.b05}
    out.update(families(d,m));out.update(flow_masks(d,m))
    eligible=m.atr15.notna()&(m.atr15>0)
    return {k:v.fillna(False)&eligible for k,v in out.items()}

def passes(q):
    return q["n"]>=40 and q["unknown"]==0 and q["conservativeMeanR"] is not None and q["conservativeMeanR"]>=.05 and q["profitFactor"] is not None and q["profitFactor"]>=1.15

def select(d,m,reg,signals,cut):
    # No training trade can exit in the evaluation year.
    dd=d.loc[d.index<cut];mm=m.loc[m.index<cut]
    rr=reg.loc[mm.index]; choices={}; audit={}
    for state in REGIMES:
        passed=[];audit[state]=[]
        for name,signal in signals.items():
            mask=signal.loc[mm.index]&(rr==state)
            if int(mask.sum())<40:continue
            q=run(dd,mm,mask)
            row=dict(name=name,n=q["n"],mean=q["conservativeMeanR"],pf=q["profitFactor"],unknown=q["unknown"])
            if passes(q):
                stress=run(dd,mm,mask,fee=.0008,slip=.0004)
                row["stress"]=stress["conservativeMeanR"]
                if stress["n"]>=40 and stress["unknown"]==0 and stress["conservativeMeanR"] is not None and stress["conservativeMeanR"]>0:
                    passed.append((min(q["conservativeMeanR"],stress["conservativeMeanR"]),name))
            audit[state].append(row)
        choices[state]=sorted(passed,key=lambda a:(-a[0],a[1]))[0][1] if passed else None
    return choices,audit

def route(reg,signals,choices):
    out=pd.Series(False,index=reg.index)
    for state,name in choices.items():
        if name is not None:out|=(reg==state)&signals[name]
    return out

def selftest():
    idx=pd.date_range("2020-01-01",periods=60*72,freq="min",tz="UTC")
    rng=np.random.default_rng(42);c=100+np.cumsum(rng.normal(0,.1,len(idx)));o=np.r_[c[0],c[:-1]];v=rng.uniform(1,10,len(idx))
    d=segments(pd.DataFrame(dict(open=o,high=np.maximum(o,c)+.05,low=np.minimum(o,c)-.05,close=c,volume=v,quote=c*v,buy=v*.55),index=idx))
    m=signal_frames(d);before=regimes(d,m);cut=idx[3000];e=d.copy();e.loc[e.index>=cut,["open","high","low","close"]]*=1.5
    pd.testing.assert_series_equal(before.loc[:cut],regimes(e,signal_frames(e)).loc[:cut])
    r=pd.Series(["up","down","unknown","range"],index=idx[:4]);s={"A":pd.Series([True]*4,index=r.index),"B":pd.Series([False,True,True,True],index=r.index)}
    assert route(r,s,{"up":"A","down":"B","range":None,"shock":None}).tolist()==[True,True,False,False]
    assert not route(r,s,{k:None for k in REGIMES}).any()
    assert not passes(dict(n=100,unknown=1,conservativeMeanR=.2,profitFactor=2))
    print("Regime router causality, abstention and selection gates PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")]
    d=load_flow(a.dataset,d);m=signal_frames(d);reg=regimes(d,m);signals=candidates(d,m)
    combined=pd.Series(False,index=m.index);unconditional=pd.Series(False,index=m.index)
    for v in signals.values():unconditional|=v
    folds={}
    for year in [2021,2022,2023]:
        cut=pd.Timestamp(f"{year}-01-01",tz="UTC");end=pd.Timestamp(f"{year+1}-01-01",tz="UTC")
        choices,audit=select(d,m,reg,signals,cut)
        active=(m.index>=cut)&(m.index<end)
        mask=route(reg,signals,choices)&active
        combined|=mask
        # Evaluation only; no fold output is used to tune the selection rules.
        dd=d.loc[d.index<end];mm=m.loc[m.index<end]
        q=run(dd,mm,mask.loc[mm.index])
        folds[str(year)]=dict(choices=choices,training=audit,evaluation=q,signals=int(mask.sum()),regime_counts=reg.loc[active].value_counts().to_dict())
        print("FOLD="+json.dumps(dict(year=year,choices=choices,signals=int(mask.sum()),n=q["n"],meanR=q["conservativeMeanR"],equity=q["equityEnd"])),flush=True)
    normal=run(d,m,combined);stress=run(d,m,combined,fee=.0008,slip=.0004)
    union=run(d,m,unconditional&(m.index.year>=2021))
    report=dict(period="2021-2023 walk-forward development",training="expanding 2020 onward; frozen thresholds; only prior closed outcomes",models=list(signals),regimes=REGIMES,folds=folds,normal=normal,stress=stress,unconditional_union=union,no_trade_equity=10000.,limitations="Previously inspected development years, not independent validation. Selection across multiple cells risks overfit. No futures funding. 4 ATR stop, 4h timeout, 2R target. Single non-overlapping portfolio; unknown exits penalized full spot notional. Aggregate replay can carry trades across evaluation year boundaries, unlike isolated fold stats. No allocation to unknown regime.")
    Path("lab-regime-router.json").write_text(json.dumps(report,indent=2))
    print("ROUTER="+json.dumps({k:v for k,v in report.items() if k!="folds"}),flush=True)
if __name__=="__main__":main()
