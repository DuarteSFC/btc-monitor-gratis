import assert from "node:assert/strict";
import {sendAlert} from "./telegram_delivery.mjs";
const response=(status,body)=>({status,ok:status===200,json:async()=>body});
async function run(seq,extras={}){
 let calls=0;const logs=[],waits=[];
 const result=await sendAlert({token:"PRIVATE_TOKEN",chat:"PRIVATE_CHAT",message:"test",
 request:async()=>{const v=seq[calls++];if(v instanceof Error)throw v;return v;},
 sleep:async n=>waits.push(n),log:x=>logs.push(x),...extras});
 assert.ok(!JSON.stringify(logs).includes("PRIVATE_"));
 return {result,calls,logs,waits};
}
const accepted=response(200,{ok:true,result:{message_id:123}});
const limit=response(429,{ok:false,error_code:429,parameters:{retry_after:2},description:"PRIVATE_TOKEN"});
const server=response(503,{ok:false,error_code:503});
const denied=response(403,{ok:false,error_code:403});
let r=await run([limit,accepted]);assert.equal(r.result.ok,true);assert.equal(r.calls,2);assert.deepEqual(r.waits,[2000]);
r=await run([server,server,accepted]);assert.equal(r.result.ok,true);assert.equal(r.calls,3);
r=await run([server,server,server]);assert.equal(r.result.reason,"retry_limit");assert.equal(r.calls,3);
r=await run([denied,accepted]);assert.equal(r.result.ok,false);assert.equal(r.calls,1);assert.equal(r.result.status,403);
r=await run([new Error("PRIVATE_TOKEN"),accepted]);assert.equal(r.result.reason,"ambiguous_network_or_response");assert.equal(r.calls,1);
r=await run([response(429,{ok:false,error_code:429,parameters:{retry_after:60}})]);assert.equal(r.result.reason,"retry_after_too_long");assert.equal(r.calls,1);
let fresh=0;r=await run([limit,accepted],{isFresh:()=>++fresh===1});assert.equal(r.result.reason,"expired_before_send");assert.equal(r.calls,1);
r=await run([accepted],{isFresh:()=>false});assert.equal(r.calls,0);
r=await run([accepted],{token:""});assert.equal(r.calls,0);
r=await run([accepted],{message:"x".repeat(4097)});assert.equal(r.calls,0);
r=await run([response(502,{unexpected:true}),accepted]);assert.equal(r.calls,1);assert.equal(r.result.ok,false);
console.log("OK: explicit 429/503 retry, retry limit, permanent rejection, ambiguous response, freshness, privacy and input checks.");
