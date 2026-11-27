import assert from "node:assert/strict";
import {mkdtemp,copyFile,writeFile,readFile,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {spawnSync} from "node:child_process";
const dir=await mkdtemp(join(tmpdir(),"btc-notify-"));
try{
 await copyFile("fast_notify.mjs",join(dir,"fast_notify.mjs"));
 await copyFile("telegram_delivery.mjs",join(dir,"telegram_delivery.mjs"));
 await writeFile(join(dir,"tactical_candidate.mjs"),"export function fromEvents(){throw Error('unvalidated candidates must not run')}");
 await writeFile(join(dir,"fast_tactical.mjs"),`export async function fastReport(){
  const now=Date.now(),tradeUtc=new Date(now-1000).toISOString();
  const events=Array.from({length:8},(_,i)=>({id:"event"+i,frame:i%2?"5M":"15M",type:"breakout",closedUtc:new Date(now-(i===7?30:i+1)*60000).toISOString(),scope:"local",level:60000+i,close:60050+i,volumeVs20:1.9,source:"mock spot"}));
  return {status:{pricesFreshAndCoherent:true,shortIndicatorsComputed:true},prices:{BTCUSD:{data:{price:60050,source:"mock USD",tradeUtc}},BTCUSDT:{data:{price:60050,source:"mock USDT",tradeUtc}}},events};
 }`);
 await writeFile(join(dir,"mock.mjs"),`import assert from "node:assert/strict";import {appendFile} from "node:fs/promises";let calls=0;
 globalThis.fetch=async (url,opts)=>{assert.equal(url,"https://api.telegram.org/botFAKE/sendMessage");const body=JSON.parse(opts.body);assert.equal(body.chat_id,"FAKE");assert.ok(body.text.length<=4096);calls++;if(process.env.FAIL_SECOND==="true"&&calls===2)return {ok:false};await appendFile("messages.jsonl",JSON.stringify(body.text)+"\\n");return {ok:true,json:async()=>({ok:true})};};`);
 const env={...process.env,BTC_FAST_ALERTS:"true",BTC_CANDIDATES_VALIDATED:"false",BTC_EARLY_PREALERTS:"false",TELEGRAM_BOT_TOKEN:"FAKE",TELEGRAM_CHAT_ID:"FAKE"};
 const run=fail=>spawnSync(process.execPath,["--import","./mock.mjs","fast_notify.mjs"],{cwd:dir,env:{...env,FAIL_SECOND:String(fail)},encoding:"utf8"});
 const a=run(true);assert.equal(a.status,1,a.stderr);
 const b=run(false);assert.equal(b.status,0,b.stderr);
 const messages=(await readFile(join(dir,"messages.jsonl"),"utf8")).trim().split("\n").map(JSON.parse);
 assert.equal(messages.length,2);assert.ok(!messages.join("\n").includes("RETROSPECTIVO"));
 assert.equal(messages.join("\n").split("Movimiento relevante").length-1,7);
 assert.ok(!messages.join("\n").includes("Candidato LONG"));
 const c=run(false);assert.equal(c.status,0,c.stderr);assert.match(c.stdout,/No new material event/);
 assert.equal((await readFile(join(dir,"messages.jsonl"),"utf8")).trim().split("\n").length,2);
 console.log("OK: mock Telegram delivery, distinct same-type events, bounded batching, partial failure recovery, deduplication, expired event suppression, candidate gate.");
}finally{await rm(dir,{recursive:true,force:true});}
