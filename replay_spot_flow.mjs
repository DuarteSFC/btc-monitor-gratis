import {readFile} from "node:fs/promises";
import {featuresAt} from "./precursor_research.mjs";
import {rankFeatures,fitRanker,scoreRanker,observe,selectAlerts,chooseThreshold,summarize} from "./rank_attention.mjs";
import {flowFeatures} from "./spot_flow_features.mjs";
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
  rows.push({t,x,flow,y:Number(outcomes[1]==="up"),outcomes});
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
for(const name of ["price_volume_only","plus_executed_buy_flow"]){
 const vector=r=>name==="price_volume_only"?r.x:[...r.x,...r.flow];
 const model=fitRanker(train.map(r=>({x:vector(r),y:r.y})));
 const scored=a=>a.map(r=>({...r,score:scoreRanker(model,vector(r))}));
 const calibration=chooseThreshold(scored(cal),31);
 const run=(a,days)=>{
  const r=scored(a),chosen=calibration.winner?selectAlerts(r,z=>z.score>=calibration.winner.threshold):[];
  // Same deterministic neutral reference per model and sample.
  const neutral=selectAlerts(r,z=>z.t%(8*60*ms)===0);
  return {selected:summarize(r,chosen,days),clock:summarize(r,neutral,days),all:summarize(r,r,days)};
 };
 results[name]={calibration,model,hold:run(hold,30),later:run(external,91)};
}
console.log(JSON.stringify({source:"Binance spot BTCUSDT public monthly archives; SHA256 verified",periods:{train:trainingMonths,cal:calMonth,hold:testMonth,later:stressMonths},bars:{development:b.length,later:stress.length},rows:{train:train.length,cal:cal.length,hold:hold.length,later:external.length},results,notice:"Observation ranking only; no entry or profitability claim. Identical sample, features and gate except eight executed-flow features. Later period never used for fit/calibration in this experiment; retrospective, not prospective; no inference of global order flow or liquidity absorption."},null,2));
