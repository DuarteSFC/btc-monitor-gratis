# Tactical early-warning research: frozen checkpoints
Production V2.1 remains the factual market-event reference; do not activate research candidates or override the Telegram delivery repair.
- V2.2 raw: 281 matched earlier baseline events over two 30-day windows; approximately 16.2 minutes mean lead; not a prediction of favorable returns. Five variants failed to outperform V2.1 in favorable-window rate.
- 90-day precursor benchmark: all six research configurations negative overall under assumed 7 bps/side. Reclaim + 5M context: 53 simulated cases, -10.56 R total, most recent 16 cases +1.93 R. Preserve as a research hypothesis, not a rule.
- Structural selection: frozen six configurations, real prior extrema, net RR >=2 at assumed costs, 0/2 min delays and 60/120 min horizons.
- Ranker: observation-only, chronological 45/15/30-day split; fixed feature set, regularization, abstention if calibration sample too small, at most 3 notices/day on calibration. Report 0/1/2-minute delays and coverage of positive-window episodes; no assertion of trade expectancy.
- All reused periods are exploratory. Before activating any predictive model, freeze the selected candidate, assess on new data not used in development, check stability and delivery lag, and keep market alerts distinct from trade decisions. Do not select by best test result or publish account data.

- Structural selection completed: 1,046 setups, 275 break confirmations, 105 reclaim+5M, seven qualified hypothetical entries at 0-min delay/60m, net -3.01R. No deployment.
- Spot archive 391,680 bars: 18-variable classifier 6/20 and 51/173 positive windows at 1-minute delay; 26-variable 16/39 and 92/331. Counts differ; no consistent improvement from buy-flow. OKX recent ranker 59/293 versus V2.1 39/358; frequency drift to 9.77/day.
- Matched calibration test: all four models negative in Apr-Jun 2026 across all tested horizons/delays/cadences, no proven edge beyond volatility. Keep observation classification only as research, not entry rule.
- Utility regression follow-up: learn net return instead of positive-window classification; fixed comparison on Jul-Sep 2025 and Jul 2026 windows not used by these earlier experiments. Require positive calibration at both delays and >=25 trades before considering further validation. No live deployment.

- Net utility experiment completed: 394,560 verified bars, all four configurations failed calibration, utility18/26 negative in both held-out windows. Do not deploy.
- Independent impulse lead audit: distinguish notice received before the 5-minute impulse window from one received during it; compare ranked models against simple volatility/momentum, with delivery latency and matched calibration frequency. Research only; reused samples.

- Independent impulse lead audit completed: Apr-Jun 2026 volatility 33/174 early, 9.73m mean; rank18 32/174, 11.50m; rank26 31/174, 10.10m; momentum 4/174, 21.50m at 1m delay. No demonstrated improvement in coverage or precision over volatility. Freeze all prior learned candidates as research.
- Directional experiment: train on first future material impulse in either direction, excluding already-underway windows; two-stage event probability and conditional direction; hard 3/day causal cap on experimental attention only. Compare against previous18 and volatility with matched calibration counts, new Oct-Dec 2025 and Jan-Mar 2026 windows in this line. Do not modify production or existing alerts.
