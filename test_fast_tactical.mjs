import assert from "node:assert/strict";
import {detectEvents,fastReport} from "./fast_tactical.mjs";
const ms=300000,now=Date.UTC(2020,10,25,18,0);
const base=Array.from({length:240},(_,i)=>({t:now-(240-i)*ms,o:60000,h:60030,l:59970,c:60000,v:10}));
const event=(patch)=>detectEvents([...base.slice(0,-1),{...base.at(-1),...patch}],"5M","mock",now);
assert.equal(event({o:59980,l:59920,h:60040,c:60030,v:20}).at(-1).type,"sweep_recovery");
assert.equal(event({o:60000,l:59990,h:60180,c:60160,v:25}).at(-1).type,"breakout");
assert.equal(event({o:60000,l:59800,h:60010,c:59820,v:25}).at(-1).type,"support_loss");
assert.equal(event({o:60000,l:59990,h:60020,c:60010,v:10}).length,0);
assert.equal(detectEvents(base.map(b=>({...b,t:b.t+ms})),"5M","mock",now).length,0);
const mock=async url=>{
  if(url.includes("market/ticker?"))return {code:"0",data:[{instId:"BTC-USDT",last:"60000",ts:String(now-1000)}]};
  if(url.includes("BTC-USD/ticker"))return {price:"60000",time:new Date(now-1000).toISOString()};
  if(url.includes("market/candles?")){
    const gran=new URL(url).searchParams.get("bar"),interval=gran==="1m"?60000:gran==="5m"?300000:gran==="15m"?900000:0;
    assert.ok(interval);
    return {code:"0",data:Array.from({length:300},(_,i)=>[String(now-(i+1)*interval),"60000","60030","59970","60000","10","0","0","1"])};
  }
  throw Error("Unexpected URL");
};
const result=await fastReport(now,mock);
assert.equal(result.status.pricesFreshAndCoherent,true);
assert.equal(result.status.shortIndicatorsComputed,true);
assert.equal(result.status.eligibleForEntrySignal,false);
assert.equal(result.timeframes["5M"].recentClosed.length,24);
assert.equal(result.timeframes["15M"].recentClosed.length,8);
const stale=await fastReport(now,async u=>u.includes("BTC-USD/ticker")?{price:"60000",time:new Date(now-120000).toISOString()}:mock(u));
assert.equal(stale.status.pricesFreshAndCoherent,false);
assert.equal(stale.events.length,0);
console.log("OK: fast market, swept levels, breakout, support loss, no entry validation, stale suppression.");

const localBase=base.map((b,i)=>i===225?{...b,h:60300,l:59700}:b);
const localBreak=detectEvents([...localBase.slice(0,-1),{...localBase.at(-1),o:60000,h:60090,l:59980,c:60080,v:20}],"5M","mock",now,0);
assert.equal(localBreak.length,1);assert.equal(localBreak[0].type,"breakout");assert.equal(localBreak[0].scope,"local");
assert.equal(detectEvents([...localBase.slice(0,-1),{...localBase.at(-1),o:60000,h:60090,l:59980,c:60080,v:10}],"5M","mock",now,0).length,0);
assert.equal(detectEvents([...localBase.slice(0,-1),{...localBase.at(-1),o:60000,h:60010,l:59900,c:59920,v:20}],"5M","mock",now,0)[0].type,"support_loss");
console.log("OK: local break, low-volume rejection, local support loss and single-close replay.");

assert.equal(result.timeframes["1M"].recentClosed.length,120);
assert.equal(result.prealerts.length,0);

assert.equal(result.version,"2.0.0");
assert.equal(result.featureVersion,"2.2.0");
assert.deepEqual(result.earlyMarketEvents,[]);
assert.deepEqual(stale.earlyMarketEvents,[]);
assert.equal(result.experimentalPrealertsEnabled,false);
assert.equal(result.experimental.classification,"research_only_not_entry");
assert.deepEqual(stale.experimental.prealerts,[]);
