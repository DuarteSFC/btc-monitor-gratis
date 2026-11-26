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
