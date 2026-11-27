"""Fixed executed-trade cost attribution; no rerouting, fitting or threshold changes."""
import argparse,json,tempfile
from pathlib import Path
import numpy as np
import pandas as pd
from market_frame import load_minutes,signal_frames,bars,atr,align
from derivative_screen import load
from hourly_futures import outcome,FEES,NS
from validation_rehearsal import scoped_spot,HORIZONS,utc
from extension_2026 import scope_2026
from path_risk import settlement_arrays

def components(raw_entry,raw_exit,qty,fee,slip,funding_per_unit):
    entry=raw_entry*(1+slip);out=raw_exit*(1-slip)
    gross=qty*(raw_exit-raw_entry)
    slippage=qty*((entry-raw_entry)+(raw_exit-out))
    fees=qty*fee*(entry+out);funding=qty*funding_per_unit
    return np.array([gross,slippage,fees,funding,gross-slippage-fees-funding,qty*raw_entry],float)

def audit(records,m,perp,mark,funding,cost):
    fee,slip=FEES[cost]
    t=perp.index.as_unit("ns").asi8
    v=perp[["open","high","low","close"]].to_numpy()
    sg=np.cumsum(np.r_[True,np.diff(t)!=NS])
    ft,fr,fp,fb=settlement_arrays(perp,mark,funding)
    equity=10000.;tot=np.zeros(6);rows=[]
    for r in records:
        dt=pd.Timestamp(r["time"]);h,stop=HORIZONS[r["route"]]
        atr1=float(m.at[dt,"atr1"])*stop/2.5
        et=dt.value+NS;k=int(np.searchsorted(t,et))
        q=outcome(t,v,sg,dt,0,atr1,h,fee,slip,ft,fr,fp,fb)
        assert q is not None and q["exit"]==r["exit"]
        np.testing.assert_allclose(q["R"],r["R"],rtol=1e-10,atol=1e-10)
        j=int(np.searchsorted(t,q["exit"]))-1
        entry=v[k,0]*(1+slip);stopprice=entry-2.5*atr1
        exitprice=min(v[j,0],stopprice) if q["reason"]=="stop" else v[j,3]
        risk_per_unit=q["riskFraction"]*entry*(1+fee)
        qty=min(.0025*equity,equity*q["riskFraction"])/risk_per_unit
        z=components(v[k,0],exitprice,qty,fee,slip,q["fundingR"]*risk_per_unit)
        np.testing.assert_allclose(z[4],r["pnl"],rtol=1e-10,atol=1e-10)
        equity+=z[4];tot+=z
        rows.append(dict(time=r["time"],gross=float(z[0]),slippage=float(z[1]),fees=float(z[2]),funding=float(z[3]),net=float(z[4]),entryNotional=float(z[5])))
    assert abs(equity-10000-tot[4])<1e-8
    return dict(n=len(records),gross=float(tot[0]),slippage=float(tot[1]),fees=float(tot[2]),funding=float(tot[3]),net=float(tot[4]),entryNotional=float(tot[5]),grossBps=float(tot[0]/tot[5]*10000) if tot[5]>0 else None,breakEvenBps=float((tot[0]-tot[3])/tot[5]*10000) if tot[5]>0 else None,actualTradingCostBps=float((tot[1]+tot[2])/tot[5]*10000) if tot[5]>0 else None,records=rows)

def selftest():
    from path_risk import selftest as test
    test()
    a=components(100,102,2,.001,.0005,.1)
    assert a[0]==4 and a[1]>0 and a[2]>0 and a[3]==.2
    assert abs(a[4]-(2*(102*(1-.0005)*(1-.001)-100*(1+.0005)*(1+.001)-.1)))<1e-10
    print("Fixed-fill gross/fee/slippage/funding identity PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--dataset");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    if a.selftest:return
    q=json.loads(Path("audit-rehearsal/lab-validation-rehearsal.json").read_text())
    z=json.loads(Path("audit-extension/lab-extension-2026.json").read_text())
    results={}
    for name,scope,derivatives,rows,end in [("2022-23",scoped_spot,a.derivatives,q["results"],"2024-01-01"),("2026",scope_2026,a.extension,z["results"]["1"],"2026-10-01")]:
        with tempfile.TemporaryDirectory() as tmp:
            scope(a.dataset,tmp);d=load_minutes(tmp)
        assert d.index.max()<utc(end)
        manifest=json.loads((Path(derivatives)/"manifest.json").read_text())
        assert all(f["end_exclusive"]<=end for f in manifest["files"])
        m=signal_frames(d);h=bars(d,60);h["a"]=atr(h);m["atr1"]=align(h,m,"a")
        perp,mark,funding=[load(derivatives,k) for k in ["perp","mark","funding"]]
        results[name]={}
        for cost in FEES:
            r=rows[cost];v=audit(r["records"],m,perp,mark,funding,cost)
            assert v["n"]==r["n"]
            np.testing.assert_allclose(v["net"],r["equity"]-10000,rtol=1e-10,atol=1e-10)
            results[name][cost]=v
            print("FRICTION="+json.dumps(dict(period=name,cost=cost,**{k:x for k,x in v.items() if k!="records"})),flush=True)
    Path("lab-friction.json").write_text(json.dumps(dict(results=results,limitations="Fixed original executed trades and quantities, gross at original unadjusted reference fills including stop geometry from original slippage. Accounting decomposition, not frictionless replay, not an achievable fee quote or proof of edge. Break-even bps is aggregate gross less funding per entry notional, not a quoted exchange fee. No holdout or orders."),indent=2))
if __name__=="__main__":main()
