# BTC Monitor Gratis · análisis público de Bitcoin

**Objetivo obligatorio: 0 €**. Sin claves de trading, sin pagos, sin órdenes, sin acceso directo a Quantfury y sin publicar datos privados.

## Estado verificado a 22/11/2026

- ✅ **GitHub Actions**: tests simulados y prueba real completados contra los proveedores, según los registros de ejecución.
- ✅ **BTC/USD y BTC/USDT**: precios spot frescos y verificados con hora original de exchange.
- ✅ **Indicadores**: 1H/4H/1D, RSI14, MACD12/26/9, EMA20/50/200, ATR14, pivotes y volumen sobre velas cerradas reales.
- ✅ **Derivados**: funding + open interest de OKX SWAP (no se confunden con el conjunto de exchanges).
- ✅ **Flujos ETF**: última sesión declarada completa según TFTC/SoSoValue, con fecha, desglose por fondos e historial (Farside directo puede devolver 403 desde GitHub).
- ✅ **On-chain**: MVRV, realized price, STH cost basis y SOPR de Bitcoin Credit Stack, contrastados contra Explore21 cuando las fechas coinciden; datos diarios y rezagados identificados.
- ✅ **Liquidaciones**: Marketlight BTCUSDT por exchanges como fuente primaria y XOOMAR como respaldo, con fecha y ventana de 24 horas. Son coberturas PARCIALES, nunca mercado global y no deben sumarse por duplicado.
- ✅ **Riesgo**: `risk.mjs` simula exposición compartida y caída adicional 10/20/30 %, solo con entradas privadas del usuario EN MEMORIA. **Nunca estima la liquidación oficial**.
- 🟠 **Pendiente**: despliegue HTTP público y su verificación desde ChatGPT, integración real de endpoint HTTP en las dos automatizaciones, más verificación de saldos actuales QF antes de cualquier tamaño operativo.

## Fuente del código y pruebas

`worker.mjs` + `context.mjs` recopilan los datos de forma gratuita. `test_worker.mjs`, `test_context.mjs`, `test_risk.mjs` son pruebas con datos simulados. `market_smoke.mjs` realiza consultas reales y falla si no hay precios, indicadores o bloques públicos esenciales; GitHub Actions corre con cada push y programado cada hora. **El éxito de una ejecución no garantiza que la siguiente funcione**.

Las respuestas contienen `status.eligibleForEntrySignal=false` incluso con los datos públicos completos, porque falta confirmar el saldo actual y todas las posiciones del usuario.

## Endpoint HTTP preparado, NO desplegado

- Cloudflare Worker: `worker.mjs` y `wrangler.toml`, endpoints `/health` y `/report`.
- Vercel Hobby gratuito: `api/health.mjs`, `api/report.mjs`, `vercel.json` y `package.json`.

Ambas alternativas necesitan que la persona autorice un alojamiento gratuito. El acceso de GitHub Actions al mercado no equivale a una URL de lectura viva para ChatGPT.

## Política de fiabilidad

Las cotizaciones usan timestamps REALES de transacciones, con tolerancia ideal de 60 s; el sistema rechaza datos vencidos, velas incompletas, huecos y diferencias graves entre proveedores. Un valor no disponible es `null`, no cero.

Las fuentes ETF y on-chain son diarias y conservan la fecha del dato, aunque se consulten ahora. Las liquidaciones son por exchange/mercado y tienen ventanas de agregación, no son predicciones. Los stops no garantizan ejecución.

Las automatizaciones de ChatGPT deben permanecer separadas por estrategia: un único long BTC/USDT de ciclo y análisis táctico BTC/USD aparte, pero patrimonio y riesgo Quantfury compartidos. Sin datos privados actualizados, no se recomienda tamaño ni nueva exposición. Nunca crédito, fondo de emergencia ni ahorro protegido.

## Manual técnico

Con Node.js 22:

```sh
npm test
npm run live
```

Abrir [GitHub Actions](https://github.com/DuarteSFC/btc-monitor-gratis/actions) para comprobar ejecuciones, logs y errores.
