import assert from "node:assert/strict";
import {validatePrice,price,report,ema,rsi,macd,atr} from "./worker.mjs";
const now=Date.UTC(2026,10,22,17,30);
assert.equal(validatePrice({price:60000,time:now-1000},now).ok,true);
assert.equal(validatePrice({price:60000,time:now-90000},now).ok,false);
assert.equal(validatePrice({price:60000,time:now+15000},now).ok,false);
assert.equal(ema(Array(210).fill(100),20).at(-1),100);
assert.equal(rsi(Array.from({length:40},(_,i)=>i)),100);
assert.equal(rsi(Array.from({length:40},(_,i)=>-i)),0);
assert.ok(Number.isFinite(macd(Array.from({length:60},(_,i)=>i)).histogram));
function bars(frame){
  const ms={"1H":3600000,"4H":14400000,"1Dutc":86400000}[frame];
  const last=Math.floor((now-ms)/ms)*ms;
  return Array.from({length:300},(_,i)=>{
    const t=last-i*ms,v=61000-i*8;
    return [String(t),String(v-5),String(v+70),String(v-70),String(v),"4","0","0","1"];
  });
}
const mock=async url=>{
  if(url.includes("market/ticker?"))return {code:"0",data:[{instId:"BTC-USDT",last:"60997",ts:String(now-2000)}]};
  if(url.includes("BTC-USD/ticker"))return {price:"61000",time:new Date(now-2500).toISOString()};
  if(url.includes("market/candles?"))return {code:"0",data:bars(new URL(url).searchParams.get("bar"))};
  if(url.includes("funding-rate?"))return {code:"0",data:[{fundingRate:"0.00001",fundingTime:String(now+1200000)}]};
  if(url.includes("open-interest?"))return {code:"0",data:[{ts:String(now-3000),oi:"1000",oiCcy:"100",oiUsd:"6100000"}]};
  throw Error("Unexpected URL "+url);
};
const x=await report(now,mock);
assert.equal(x.status.pricesFreshAndCoherent,true);
assert.equal(x.status.technicalIndicatorsComputed,true);
assert.equal(x.status.eligibleForEntrySignal,false);
assert.ok(x.timeframes["1H"].rsi14>=0);
assert.ok(x.timeframes["4H"].atr14>0);
assert.ok(x.timeframes["1D"].ema200>0);
assert.equal(x.prices.BTCUSD.data.plan,"A");
assert.ok(x.derivatives.openInterest.usd>0);
const failover=await price("BTCUSDT",now,async url=>{
 if(url.includes("okx.com"))throw Error("temporary outage");
 if(url.includes("bitget.com"))return {data:[{symbol:"BTCUSDT",lastPr:"60999",ts:String(now-3000)}]};
 throw Error("offline");
});
assert.equal(failover.data.plan,"B");
const fail=await price("BTCUSD",now,async()=>{throw Error("offline")});
assert.equal(fail.data,null);
assert.equal(fail.attempts.length,3);
console.log("OK: price freshness, fallback A/B/C, complete 1H/4H/1D, RSI, MACD, EMA, ATR and trade gate disabled without QF.");
console.log("These are MOCK tests. Live API access is tested separately.");
