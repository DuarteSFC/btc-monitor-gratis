"""MS0: actual aggregate-execution data feasibility. No strategy PnL."""
import argparse,csv,gzip,hashlib,io,json,math,zipfile
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from derivatives_dataset import fetch
from derivative_screen import load

DATES=["2022-02-15","2022-06-15","2023-02-15","2023-06-15","2026-04-15","2026-07-15"]
BASE="https://data.binance.vision/data/futures/um/daily/aggTrades/BTCUSDT/"
HEADER=["agg_trade_id","price","quantity","first_trade_id","last_trade_id","transact_time","is_buyer_maker"]
def parse(raw,day):
    lo=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000);hi=lo+86400000
    bins={};n=0;gaps=0;missing_ids=0;dup=0;last=None;lastid=None;lasttrade=None;trade_gap=0;overlap=0;outside=0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[x for x in z.namelist() if x.endswith(".csv")]
        if len(names)!=1:raise ValueError("unexpected archive members")
        with z.open(names[0]) as f:
            it=csv.reader(io.TextIOWrapper(f,encoding="utf-8"));head=next(it)
            if head[:7]!=HEADER:
                try:int(head[0])
                except ValueError:raise ValueError("unknown header "+str(head))
                from itertools import chain
                it=chain([head],it)
            for r in it:
                if len(r)<7:raise ValueError("short record")
                aid=int(r[0]);p=float(r[1]);q=float(r[2]);first=int(r[3]);end=int(r[4]);t=int(r[5]);side=r[6].strip().lower()
                if t>=10**14:raise ValueError("unexpected futures timestamp unit")
                if not(lo<=t<hi):outside+=1;continue
                if not math.isfinite(p) or not math.isfinite(q) or p<=0 or q<=0 or first>end or side not in ["true","false"]:raise ValueError("invalid execution")
                if lastid is not None:
                    if aid==lastid:dup+=1;raise ValueError("duplicate aggregate id")
                    if aid<lastid or t<last:raise ValueError("out-of-order aggregate execution")
                    if aid>lastid+1:gaps+=1;missing_ids+=aid-lastid-1
                    if first>lasttrade+1:trade_gap+=first-lasttrade-1
                    if first<=lasttrade:overlap+=1
                last=t;lastid=aid;lasttrade=end;n+=1
                k=t//5000*5000;buy=side=="false"
                # open high low close, qty, buy qty, aggregate count,
                # buy aggregate count, max aggregate, quote qty, implied trades
                b=bins.get(k)
                if b is None:b=[p,p,p,p,0.,0.,0,0,0.,0.,0];bins[k]=b
                b[1]=max(b[1],p);b[2]=min(b[2],p);b[3]=p;b[4]+=q;b[5]+=q if buy else 0.;b[6]+=1;b[7]+=int(buy);b[8]=max(b[8],q);b[9]+=p*q;b[10]+=end-first+1
    if not n:raise ValueError("empty execution sample")
    a=pd.DataFrame.from_dict(bins,orient="index",columns=["open","high","low","close","volume","buyVolume","aggregates","buyAggregates","maxAggregate","quoteVolume","impliedTrades"])
    a.index=pd.to_datetime(a.index,unit="ms",utc=True);a.index.name="openUtc";a=a.sort_index()
    return a,dict(day=day,aggregates=n,bins=len(a),emptyBins=17280-len(a),aggregateIdGaps=gaps,missingAggregateIds=missing_ids,impliedTradeIdGaps=trade_gap,impliedTradeIdOverlaps=overlap,duplicates=dup,outside=outside)

def compare(a,expected):
    b=a.resample("1min",closed="left",label="left").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
    b=b.loc[b.open.notna()]
    j=b.join(expected[["open","high","low","close","volume"]],how="inner",lsuffix="_agg",rsuffix="_kline")
    if len(j)==0:raise ValueError("no shared minutes")
    error=(j.volume_agg-j.volume_kline).abs()
    rel=error/j.volume_kline.where(j.volume_kline>0)
    px=np.column_stack([(j[k+"_agg"]-j[k+"_kline"]).abs().to_numpy() for k in ["open","high","low","close"]])
    return dict(sharedMinutes=len(j),missingMinutes=len(expected.index.difference(b.index)),extraMinutes=len(b.index.difference(expected.index)),volumeRelativeMedian=float(rel.median()),volumeRelativeP99=float(rel.quantile(.99)),volumeRelativeMax=float(rel.max()),volumeWithinTolerance=int((error<=1e-6*np.maximum(1,j.volume_kline)).sum()),ohlcWithinTolerance=int((px.max(axis=1)<=1e-6).sum()),archiveVolume=float(b.volume.sum()),klineVolume=float(expected.volume.sum()))

def task(day,perp,root):
    url=BASE+"BTCUSDT-aggTrades-"+day+".zip"
    expected=fetch(url+".CHECKSUM").decode().split()[0].lower()
    raw=fetch(url);sha=hashlib.sha256(raw).hexdigest()
    if sha!=expected:raise ValueError("source digest mismatch: "+day)
    a,q=parse(raw,day)
    t=pd.Timestamp(day,tz="UTC");ref=perp.loc[(perp.index>=t)&(perp.index<t+pd.Timedelta(days=1))]
    q.update(compare(a,ref),source=url,sourceSHA256=sha,sourceBytes=len(raw))
    out=root/(day+"-5s.csv.gz");a.to_csv(out,compression={"method":"gzip","mtime":0})
    q.update(file=out.name,fileSHA256=hashlib.sha256(out.read_bytes()).hexdigest())
    print("MS_DAY="+json.dumps(q),flush=True)
    return q

def selftest():
    t=int(pd.Timestamp(DATES[0],tz="UTC").value//1000000)
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w") as z:
        z.writestr("a.csv",",".join(HEADER)+"\n"+f"1,100,2,1,2,{t},false\n2,99,3,3,3,{t+1000},true\n4,101,1,5,5,{t+5000},false\n")
    a,q=parse(b.getvalue(),DATES[0])
    assert len(a)==2 and a.volume.tolist()==[5.,1.] and a.buyVolume.tolist()==[2.,1.] and q["missingAggregateIds"]==1
    ref=pd.DataFrame(dict(open=[100.],high=[101.],low=[99.],close=[101.],volume=[6.]),index=pd.to_datetime([t],unit="ms",utc=True))
    c=compare(a,ref);assert c["volumeWithinTolerance"]==1 and c["ohlcWithinTolerance"]==1
    print("MS0 execution side, event-time binning, ID gaps and kline reconciliation PASS",flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");p.add_argument("--derivatives");p.add_argument("--extension");a=p.parse_args();selftest()
    if a.selftest:return
    root=Path("lab-microstructure");root.mkdir(exist_ok=True)
    old=load(a.derivatives,"perp");new=load(a.extension,"perp")
    assert old.index.max()<pd.Timestamp("2024-01-01",tz="UTC") and new.index.min()>=pd.Timestamp("2026-01-01",tz="UTC")
    perp=pd.concat([old,new])
    result=[];errors=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[(day,pool.submit(task,day,perp,root)) for day in DATES]
        for day,f in futures:
            try:result.append(f.result())
            except Exception as e:
                errors.append(dict(day=day,error=str(e)));print("MS_ERROR="+json.dumps(errors[-1]),flush=True)
    summary=dict(dates=DATES,verified=len(result),aggregateExecutions=sum(x["aggregates"] for x in result),observedBins=sum(x["bins"] for x in result),results=result,errors=errors,limitations="Six preselected diagnostic days. Event-time aggregate records, not depth or individual orders. Missing bins not filled. No strategy evaluated or fit, no independent validation, no holdout.")
    (root/"manifest.json").write_text(json.dumps(summary,indent=2))
    print("MS_SUMMARY="+json.dumps({k:v for k,v in summary.items() if k!="results"}),flush=True)
    if errors:raise SystemExit("MS0 incomplete; no profitability conclusion")
if __name__=="__main__":main()
