"""Fail-closed release decision from the archived final development screen.
No market data access, no orders, no automatic approval or unlock.
"""
import argparse,json,hashlib,math
from pathlib import Path
POLICIES=["C01-known","M01-known","M01-MD01-known"]
DELAYS=[1,5,15]
COSTS=["normal","stress"]
SOURCE="evidence/known-trend-45871507129.json"
def valid(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def check(a,b):
    years=b.get("years",{})
    return {
        "150_resolved_each_cost":all(valid(q.get("n")) and q["n"]>=150 for q in [a,b]),
        "zero_unknown":all(q.get("unknown")==0 for q in [a,b]),
        "normal_mean_at_least_0.05":valid(a.get("mean")) and a["mean"]>=.05,
        "normal_pf_at_least_1.15":valid(a.get("pf")) and a["pf"]>=1.15,
        "positive_adjusted_stress_lower":valid(b.get("adjustedLower")) and b["adjustedLower"]>0,
        "12_active_months":valid(b.get("activeMonths")) and b["activeMonths"]>=12,
        "both_years_positive_30_each":set(years)=={"2022","2023"} and all(valid(v.get("n")) and v["n"]>=30 and valid(v.get("mean")) and v["mean"]>0 for v in years.values()),
    }
def assess(rows):
    expected={(p,d,c) for p in POLICIES for d in DELAYS for c in COSTS}
    index={(r["policy"],r["delay"],r["cost"]):r for r in rows}
    if len(rows)!=len(expected) or set(index)!=expected:raise ValueError("missing, duplicate or unrecognized evidence")
    out={}
    for p in POLICIES:
        scenarios={}
        for d in DELAYS:
            a,b=[index[p,d,c] for c in COSTS];tests=check(a,b)
            scenarios[str(d)]=dict(checks=tests,passed=all(tests.values()),failed=[k for k,v in tests.items() if not v])
        out[p]=dict(baselinePassed=scenarios["1"]["passed"],allDelaysPassed=all(v["passed"] for v in scenarios.values()),scenarios=scenarios)
    return out
def selftest():
    a=dict(n=150,unknown=0,mean=.05,pf=1.15)
    b=dict(n=150,unknown=0,adjustedLower=.01,activeMonths=12,years={"2022":{"n":75,"mean":.01},"2023":{"n":75,"mean":.02}})
    assert all(check(a,b).values())
    assert not check(a,dict(b,adjustedLower=0))["positive_adjusted_stress_lower"]
    assert not check(a,dict(b,unknown=1))["zero_unknown"]
    assert not check(a,dict(b,years={}))["both_years_positive_30_each"]
    try:assess([])
    except ValueError:pass
    else:raise AssertionError("accepted incomplete evidence")
    print("Release threshold boundary, missing evidence and unknown outcome guards PASS",flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");a=p.parse_args();selftest()
    if a.selftest:return
    root=Path(__file__).parent
    raw=(root/SOURCE).read_bytes();q=json.loads(raw)
    if q["run"]!=45871507129:raise ValueError("unexpected source run")
    results=assess(q["results"])
    baseline=[k for k,v in results.items() if v["baselinePassed"]]
    robust=[k for k,v in results.items() if v["allDelaysPassed"]]
    out=dict(sourceRun=q["run"],sourceSHA256=hashlib.sha256(raw).hexdigest(),policies=results,baselinePasses=baseline,allDelayPasses=robust,holdoutLocked=True,releaseAuthorized=False,limitations="Checks final three archived policies against existing numerical gates only. Adjusted confidence accounts for a local batch, not all past search. Even a numerical pass would require separate review, execution audit and explicit freeze; never unlock automatically. Actual development screens did not pass; no market data read.")
    print("GATE_DECISION="+json.dumps(out),flush=True)
    Path("lab-gate-decision.json").write_text(json.dumps(out,indent=2))
if __name__=="__main__":main()
