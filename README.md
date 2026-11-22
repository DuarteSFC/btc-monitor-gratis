# BTC Monitor Gratis · v1.1

**Coste cero.** Repositorio abierto con código, datos públicos e indicadores técnicos calculados automáticamente. No ejecuta trading, no accede a Quantfury, ni almacena información privada del usuario.

## Estado validado el 22/11/2026

GitHub Actions superó pruebas sintéticas y pruebas REALES del mercado:
- Spot BTC/USD en Coinbase Exchange con timestamp de operación.
- Spot BTC/USDT en OKX con timestamp de operación.
- Velas 1H / 4H / diario y cálculo RSI14, MACD12/26/9, EMA20/50/200, ATR14, volumen spot, extremos locales y niveles matemáticos de Fibonacci con anclajes y periodo mostrado.
- Funding e interés abierto de OKX SWAP (solo OKX, no un agregado global).
- ETF: último cierre completo publicado por [TFTC](https://www.tftc.io/bitcoin-etf-flows/latest.json) basado en SoSoValue; Farside dio 403 desde GitHub. Etiquetar revisiones posibles de cifras históricas.
- MVRV, realized price y SOPR fechados mediante [Bitcoin Credit Stack](https://api.bitcoincreditstack.com/v1/onchain/indicators/latest), y contraste MVRV y realized price con [Explore21](https://data.explore21.com/v1/metrics/bitcoin-mvrv-ratio/latest) (puede ser un día distinto).
- Liquidaciones BTCUSDT de ventana 24 h por [Marketlight](https://marketlight.ai/bt/api/public/liquidations/summary?symbol=BTCUSDT), cobertura Binance Futures / Bybit / OKX; respaldo [XOOMAR](https://xoomar.com/api/markets/liquidations), cobertura OKX / Gate.io / HTX; **no representa todas las liquidaciones del mercado**.
- Simulador offline de riesgo agregado Quantfury que exige saldo y posiciones actuales confirmadas y nunca afirma conocer liquidación oficial.

Las comprobaciones se ejecutan al subir cambios y cada hora mediante .github/workflows/validate.yml; GitHub puede retrasar los trabajos programados. Un job exitoso no significa señal de entrada.

## Pruebas de seguridad de datos

- Rechaza precio original sin marca temporal o con más de 60 s.
- Rechaza series OHLCV con huecos, valores imposibles o sin suficientes velas para EMA200.
- No presenta ETF, SOPR y realized price como lecturas al segundo; sus fechas son diarias.
- Rechaza liquidaciones sin fecha y periodo coherentes, y nunca mezcla cantidades de exchanges de diferente cobertura.
- Si una fuente falla, usa los respaldos disponibles. No inventa valores faltantes.
- `eligibleForEntrySignal` permanece en **false**: sin estado privado completo y actualizado de Quantfury y confirmación humana no hay señal operativa aprobada.
- Fibonacci se calcula de extremos de la ventana de lookback; NO interpreta automáticamente Elliott (es subjetivo) ni convierte niveles en órdenes.

## Cómo ejecutar las pruebas

Requiere Node.js 22:

    node test_worker.mjs
    node test_context.mjs
    node test_technical_context.mjs
    node test_risk.mjs
    node market_smoke.mjs

La última prueba realiza peticiones reales. Los tests unitarios usan fixtures simulados.

## Despliegue web e integración ChatGPT

El endpoint `/api/report` está preparado para Vercel Hobby y debe devolver datos de mercado recientes cada vez que se solicita, con `Cache-Control: no-store`; `/api/health` prueba la ejecución del servicio, no los datos de mercado. Existe además `worker.mjs` como entrada para Cloudflare Workers Free.

**Pendiente:** Vercel necesita autorización del usuario para el ámbito de su cuenta antes de crear el proyecto y publicar el endpoint. Aún no existe una URL desplegada y probada desde esta integración. Después de publicar, verificar que el navegador / lector ChatGPT realmente recibe JSON sin caché. La actualización de tareas ChatGPT no está conectada en vivo hasta demostrar esa lectura.

No insertar credenciales, nombres de usuario financiero, capturas personales ni saldos Quantfury en el repositorio. No activar servicios de pago.

## Política de riesgo

Único long BTC/USDT de ciclo y estrategias independientes de longs tácticos BTC/USD; riesgo conjunto sobre una sola cuenta QF. Nunca utilizar crédito, emergencia ni reservas de ahorro.

## Verificación externa (22/11/2026)

API Vercel Hobby publicada en https://btc-monitor-gratis.vercel.app/api/report. El job `http-endpoint-live` superó la prueba HTTP real (22/11/2026, 19:38 h Europe/Madrid; ejecución https://github.com/DuarteSFC/btc-monitor-gratis/actions/runs/45056247247): /api/health y /api/report respondieron, BTC/USD y BTC/USDT tenían marcas de operación de ~1 s, RSI/MACD/EMA/ATR y contexto ETF/on-chain/liquidaciones presentes. Cache-Control: no-store validado. LIMITACIÓN: el lector web de ChatGPT no consiguió abrir ese endpoint; su acceso desde automatizaciones sigue sin demostrarse. El despliegue Vercel fue directo y todavía NO se vinculó al repositorio de GitHub para autodesplegar cambios.
