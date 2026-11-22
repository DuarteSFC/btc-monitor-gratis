/**
 * Public market smoke test: no Quantfury account, no trading.
 * Run in GitHub Actions on schedule or manual trigger.
 */
import {report} from "./worker.mjs";
const r=await report();
const summary={
  generatedUtc:r.generatedUtc,
  prices:Object.fromEntries(["BTCUSD","BTCUSDT"].map(k=>[k,{source:r.prices[k].data?.source??null,
    price:r.prices[k].data?.price??null,observedUtc:r.prices[k].data?.tradeUtc??null,
    ageSeconds:r.prices[k].data?.ageSeconds??null,attempts:r.prices[k].attempts}])),
  frames:Object.fromEntries(Object.entries(r.timeframes).map(([k,v])=>[k,{
    source:v.source??null,lastCandleEndUtc:v.lastClosedEndUtc??null,
    rsi14:v.rsi14??null,macdHistogram:v.macd12_26_9?.histogram??null,
    ema200:v.ema200??null,atr14:v.atr14??null,attempts:v.attempts
  }])),
  derivatives:r.derivatives,
  etf:r.context.etf,
  onchain:r.context.onchain,
  liquidations:r.context.liquidations,
  contextCoverage:r.context.coverage,
  status:r.status
};
console.log(JSON.stringify(summary,null,2));
if(!r.status.pricesFreshAndCoherent||!r.status.technicalIndicatorsComputed||!r.status.contextComplete){
 console.error("INCOMPLETE PUBLIC DATA — NO ENTRY SIGNAL");
 process.exitCode=1;
}
