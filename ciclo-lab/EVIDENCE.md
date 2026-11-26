# CICLO LAB — Registro de evidencia y candidatos
Fecha inicial: 2026-11-26. Rama exclusiva ciclo-lab-research.
Este registro conserva hallazgos favorables y desfavorables. No son recomendaciones de inversión ni autorización de producción.
## Datos certificados
- Spot BTCUSDT 1m: 2020-01-01 a 2026-11-25 exclusivo, 3.626.467 / 3.628.800 minutos, 2.333 ausentes (incluye 8 timestamps rechazados). Run 45734087753.
- Derivados BTCUSDT 2021-2023: 1.203/1.203 archivos verificados SHA-256; 1.576.800 velas perpetuo, 1.565.280 mark, 314.746 métricas, 3.285 funding. 40.152 duplicados y 143 inválidos en métricas; 11.520 minutos mark ausentes. Run 45861953804. No se dispone de liquidaciones directas.
## Candidatos congelados, no validados
| ID | Configuración | Periodo | Operaciones | Aciertos | R neta media | PF | Capital final | R estrés | IC exploratorio estrés |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| R01 | Ridge anual 28 variables, alpha 20, score >=0.10 | 2021-23 | 24 | 70,83% | +0,111233 | 1,87824 | 10066,78 | +0,095712 | [-0,0711,+0,3237] |
| R02 | Ridge trimestral 28 variables, alpha 20, score >=0.10 | 2021-23 | 26 | no extraído | +0,097800 | 1,74888 | 10063,59 | +0,081313 | [-0,0823,+0,2799] |

R01 run 45857241202, commit eef91d13b3e18c819213bf4574b39db9a590b057; R01/R02 frequency run 45861541619, commit 8c8905bde085ed5aa848da6d7aca3fc0eb2ee00d. Riesgo 0,25% capital, spot sin apalancamiento, stop 4 ATR15, target 2R neto, timeout 240m, latencia 1m, coste normal 14bps round trip; estrés 24bps. No funding en PnL. R01: 14/24 alcanzan +1% antes de -1% durante operación según auditoría conservadora; mediana 5m entre éxitos. R02: 15/26, mediana 7m. No mide recall de todas las subidas. Muestra pequeña, intervalos incluyen cero, candidatos correlacionados y periodo de desarrollo ya inspeccionado.
## Otros hallazgos
- B03 tendencia bajista + recuperación: 185 operaciones, 54,05% aciertos, -0,00546 R, PF 0,976; estrés -0,07925 R. No supera umbrales.
- Selector de régimen v0.1: 103 operaciones, capital final 9889,63 (vs unión sin selector 1733,67), PF 0,807, drawdown cerrado 1,59%. No rentable. Run 45856292751.
- B02-B06, B08-B16: no superan criterios. No seguir optimizando B03 sin nueva hipótesis.
- Aumentar frecuencia Ridge reduciendo umbral destruye rentabilidad. 15 variantes de frecuencia: 0/15 superan gate.
## Política
Preservar 2024-25 para evaluación separada, 2026 explorado parcialmente en piloto (no holdout prístino); prueba prospectiva obligatoria. No cambiar parámetros de candidatos archivados sin nuevo ID. Registrar todo experimento, incluidos negativos. No operar dinero real ni cambiar CICLO MONITOR, alertas, Telegram o main. Los artefactos Actions caducan; este resumen y los identificadores de código quedan en Git.

## 2026-11-26 — Derivados: valor incremental (run 45862531838)
9 variantes, evaluación 2022-23, universo común, costes normal/estrés. 0/9 superan gate. Candidatos exploratorios, separados de R01/R02 (muestras no comparables directamente):
| ID | Configuración | n | R normal | PF | R estrés | IC exploratorio estrés |
|---|---|---:|---:|---:|---:|---|
| D00 | Spot matched trimestral, score >=0.10 | 11 | +0.068536 | 1.5410 | +0.042391 | [-0.2013,+0.2369] |
| D01 | Spot+derivados lag 15m, score >=0.10 | 25 | +0.037119 | 1.1784 | +0.011946 | [-0.1736,+0.2189] |
| D02 | Spot+derivados lag 30m, score >=0.10 | 29 | +0.067475 | 1.3497 | +0.040595 | [-0.1463,+0.2667] |
D02 aumenta frecuencia frente a D00, no demuestra mejora significativa. Funding predictor, no coste de financiación; publicación OI no verificada; spot proxy. Código congelado en commit 6ee4191dc3eec5f5621abb13a058709654393c9c. Mantener todos los negativos y no flexibilizar el gate.

## 2026-11-26 — Señales directas de derivados (run 45863063325)
56 replays incluidos controles. Ninguna supera gate. B19 (discount_recovery, 15/30m OI lag) conserva +0.075192 R normal, +0.052307 R estrés, PF 1.5298, 14 operaciones, 0 desconocidas, IC estrés [-0.3074,+0.3205]; ambos lags producen exactamente las mismas entradas y NO son dos pruebas independientes. Uno de cinco controles supera su media. ID D03, candidato secundario no validado, código commit 877029c4f0782c685e41e51db54a703c82e0919a. B17/B18 positivos solo a coste normal y lag 15m; B20 negativo. Funding no imputado al PnL. No evidencia de liquidaciones directas.

## 2026-11-26 — Hourly futures v0.4 (run 45864240163)
Six configurations; quarterly expanding development, 2022-23, hourly grid, 2.5 ATR1h stop, time exit, no TP, no leverage, historical funding cash flow included. 0/6 pass. Archive H01 (spot features, 4h): n=7, +0.237643 R normal, PF 7.3301, 71.43% wins, +0.158031 R stress, CI [-0.1600,+0.6732], mark fallback 0. H02 (spot+derivatives, 4h): n=23, +0.063447 R normal, PF 1.4281, 56.52% wins, +0.024251 R stress, CI [-0.2051,+0.2694], mark fallback 2. Both very small and correlated; not validated. Longer horizons negative, including 199 (12h) and 360 (24h) derivative-feature trades. Unknown PnL count zero. Code frozen commit 2c00d74575f74cfa4401f73d70883350cd4d644b. Funding reference is estimated from completed mark, with perp fallback counted; not exchange ledger. No independent data opened.

## 2026-11-26 — Gradient Boosting v0.5 (run 45864884948)
8 configs, 2022-23 development, hourly futures 4h. H01/H02 reproduced exactly. New G01 spot:boost:0.05, n=44, win 50%, mean +0.126498 R, PF 1.747782, stress +0.088647, CI [-0.049407,+0.313116], final 10139.50. G02 spot:boost:0.10, n=9, win 66.67%, mean +0.433528 R, PF 11.329226, stress +0.377132, CI [-0.067063,+1.228363], final 10097.76. G02 nested selection, NOT independent from G01. Both unknown=0; 0/8 pass, no independent validation. Boost with derivatives negative for both thresholds. Frozen code commit 1e292c2bd9c6edd7bff19fae9af8ebe8061758e9. Preserve candidates; prioritize frequency and test robustness without reoptimizing on holdout.

## 2026-11-26 — Dense grid v0.6 (run 45865211706)
6 configs; 69,863 known overlapping candidate labels per model; 0/6 pass. New preserved candidates: J01 ridge:0.05 n16, mean +0.080450, PF2.1495, stress +0.066285, CI [0.02163,0.13612]; J02 ridge:0.10 n3, mean +0.166947, PF3.2211, stress +0.154496, degenerate bootstrap (insufficient active months, NOT evidence); J03 ensemble:0.05 n42, mean +0.073213, PF1.3043, stress +0.028467, CI [-0.22724,0.29025]; J04 ensemble:0.10 n13, mean +0.334909, PF3.0917, stress +0.261450, CI [-0.19127,0.62047]. Unknown=0 all. J02 nested in J01; J04 nested in J03 at signal level. Boost 0.05 n172 almost flat normal +0.000985 but stress -0.056344; boost 0.10 negative. Spearman rank correlation ridge .1000, boost .1133, ensemble .1147; all quintiles negative after stress costs, highest quintile means -.1001, -.0924, -.0917 respectively. Descriptive only, overlapping labels. Frozen code commit 303dcbb8fc995b5cf78e68a0dd88502640919829. No holdout accessed.

## 2026-11-26 — Batch v0.7 (run 45866038855)
108 configurations, 216 cost replays, 44 positive at both cost settings, 0 pass. Includes exact repeats from v0.4-v0.6; do not sum as independent discoveries. Full permanent summaries: evidence/batch-45866038855.json. Highest-frequency both-positive: 60:expanding:ensemble:0.000 n70, +0.084248 R normal, PF1.48747, stress +0.054174, adjusted lower -0.15677, 14 active months. 15:365d:ensemble:0.050 n62, +0.068818 normal, +0.020606 stress. 60:365d:boost:0.075 n37, +0.169991 normal, +0.119688 stress. High-frequency 15:365d:ensemble:0.000 n192 normal +0.035380, stress -0.012112, PF1.15233; not accepted. No config >=150 trades profitable under stress. Multiplicity bound exploratory only; 2024-25 untouched. No production changes.

## 2026-11-26 — Two-stage v0.8 (run 45867003715)
24 configs, 48 replays, 9 positive both costs, 0 pass. Full summaries and probability audits: evidence/hurdle-45867003715.json. Primary research candidate P01 15:expanding:tree:0.05, n80, win55%, +0.146630 R, PF1.66448, capital10295.79, stress +0.098919 R, ordinary CI [-0.05398,+0.27003], adjusted lower -0.14477, 18 active months. P02 same model threshold0.10 n26, +0.252375 R, PF1.96959, stress +0.197172, CI [-0.27703,+0.65190], 11 active months. P02 correlated/nested at signal level. All eight probability models beat their fold-specific historical-rate Brier reference descriptively, not independent calibration evidence. No >=150 trades profitable under stress. No holdout accessed; no production changes.

## 2026-11-26 — Exit geometry v0.9 (run 45867520944)
54 configs, 108 cost replays, 16 positive both, 0 pass. Full summaries: evidence/exit-45867520944.json. New X01 120:1.5:hurdle_tree:0.00 n109 normal +0.092677 R, PF1.29797, stress +0.022497, adjusted lower -0.260258, all24 active months. X02 120:2.5:ensemble:0.00 n63 normal +0.081739, stress +0.053851, PF1.64378, 9 active months. P01 replicated exactly. No >=150 trades profitable under stress; no independent validation. Release protocol frozen in RELEASE_GATE.md; no production integration until all gates pass and user authorization.

## 2026-11-26 — Multi-model portfolio (run 45867984261)
Three policies, six cost replays; 0/3 pass. C01 union of P01,G01,E60,E15, n156, mean +0.076765 R, PF1.32082, win48.08%, equity10300.69, stress +0.033923, CI [-0.02848,+0.13408], adjusted lower -0.036068, active22 months, zero unknown. First both-cost positive portfolio >=150 trades in the recorded experiments, but fails adjusted confidence. C02 two votes n47, +0.102274 R, stress +0.062907, PF1.54925; C03 three votes n18, +0.165232 R, stress +0.128665, PF2.05518. No independent validation. Full summaries: evidence/portfolio-45867984261.json. Preserve no-trade constraints; do not lower release gate.
