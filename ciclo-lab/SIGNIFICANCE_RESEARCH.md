# Targeted significance investigation — MC01
2026-11-26 — development only, after the user's request to correct the remaining significance gate.

## Hypothesis
M01-known has an observed positive mean but inadequate adjusted lower confidence bound. The existing features have many binary conditions; continuous volatility-normalized context may capture the intensity of trends, pressure and distances to recent support/resistance. Test exactly one feature-group addition, not a threshold grid.

- Reference: M01-known, fixed existing six predictors and routing priorities.
- New policy MC01: add 24 continuous features (8 each at 15m, 1h, 4h), using only completed bars and same-segment past values.
- Keep thresholds, quarterly training schedules, labels, position sizing, costs, exits and known-trend gate unchanged.
- Compare 1/5/15 minute delayed execution under normal and stress costs. Paired calendar PnL difference is descriptive.
- Assess the existing release criteria without modification. Compute block-bootstrap stress mean lower bounds at 1/3/6 months with the conservative enumerated reference count of 579; this is NOT a complete correction for all prior adaptive search.
- Expanded joint max-statistic audit includes 234 archived comparable strategy/delay endpoints (including repeated and correlated policies), before adding MC01; support screen is applied regardless of profit sign.
- Preserve negative outcomes. No threshold selection from these results. If MC01 fails, do not rescue it through arbitrary feature/threshold adjustments on this same sample. New research would require a materially different predeclared hypothesis or additional research-only data not taken from the locked holdout.
- Actual 2024–25 strategy evaluation remains locked. No production changes, no live trading.

Code: multiscale.py and expanded_stat.py. This note records the already committed experiment, not an independent preregistration of all prior research.

## 2026-11-27 — research sample extension after MC01 rejection
MC01 failed; its feature group is retired, no threshold rescue. One new replication hypothesis: M01-known fitted once with all labels available by 2024-01-01 (rolling predictor uses previous 365 days) retains its advantage in April–September 2026. Preserve original indicators, thresholds, routing, stop/timeout, sizing and costs, test delays 1/5/15 minutes. January–March 2026 is warmup only; 2026 labels never train the fixed model. This intentionally tests persistence across a long discontinuity, not normal quarterly refitting. Derivatives archive January–September 2026 must be checksum-verified; fail on missing archive files. The September pilot partially overlaps this period; it is an additional development sample, NOT pristine holdout or proof of statistical significance. 2024–25 remain excluded from parsing and evaluation. No release criteria lowered, no production or live trades. Script extension_2026.py committed c0d8190c8ba0c78311223d4d9b71dfe57da5bbb2; workflow c882e6d5e9dee27bdb5db376962299a993f176a7. Record all outcomes; no changing time bounds in response to performance.
