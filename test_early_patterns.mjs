import assert from "node:assert/strict";
import {earlyPatterns} from "./early_patterns.mjs";
const base=Array.from({length:40},(_,i)=>({t:i*60000,o:100,h:101,l:99,c:100,v:10}));
assert.deepEqual(earlyPatterns(base),[]);
const sweep=[...base.slice(0,-1),{...base.at(-1),o:98,l:97,h:101,c:100.5,v:20}];
assert.ok(earlyPatterns(sweep).some(e=>e.type==="sweep_recovery"));
assert.deepEqual(earlyPatterns(sweep.map((b,i)=>i===39?{...b,t:b.t+60000}:b)),[]);
assert.deepEqual(earlyPatterns(base.slice(0,20)),[]);
console.log("Early pattern smoke tests passed");
