"""DX01: extra futures archive feasibility, never holdout or orders."""
import csv,json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import derivatives_dataset as source

SCOPES=[('early',date(2019,10,1),date(2021,1,1)),('recent',date(2026,10,1),date(2026,11,1))]
KINDS=('perp','mark','funding')

def jobs(start,end):
    out=[];d=start
    while d<end:
        nxt=source.monthnext(d)
        assert nxt<=end and (nxt<=date(2024,1,1) or d>=date(2026,1,1))
        out.extend((k,d,nxt) for k in KINDS);d=nxt
    return out

def funding_quality(root,r):
    with (root/r['file']).open() as f:
        rows=list(csv.DictReader(f))
    times=[int(x['time_ms']) for x in rows]
    hours=[int(x['interval_hours']) for x in rows]
    gaps=[(b-a)/3600000 for a,b in zip(times,times[1:])]
    return dict(settlements=len(times),intervalHours=sorted(set(hours)),maxGapHours=max(gaps,default=None),
        gapsOver8h10m=sum(g>8+1/6 for g in gaps),first=times[0],last=times[-1])

def main():
    source.selftest();assert sum(len(jobs(a,b)) for _,a,b in SCOPES)==48
    base=Path('lab-dx01');base.mkdir(exist_ok=True);summary={};unexpected=[]
    for name,start,end in SCOPES:
        root=base/name;root.mkdir(exist_ok=True)
        with ThreadPoolExecutor(max_workers=6) as pool:
            items=list(pool.map(lambda x:source.task(*x,root),jobs(start,end)))
        for r in items:
            if r['status']=='ok':
                if r['kind']=='funding':r['fundingQuality']=funding_quality(root,r)
                else:r['coverage']=r['rows']/r['expected_grid']
            elif 'HTTP Error 404' not in r.get('error',''):unexpected.append(r)
            print('DX01_SOURCE='+json.dumps(r),flush=True)
        monthly=[]
        for month in sorted(set(r['start'] for r in items)):
            group={r['kind']:r for r in items if r['start']==month}
            candidate=all(group[k]['status']=='ok' for k in KINDS) and all(group[k]['coverage']>=.95 for k in ('perp','mark'))
            monthly.append(dict(month=month,priceCoveragePass=candidate))
        report=dict(scope=name,start=str(start),end_exclusive=str(end),files=items,monthly=monthly,policy='Acquisition only; funding cadence must be audited before economic use. No holdout.')
        (root/'manifest.json').write_text(json.dumps(report,indent=2))
        summary[name]=dict(months=len(monthly),files=len(items),verified=sum(r['status']=='ok' for r in items),priceCoveragePass=sum(r['priceCoveragePass'] for r in monthly),monthly=monthly)
    (base/'summary.json').write_text(json.dumps(summary,indent=2))
    print('DX01_SUMMARY='+json.dumps(summary),flush=True)
    if unexpected:raise SystemExit('unexpected source errors; see manifest')
if __name__=='__main__':main()
