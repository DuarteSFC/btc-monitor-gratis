"""MS01 technical real-data check on six MS0 diagnostic days; no PnL."""
import argparse,hashlib,json
from pathlib import Path
import pandas as pd
from derivative_screen import load
from ms01_absorption import quality,conditions,selftest
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args()
    selftest()
    if a.selftest:return
    root=Path("audit-ms0");meta=json.loads((root/"manifest.json").read_text())
    assert meta["verified"]==6 and not meta["errors"]
    old=load(a.derivatives,"perp");new=load(a.extension,"perp")
    assert old.index.max()<pd.Timestamp("2024-01-01",tz="UTC") and new.index.min()>=pd.Timestamp("2026-01-01",tz="UTC")
    perp=pd.concat([old,new]);out=[]
    for f in meta["results"]:
        day=pd.Timestamp(f["day"],tz="UTC");end=day+pd.Timedelta(days=1)
        path=root/f["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest()==f["fileSHA256"]
        x=pd.read_csv(path,compression="gzip");x.index=pd.to_datetime(x.pop("openUtc"),utc=True)
        ref=perp.loc[(perp.index>=day)&(perp.index<end)]
        good=quality(x,ref);x=x.loc[good.reindex(x.index.floor("min")).fillna(False).to_numpy()]
        x=x.reindex(pd.date_range(day,end,freq="5s",inclusive="left"));x.index+=pd.Timedelta(seconds=5)
        full=conditions(x)
        for hours in [8,12,16]:
            cut=day+pd.Timedelta(hours=hours)
            pd.testing.assert_frame_equal(full.loc[:cut],conditions(x.loc[:cut]),check_exact=False,rtol=1e-10,atol=1e-12)
        minute=full.loc[full.index.second==0]
        q=dict(day=f["day"],goodMinutes=int(good.sum()),excludedMinutes=int((~good).sum()),completeDecisions=int(minute.complete.sum()),totalDecisions=len(minute),prefixChecks=3)
        out.append(q);print("MS01_TECH="+json.dumps(q),flush=True)
    Path("lab-ms01-tech.json").write_text(json.dumps(dict(results=out,limitations="Six MS0 diagnostic days only, three prefix cuts per day; no strategy PnL, no modification of thresholds, no live publication guarantee."),indent=2))
if __name__=="__main__":main()
