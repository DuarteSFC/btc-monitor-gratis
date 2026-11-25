import {fromEvents} from "./tactical_candidate.mjs";
import {fastReport} from "./fast_tactical.mjs";
import {readFile,writeFile,mkdir} from "node:fs/promises";
const active=process.env.BTC_FAST_ALERTS==="true";
const file=".fast-state/state.json";
const token=process.env.TELEGRAM_BOT_TOKEN,chat=process.env.TELEGRAM_CHAT_ID;
const snapshot=await fastReport();
const now=Date.now();
const valid=Object.values(snapshot.prices).filter(p=>p?.data).length===2&&snapshot.status.pricesFreshAndCoherent&&snapshot.status.shortIndicatorsComputed&&
  ["BTCUSD","BTCUSDT"].every(p=>{const age=now-Date.parse(snapshot.prices[p].data.tradeUtc);return age>=0&&age<60000;});
if(!valid){console.log("No valid fresh market data; no alerts.");process.exit(0);}
if(!active){console.log("Dry run: market valid; Telegram disabled; no messages sent.");process.exit(0);}
if(!token||!chat){console.log("Telegram credentials not configured; no alerts.");process.exit(0);}
let state={sent:[],lastByType:{}};
try{const x=JSON.parse(await readFile(file,"utf8"));if(Array.isArray(x.sent)&&x.lastByType&&typeof x.lastByType==="object")state=x;}catch{}
const labels={support_loss:"Pérdida de soporte",breakout:"Ruptura alcista",sweep_recovery:"Barrido y recuperación",recovery_impulse:"Impulso de recuperación"};
const seen=new Set(state.sent.filter(x=>typeof x==="string").slice(-500));
const candidates=fromEvents(snapshot.events,now,5,2).map(c=>({...c,type:"candidate",level:c.stop,close:c.entry,source:"Costes hipotéticos: 5 + 2 puntos básicos por lado"}));
const recent=[...snapshot.events,...candidates].filter(e=>now-Date.parse(e.closedUtc)>=0&&now-Date.parse(e.closedUtc)<=7200000&&!seen.has(e.id));
const groups=new Map();
for(const e of recent.slice(0,8)){groups.set(e.id,e);}
const fmt=x=>Number(x).toLocaleString("es-ES",{maximumFractionDigits:2});
if(groups.size){
  const lines=["BTC · Aviso preliminar (no es entrada)",...Array.from(groups.values()).map(e=>e.type==="candidate"?"🟢 BTC · Candidato LONG táctico (hipotético)\nEntrada "+fmt(e.entry)+" | Stop "+fmt(e.stop)+" | Objetivo "+fmt(e.target)+" | B/R neto estimado "+fmt(e.rr)+"\n"+e.source+"\nValidar costes reales y riesgo agregado; no ejecutar automáticamente.":(e.type==="support_loss"?"🔴 BTC · Pérdida de soporte":"🟡 BTC · Movimiento relevante")+"\n"+labels[e.type]+" · "+e.frame+" · "+new Date(e.closedUtc).toLocaleString("es-ES",{timeZone:"Europe/Madrid"})+"\nNivel "+fmt(e.level)+" | cierre "+fmt(e.close)+" | volumen "+fmt(e.volumeVs20)+"x | "+e.source),"BTC/USD "+fmt(snapshot.prices.BTCUSD.data.price)+" · BTC/USDT "+fmt(snapshot.prices.BTCUSDT.data.price),"Esperar validación de estructura y riesgo. No perseguir el precio."];
  let sent=false;
  try{
    const r=await fetch("https://api.telegram.org/bot"+token+"/sendMessage",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chat_id:chat,text:lines.join("\n\n"),disable_web_page_preview:true}),signal:AbortSignal.timeout(10000)});
    sent=r.ok&&(await r.json()).ok===true;
  }catch{}
  if(!sent){console.error("Telegram delivery failed (credentials and response omitted).");process.exit(1);}
  for(const e of recent){if(groups.has(e.id)){seen.add(e.id);state.lastByType[e.type]=Math.max(state.lastByType[e.type]||0,Date.parse(e.closedUtc));}}
  console.log("Material market alert sent.");
}else console.log("No new material event.");
state.sent=[...seen].slice(-500);
await mkdir(".fast-state",{recursive:true});await writeFile(file,JSON.stringify(state));
