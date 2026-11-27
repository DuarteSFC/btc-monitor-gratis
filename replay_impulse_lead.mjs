import {readFile} from "node:fs/promises";
import {featuresAt} from "./precursor_research.mjs";
import {rankFeatures,fitRanker,scoreRanker,observe,selectAlerts,chooseThreshold,summarize} from "./rank_attention.mjs";
import {flowFeatures} from "./spot_flow_features.mjs";
import {matchedThreshold} from "./matched_attention.mjs";
import {impulses,measureLead} from "./impulse_lead.mjs";
const path=process.argv[2]??"/tmp/tactical-flow",ms=60000;
const trainingMonths=["2025-01","2025-02","2025-03","2025-04"],calMonth="2025-05",testMonth="2025-06",stressMonths=["2026-04","2026-05","2026-06"];
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
function makeRows(b,boundaries){
 const rows=[];
 for(let i=180;i<b.length-35;i++){
  const t=b[i].t+ms;if(t%(5*ms)||boundaries.some(x=>t<x&&x-t<=32*ms))continue;
  const f=featuresAt(b.slice(i-60,i+1)),x=rankFeatures(b.slice(i-180,i+1),f),flow=flowFeatures(b.slice(i-60,i+1));
  if(!x||!flow)continue;
  const outcomes=Object.fromEntries([0,1,2].map(d=>[d,observe(b,i,d)]));
  if(Object.values(outcomes).some(v=>v===null))continue;
  rows.push({t,i,x,flow,y:Number(outcomes[1]==="up"),outcomes});
 }
 return rows;
}
const ts=s=>Date.parse(s+"-01T00:00:00Z");
const calStart=ts(calMonth),testStart=ts(testMonth);
const b=await readMonths([...trainingMonths,calMonth,testMonth]);
const stress=await readMonths(stressMonths);
const rows=makeRows(b,[calStart,testStart,ts("2025-07")]);
const train=rows.filter(r=>r.t<calStart),cal=rows.filter(r=>r.t>=calStart&&r.t<testStart),hold=rows.filter(r=>r.t>=testStart);
const external=makeRows(stress,[ts("2026-07")]);


const results={};
for(const name of ["volatility","momentum","rank18","rank26"]){
 const vec=r=>name==="rank26"?[...r.x,...r.flow]:r.x;
 const learned=name.startsWith("rank");
 const model=learned?fitRanker(train.map(r=>({x:vec(r),y:r.y}))):null;
 const score=r=>learned?scoreRanker(model,vec(r)):name==="volatility"?r.x[6]:r.x[0];
 const scored=a=>a.map(r=>({...r,score:score(r)}));
 const gate=matchedThreshold(scored(cal),28);
 function run(a,bars){
  const selected=selectAlerts(scored(a),r=>r.score>=gate.threshold);
  const from=a[0].t,to=a.at(-1).t;
  const events=impulses(bars).filter(e=>e.start>=from&&e.finish<=to);
  return Object.fromEntries([0,1,2].map(delay=>[delay,measureLead(selected,events,{delay})]));
 }
 results[name]={gate,hold:run(hold,b),later:run(external,stress)};
}
console.log(JSON.stringify({periods:{train:trainingMonths,cal:calMonth,hold:testMonth,later:stressMonths},definition:"first closed 5-minute rolling price gain >=0.5%, separated by 30 minutes; early only if alert received by START of that 5-minute window; one alert per episode; 30-minute lookahead to finish",results,notice:"Reused retrospective samples; impulse window start is a reproducible proxy, not the true market turning point. No profitability claim or live signals."},null,2));
