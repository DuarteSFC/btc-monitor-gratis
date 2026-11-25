import assert from "node:assert/strict";
import {candidate,fromEvents,fromBars} from "./tactical_candidate.mjs";
let count=0;
for(const entry of [50000,60000,70000,80000,90000]){
 for(const [distance,multiple,feeBps,slippageBps,confirmed,expected] of [[500,4,5,2,true,true],[500,1.5,5,2,true,false],[500,2,5,2,true,false],[500,4,5,2,false,false],[0,4,5,2,true,false],[500,4,100,100,true,false]]){
 const c=candidate({entry,stop:entry-distance,target:entry+distance*multiple,feeBps,slippageBps,confirmed});
 assert.equal(Boolean(c),expected);if(c)assert.ok(c.rr>=2);count++;
 }
}
assert.equal(fromEvents([],Date.now(),5,2).length,0);
console.log(count+" synthetic risk scenarios passed (not historical trades)");

const time=Date.UTC(2020,10,25,18,0);
const five=Array.from({length:300},(_,i)=>({t:time-(300-i)*300000,o:60000,h:60030,l:59970,c:60000,v:10}));
five[299]={...five[299],o:60000,h:60025,l:59995,c:60020,v:12};
const fifteen=Array.from({length:300},(_,i)=>{const c=59500+i*1.5+(i%2?8:-8);return {t:time-(300-i)*900000,o:c-3,h:c+12,l:c-12,c,v:30};});
fifteen[230]={...fifteen[230],h:60800};
const setup={id:"fixture",frame:"5M",type:"breakout",level:60000,closedUtc:new Date(time-300000).toISOString()};
const valid={five,fifteen,events:[setup],now:time};
const plans=fromBars(valid);assert.equal(plans.length,1);assert.ok(plans[0].rr>=2);assert.equal(plans[0].setupId,"fixture");
assert.equal(fromBars({...valid,events:[{...setup,closedUtc:new Date(time+300000).toISOString()}]}).length,0);
assert.equal(fromBars({...valid,events:[]}).length,0);
assert.equal(fromBars({...valid,now:time+300000}).length,0);
const future={...fifteen.at(-1),t:time,h:90000};assert.deepEqual(fromBars({...valid,fifteen:[...fifteen,future]}),plans);
console.log("OK: retest structure, historical resistance, no future data, stale and missing setup rejection.");
