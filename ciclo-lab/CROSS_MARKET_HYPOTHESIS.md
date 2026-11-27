# CM01 — Divergence in spot versus perpetual aggressive flow
2026-11-27. New development hypothesis; not a rescue of MC01 and not an independent holdout.

## Economic hypothesis
Aggressive selling in BTCUSDT perpetual futures while spot is being aggressively bought and the spot price finishes a 15-minute candle in its upper half can indicate absorption of short-side pressure. This is a hypothesis, not proof of actual positioning or liquidations. Existing research tested spot taker imbalance and derivative snapshots, but not the actual perpetual kline taker-buy quantity versus contemporaneous spot taker-buy quantity.

## Fixed design
- Source: verified Binance spot and perpetual 1-minute klines, using the original perpetual archive's source SHA-256 from the certified manifest. Extract actual taker-buy base volume (column 9); cross-check timestamps and total base volume with normalized perpetual candles.
- 2022–23 development only, and Apr–Sep 2026 development replication (Jan–Mar warmup) if available. No 2024–25 strategy reads, no tuning.
- At completed 15m candles: spot signed volume ratio >= +0.10, perpetual signed volume ratio <= -0.15, positive spot candle and close in upper half. All ratios (2*taker-buy - total)/total. Require complete candles, available 4h trend, positive ATR1h.
- One long strategy, no training or threshold sweep. Entry after 1 minute (sensitivity 5 and 15), 2.5 ATR1h stop, 4h maximum hold, unchanged futures fee/slippage/funding model, 0.25% equity risk, one position at a time, no leverage.
- Compare to cash and 199 seeded random controls from eligible spot-only base conditions, matching month, 6h UTC session, trend and ATR band, preserving proposed signal counts. Report observed executed counts and unknown outcomes; conditional controls are approximate, not proof of profitable trading. Relative p-value separate from absolute adjusted confidence.
- For absolute profitability, report mean R, PF, annual results, sample support and monthly block CIs; 2026 is short and partly explored. Any apparent success stays experimental, not automatic authorization. If no useful result, archive and reject, not retune thresholds or dates.
