import {fromEvents} from "./tactical_candidate.mjs";
import {fastReport} from "./fast_tactical.mjs";
import {readFile,writeFile,mkdir,rename} from "node:fs/promises";
const active=process.env.BTC_FAST_ALERTS==="true";
const file=".fast-state/state.json";
const token=process.env.TELEGRAM_BOT_TOKEN,chat=process.env.TELEGRAM_CHAT_ID;
const snapshot=await fastReport();
const now=Date.now();
const valid=snapshot.status.pricesFreshAndCoherent&&snapshot.status.shortIndicatorsComputed&&
  ["BTCUSD","BTCUSDT"].every(p=>{const age=now-Date.parse(snapshot.prices[p]?.data?.tradeUtc);return age>=0&&age<60000;});
if(!valid){console.log("No valid fresh market data; no alerts.");process.exit(0);}
if(!active){console.log("Dry run: market valid; Telegram disabled; no messages sent.");process.exit(0);}
if(!token||!chat){console.log("Telegram credentials not configured; no alerts.");process.exit(0);}
let state={sent:[],lastByType:{}};
try{const x=JSON.parse(await readFile(file,"utf8"));if(Array.isArray(x.sent))state=x;}catch{}
const seen=new Set(state.sent.filter(x=>typeof x==="string").slice(-500));
const labels={support_loss:"Pérdida de soporte",breakout:"Ruptura alcista",sweep_recovery:"Barrido y recuperación",recovery_impulse:"Impulso de recuperación"};
const fmt=x=>Number(x).toLocaleString("es-ES",{maximumFractionDigits:2});
const localTime=x=>new Date(x).toLocaleString("es-ES",{timeZone:"Europe/Madrid",hour12:false});
const market=snapshot.prices.BTCUSDT.data.price;
const candidates=process.env.BTC_CANDIDATES_VALIDATED==="true"?fromEvents(snapshot.events,now,5,2).filter(c=>Math.abs(market-c.entry)<=0.15*(c.entry-c.stop)).map(c=>({...c,type:"candidate"})):[];
const prealerts=process.env.BTC_EARLY_PREALERTS==="true"?(snapshot.prealerts??[]).map(e=>({...e,pattern:e.type,type:"prealert"})):[];
const recent=[...snapshot.events,...candidates,...prealerts].filter(e=>{
 const age=now-Date.parse(e.closedUtc);
 return age>=0&&age<=(e.type==="candidate"?600000:e.type==="prealert"?300000:1200000)&&!seen.has(e.id);
}).sort((a,b)=>Date.parse(b.closedUtc)-Date.parse(a.closedUtc));
const header="BTC · Monitor táctico · Sin ejecución de órdenes";
const quote="BTC/USD "+fmt(snapshot.prices.BTCUSD.data.price)+" ("+snapshot.prices.BTCUSD.data.source+"; "+localTime(snapshot.prices.BTCUSD.data.tradeUtc)+")\nBTC/USDT "+fmt(market)+" ("+snapshot.prices.BTCUSDT.data.source+"; "+localTime(snapshot.prices.BTCUSDT.data.tradeUtc)+")";
function format(e){
 const time=localTime(e.closedUtc)+" · "+e.frame;
 if(e.type==="prealert")return "BTC · PREALERTA EXPERIMENTAL (no entrada)\n"+time+"\n"+({early_reversal:"Reversión temprana",sweep_recovery:"Barrido y recuperación",compression:"Compresión",continuation:"Continuación"}[e.pattern]??e.pattern)+"\nNivel de observación "+fmt(e.level)+" | cierre "+fmt(e.close)+" | volumen "+fmt(e.volumeVs20)+"x\nFuente: "+e.source+"\nNo es una recomendación de compra. Evaluar estructura y riesgo; descartar si pierde el nivel.";
 if(e.type==="candidate")return "🟢 BTC · Candidato LONG táctico (hipotético)\n"+time+"\nEntrada "+fmt(e.entry)+" | Stop "+fmt(e.stop)+" | Objetivo "+fmt(e.target)+"\nB/R neto estimado "+fmt(e.rr)+":1 (costes supuestos: 0,05% comisión + 0,02% deslizamiento por lado).\nAcción: validar costes, estructura y riesgo agregado; no perseguir.";
 const age=now-Date.parse(e.closedUtc);
 const title=e.type==="support_loss"?"🔴 BTC · Pérdida de soporte":"🟡 BTC · Movimiento relevante";
 return title+"\n"+time+(age>1200000?" · RETROSPECTIVO":"")+"\n"+labels[e.type]+" · "+(e.scope==="local"?"nivel local":"estructura/impulso")+"\nNivel "+fmt(e.level)+" | cierre "+fmt(e.close)+" | volumen "+fmt(e.volumeVs20)+"x\nFuente: "+e.source+"\nAcción: "+(e.type==="support_loss"?"No abrir long sobre soporte perdido.":"Vigilar confirmación o retroceso; no entrar todavía.");
}
async function persist(){
 state.sent=[...seen].slice(-500);
 await mkdir(".fast-state",{recursive:true});await writeFile(file+".tmp",JSON.stringify(state));await rename(file+".tmp",file);
}
for(let i=0;i<recent.length;i+=6){
 const batch=recent.slice(i,i+6);
 const message=[header,...batch.map(format),quote].join("\n\n");
 if(message.length>4096)throw Error("Telegram message too long");
 let sent=false;
 try{
  const r=await fetch("https://api.telegram.org/bot"+token+"/sendMessage",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chat_id:chat,text:message,disable_web_page_preview:true}),signal:AbortSignal.timeout(10000)});
  sent=r.ok&&(await r.json()).ok===true;
 }catch{}
 if(!sent){console.error("Telegram delivery failed (credentials and response omitted).");process.exit(1);}
 for(const e of batch)seen.add(e.id);
 await persist();
 console.log("Material market alert sent: "+batch.length+" distinct events.");
}
if(!recent.length){console.log("No new material event.");await persist();}
