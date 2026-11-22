import assert from "node:assert/strict";
import {riskSnapshot} from "./risk.mjs";
const r=riskSnapshot({equityUsd:3600,markPriceUsd:60000,
 positions:[{confirmed:true,side:"long",btcQuantity:0.2},{confirmed:true,side:"long",btcQuantity:0.05}]},{stopPriceUsd:57000});
assert.equal(r.totalBtcExposed,0.25);
assert.equal(r.notionalUsd,15000);
assert.equal(r.approximateZeroEquityPriceUsd,45600);
assert.equal(r.scenarios[0].newLossUsd,1500);
assert.equal(r.scenarios[1].equityUsd,600);
assert.equal(r.scenarios[2].mathematicalExhaustionBeforeLevel,true);
assert.equal(r.stop.lossIfFilledUsd,750);
assert.equal(r.officialLiquidationPriceUsd,null);
assert.throws(()=>riskSnapshot({equityUsd:3600,markPriceUsd:60000,positions:[]}));
assert.throws(()=>riskSnapshot({equityUsd:3600,markPriceUsd:60000,
 positions:[{side:"long",btcQuantity:0.2}]}));
console.log("PASS: private QF stress-test mathematics with no persisted balances and no official liquidation guess.");
