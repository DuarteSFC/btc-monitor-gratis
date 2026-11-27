# CICLO LAB — Microstructure research track (MS)
2026-11-27. Existing indicator/model family failed deployment gates; no approved strategy.
## Stage MS0 — data feasibility before strategy design
Use actual Binance USD-M BTCUSDT aggregated trade records, not OHLCV-derived imbalance alone. Aggregated trades are executions grouped by exchange, NOT full order book, individual orders or liquidation records. Buyer-maker flag identifies inferred aggressive sell; false identifies aggressive buy.
Fixed diagnostic dates: 2022-02-15, 2022-06-15, 2023-02-15, 2023-06-15, 2026-04-15, 2026-07-15. All outside locked 2024–25. Dates are chosen as calendar samples, not from observed market outcome. No return selection or trading strategy fit in MS0.
- Download daily aggTrades ZIP + published SHA-256; verify source and inspect schema.
- Preserve event time, aggregate-ID continuity, implied trade-ID range count, price, quantity, taker side. Summarize duplicate/gap/ordering anomalies.
- Aggregate complete observed 5-second event-time bins; separate buy/sell quantity, counts, largest aggregate, price path, weighted prices. No fabricated empty bins.
- Compare each minute's aggregate volume and OHLC to certified futures klines. Report discrepancy distribution and missing minutes. Archive checksum and normalized samples. No claim of depth or exact real-time availability; exchange timestamps are not reception timestamps.
- If feasible, next design a price-response/absorption hypothesis using short-window flow, trade size distribution and price response with prior-only normalization. Fix execution and evaluation before testing; expand beyond these six diagnostic days first. No strategy significance on six days. Do not spend or unlock holdout to rescue a candidate.
- No changes to production, existing alerts, or release criteria.
