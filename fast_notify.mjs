import {fromEvents} from "./tactical_candidate.mjs";
import {fastReport} from "./fast_tactical.mjs";
import {chooseAttention} from "./early_market.mjs";
import {readFile,writeFile,mkdir,rename} from "node:fs/promises";
const active=process.env.BTC_FAST_ALERTS==="true";
const file=".fast-state/state.json";
const token=process.env.TELEGRAM_BOT_TOKEN,chat=process.env.TELEGRAM_CHAT_ID;
const snapshot=await fastReport();
const now=Date.now();
const valid=snapshot.status.pricesFreshAndCoherent&&snapshot.status.shortIndicatorsComputed&&
  ["BTCUSD","BTCUSDT"].every(p=>{const age=now-Date.parse(snapshot.prices[p]?.data?.tradeUtc);return age>=0&&age<60000;});
if(!active){console.log(valid?"Dry run: market valid; Telegram disabled; no messages sent.":"Dry run: coverage unavailable; no messages sent.");process.exit(valid?0:1);}
if(!token||!chat){console.error("Telegram credentials not configured; alert delivery unavailable.");process.exit(1);}
let state={sent:[],lastByType:{}};
try{const x=JSON.parse(await readFile(file,"utf8"));if(Array.isArray(x.sent))state=x;}catch{}
state.lastByType=state.lastByType&&typeof state.lastByType==="object"?state.lastByType:{};
const seen=new Set(state.sent.filter(x=>typeof x==="string").slice(-500));
async function deliver(message){
 if(message.length>4096)throw Error("Telegram message too long");
 try{
  const r=await fetch("https://api.telegram.org/bot"+token+"/sendMessage",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chat_id:chat,text:message,disable_web_page_preview:true}),signal:AbortSignal.timeout(10000)});
  return r.ok&&(await r.json()).ok===true;
 }catch{return false;}
}
if(!valid){
 const previous=Number.isSafeInteger(state.coverageFailures)&&state.coverageFailures>=0?state.coverageFailures:0;
 state.coverageFailures=previous+1;
 if(state.coverageFailures>=2&&!state.coverageNoticeSent){
  state.coverageNoticeSent=await deliver("BTC · INCIDENCIA DE COBERTURA\nDos o más revisiones consecutivas sin cotizaciones e indicadores esenciales verificados. No se puede descartar un movimiento material. No es una señal de entrada.");
  if(state.coverageNoticeSent)console.log("Coverage warning accepted by Telegram API; device receipt unknown.");
  else console.error("Coverage warning delivery failed.");
 }
 await persist();
 console.error("Market coverage unavailable; consecutive failed checks: "+state.coverageFailures);
 process.exit(1);
}
if(state.coverageFailures||state.coverageNoticeSent){
 console.log("Market coverage recovered; prior failure count: "+(state.coverageFailures??0));
 state.coverageFailures=0;state.coverageNoticeSent=false;
 await persist();
}
const labels={support_loss:"Pérdida de soporte",breakout:"Ruptura alcista",sweep_recovery:"Barrido y recuperación",recovery_impulse:"Impulso de recuperación"};
const fmt=x=>Number(x).toLocaleString("es-ES",{maximumFractionDigits:2});
const localTime=x=>new Date(x).toLocaleString("es-ES",{timeZone:"Europe/Madrid",hour12:false});
const market=snapshot.prices.BTCUSDT.data.price;
const candidates=process.env.BTC_CANDIDATES_VALIDATED==="true"?fromEvents(snapshot.events,now,5,2).filter(c=>Math.abs(market-c.entry)<=0.15*(c.entry-c.stop)).map(c=>({...c,type:"candidate"})):[];
const prealerts=process.env.BTC_EARLY_PREALERTS==="true"?(snapshot.prealerts??[]).map(e=>({...e,pattern:e.type,type:"prealert"})):[];
const selected=new Map();
for(const e of prealerts.sort((a,b)=>Date.parse(b.closedUtc)-Date.parse(a.closedUtc))){const key=e.pattern;const age=now-Date.parse(e.closedUtc);const prev=state.lastByType[key];if(age<0||age>300000||seen.has(e.id)||selected.has(key))continue;if(prev&&now-prev.time<300000&&Math.abs(e.level-prev.level)/market<.002)continue;selected.set(key,e);}
const attention=chooseAttention(snapshot.earlyMarketEvents??[],snapshot.events,seen,state.lastAttention??0,now);
const recent=[...snapshot.events,...attention,...candidates,...selected.values()].filter(e=>{
 const age=now-Date.parse(e.closedUtc);
 return age>=0&&age<=(e.type==="candidate"?600000:e.type==="prealert"?300000:e.type==="early_attention"?600000:1200000)&&!seen.has(e.id);
}).sort((a,b)=>Date.parse(b.closedUtc)-Date.parse(a.closedUtc));
const header="BTC · Monitor táctico · Sin ejecución de órdenes";
const quote="BTC/USD "+fmt(snapshot.prices.BTCUSD.data.price)+" ("+snapshot.prices.BTCUSD.data.source+"; "+localTime(snapshot.prices.BTCUSD.data.tradeUtc)+")\nBTC/USDT "+fmt(market)+" ("+snapshot.prices.BTCUSDT.data.source+"; "+localTime(snapshot.prices.BTCUSDT.data.tradeUtc)+")";
function format(e){
 const time=localTime(e.closedUtc)+" · "+e.frame;
 if(e.type==="early_attention")return "BTC · ATENCIÓN TEMPRANA (movimiento observado, no entrada)\n"+time+"\n"+(e.pattern==="volume_acceleration"?"Aceleración con volumen excepcional":"Aceleración acumulada en tres minutos")+"\nNivel "+fmt(e.level)+" | cierre "+fmt(e.close)+" | volumen 1M "+fmt(e.volumeVs20)+"x | volumen 3M "+fmt(e.volume3Vs20)+"x\nFuente: "+e.source+"\nVigilar reacción 5M/15M. No perseguir ni abrir por este aviso.";
 if(e.type==="prealert")return "BTC · PREALERTA EXPERIMENTAL (no entrada)\n"+time+"\n"+({early_reversal:"Reversión temprana",sweep_recovery:"Barrido y recuperación",compression:"Compresión",continuation:"Continuación"}[e.pattern]??e.pattern)+"\nNivel de observación "+fmt(e.level)+" | invalidación estructural "+fmt(e.invalidation)+" | cierre "+fmt(e.close)+" | volumen "+fmt(e.volumeVs20)+"x\nFuente: "+e.source+"\nNo es una recomendación de compra. Vigilar confirmación del patrón; descartar si pierde la invalidación.";
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
 const sent=await deliver(message);
 if(!sent){console.error("Telegram delivery failed (credentials and response omitted).");process.exit(1);}
 for(const e of batch){seen.add(e.id);if(e.type==="early_attention")state.lastAttention=Date.parse(e.closedUtc);if(e.type==="prealert")state.lastByType[e.pattern]={time:now,level:e.level};}
 await persist();
 console.log("Material market alert sent: "+batch.length+" distinct events.");
 console.log("Telegram API accepted public event IDs: "+JSON.stringify(batch.map(e=>e.id))+"; device receipt unknown.");
}
if(!recent.length){console.log("No new material event.");await persist();}
