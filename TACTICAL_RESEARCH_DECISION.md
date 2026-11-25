# Tactical retest research decision — 2026-11-25

**Rejected for operational use. Keep BTC_CANDIDATES_VALIDATED=false.**

Frozen model: closed_retest_v1, commit 45b779944962205a59ae4418e861fd1fede9a9a4, extended windows at 9c6d6482f9ffc7cfc15891a3f90ac1aa5ac17e45.

Data: OKX BTC-USDT spot, closed 5-minute candles, 15-minute aggregation, six non-overlapping 90-day windows; 155,520 candles before per-window warm-up. Entry at next open only if within 0.15 initial stop distance and net R/R >= 2; 24-bar timeout, stop-first intrabar convention; assumed 5 bps fee + 2 bps slippage each side, funding not included.

| UTC dates | Trades | Wins | Losses | Net R |
|---|---:|---:|---:|---:|
| 2025-06-03 to 2025-09-01 | 14 | 4 | 10 | -4.58293049 |
| 2025-09-01 to 2025-11-30 | 17 | 4 | 13 | -4.52272489 |
| 2025-11-30 to 2026-02-28 | 19 | 4 | 15 | -8.97280210 |
| 2026-02-28 to 2026-05-29 | 8 | 1 | 7 | -3.49867277 |
| 2026-05-29 to 2026-08-27 | 14 | 2 | 12 | -7.72536863 |
| 2026-08-27 to 2026-11-25 | 7 | 3 | 4 | -1.08848275 |
| Total | 79 | 18 | 61 | -30.39098163 |

Evidence: https://github.com/DuarteSFC/btc-monitor-gratis/actions/runs/45692378692 and https://github.com/DuarteSFC/btc-monitor-gratis/actions/runs/45692780721.

The original candidate algorithm also returned zero trades in 60 days: https://github.com/DuarteSFC/btc-monitor-gratis/actions/runs/45691454192.

These tests do not establish live execution costs or future profitability. Do not tune the model merely to improve this sample; future independent research needs a fixed hypothesis and previously unused evaluation data.

The production V2 market-event detector is independent: commit 1f7d84cfd6e930b79abc28a766a539c0da158d75, production deployment dpl_6BNou2tDCMT2GUoPSfBCAUNcugaa, successful Telegram API delivery of two distinct events and persisted IDs in run 45692384931. Preliminary market alerts are not entry signals. No live orders.
