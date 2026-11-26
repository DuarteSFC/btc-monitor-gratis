"""Expanded retrospective family audit. No trading model fit or holdout.
Joint calendar block max-statistic tests across archived comparable portfolios.
"""
import argparse,json
from pathlib import Path
import numpy as np
from statistical_audit import load_family,month_stats,bootstrap,stat,selftest as base_test

EXTRAS=[
 ("mixed","audit-mixed/lab-mixed-portfolio.json","direct",3),
 ("known","audit-known/lab-known-trend.json","scenarios_full",9),
 ("robust","audit-robust/lab-robust-delay.json","scenarios",12),
 ("moderate","audit-moderate/lab-moderate-delay.json","scenarios_full",12),
 ("relative","audit-relative/lab-relative-delay.json","delays_full",9),
]
def extract(obj,mode):
    out={}
    for name,v in obj["results"].items():
        if mode=="direct":out[name]=v["stress"]
        else:
            group=v["scenarios"] if mode.startswith("scenarios") else v
            for delay,q in group.items():
                out[name+":"+delay]=q["stress"]["full"] if mode.endswith("_full") else q["stress"]
    return out

def selftest():
    base_test()
    r={"n":1}
    for mode,obj in [
        ("direct",{"results":{"a":{"stress":r}}}),
        ("scenarios",{"results":{"a":{"scenarios":{"1":{"stress":r}}}}}),
        ("scenarios_full",{"results":{"a":{"scenarios":{"1":{"stress":{"full":r}}}}}}),
        ("delays_full",{"results":{"a":{"1":{"stress":{"full":r}}}}})]:
        assert list(extract(obj,mode).values())==[r]
    print("Expanded archive schema and endpoint extraction PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");a=p.parse_args();selftest()
    if a.selftest:return
    q={k:v["stress"] for k,v in load_family().items()}
    assert len(q)==189
    for family,path,mode,n in EXTRAS:
        x=extract(json.loads(Path(path).read_text()),mode)
        assert len(x)==n,(family,len(x),n)
        q.update({family+":"+k:v for k,v in x.items()})
    assert len(q)==234
    stats={}
    for key,v in q.items():
        p,n,r=month_stats(v)
        assert int(n.sum())==v["n"]
        assert abs(p.sum()-(v["equity"]-10000)/10000)<1e-8
        if v["n"]>=150 and not v["unknown"] and int((n>0).sum())>=12 and p.std(ddof=1)>1e-12:stats[key]=(p,n,r)
    keys=list(stats);x=np.column_stack([stats[k][0] for k in keys]);observed=stat(x)
    results={}
    for block in [1,3,6]:
        z=bootstrap(x,block)
        results[str(block)]=dict(familyP=z["familyP"],models={k:dict(t=float(observed[i]),p=float(z["raw"][i]),adjustedP=float(z["adjusted"][i])) for i,k in enumerate(keys)})
    targets=[k for k in keys if k.startswith("known:")]
    summary=dict(total=len(q),eligible=len(keys),targets={k:{b:v["models"][k] for b,v in results.items()} for k in targets},familyP={b:v["familyP"] for b,v in results.items()})
    print("EXPANDED_STAT="+json.dumps(summary),flush=True)
    Path("lab-expanded-stat.json").write_text(json.dumps(dict(summary=summary,results=results,limitations="234 archived strategy/delay endpoints, including overlapping policies and repeats; support filter independent of PnL sign; missing earlier families and other forensic diagnostics, adaptive selection not fully accounted for. Calendar PnL t statistic, not trade R. 24 monthly blocks, circular resampling, no stationarity guarantee. Not independent validation."),indent=2))
if __name__=="__main__":main()
