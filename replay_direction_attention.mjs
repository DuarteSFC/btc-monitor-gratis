import {readFile} from "node:fs/promises";
import {featuresAt} from "./precursor_research.mjs";
import {rankFeatures,fitRanker,scoreRanker,observe,selectAlerts,chooseThreshold,summarize} from "./rank_attention.mjs";
import {flowFeatures} from "./spot_flow_features.mjs";
import {directionEvents,eventLabel,causalSelect,countGate,auditDirection} from "./direction_attention.mjs";
const path=process.argv[2]??"/tmp/tactical-flow",ms=60000;
const trainingMonths=["2025-01","2025-02","2025-03","2025-04"],calMonth="2025-05",testMonths=["2025-10","2025-11","2025-12"],stressMonths=["2026-01","2026-02","2026-03"];
async function readMonths(months){
 const b=[];
 for(const m of months){
  const text=await readFile(path+"/"+m+".csv","utf8");
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
function dataset(b,boundaries=[]){
 const events=directionEvents(b),rows=[];
 for(let i=180;i<b.length-35;i++){
  const t=b[i].t+ms;if(t%(5*ms)||boundaries.some(x=>t<x&&x-t<=32*ms))continue;
  const f=featuresAt(b.slice(i-60,i+1)),x=rankFeatures(b.slice(i-180,i+1),f),flow=flowFeatures(b.slice(i-60,i+1));
  if(!x||!flow)continue;
  const l=eventLabel(events,t,1);
  rows.push({t,x,flow,y:Number(l.kind==="up"),direction:l.kind,oldY:Number(observe(b,i,1)==="up")});
 }
 return {rows,events};
}
const dev=dataset(await readMonths([...trainingMonths,calMonth]),[ts(calMonth),ts("2025-06")]);
const hold=dataset(await readMonths(testMonths)),later=dataset(await readMonths(stressMonths));
const train=dev.rows.filter(r=>r.t<ts(calMonth)),cal=dev.rows.filter(r=>r.t>=ts(calMonth));
const results={};
for(const name of ["volatility","previous18","direct18","direct26","twoStage26"]){
 const vec=r=>name.endsWith("26")?[...r.x,...r.flow]:r.x;
 const fit=name==="volatility"?null:fitRanker(train.map(r=>({x:vec(r),y:name==="previous18"?r.oldY:name==="twoStage26"?Number(r.direction==="up"||r.direction==="down"):r.y})));
 const directional=name==="twoStage26"?fitRanker(train.filter(r=>["up","down"].includes(r.direction)).map(r=>({x:vec(r),y:r.y}))):null;
 const score=r=>name==="volatility"?r.x[6]:scoreRanker(fit,vec(r))*(directional?scoreRanker(directional,vec(r)):1);
 const scored=a=>a.map(r=>({...r,score:score(r)}));
 const gate=countGate(scored(cal),28);
 const run=(a,events)=>{
  const selected=causalSelect(scored(a),gate.threshold);
  const relevant=events.filter(e=>e.start>=a[0].t&&e.finish<=a.at(-1).t);
  return Object.fromEntries([0,1,2].map(d=>[d,auditDirection(selected,relevant,d)]));
 };
 results[name]={gate,calibration:run(cal,dev.events),hold:run(hold.rows,hold.events),later:run(later.rows,later.events)};
}
console.log(JSON.stringify({periods:{train:trainingMonths,cal:calMonth,hold:testMonths,later:stressMonths},rows:{train:train.length,cal:cal.length,hold:hold.rows.length,later:later.rows.length},results,notice:"Observation-only research. First material impulse in either direction, already-underway episodes excluded from positive labels; daily UTC cap 3, 30m cooldown, matched calibration count, 0/1/2m latency. New windows in this research line, not prospective validation. No live signals or trading."},null,2));
