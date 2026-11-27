import {readFile} from "node:fs/promises";
import {featuresAt} from "./precursor_research.mjs";
import {rankFeatures,fitRanker,scoreRanker,observe,selectAlerts,chooseThreshold,summarize} from "./rank_attention.mjs";
import {flowFeatures} from "./spot_flow_features.mjs";
import {matchedThreshold,netBarrier,simulateSelected} from "./matched_attention.mjs";
import {fitUtility,scoreUtility,utilityLabel} from "./utility_attention.mjs";
const path=process.argv[2]??"/tmp/tactical-flow",ms=60000;
const trainingMonths=["2025-01","2025-02","2025-03","2025-04"],calMonth="2025-05",testMonths=["2025-07","2025-08","2025-09"],stressMonths=["2026-07"];
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
function rowsFor(b,boundaries=[]){
 const rows=[];
 for(let i=180;i<b.length-125;i++){
  const t=b[i].t+ms;if(t%(5*ms)||boundaries.some(x=>t<x&&x-t<=122*ms))continue;
  const f=featuresAt(b.slice(i-60,i+1)),x=rankFeatures(b.slice(i-180,i+1),f),flow=flowFeatures(b.slice(i-60,i+1));
  if(!x||!flow)continue;
  const outcomes=Object.fromEntries([0,1,2].map(d=>[d,observe(b,i,d)]));
  const a=utilityLabel(b,i,netBarrier,1),c=utilityLabel(b,i,netBarrier,2);
  if(a===null||c===null)continue;
  rows.push({t,i,x,flow,y:(a+c)/2,up:Number(outcomes[1]==="up"),outcomes});
 }
 return rows;
}
const dev=await readMonths([...trainingMonths,calMonth]),holdBars=await readMonths(testMonths),laterBars=await readMonths(stressMonths);
const rows=rowsFor(dev,[ts(calMonth),ts("2025-06")]),train=rows.filter(r=>r.t<ts(calMonth)),cal=rows.filter(r=>r.t>=ts(calMonth)),hold=rowsFor(holdBars),later=rowsFor(laterBars);
const result={};
for(const name of ["volatility","probability18","utility18","utility26"]){
 const vector=r=>name==="utility26"?[...r.x,...r.flow]:r.x;
 const fit=name.startsWith("utility")?fitUtility(train.map(r=>({x:vector(r),y:r.y}))):name==="probability18"?fitRanker(train.map(r=>({x:r.x,y:r.up}))):null;
 const score=r=>name==="volatility"?r.x[6]:name==="probability18"?scoreRanker(fit,r.x):scoreUtility(fit,vector(r));
 const scored=a=>a.map(r=>({...r,score:score(r)}));
 const c=scored(cal),h=scored(hold),e=scored(later),gate=matchedThreshold(c,28);
 const select=a=>selectAlerts(a,r=>r.score>=gate.threshold);
 const calibration=simulateSelected(dev,select(c),{delay:1,horizon:60});
 const calibration2=simulateSelected(dev,select(c),{delay:2,horizon:60});
 const pass=calibration.n>=25&&calibration2.n>=25&&calibration.meanR>0&&calibration2.meanR>0;
 const run=(a,days,bars)=>{
  const chosen=select(a),economics={};for(const delay of [1,2])for(const horizon of [60,120])economics[delay+"_"+horizon]=simulateSelected(bars,chosen,{delay,horizon});
  return {report:summarize(a,chosen,days),economics};
 };
 result[name]={gate,calibration,calibration2,calibrationPass:pass,model:fit,hold:run(h,92,holdBars),later:run(e,31,laterBars)};
}
console.log(JSON.stringify({periods:{train:trainingMonths,cal:calMonth,hold:testMonths,later:stressMonths},bars:{development:dev.length,hold:holdBars.length,later:laterBars.length},rows:{train:train.length,cal:cal.length,hold:hold.length,later:later.length},results:result,notice:"New periods for this experiment, not necessarily untouched by other projects. Fixed training objective mean net R for 1/2-minute delays; fixed 60m primary horizon, 120m sensitivity. Cost 7bps per side, fixed 0.25% stop, exact net 2:1 target. No funding, no live trades. Failed calibration cannot authorize deployment even if later results look positive."},null,2));
