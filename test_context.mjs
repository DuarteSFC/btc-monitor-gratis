import assert from "node:assert/strict";
import {getEtf,getOnchain,getLiquidations,collectContext} from "./context.mjs";
const now=Date.UTC(2026,10,22,18,28);
const fixtures={
  etf:{updatedThrough:"2026-11-19",dateModified:"2026-11-19T22:00:00Z",
    latestSession:{date:"2026-11-19",netFlowUsd:-582193660.705,perEtfUsd:{IBIT:-541079000}}},
  mvrv:{chart_url:"https://charts.explore21.com/bitcoin-mvrv-ratio",as_of_block:976900,
    data:[{date:"2026-11-21",mvrv_ratio:1.13}]},
  realized:{chart_url:"https://charts.explore21.com/bitcoin-realized-price",as_of_block:976900,
    data:[{date:"2026-11-21",realized_price_usd:53200}]},
  credit:{date:"2026-11-21",computed_at:"2026-11-22T01:01:22Z",mvrv:"1.1313",
    realised_price_usd:"53206.92",sopr:"0.986537",sopr_7d_avg:"0.980963",mvrv_z_score:"0.2276"},
  marketlight:{fromMs:now-86400000-10000,toMs:now-10000,
    bySymbol:[{symbol:"BTCUSDT",long:1000000,short:2000000,total:3000000,
      byExchange:{"binance-futures":{long:1000000,short:2000000}}}]},
  xoomar:{updatedAt:new Date(now-30000).toISOString(),data:{
    topSymbols:[{symbol:"BTCUSDT",longUsd:100000,shortUsd:250000,totalUsd:350000}]}}
};
const requester=async(url)=>{
  if(url.includes("latest.json"))return fixtures.etf;
  if(url.includes("data.json"))return {updatedThrough:"2026-11-19",days:[fixtures.etf.latestSession]};
  if(url.includes("bitcoincreditstack"))return fixtures.credit;
  if(url.includes("mvrv-ratio"))return fixtures.mvrv;
  if(url.includes("realized-price"))return fixtures.realized;
  if(url.includes("marketlight"))return fixtures.marketlight;
  if(url.includes("xoomar"))return fixtures.xoomar;
  throw Error("unknown url "+url);
};
const etf=await getEtf(now,requester);
assert.equal(etf.data.date,"2026-11-19");
assert.equal(etf.data.netFlowUsd,-582193660.705);
const on=await getOnchain(now,requester);
assert.equal(on.data.sopr,0.986537);
assert.ok(on.crossCheck);
const liq=await getLiquidations(now,requester);
assert.equal(liq.data.source,"Marketlight");
assert.equal(liq.data.longUsd,1000000);
const all=await collectContext(now,requester);
assert.ok(Object.values(all.coverage).every(Boolean));
const staleETF=await getEtf(now,async(url)=>({updatedThrough:"2026-11-07",latestSession:{date:"2026-11-07",netFlowUsd:0},days:[{date:"2026-11-07",netFlowUsd:0}]}));
assert.equal(staleETF.data,null);
const onMissing=await getOnchain(now,async(url)=>{
  if(url.includes("bitcoincreditstack"))throw Error("offline");
  return url.includes("mvrv-ratio")?fixtures.mvrv:fixtures.realized;
});
assert.equal(onMissing.data.sopr,null);
assert.equal(onMissing.data.mvrv,1.13);
const liqBackup=await getLiquidations(now,async(url)=>{
  if(url.includes("marketlight"))throw Error("offline");
  return fixtures.xoomar;
});
assert.equal(liqBackup.data.source,"XOOMAR");
const liqStale=await getLiquidations(now,async(url)=>{
  return url.includes("marketlight")?
    {...fixtures.marketlight,toMs:now-2000000,fromMs:now-86400000-2000000}:
    {...fixtures.xoomar,updatedAt:new Date(now-2000000).toISOString()};
});
assert.equal(liqStale.data,null);
console.log("PASS: ETF settled data with date, on-chain SOPR/MVRV/realized, exchange-limited liquidations, failover and stale rejection.");
