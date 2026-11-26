# CICLO LAB — Release gate (research only)

2026-11-26. No integration into CICLO MONITOR until all applicable gates pass.
This protocol is a prospective commitment for the next experiment, not evidence that prior results are valid.

## 1. Development
- 2020–23 spot, 2021–23 derivatives. Multiple comparisons and overlapping labels are acknowledged.
- Preserve all positive and negative outcomes, code hashes, execution assumptions and data checksums.
- Select at most one final trading policy (including any ensemble, thresholds and retraining schedule) after the currently launched exit-grid and portfolio screens complete.
- Require >=150 resolved non-overlapping portfolio trades under both cost scenarios, zero unknown outcomes, normal mean >=0.05 R, normal PF >=1.15, positive adjusted lower bound of stress mean, >=12 active months, and both evaluation years positive with >=30 stress trades each.
- If none passes, development fails. Do not select a winner purely by maximum observed mean or PF, and do not open the holdout merely to rescue a failed candidate.
- Audit execution parity and data availability. In particular check actual funding settlement accounting, mark fallback, intraminute stop ordering, missing outcomes, timestamp cutoffs, and chronological feature availability. OI release delay is assumed, not verified; prospective feed timestamps must establish actual latency.

## 2. Locked historical evaluation
- Before evaluating: commit exact candidate, code/data hashes, model features, costs, decision schedule, stop/exit, sizing, data exclusions, and all acceptance rules.
- 2024–25 not used for development decisions. Acquire verified futures, mark, funding and metrics archives for that period only after candidate freeze; no inspecting performance or tuning on these years.
- Walk forward only per frozen retraining schedule. Training labels must be fully observable before each refit. Preserve warmup and history from earlier years.
- Same execution and funding assumptions; normal and stress costs. Report full portfolio return, closed and intratrade drawdown, trade counts, missing data, monthly and yearly breakdown, and comparison with cash and a matched time/regime/volatility control.
- Require >=150 resolved trades under both costs, zero unknown outcomes, positive mean after stress costs with a positive one-sided 95% block-based lower bound, normal PF >=1.15, both calendar years positive after stress costs. Report uncertainty due to limited blocks; if insufficient evidence, fail/inconclusive, not approval. An independent holdout failure cannot be repaired by retuning on that holdout.
- 2026 already partially explored; not a pristine independent validation period.

## 3. Prospective simulation, not production
- Freeze code and model, record timestamped quotes, data provenance, signal, intended entry and actual simulated fill. Record no-trade decisions, fees, slippage and funding.
- At least 90 calendar days AND 50 resolved non-overlapping paper trades; no fixed completion date. Require positive after observed costs and no critical execution/latency faults. Report uncertainty; this is a minimum operational test, not a guarantee of statistical power.
- Risk controls: no real orders, no leverage in this test, risk budget 0.25% simulated equity per trade, one open position, fail closed for stale/missing data. Kill switch and rollback test before any deployment.
- No changes to existing cycle and tactical alerts, Telegram, production API, or main. Any later CICLO integration requires separate user authorization after review. No automatic money trading.

## Status
Currently no candidate has passed development; exit-grid run 45867520944 and portfolio screen are pending. This gate intentionally does not promise that a profitable strategy exists or a date of completion.
