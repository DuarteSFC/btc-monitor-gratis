import assert from "node:assert/strict";
import {derivatives} from "./worker.mjs";
const now=Date.UTC(2026,10,22,19,32);
const provider=async url=>{
 if(url.includes("okx.com"))throw Error("Injected OKX outage");
 if(url.includes("bitget.com"))return {
  code:"00000",data:[{symbol:"BTCUSDT",ts:String(now-1000),
   fundingRate:"-0.000043",holdingAmount:"34938.75",markPrice:"60742.2"}]
 };
 throw Error("Unexpected");
};
const d=await derivatives(now,provider);
assert.equal(d.funding.plan,"B");
assert.equal(d.openInterest.plan,"B");
assert.equal(d.funding.rate,-0.000043);
assert.equal(d.openInterest.btc,34938.75);
assert.equal(d.openInterest.usdIsEstimate,true);
const stale=await derivatives(now,async url=>{
 if(url.includes("okx.com"))throw Error("Offline");
 return {code:"00000",data:[{symbol:"BTCUSDT",ts:String(now-600000),fundingRate:"0.01",holdingAmount:"999",markPrice:"60000"}]}
});
assert.equal(stale.funding,null);
assert.equal(stale.openInterest,null);
console.log("PASS: Derivatives Bitget fallback and stale rejection.");
