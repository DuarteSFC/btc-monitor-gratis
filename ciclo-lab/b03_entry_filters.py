"""B03 entry-filter hypotheses. Development 2020-2023 only; no live orders.
Prespecified small family, common exits, cost stress, conservative gap accounting.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,segments,lag
from b03_diagnostic import replay

def hypotheses(m):
    base=m.b03 & m.atr15.notna() & (m.atr15>0)
    down=m.trend4h.eq(False)
    vol=m.volume>=1.5*lag(m,"vol20")
    recovery=(m.close>m.open)&((m.close-m.low)>=.65*(m.high-m.low))&(m.high>m.low)
    impulse=(m.rsi-lag(m,"rsi"))>=5
    # ATR must be large relative to estimated round-trip friction; independent of price level.
    room=m.atr15/m.close>=.002
    return {"base":base,"down":base&down,"relative_volume":base&vol,
            "recovery_candle":base&recovery,"rsi_impulse":base&impulse,
            "volatility_room":base&room,"down_volume":base&down&vol,
            "down_recovery":base&down&recovery}

def run(d,m,mask,s,fee,slip):
    z=m.copy(deep=False)
    z=z.assign(b03=mask.fillna(False))
    return replay(d,z,s,240,fee,slip)

def gate(q):
    # Exploratory screen, NOT significance or a pass to trade.
    return (q["n"]>=150 and q["unknown"]==0 and q["conservativeMeanR"] is not None
            and q["conservativeMeanR"]>=.05 and q["profitFactor"] is not None
            and q["profitFactor"]>=1.15 and sum(1 for v in q["years"].values()
                if v["n"]>=25 and v["conservativeMeanR"] is not None and v["conservativeMeanR"]>0)>=3)

def selftest():
    idx=pd.date_range("2020-01-01",periods=3,freq="5min",tz="UTC")
    m=pd.DataFrame(dict(b03=[False,True,True],atr15=[1.,1.,1.],close=[100.,100.,100.],
      open=[99.,99.,101.],low=[98.,98.,98.],high=[101.,101.,102.],volume=[1.,2.,.5],
      vol20=[1.,1.,1.],rsi=[25.,31.,33.],trend4h=[False,False,True],segment=[1,1,1]),index=idx)
    masks=hypotheses(m)
    assert int(masks["base"].sum())==2 and int(masks["down_volume"].sum())==1
    assert int(masks["rsi_impulse"].sum())==1 and int(masks["recovery_candle"].sum())==1
    assert all(not (v & ~masks["base"]).any() for v in masks.values())
    print("B03 filter tests PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");a=p.parse_args()
    selftest()
    if a.selftest:return
    d=load_minutes(a.dataset);d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")]
    m=signal_frames(d)
    results={}
    for name,mask in hypotheses(m).items():
        normal=run(d,m,mask,4.,.0005,.0002)
        stress=run(d,m,mask,4.,.0008,.0004)
        neighbor=run(d,m,mask,2.5,.0005,.0002)
        passes=gate(normal) and stress["conservativeMeanR"] is not None and stress["conservativeMeanR"]>0 and neighbor["conservativeMeanR"] is not None and neighbor["conservativeMeanR"]>0
        results[name]=dict(signals=int(mask.sum()),normal=normal,stress=stress,neighbor=neighbor,screenPass=bool(passes))
        print(json.dumps(dict(name=name,signals=int(mask.sum()),n=normal["n"],meanR=normal["meanR"],conservative=normal["conservativeMeanR"],stress=stress["conservativeMeanR"],neighbor=neighbor["conservativeMeanR"],screenPass=bool(passes))),flush=True)
    report=dict(period="2020-2023 development only",models=results,limitations="Eight correlated hypotheses informed by prior development results. No holdout, statistical confidence, funding, or live validation. Conservative gap penalty assumes spot notional loss. Normal and stress costs change exit geometry. Filters fixed before this run, not independent preregistration.")
    Path("lab-b03-entry-filters.json").write_text(json.dumps(report,indent=2))
    print("B03_FILTERS="+json.dumps(report),flush=True)
if __name__=="__main__":main()
