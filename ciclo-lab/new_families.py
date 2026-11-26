"""CICLO LAB: distinct entry families, frozen before this development run.
15m decision time, 1m execution, 2020-2023 only. No live trading.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,segments,bars,lag,rolling,ema,rsi,atr,align
from b03_diagnostic import replay
from b03_entry_filters import gate

def confirmed_divergence(q):
    # A pivot two bars ago is knowable only now, after two right-hand bars.
    p=lag(q,"low",2)
    pivot=(p<lag(q,"low",4))&(p<lag(q,"low",3))&(p<lag(q,"low",1))&(p<q.low)
    pr=lag(q,"rsi",2)
    a=q.assign(pl=p.where(pivot),pr=pr.where(pivot),
               pi=pd.Series(np.arange(len(q)),index=q.index).where(pivot))
    def previous(col):
        z=a.groupby("segment",sort=False)[col].ffill()
        return z.groupby(a.segment,sort=False).shift(1)
    oldl,oldr,oldi=previous("pl"),previous("pr"),previous("pi")
    age=np.arange(len(q))-oldi
    return pivot&(age<=48)&(p<oldl)&(pr>=oldr+3)&(pr<45)&(q.close>lag(q,"close",2))

def families(d,m):
    q=bars(d,15); h=bars(d,60)
    q["rsi"]=rsi(q);q["atr"]=atr(q);q["e20"]=ema(q,20)
    q["lo24"]=rolling(q,"low",24,lambda r:r.min())
    q["hi24"]=rolling(q,"high",24,lambda r:r.max())
    q["v20"]=rolling(q,"volume",20,lambda r:r.mean())
    h["e20"]=ema(h,20);h["e50"]=ema(h,50)
    h["trend"]=(h.e20>h.e50)&(h.e20>lag(h,"e20",3))
    up=align(h,q,"trend").eq(True)
    rng=q.high-q.low
    closepos=(q.close-q.low)/rng.where(rng>0)
    vol=q.volume/lag(q,"v20")
    low=lag(q,"lo24");high=lag(q,"hi24")
    sweep=(q.low<low)&(q.close>low)&(closepos>=.65)&(q.close>q.open)
    # First retest of a known breakout level, one to six completed bars later.
    breakout=(q.close>high)&(vol>=1.5)&(q.close>q.open)
    a=q.assign(level=high.where(breakout),event=pd.Series(np.arange(len(q)),index=q.index).where(breakout))
    a["level"]=a.groupby("segment",sort=False).level.ffill()
    a["event"]=a.groupby("segment",sort=False).event.ffill()
    level=lag(a,"level");event=lag(a,"event")
    age=np.arange(len(q))-event
    retest=(age>=1)&(age<=6)&(q.low<=level+.2*lag(q,"atr"))&(q.low>=level-.5*lag(q,"atr"))&(q.close>level)&(q.close>q.open)
    first=retest & (retest.astype(int).groupby([q.segment,event],dropna=True).cumsum()==1)
    # Exhaustion followed by a confirmed recovery, not a contemporaneous forecast.
    exhaustion=(q.close<q.open)&(vol>=2.5)&(rng>=1.5*lag(q,"atr"))&(q.rsi<35)
    recovery=(q.close>lag(q,"high"))&(q.close>q.open)
    q["structure_sweep"]=sweep&(vol>=1.5)
    q["pivot_divergence"]=confirmed_divergence(q)
    q["breakout_retest"]=first
    q["volume_exhaustion"]=lag(q.assign(ex=exhaustion),"ex").eq(True)&recovery
    q["trend_pullback"]=up&(q.low<=q.e20)&(q.close>q.e20)&(q.close>lag(q,"high"))&(q.rsi>=45)&(q.rsi<=65)
    keys=["structure_sweep","pivot_divergence","breakout_retest","volume_exhaustion","trend_pullback"]
    return {k:align(q,m,k,exact=True).eq(True)&m.atr15.notna()&(m.atr15>0) for k in keys}

def run(d,m,mask,s=4.,fee=.0005,slip=.0002):
    return replay(d,m.assign(b03=mask.fillna(False)),s,240,fee,slip)

def control(m,mask,seed):
    # Match year, 4h trend regime, UTC 6h bucket and volatility band. 15m grid only.
    eligible=m.atr15.notna()&(m.atr15>0)&(m.index.minute%15==0)
    strata=pd.DataFrame(dict(year=m.index.year,regime=m.trend4h.astype("string").fillna("unknown"),
        session=m.index.hour//6,vol=pd.cut(m.atr15/m.close,[-np.inf,.002,.005,.01,np.inf],labels=False)),index=m.index)
    out=pd.Series(False,index=m.index);rng=np.random.default_rng(seed)
    for _,g in strata.loc[eligible].groupby(["year","regime","session","vol"],dropna=False):
        n=int(mask.loc[g.index].sum())
        if n:out.loc[rng.choice(g.index,size=n,replace=False)]=True
    assert int(out.sum())==int(mask.sum())
    return out

def selftest():
    from market_frame import selftest as frame_test
    frame_test()
    idx=pd.date_range("2020-01-01",periods=60*72,freq="min",tz="UTC")
    rng=np.random.default_rng(42);c=100+np.cumsum(rng.normal(0,.1,len(idx)))
    o=np.r_[c[0],c[:-1]]
    d=segments(pd.DataFrame(dict(open=o,high=np.maximum(o,c)+.05,low=np.minimum(o,c)-.05,
          close=c,volume=rng.uniform(1,10,len(idx)),quote=c*5),index=idx))
    m=signal_frames(d);before=families(d,m)
    cut=idx[3000];e=d.copy();e.loc[e.index>=cut,["open","high","low","close"]]*=1.5
    after=families(e,signal_frames(e))
    for k in before:
        pd.testing.assert_series_equal(before[k].loc[:cut],after[k].loc[:cut])
        assert all(before[k].index[before[k]].minute%15==0)
    # Two synthetic confirmed lows: second lower low with stronger RSI.
    qi=pd.date_range("2020-01-01",periods=12,freq="15min",tz="UTC")
    lows=[12,11,9,11,12,12,11,8,11,12,13,14]
    q=pd.DataFrame(dict(low=lows,close=np.array(lows)+.5,rsi=[40,35,25,30,40,40,38,31,40,45,50,55],segment=1),index=qi)
    div=confirmed_divergence(q)
    assert div.iloc[9] and not div.iloc[7] and int(div.sum())==1
    print("New family causality, decision-grid and pivot-confirmation tests PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")]
    m=signal_frames(d);results={}
    for name,mask in families(d,m).items():
        normal=run(d,m,mask);stress=run(d,m,mask,fee=.0008,slip=.0004);neighbor=run(d,m,mask,s=2.5)
        random=[run(d,m,control(m,mask,seed)) for seed in [101,202,303,404,505]]
        ctrl=[v["conservativeMeanR"] for v in random if v["conservativeMeanR"] is not None]
        beats=bool(ctrl and normal["conservativeMeanR"] is not None and normal["conservativeMeanR"]>max(ctrl))
        passes=bool(gate(normal) and stress["conservativeMeanR"] is not None and stress["conservativeMeanR"]>0 and neighbor["conservativeMeanR"] is not None and neighbor["conservativeMeanR"]>0 and beats)
        results[name]=dict(signals=int(mask.sum()),normal=normal,stress=stress,neighbor=neighbor,random=random,beatsAllFive=beats,screenPass=passes)
        print(json.dumps(dict(name=name,signals=int(mask.sum()),n=normal["n"],meanR=normal["meanR"],conservative=normal["conservativeMeanR"],stress=stress["conservativeMeanR"],neighbor=neighbor["conservativeMeanR"],control=ctrl,screenPass=passes)),flush=True)
    report=dict(period="2020-2023 development only",models=results,limitations="Five new families, three exit/cost configurations and five matched random controls each. Controls match signal counts, not executed-trade counts. Five controls are not a significance test. Spot proxy, no funding; gap penalty total spot notional loss; not independent validation. No holdout evaluated.")
    Path("lab-new-families.json").write_text(json.dumps(report,indent=2))
    print("NEW_FAMILIES="+json.dumps(report),flush=True)
if __name__=="__main__":main()
