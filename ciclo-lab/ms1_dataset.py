"""MS1: fixed calendar sample; no strategy evaluation or reserved dates."""
import argparse,json
from pathlib import Path
from datetime import date,timedelta
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from microstructure_probe import task,selftest
from derivative_screen import load

WEEKS=[f"{y}-{m:02d}-01" for y in [2022,2023] for m in [2,5,8,11]]+["2026-04-01","2026-07-01"]
DATES=[str(date.fromisoformat(w)+timedelta(days=i)) for w in WEEKS for i in range(7)]
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    assert len(DATES)==70 and len(set(DATES))==70 and all(d[:4] in ["2022","2023","2026"] for d in DATES)
    if a.selftest:return
    root=Path("lab-ms1");root.mkdir(exist_ok=True)
    old=load(a.derivatives,"perp");new=load(a.extension,"perp")
    assert old.index.max()<pd.Timestamp("2024-01-01",tz="UTC") and new.index.min()>=pd.Timestamp("2026-01-01",tz="UTC")
    perp=pd.concat([old,new]);results=[];errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[(day,pool.submit(task,day,perp,root)) for day in DATES]
        for day,f in futures:
            try:results.append(f.result())
            except Exception as e:
                errors.append(dict(day=day,error=str(e)));print("MS1_ERROR="+json.dumps(errors[-1]),flush=True)
    q=dict(weeks=WEEKS,dates=DATES,verified=len(results),aggregateExecutions=sum(x["aggregates"] for x in results),observedBins=sum(x["bins"] for x in results),results=results,errors=errors)
    (root/"manifest.json").write_text(json.dumps(q,indent=2))
    print("MS1_DATA="+json.dumps({k:v for k,v in q.items() if k not in ["results","dates"]}),flush=True)
    if errors or len(results)!=70:raise SystemExit("MS1 sample incomplete; stop")
if __name__=="__main__":main()
