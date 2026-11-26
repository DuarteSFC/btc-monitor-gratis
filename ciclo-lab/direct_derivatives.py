"""Direct derivatives-context signals, development 2022-23.
No trading. Compare both assumed metrics lags and matched controls.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,lag,rolling,segments
from derivative_screen import load,derivative_features
from new_families import run
from frequency_screen import trade_audit

def signals(m,x):
    eligible=(m.index.minute%15==0)&m.atr15.notna()&(m.atr15>0)&x[["basis","oi_change15","oi_change60","funding"]].notna().all(axis=1)&(m.index.year>=2022)
    recovery=(m.close>m.open)&(m.close>lag(m,"high"))
    sweep=(m.low<lag(m,"lo20"))&(m.close>lag(m,"lo20"))
    prior_basis=lag(m.assign(b=x.basis),"b",3)
    prior_hi=lag(m.assign(hi=rolling(m,"high",24,lambda r:r.max())),"hi")
    vol=m.volume/lag(m,"vol20")
    return eligible,{
        "oi_flush_recovery":eligible&(x.oi_change60<=-.015)&(m.ret30<=-.005)&recovery,
        "negative_funding_reclaim":eligible&(x.funding<-.0001)&(x.oi_change60<0)&sweep,
        "discount_recovery":eligible&(prior_basis<=-.001)&(x.basis>prior_basis)&recovery,
        "oi_expansion_breakout":eligible&(x.oi_change60>=.015)&(m.close>prior_hi)&(vol>=1.5)&(x.funding<=.0003)
    }

def control(m,eligible,signal,seed):
    strata=pd.DataFrame(dict(year=m.index.year,trend=m.trend4h.astype("string").fillna("unknown"),session=m.index.hour//6,vol=pd.cut(m.atr15/m.close,[-np.inf,.002,.005,.01,np.inf],labels=False)),index=m.index)
    out=pd.Series(False,index=m.index);rng=np.random.default_rng(seed)
    for _,g in strata.loc[eligible].groupby(["year","trend","session","vol"],dropna=False):
        n=int(signal.loc[g.index].sum())
        if n:out.loc[rng.choice(g.index,size=n,replace=False)]=True
    assert int(out.sum())==int(signal.sum())
    return out

def selftest():
    from derivative_screen import selftest as test
    test()
    idx=pd.date_range("2022-01-01",periods=60,freq="5min",tz="UTC")
    m=pd.DataFrame(dict(atr15=1.,open=99.,high=99.5,low=98.,close=99.4,lo20=98.5,vol20=1.,volume=2.,segment=1,ret30=-.01,trend4h=False),index=idx)
    m.loc[idx[3],["close","high"]]=[100.,101.]
    x=pd.DataFrame(dict(basis=-.002,oi_change15=-.01,oi_change60=-.02,funding=-.0002),index=idx)
    e,s=signals(m,x)
    assert s["oi_flush_recovery"].loc[idx[3]]
    assert all(not (v&~e).any() for v in s.values())
    assert int(control(m,e,s["oi_flush_recovery"],42).sum())==int(s["oi_flush_recovery"].sum())
    x.loc[idx[3],"oi_change60"]=np.nan
    assert not signals(m,x)[1]["oi_flush_recovery"].loc[idx[3]]
    print("Direct derivative triggers, missing-data gate and matched control PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")]
    m=signal_frames(d)
    sources=[load(a.derivatives,k) for k in ["perp","mark","metrics","funding"]]
    e15,s15=signals(m,derivative_features(m,*sources,15))
    e30,s30=signals(m,derivative_features(m,*sources,30))
    common=e15&e30
    results={}
    for name in s15:
        out={}
        for delay,s in [(15,s15[name]),(30,s30[name])]:
            s=s&common
            q=run(d,m,s);stress=run(d,m,s,fee=.0008,slip=.0004);audit=trade_audit(d,m,s,.0008,.0004)
            assert audit["n"]==stress["n"]
            if audit["n"]:assert abs(audit["mean"]-stress["conservativeMeanR"])<1e-8
            random=[run(d,m,control(m,common,s,seed)) for seed in [101,202,303,404,505]]
            ctl=[v["conservativeMeanR"] for v in random if v["conservativeMeanR"] is not None]
            ci=audit["ci"]
            passed=bool(q["n"]>=150 and stress["n"]>=150 and q["unknown"]==0 and stress["unknown"]==0 and ci and ci[0]>0 and q["conservativeMeanR"]>=.05 and q["profitFactor"] is not None and q["profitFactor"]>=1.15 and ctl and q["conservativeMeanR"]>max(ctl))
            out[str(delay)]=dict(normal=q,stress=stress,audit=audit,random=random,screenPass=passed)
            print("DIRECT="+json.dumps(dict(name=name,delay=delay,n=q["n"],normal=q["conservativeMeanR"],stress=stress["conservativeMeanR"],pf=q["profitFactor"],equity=q["equityEnd"],ci=ci,hit1=audit["hitRate"],lead=audit["medianLead"],unknown=q["unknown"],controls=ctl,passed=passed)),flush=True)
        results[name]=out
    Path("lab-direct-derivatives.json").write_text(json.dumps(dict(period="2022-2023 development only",eligible=int(common.sum()),results=results,limitations="Direct four hypotheses, two assumed metric delays, 16 cost replays and 40 matched controls. 5m signal-bar price conditions on 15m grid. Funding predictor only; OI decline is not observed liquidations. Spot execution proxy, no funding cash flow. Unadjusted exploratory bootstrap; no holdout."),indent=2))
if __name__=="__main__":main()
