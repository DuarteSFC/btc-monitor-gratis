"""BD05: frozen BD03 replication on disjoint depth days; no economic replay."""
import argparse,json
from pathlib import Path
import pandas as pd
from book_depth_predict import frame,evaluate,selftest as predictor_test
from book_depth_audit import read_day,audit
from derivative_screen import load
from book_depth_probe import DATES as ORIGINAL
from book_depth_expand import DATES as NEW


def split(original,new):
    o=sorted(k for k in original if k.startswith('2023'))
    n=sorted(k for k in new if k.startswith('2023'))
    r=sorted(k for k in new if k.startswith('2026'))
    assert len(o)==22 and len(n)==71 and len(r)==34
    assert not set(original)&set(new)
    early=[k for k in n if k<=o[10]];late=[k for k in n if k>o[10]]
    assert max(o[:11])<min(late) and max(o)<min(r)
    return o,early,late,r


def admitted(root,audit_path,expected):
    m=json.loads((root/'manifest.json').read_text());q=json.loads(audit_path.read_text())
    items={r['day']:r for r in m['files']};reports={r['day']:r for r in q['days']}
    assert len(items)==len(m['files'])==len(expected) and set(items)==set(reports)==set(expected)
    selected={k:reports[k] for k in sorted(reports) if reports[k]['admitted']}
    assert all(items[k]['status']=='ok' for k in selected)
    return items,selected


def collect(root,items,reports,keys,old,recent):
    out={}
    for day in keys:
        item=items[day];p=old if day.startswith('2023') else recent
        d=read_day(root,item);r=audit(d,p,item)
        assert r['admitted'] and r['fresh']==reports[day]['fresh']
        f,n=frame(day,d,p);assert n<=r['fresh']
        out[day]=f
        print('BD05_DAY='+json.dumps(dict(day=day,fresh=n,features=len(f),known=int(f.y.notna().sum()))),flush=True)
    return out


def selftest():
    predictor_test()
    assert len(ORIGINAL)==42 and len(NEW)==126 and not set(ORIGINAL)&set(NEW)
    print('BD05 frozen model and calendar disjointness PASS',flush=True)


def main():
    a=argparse.ArgumentParser();a.add_argument('--selftest',action='store_true');a.add_argument('--book');a.add_argument('--audit');a.add_argument('--new');a.add_argument('--derivatives');a.add_argument('--extension');a.add_argument('--extra');a=a.parse_args();selftest()
    if a.selftest:return
    book=Path(a.book);new=Path(a.new)
    oi,oa=admitted(book,Path(a.audit),[str(d) for d in ORIGINAL])
    ni,na=admitted(new,new/'audit.json',[str(d) for d in NEW])
    assert len(oa)==33 and len(na)==105
    o,early,late,r=split(oa,na)
    old=load(a.derivatives,'perp');assert old.index.max()<pd.Timestamp('2024-01-01',tz='UTC')
    recent=pd.concat([load(a.extension,'perp'),load(Path(a.extra)/'recent','perp')]).sort_index()
    assert recent.index.is_unique and recent.index.min()>=pd.Timestamp('2026-01-01',tz='UTC') and recent.index.max()<pd.Timestamp('2026-11-01',tz='UTC')
    train=collect(book,oi,oa,o,old,recent);test=collect(new,ni,na,late+r,old,recent)
    def join(frames,keys):return pd.concat([frames[k] for k in keys]).sort_index()
    result={'2023':evaluate(join(train,o[:11]),join(test,late)), '2026':evaluate(join(train,o),join(test,r))}
    scope=dict(train2023=o[:11],train2026=o,test2023=late,test2026=r,unused2023=early)
    print('BD05_SCOPE='+json.dumps(scope),flush=True)
    for name,v in result.items():print('BD05_RESULT='+json.dumps(dict(period=name,**v)),flush=True)
    passed=all(v['meanImprovement']>0 and v['ci'][0]>0 and v['models']['full']['mse']<v['models']['mean']['mse'] for v in result.values())
    Path('lab-bd05.json').write_text(json.dumps(dict(scope=scope,results=result,screenPass=passed,limitations='Frozen BD03 replication on disjoint depth days, not global independent time; assumed UTC/receipt lag; no economic evidence or orders.'),indent=2))
    print('BD05_PASS='+str(passed),flush=True)
if __name__=='__main__':main()
