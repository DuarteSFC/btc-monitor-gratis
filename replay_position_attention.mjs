import {readFile} from "node:fs/promises";
import {featuresAt} from "./precursor_research.mjs";
import {rankFeatures,fitRanker,scoreRanker,observe,selectAlerts,chooseThreshold,summarize} from "./rank_attention.mjs";
import {flowFeatures} from "./spot_flow_features.mjs";
import {positionFeatures} from "./position_attention.mjs";
import {directionEvents,eventLabel,causalSelect,countGate,auditDirection} from "./direction_attention.mjs";
const path=process.argv[2]??"/tmp/tactical-position",ms=60000;
const trainingMonths=["2025-01","2025-02","2025-03","2025-04"],calMonth="2025-05",testMonths=["2025-10","2025-11","2025-12"],stressMonths=["2026-01","2026-02","2026-03"];
async function readMonths(months,market){
 const b=[];
 for(const m of months){
  const text=await readFile(path+"/"+market+"/"+m+".csv","utf8");
  for(const line of text.trim().split(/\r?\n/)){
   const a=line.split(",").map(Number);if(a.length!==9||a.some(v=>!Number.isFinite(v)))throw Error("bad public row");
   const [t,o,h,l,c,v,q,n,buy]=a;
   if(l<=0||h<Math.max(o,c)||l>Math.min(o,c)||v<0||q<0||n<0||!Number.isInteger(n)||buy<0||buy>q+1e-6)throw Error("invalid candle");
   if(b.length&&t-b.at(-1).t!==ms)throw Error("archive discontinuity");
   b.push({t,o,h,l,c,v,q,n,buy});
  }
 }
 return b;
}



const ts=s=>Date.parse(s+"-01T00:00:00Z");
const raw=await readFile(path+"/metrics.csv","utf8");
const metrics=new Map();
for(const line of raw.trim().split(/\r?\n/)){
 const [t,...v]=line.split(",").map(Number);
 if(!Number.isFinite(t)||t%300000||v.length!==4||!v.every(x=>Number.isFinite(x)&&x>0)||metrics.has(t))throw Error("Invalid positioning table");
 metrics.set(t,v);
}
async function dataset(months,boundaries=[]){
 const b=await readMonths(months,"spot"),events=directionEvents(b),rows=[];
 let opportunities=0;
 for(let i=180;i<b.length-35;i++){
  const t=b[i].t+ms;if(t%(5*ms)||boundaries.some(x=>t<x&&x-t<=32*ms))continue;
  const f=featuresAt(b.slice(i-60,i+1)),x=rankFeatures(b.slice(i-180,i+1),f),flow=flowFeatures(b.slice(i-60,i+1));
  if(!x||!flow)continue;
  opportunities++;
  const position=positionFeatures(metrics,t,10),position15=positionFeatures(metrics,t,15);
  if(!position||!position15)continue;
  const l=eventLabel(events,t,1);
  rows.push({t,x,flow,position,position15,y:Number(l.kind==="up")});
 }
 if(rows.length/opportunities<.9)throw Error("Less than 90 percent matched feature coverage: "+months.join(","));
 return {rows,events,opportunities,bars:b.length};
}
const dev=await dataset([...trainingMonths,calMonth],[ts(calMonth),ts("2025-06")]),hold=await dataset(testMonths),later=await dataset(stressMonths);
const train=dev.rows.filter(r=>r.t<ts(calMonth)),cal=dev.rows.filter(r=>r.t>=ts(calMonth));
const results={};
for(const name of ["volatility","spot26","position37","position37_lag15"]){
 const vec=r=>name==="position37"?[...r.x,...r.flow,...r.position]:name==="position37_lag15"?[...r.x,...r.flow,...r.position15]:[...r.x,...r.flow];
 const fit=name==="volatility"?null:fitRanker(train.map(r=>({x:vec(r),y:r.y})));
 const score=r=>fit?scoreRanker(fit,vec(r)):r.x[6];
 const scored=a=>a.map(r=>({...r,score:score(r)}));
 const gate=countGate(scored(cal),28);
 const run=(a,events)=>{
  const selected=causalSelect(scored(a),gate.threshold);
  const relevant=events.filter(e=>e.start>=a[0].t&&e.finish<=a.at(-1).t);
  return Object.fromEntries([0,1,2].map(d=>[d,auditDirection(selected,relevant,d)]));
 };
 results[name]={gate,calibration:run(cal,dev.events),hold:run(hold.rows,hold.events),later:run(later.rows,later.events)};
}
console.log(JSON.stringify({periods:{train:trainingMonths,cal:calMonth,hold:testMonths,later:stressMonths},metricRows:metrics.size,coverage:{dev:dev.rows.length/dev.opportunities,hold:hold.rows.length/hold.opportunities,later:later.rows.length/later.opportunities},rows:{train:train.length,cal:cal.length,hold:hold.rows.length,later:later.rows.length},results,notice:"Historical official USD-M metrics; only Jan 2025 through Mar 2026 selected windows before reported June 2026 timestamp change. 10/15m conservative availability lag, not proven historical publication time. All controls use same complete rows. No interpolation, no actual positions or liquidation inference. Exploratory reused windows. No live signals."},null,2));
