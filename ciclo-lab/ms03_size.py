"""MS03 fixed buy-side aggregate execution-size asymmetry breakout hypothesis."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from ms1_dataset import WEEKS,DATES
from ms01_absorption import read_week,market,controls,selftest as base_test
from derivative_screen import load
from hourly_futures import make_outcomes,FEES
from validation_rehearsal import replay,utc

def conditions(a):
    cols=["open","high","low","close","volume","buyVolume","aggregates","buyAggregates"]
    g=a[cols].resample("5min",closed="right",label="right")
    z=g.agg(dict(open="first",high="max",low="min",close="last",volume="sum",buyVolume="sum",aggregates="sum",buyAggregates="sum"))
    complete=g.count().eq(60).all(axis=1)
    z=z.where(complete)
    prior_high=z.high.shift(1).rolling(6,min_periods=6).max()
    prior_volume=z.volume.shift(1).rolling(6,min_periods=6).median()
    sellcount=z.aggregates-z.buyAggregates
    sells=z.volume-z.buyVolume
    ratio=(z.buyVolume/z.buyAggregates.where(z.buyAggregates>0))/(sells.where(sells>0)/sellcount.where(sellcount>0))
    base=complete&prior_high.notna()&prior_volume.gt(0)&z.volume.gt(0)&z.close.gt(prior_high)&z.close.gt(z.open)&(z.buyVolume/z.volume>=.60)&z.volume.ge(prior_volume)&ratio.notna()
    return pd.DataFrame(dict(base=base,selected=base&ratio.ge(2),ratio=ratio),index=z.index)
def tables(m,perp,mark,funding,delay,cost):
    z=m.copy();z["atr1"]/=.6;z.index+=pd.Timedelta(minutes=delay-1)
    return make_outcomes(z,pd.Series(True,index=z.index),perp,mark,funding,240,*FEES[cost])
def selftest():
    base_test()
    i=pd.date_range("2022-01-01 00:00:05",periods=60*9,freq="5s",tz="UTC")
    a=pd.DataFrame(dict(open=100.,high=100.1,low=99.9,close=100.,volume=1.,buyVolume=.5,aggregates=10.,buyAggregates=5.),index=i)
    ix=i[360:420]
    a.loc[ix,["high","close","buyVolume","buyAggregates"]]=[101.,100.5,.75,4.]
    f=conditions(a);assert f.selected.loc[ix[-1]]
    b=a.copy();b.loc[i[430]:,"close"]=1000.
    pd.testing.assert_frame_equal(f.loc[:ix[-1]],conditions(b).loc[:ix[-1]])
    b=a.copy();b.loc[i[100],:]=np.nan
    assert not conditions(b).selected.loc[ix[-1]]
    print("MS03 positive breakout, execution-size ratio, prior-window gap and prefix tests PASS",flush=True)
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
            f=conditions(d);f=f.loc[f.index<utc(week)+pd.Timedelta(days=7,hours=-4,minutes=-30)]
            base.append(f.index[f.base]);selected.append(f.index[f.selected])
            q.update(baseSignals=int(f.base.sum()),selected=int(f.selected.sum()))
            audit.append(q)
        ix=base[0].append(base[1:]);s=selected[0].append(selected[1:])
        m=market(perp,ix);m=m.loc[m.atr1.notna()&m.atr1.gt(0)&m.segment.notna()]
        ix=m.index;s=s.intersection(ix)
        print("MS03_SCOPE="+json.dumps(dict(period=name,baseSignals=len(ix),signals=len(s),weeks=len(weeks))),flush=True)
        out={}
        for delay in [1,5,15]:
            out[str(delay)]={}
            for cost in FEES:
                y=tables(m if delay==1 and cost=="stress" else m.loc[s],perp,mark,funding,delay,cost)
                r=pd.Series("4h",index=s+pd.Timedelta(minutes=delay-1),dtype="object")
                q=replay(r,{"4h":{cost:y}},cost,start=start,end=end)
                out[str(delay)][cost]=q
                print("MS03_RESULT="+json.dumps(dict(period=name,delay=delay,cost=cost,n=q["n"],mean=q["mean"],pf=q["pf"],equity=q["equity"],ci=q["ci"],unknown=q["unknown"],years=q["years"])),flush=True)
                if delay==1 and cost=="stress":
                    b=replay(pd.Series("4h",index=ix,dtype="object"),{"4h":{cost:y}},cost,start=start,end=end)
                    c=controls(ix,s,y,q)
                    out["base"]=b;out["controls"]=c
                    print("MS03_CONTROL="+json.dumps(dict(period=name,baseN=b["n"],baseMean=b["mean"],baseUnknown=b["unknown"],**{k:v for k,v in c.items() if k!="draws"})),flush=True)
        results[name]=dict(weekAudit=audit,results=out)
    Path("lab-ms03.json").write_text(json.dumps(dict(results=results,limitations="Fixed 70-day reused development sample, no fitted models, aggregate execution sizes not individual order sizes; minute reconciliation retrospective, day/session controls approximate, overlapping policies and sparse weeks, no independent significance, no production or reserved data."),indent=2))
if __name__=="__main__":main()
