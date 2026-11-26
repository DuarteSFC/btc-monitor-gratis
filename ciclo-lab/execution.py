"""Experimental next-minute long execution; independent strategy simulations.
No live orders or production imports. Fixed-capital risk sizing, no leverage.
"""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,segments

RISK_FRACTION=.0025
CAPITAL=10000.
FEE=.0005
SLIPPAGE=.0002
LATENCY=1
HORIZON=240
NS=60_000_000_000

def prices(raw,atr,fee=FEE,slip=SLIPPAGE):
    # Entry paid above quote; stop is a trigger; realized sell priced below trigger.
    entry=raw*(1+slip)
    stop=entry-1.5*atr
    if not (0<stop<entry):return None
    risk=entry*(1+fee)-stop*(1-slip)*(1-fee)
    target=(entry*(1+fee)+2*risk)/((1-slip)*(1-fee))
    qty=min(CAPITAL*RISK_FRACTION/risk,CAPITAL/(entry*(1+fee)))
    return entry,stop,target,risk,qty

def simulate(d,m,mask,fee=FEE,slip=SLIPPAGE):
    t=d.index.as_unit("ns").asi8
    x=d[["open","high","low","close"]].to_numpy()
    sg=d.segment.to_numpy()
    signals=m.index[mask].as_unit("ns").asi8
    atrs=m.loc[mask,"atr15"].to_numpy()
    segs=m.loc[mask,"segment"].to_numpy()
    records=[];skips={"overlap":0,"missing_entry":0,"bad_risk":0,"end_of_sample":0}
    last=-1
    for signal,atr,seg in zip(signals,atrs,segs):
        et=signal+LATENCY*NS
        if et<=last:skips["overlap"]+=1;continue
        if et+(HORIZON-1)*NS>t[-1]:skips["end_of_sample"]+=1;continue
        k=int(np.searchsorted(t,et))
        if k>=len(t) or t[k]!=et or sg[k]!=seg:
            skips["missing_entry"]+=1;continue
        p=prices(x[k,0],atr,fee,slip)
        if p is None:skips["bad_risk"]+=1;continue
        entry,stop,target,risk,qty=p
        outcome=None;raw_exit=None
        for j in range(k,k+HORIZON):
            if j>=len(t) or t[j]!=et+(j-k)*NS or sg[j]!=seg:
                outcome="unknown_gap"
                last=int(t[j]) if j<len(t) else int(t[-1])
                break
            o,h,l,c=x[j]
            if l<=stop:raw_exit=min(o,stop);outcome="stop";break
            if h>=target:raw_exit=target;outcome="target";break
            if j==k+HORIZON-1:raw_exit=c;outcome="timeout";break
        if outcome=="unknown_gap":
            # Never delete unknown trades from the denominator; bound by spot total loss.
            records.append({"result":outcome,"signal":int(signal),"R":None,
                            "worst_R":-entry*(1+fee)/risk,"pnl":None,
                            "worst_pnl":-entry*(1+fee)*qty})
            continue
        last=int(t[j]+NS) # exit could occur at any time within this minute
        exit=raw_exit*(1-slip)
        per=exit*(1-fee)-entry*(1+fee)
        records.append({"result":outcome,"signal":int(signal),"entry_time":int(et),
                        "exit_bar":int(t[j]),"R":float(per/risk),"pnl":float(per*qty)})
    known=[r for r in records if r["R"] is not None];unknown=[r for r in records if r["R"] is None]
    rr=np.array([r["R"] for r in known],dtype=float)
    pnl=np.array([r["pnl"] for r in known],dtype=float)
    n=len(records);loss=-rr[rr<0].sum();gain=rr[rr>0].sum()
    low=float(rr.sum()+sum(r["worst_R"] for r in unknown))
    # Closed-equity drawdown is descriptive; unknown exits invalidate full path metrics.
    equity=CAPITAL+np.r_[0.,pnl.cumsum()]
    dd=float(np.max((np.maximum.accumulate(equity)-equity)/np.maximum.accumulate(equity)))
    return {"signals":len(signals),"entered":n,"resolved":len(known),"unknown_exits":len(unknown),"skips":skips,
            "win_rate_lower":float((rr>0).sum()/n) if n else None,
            "win_rate_upper":float(((rr>0).sum()+len(unknown))/n) if n else None,
            "net_R_resolved":float(rr.sum()),"mean_R_resolved":float(rr.mean()) if len(rr) else None,
            "net_R_conservative":low,"mean_R_conservative":low/n if n else None,
            "profit_factor_resolved_R":float(gain/loss) if loss else None,
            "net_pnl_resolved":float(pnl.sum()),"closed_drawdown_resolved_only":dd},records

def test():
    idx=pd.date_range("2024-01-01",periods=300,freq="min",tz="UTC")
    d=segments(pd.DataFrame({"open":100.,"high":100.1,"low":99.9,"close":100.,"volume":1.,"quote":100.},index=idx))
    m=pd.DataFrame({"atr15":[1.],"segment":[1]},index=pd.DatetimeIndex([idx[5]]))
    mask=pd.Series(True,index=m.index)
    a,b=simulate(d,m,mask)
    assert a["entered"]==1 and b[0]["entry_time"]==idx[6].value and b[0]["result"]=="timeout"
    p=prices(100,1)
    d1=d.copy();d1.loc[idx[6],["low","high"]]=[p[1]-1,p[2]+1]
    a,b=simulate(d1,m,mask)
    assert b[0]["result"]=="stop" and abs(b[0]["R"]+1)<1e-9
    d1=d.copy();d1.loc[idx[6],"high"]=p[2]+1
    a,b=simulate(d1,m,mask)
    assert b[0]["result"]=="target" and abs(b[0]["R"]-2)<1e-9
    d1=segments(d.drop(idx[9]));a,b=simulate(d1,m,mask)
    assert a["unknown_exits"]==1 and a["mean_R_conservative"]<0
    d1=segments(d.drop(idx[6]));a,b=simulate(d1,m,mask)
    assert a["skips"]["missing_entry"]==1
    print("Execution tests: latency, costs, target, stop-first, missing entry and unknown exit PASS")

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset")
    a=p.parse_args();test()
    if a.selftest:return
    d=load_minutes(a.dataset)
    d=d.loc[d.index<pd.Timestamp("2024-01-01",tz="UTC")]
    m=signal_frames(d);eligible=m.atr15.notna()&(m.atr15>0)
    results={};all_records={}
    for col in ["b02","b03","b04","b05","b06"]:
        mask=m[col]&eligible
        results[col],all_records[col]=simulate(d,m,mask)
        # Random baseline matched to each model's signal count by UTC year and 4H regime.
        random=[]
        strata=pd.DataFrame({"year":m.index.year,"regime":m.trend4h.astype("string").fillna("unknown")},index=m.index)
        for seed in [101,202,303,404,505]:
            rng=np.random.default_rng(seed)
            ctrl=pd.Series(False,index=m.index)
            for _,group in strata.groupby(["year","regime"]):
                n=int(mask.loc[group.index].sum())
                pool=group.index[eligible.loc[group.index]]
                if n:ctrl.loc[rng.choice(pool,size=n,replace=False)]=True
            q,_=simulate(d,m,ctrl);random.append(q)
        results[col]["matched_B01_random"]=random
    report={"period":"2020-2023 development only","fee_each_side":FEE,"slippage_each_side":SLIPPAGE,"risk_fraction":RISK_FRACTION,"capital":CAPITAL,"latency_minutes":LATENCY,"max_minutes":HORIZON,"results":results,"limitations":"B07 absent; fixed-capital spot proxy; no funding; stop-first intrabar; no statistical validation or optimization; 5m and 15m signal decisions; unresolved exits conservatively bounded."}
    print(json.dumps(report))
    Path("lab-execution-summary.json").write_text(json.dumps(report,indent=2))
    Path("lab-execution-trades.json").write_text(json.dumps(all_records))
if __name__=="__main__":main()
