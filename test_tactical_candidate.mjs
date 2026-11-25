import assert from "node:assert/strict";
import {candidate,fromEvents} from "./tactical_candidate.mjs";
let count=0;
for(const entry of [50000,60000,70000,80000,90000]){
 for(const [distance,multiple,feeBps,slippageBps,confirmed,expected] of [[500,4,5,2,true,true],[500,1.5,5,2,true,false],[500,2,5,2,true,false],[500,4,5,2,false,false],[0,4,5,2,true,false],[500,4,100,100,true,false]]){
 const c=candidate({entry,stop:entry-distance,target:entry+distance*multiple,feeBps,slippageBps,confirmed});
 assert.equal(Boolean(c),expected);if(c)assert.ok(c.rr>=2);count++;
 }
}
assert.equal(fromEvents([],Date.now(),5,2).length,0);
console.log(count+" synthetic risk scenarios passed (not historical trades)");
