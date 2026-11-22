# BTC Monitor Gratis

Coste objetivo: 0 €. No se conecta a Quantfury, no opera, ni requiere credenciales privadas.

## Situación actual

- El motor y pruebas están alojados en este repositorio público.
- Las pruebas sintéticas se ejecutan al publicar cambios en GitHub Actions.
- La prueba con fuentes REALES se lanza de forma programada cada hora y también manualmente en Actions. Comprobar el resultado de ejecución: no basta con tener un workflow creado.
- El motor HTTP aún no está desplegado ni conectado a las automatizaciones ChatGPT. GitHub Actions no ofrece precios al minuto al consultar ChatGPT.
- ETF, métricas on-chain y liquidaciones globales todavía requieren adaptadores específicos comprobados. Una señal operativa sigue bloqueada.

## Fuentes gratuitas

- BTC/USDT spot: OKX (A), Bitget (B), Binance (C).
- BTC/USD spot: Coinbase Exchange (A), Kraken (B), Bitfinex (C).
- Velas y volumen 1H/4H/1D: OKX (A), Bitget (B), Kraken (C).
- RSI14, MACD12/26/9, EMA20/50/200, ATR14 y pivotes calculados sobre velas cerradas.
- Funding y open interest de OKX SWAP, NO del mercado global.

Se rechazan cotizaciones con marcas temporales originales de más de 60 segundos, series con huecos y diferencias entre USD y USDT mayores al 1%. Si falta información, ninguna señal de entrada se habilita.

## Pruebas

Con Node.js 22 se puede ejecutar:

    node --check worker.mjs
    node test_worker.mjs
    node market_smoke.mjs

El primer test no usa Internet: emplea datos simulados. El tercero intenta las API reales y falla explícitamente si no se consiguen ambos precios y las tres series técnicas necesarias.

## Despliegue HTTP pendiente

En una cuenta Cloudflare Workers Free, publicar worker.mjs mediante wrangler.toml o editor del Worker. Verificar los endpoints /health y /report. La existencia de /health NO prueba el acceso al mercado; el reporte /report debe contener timestamps recientes, indicadores y status válido. El lector web de ChatGPT puede devolver datos en caché: comprobar y rechazar datos desfasados.

NUNCA subir capturas de Quantfury, balances personales, tokens de exchange o contraseñas a este repositorio público. No activar planes de pago.

## Estrategias

Un solo long de ciclo BTC/USDT y análisis independiente de longs tácticos BTC/USD. Ambas estrategias comparten margen Quantfury y exigen verificación conjunta del saldo privado aportado por el usuario antes de ampliar exposición. Nunca usar crédito ni fondo de emergencia.

## Tareas aún pendientes

1. Validar ejecución real en GitHub Actions y revisar bloqueos por proveedor.
2. Desplegar un endpoint público gratuito y comprobar lecturas nuevas extremo a extremo.
3. Incorporar ETF, on-chain y liquidaciones gratuitas con fechas y límites explícitos.
4. Demostrar que ambas automatizaciones ChatGPT pueden consultar el endpoint sin caché; hasta entonces no están integradas.
