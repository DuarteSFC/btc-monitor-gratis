"""SL01: fixed New York clock-session recovery, expanded development only."""
import argparse, json
from pathlib import Path
import pandas as pd
from market_frame import segments, bars, atr, lag
from derivative_screen import load
from hourly_futures import make_outcomes, FEES
from validation_rehearsal import replay, utc
from ca01_relative_strength import controls


def signals(b):
    b = b.copy()
    b['atr1'] = atr(b, 28) * 1.2
    prev = lag(b, 'close', 2)
    prior = lag(b, 'close', 50)
    ny = b.index.tz_convert('America/New_York')
    clock = (ny.dayofweek < 5) & (ny.hour == 10) & (ny.minute == 30)
    eligible = prev.notna() & prior.notna() & b.atr1.gt(0)
    recovery = eligible & prev.lt(prior) & b.close.gt(prev)
    return b, pd.DataFrame(dict(eligible=eligible, base=eligible & clock,
                                selected=recovery & clock), index=b.index)


def selftest():
    from validation_rehearsal import selftest as test
    test()
    i = pd.date_range('2022-03-10', periods=400, freq='30min', tz='UTC')
    b = pd.DataFrame(dict(open=100., high=101., low=99., close=100., segment=1), index=i)
    t = utc('2022-03-14 14:30')
    b.loc[t-pd.Timedelta(hours=1), 'close'] = 99.
    _, s = signals(b)
    assert s.loc[t, 'selected'] and not s.loc[t+pd.Timedelta(hours=1), 'base']
    assert s.loc[utc('2022-03-11 15:30'), 'base']
    b.loc[b.index>t, 'close'] = 200.
    _, q = signals(b)
    pd.testing.assert_frame_equal(s.loc[:t], q.loc[:t])
    print('SL01 time zone, DST and causal feature checks PASS', flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--selftest', action='store_true')
    p.add_argument('--derivatives'); p.add_argument('--extension')
    a = p.parse_args(); selftest()
    if a.selftest: return
    results = {}
    for name, root, warm, start, end in [
        ('2021-23', a.derivatives, '2021-01-01', '2021-02-01', '2024-01-01'),
        ('2026', a.extension, '2026-01-01', '2026-02-01', '2026-10-01')]:
        btc, mark, funding = [load(root, k) for k in ('perp', 'mark', 'funding')]
        assert btc.index.min() >= utc(warm) and btc.index.max() < utc(end)
        b, f = signals(bars(segments(btc.assign(quote=btc.volume*btc.close)), 30))
        f = f.loc[(f.index >= utc(start)) & (f.index < utc(end)-pd.Timedelta(days=1))]
        base, selected = f.index[f.base], f.index[f.selected]
        print('SL01_SCOPE='+json.dumps(dict(period=name, base=len(base), selected=len(selected))), flush=True)
        out = {}
        for delay in (1, 5, 15):
            shift = pd.Timedelta(minutes=delay-1)
            m = b.loc[base, ['atr1', 'segment']].copy(); m.index += shift
            out[str(delay)] = {}
            for cost, fees in FEES.items():
                y = make_outcomes(m, pd.Series(True, index=m.index), btc, mark, funding, 720, *fees)
                policies = {}
                for policy, ix in [('clock_base', base), ('SL01', selected)]:
                    r = replay(pd.Series('12h', index=ix+shift, dtype='object'), {'12h': {cost: y}}, cost, start=start, end=end)
                    policies[policy] = r
                    print('SL01_RESULT='+json.dumps(dict(period=name, delay=delay, cost=cost, policy=policy, **{k:r[k] for k in ('n','mean','pf','equity','ci','dd','unknown','years')})), flush=True)
                out[str(delay)][cost] = policies
                if delay == 1 and cost == 'stress':
                    out['controls'] = controls(base, selected, y, policies['SL01'])
        results[name] = out
    Path('lab-sl01.json').write_text(json.dumps(dict(results=results, limitations='Fixed weekday New York clock proxy, not actual exchange holiday schedule. Reused development; no independent holdout or orders.'), indent=2))


if __name__ == '__main__': main()
