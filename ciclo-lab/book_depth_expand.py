"""BD04: additional disjoint depth days, acquisition and unchanged quality audit only."""
import argparse,json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import pandas as pd
from book_depth_probe import DATES as ORIGINAL,task,selftest as probe_test
from book_depth_audit import read_day,audit,selftest as audit_test
from derivative_screen import load

DATES=[date(y,m,d) for y,months in [(2023,range(1,13)),(2026,range(2,11))] for m in months for d in (3,7,11,19,23,27)]

def selftest():
    probe_test();audit_test()
    assert len(DATES)==len(set(DATES))==126 and not set(DATES)&set(ORIGINAL)
    assert sum(d.year==2023 for d in DATES)==72
    assert sum(d.year==2026 for d in DATES)==54
    print('BD04 disjoint calendar scope PASS',flush=True)

def main():
    a=argparse.ArgumentParser();a.add_argument('--selftest',action='store_true');a.add_argument('--derivatives');a.add_argument('--extension');a.add_argument('--extra');a=a.parse_args();selftest()
    if a.selftest:return
    p=load(a.derivatives,'perp');assert p.index.max()<pd.Timestamp('2024-01-01',tz='UTC')
    recent=pd.concat([load(a.extension,'perp'),load(Path(a.extra)/'recent','perp')]).sort_index()
    assert recent.index.is_unique and recent.index.min()>=pd.Timestamp('2026-01-01',tz='UTC') and recent.index.max()<pd.Timestamp('2026-11-01',tz='UTC')
    root=Path('lab-bd04');root.mkdir(exist_ok=True)
    items=[];reports=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for item in pool.map(lambda d:task(d,root),DATES):
            items.append(item)
            if item['status']!='ok':
                r=dict(day=item['day'],admitted=False,reasons=[item['status']],fresh=0,snapshots=0)
            elif any(item[k] for k in ('invalid','duplicates','conflicts')):
                r=dict(day=item['day'],admitted=False,reasons=['invalid_source'],fresh=0,snapshots=item['snapshots'])
            else:
                try:
                    r=audit(read_day(root,item),p if item['day'].startswith('2023') else recent,item)
                except Exception as e:
                    r=dict(day=item['day'],admitted=False,reasons=['audit_error'],error=str(e),fresh=0,snapshots=item['snapshots'])
            reports.append(r)
            print('BD04_DAY='+json.dumps({k:v for k,v in r.items() if k!='bands'}),flush=True)
    summary={str(y):dict(requested=sum(r['day'].startswith(str(y)) for r in reports),verified=sum(i['day'].startswith(str(y)) and i['status']=='ok' for i in items),admitted=sum(r['day'].startswith(str(y)) and r['admitted'] for r in reports),fresh=sum(r['fresh'] for r in reports if r['day'].startswith(str(y)) and r['admitted'])) for y in (2023,2026)}
    (root/'manifest.json').write_text(json.dumps(dict(files=items,summary=summary),indent=2))
    (root/'audit.json').write_text(json.dumps(dict(days=reports,summary=summary,limitations='Quality audit only; provisional UTC; new depth dates, not global holdout.'),indent=2))
    print('BD04_SUMMARY='+json.dumps(summary),flush=True)
    if any(i['status']=='error' for i in items) or any('audit_error' in r['reasons'] for r in reports):raise SystemExit('BD04 acquisition or audit error; inspect preserved report')
if __name__=='__main__':main()
