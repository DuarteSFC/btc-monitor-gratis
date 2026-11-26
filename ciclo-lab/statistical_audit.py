"""CICLO LAB development-only joint multiple testing and stability audit.
Read existing immutable experiment artifacts; no new fit and no holdout.
"""
import argparse,json,math
from pathlib import Path
import numpy as np
import pandas as pd

MONTHS=pd.period_range("2022-01","2023-12",freq="M").astype(str)
FILES=[("batch","audit-batch/lab-batch-futures.json","models",108),("hurdle","audit-hurdle/lab-hurdle-futures.json","models",24),("exit","audit-exit/lab-exit-grid.json","models",54),("portfolio","audit-portfolio/lab-portfolio-screen.json","results",3)]
BLOCKS=[1,3,6]
NBOOT=30000
def load_family():
    allmodels={}
    for prefix,path,key,count in FILES:
        obj=json.loads(Path(path).read_text());models=obj[key]
        assert len(models)==count,(prefix,len(models))
        for name,result in models.items():
            allmodels[prefix+":"+name]=result
    return allmodels
def month_stats(q):
    f=pd.DataFrame(q["records"])
    if f.empty:return np.zeros(24),np.zeros(24),np.zeros(24)
    f["month"]=pd.to_datetime(f.time,utc=True).dt.strftime("%Y-%m")
    if not f.month.isin(MONTHS).all():raise ValueError("outside development")
    g=f.groupby("month").agg(net=("pnl","sum"),n=("R","size"),r=("R","sum")).reindex(MONTHS,fill_value=0)
    # PnL normalized to same starting capital, common calendar axis.
    return g.net.to_numpy()/10000.,g.n.to_numpy(),g.r.to_numpy()
def stat(x):
    sd=x.std(axis=0,ddof=1)
    return np.divide(x.mean(axis=0)*np.sqrt(x.shape[0]),sd,out=np.zeros_like(sd),where=sd>1e-12)
def bootstrap(x,block,nboot=NBOOT):
    # Center each strategy under a zero mean null; resample the SAME months
    # across strategies to retain cross-strategy dependence.
    n,k=x.shape;centered=x-x.mean(axis=0);observed=stat(x)
    rng=np.random.default_rng(20261126+block)
    raw=np.zeros(k);adj=np.zeros(k);max_stats=[]
    for start in range(0,nboot,250):
        count=min(250,nboot-start)
        starts=rng.integers(0,n,size=(count,math.ceil(n/block)))
        idx=((starts[:,:,None]+np.arange(block))%n).reshape(count,-1)[:,:n]
        z=centered[idx];sd=z.std(axis=1,ddof=1)
        v=np.divide(z.mean(axis=1)*np.sqrt(n),sd,out=np.zeros_like(sd),where=sd>1e-12)
        mx=v.max(axis=1)
        raw+=(v>=observed[None,:]).sum(axis=0)
        adj+=(mx[:,None]>=observed[None,:]).sum(axis=0)
        max_stats.extend(mx.tolist())
    return dict(raw=(raw+1)/(nboot+1),adjusted=(adj+1)/(nboot+1),critical=float(np.quantile(max_stats,.95)),familyP=float((1+np.sum(np.array(max_stats)>=observed.max()))/(nboot+1)))
def selftest():
    rng=np.random.default_rng(1)
    x=rng.normal(size=(24,4));x[:,1]=x[:,0]
    a=bootstrap(x,3,1000)
    assert np.all(a["adjusted"]>=a["raw"]) and a["adjusted"][0]==a["adjusted"][1]
    assert np.isfinite(a["familyP"])
    q={"records":[{"time":"2022-02-01T00:00:00Z","pnl":100,"R":1}]}
    p,n,r=month_stats(q);assert p[1]==.01 and n.sum()==1 and r.sum()==1
    print("Joint bootstrap dependence, multiplicity ordering and calendar parity PASS",flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("--selftest",action="store_true");a=p.parse_args();selftest()
    if a.selftest:return
    models=load_family();stats={}
    for key,v in models.items():
        q=v["stress"];p,n,r=month_stats(q)
        if int(n.sum())!=q["n"]:raise ValueError("trade count mismatch")
        if abs(p.sum()-(q["equity"]-10000)/10000)>1e-8:raise ValueError("equity mismatch")
        # No model eligibility based on observed profitability. Require calendar
        # support to avoid degenerate t statistics; sparse variants not tested.
        if q["n"]>=150 and not q["unknown"] and int((n>0).sum())>=12 and p.std(ddof=1)>1e-12:
            stats[key]=(p,n,r)
    key="portfolio:union";assert key in stats
    keys=list(stats);x=np.column_stack([stats[k][0] for k in keys]);observed=stat(x)
    results={}
    for b in BLOCKS:
        z=bootstrap(x,b)
        results[str(b)]=dict(familyP=z["familyP"],critical=z["critical"],models={k:dict(t=float(observed[i]),p=float(z["raw"][i]),adjustedP=float(z["adjusted"][i])) for i,k in enumerate(keys)})
    p,n,r=stats[key];loo=[float((r.sum()-r[i])/(n.sum()-n[i])) for i in range(24) if n.sum()>n[i]]
    good=np.argsort(p)[-3:]
    stability=dict(n=int(n.sum()),activeMonths=int((n>0).sum()),positiveMonths=int((p>0).sum()),negativeMonths=int((p<0).sum()),totalReturn=float(p.sum()),meanR=float(r.sum()/n.sum()),withoutBest3MonthsReturn=float(p.sum()-p[good].sum()),best3Months=[str(MONTHS[i]) for i in good],leaveOneMonthMinR=min(loo),leaveOneMonthMaxR=max(loo),years={str(y):dict(n=int(n[i:i+12].sum()),meanR=float(r[i:i+12].sum()/n[i:i+12].sum()),returnFraction=float(p[i:i+12].sum())) for y,i in [(2022,0),(2023,12)]},monthly=[dict(month=str(MONTHS[i]),trades=int(n[i]),returnFraction=float(p[i]),netR=float(r[i])) for i in range(24)])
    report=dict(totalConfigurations=len(models),eligible=len(keys),candidate=key,stability=stability,bootstrap=results,limitations="Retrospective partial family (189 configs, including duplicates), support-filtered; prior experimentation and data-adaptive choice not fully corrected. Centered circular monthly block bootstrap approximates dependence, only 24 months; no stationarity guarantee. Tests mean calendar PnL not mean trade R; no independent holdout; no causal claim.")
    Path("lab-statistical-audit.json").write_text(json.dumps(report,indent=2))
    print("STAT_AUDIT="+json.dumps(dict(total=len(models),eligible=len(keys),candidate=key,stability=stability,bootstrap={b:dict(familyP=v["familyP"],candidate=v["models"][key]) for b,v in results.items()})),flush=True)
if __name__=="__main__":main()
