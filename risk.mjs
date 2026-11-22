/**
 * Private-account math only; no persistent storage. Never infer official liquidation.
 * Supply snapshots manually from the owner at the moment of review.
 */
const f=x=>typeof x==="number"&&Number.isFinite(x);
function requireSnapshot(s){
  if(!s||!f(s.equityUsd)||s.equityUsd<=0||!f(s.markPriceUsd)||s.markPriceUsd<=0||
    !Array.isArray(s.positions)||s.positions.length<1)throw Error("Current QF equity/mark/confirmed positions required");
  for(const p of s.positions)if(!f(p.btcQuantity)||p.btcQuantity<=0||p.side!=="long"||
     p.confirmed!==true)throw Error("Require all long BTC positions confirmed and quantified");
  return s;
}
export function riskSnapshot(snapshot,{stopPriceUsd=null,slippagePct=0.01}={}){
  const s=requireSnapshot(snapshot),btc=s.positions.reduce((a,p)=>a+p.btcQuantity,0);
  const equityAt=p=>s.equityUsd+btc*(p-s.markPriceUsd);
  const breakEvenExhaustion=s.markPriceUsd-s.equityUsd/btc;
  const drawdowns=[0.1,0.2,0.3].map(d=>{
    const price=s.markPriceUsd*(1-d);
    return {dropPct:d*100,priceUsd:price,equityUsd:equityAt(price),
      newLossUsd:s.equityUsd-equityAt(price),mathematicalExhaustionBeforeLevel:price<=breakEvenExhaustion};
  });
  let stop=null;
  if(stopPriceUsd!==null){
    if(!f(stopPriceUsd)||stopPriceUsd<=0||stopPriceUsd>=s.markPriceUsd)throw Error("Stop must be below mark");
    const stressedExecution=stopPriceUsd*(1-slippagePct);
    stop={stopPriceUsd,lossIfFilledUsd:btc*(s.markPriceUsd-stopPriceUsd),
      theoreticalEquityAtStopUsd:equityAt(stopPriceUsd),
      hypotheticalAdverseFillPriceUsd:stressedExecution,
      equityAtAdverseFillUsd:equityAt(stressedExecution),
      warning:"Stops can slip or fail; Quantfury official liquidation price is not known"};
  }
  return {referenceMarkUsd:s.markPriceUsd,referenceEquityUsd:s.equityUsd,
    totalBtcExposed:btc,notionalUsd:btc*s.markPriceUsd,
    approximateZeroEquityPriceUsd:breakEvenExhaustion,
    officialLiquidationPriceUsd:null,
    approximate:true,
    scenarios:drawdowns,stop,
    warning:"Simulation assumes static BTC quantities, one directional long and equity including unrealized P&L. Excludes spreads, fees, funding, platform thresholds, slippage and future deposits. No sizing advice."
  };
}
