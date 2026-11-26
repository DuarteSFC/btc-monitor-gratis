"""CICLO LAB: descriptive sample-size sensitivity, not a significance test.
No new model selection, no holdout, no live trading.
"""
import argparse,json,math
from pathlib import Path
import numpy as np
import pandas as pd
MONTHS=pd.period_range("2022-01","2023-12",freq="M").astype(str)
def audit(q):
    f=pd.DataFrame(q["records"]);f["month"]=pd.to_datetime(f.time,utc=True).dt.strftime("%Y-%m")
    b=f.groupby("month").agg(net=("pnl","sum"),n=("R","size")).reindex(MONTHS,fill_value=0)
    x=b.net.to_numpy()/10000
    assert b.n.sum()==q["n"] and abs(x.sum()-(q["equity"]-10000)/10000)<1e-8
    out=[]
    # Compare independent calendar months vs non-overlapping quarterly and
    # half-year aggregates. Stationarity and independence are assumptions.
    for block in [1,3,6]:
        z=x.reshape(-1,block).sum(axis=1)
        mu=float(z.mean());sd=float(z.std(ddof=1));effect=mu/sd if sd>0 else None
        # Normal-approx one-sided alpha .05, power .8; optimistic no search penalty.
        needs={}
        for shrink in [1.,.5]:
            needs[str(shrink)]=int(math.ceil(((1.6448536269514722+.8416212335729143)/(effect*shrink))**2))*block if effect is not None and effect>0 else None
        out.append(dict(blockMonths=block,observedBlocks=len(z),mean=mu,sd=sd,effect=effect,illustrativeTotalMonths=needs))
    return dict(n=q["n"],monthlyMean=float(x.mean()),totalReturn=float(x.sum()),positiveMonths=int((x>0).sum()),blocks=out,unknown=q["unknown"])
def selftest():
    q={"records":[{"time":"2022-01-01T00:00:00Z","pnl":100,"R":1},{"time":"2022-02-01T00:00:00Z","pnl":-50,"R":-.5}],"n":2,"equity":10050,"unknown":0}
    a=audit(q);assert abs(a["totalReturn"]-.005)<1e-12 and len(a["blocks"])==3
    print("Calendar accounting and sample-size sensitivity PASS",flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");a=p.parse_args();selftest()
    if a.selftest:return
    g=json.loads(Path("audit-feature/lab-feature-audit.json").read_text())["results"]
    m=json.loads(Path("audit-moderate/lab-moderate-delay.json").read_text())["results"]["365d:0.000"]["scenarios"]
    q={"C01-known":g["C01"]["diagnostics"]["known_trend"]["stress"],"M01-known":g["M01"]["diagnostics"]["known_trend"]["stress"]}
    q.update({"MD01-"+str(i)+"m":m[str(i)]["stress"]["full"] for i in [1,5,15]})
    results={k:audit(v) for k,v in q.items()}
    for k,v in results.items():print("SUPPORT="+json.dumps(dict(policy=k,**v)),flush=True)
    Path("lab-support-audit.json").write_text(json.dumps(dict(results=results,limitations="Illustrative normal approximation for total sample size with 80% power, one-sided 5% alpha, unadjusted. Nonoverlapping calendar aggregates assumed IID/stationary, with only 24/8/4 observed blocks; estimated effects highly uncertain and selection-biased. Not forecast, not minimum number of live months, not release criterion, not an instruction to trade or extend historical search."),indent=2))
if __name__=="__main__":main()
