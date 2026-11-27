import {precursorAt,featuresAt} from "./precursor_research.mjs";
import {detectEvents} from "./fast_tactical.mjs";
import {rankFeatures,fitRanker,scoreRanker,observe,selectAlerts,chooseThreshold,summarize} from "./rank_attention.mjs";
const ms=60000, days=90, warmupDays=4;
const end=Date.parse("2026-11-27T11:36:00Z");
const evalStart=end-days*86400000,start=evalStart-warmupDays*86400000;
let cursor=end;const map=new Map();
while(cursor>start){
 const r=await fetch("https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=1m&limit=100&after="+cursor,{signal:AbortSignal.timeout(15000)});
 const j=await r.json();if(!r.ok||j.code!=="0"||!j.data?.length)throw Error("Historical fetch failed");
 const next=Math.min(...j.data.map(z=>+z[0]));if(next>=cursor)throw Error("Pagination stalled");cursor=next;
 for(const z of j.data){const [t,o,h,l,c,v]=z.slice(0,6).map(Number);if(String(z[8])==="1"&&t>=start&&t+ms<=end&&[t,o,h,l,c,v].every(Number.isFinite)&&l>0&&h>=Math.max(o,c)&&l<=Math.min(o,c)&&v>=0)map.set(t,{t,o,h,l,c,v});}
 await new Promise(r=>setTimeout(r,250));
}
const b=[...map.values()].sort((a,b)=>a.t-b.t);
if(b.length!==(days+warmupDays)*1440||b.some((z,i)=>i&&z.t-b[i-1].t!==ms))throw Error("Incomplete historical coverage");





// Chronological train 45d / calibration 15d / final evaluation 30d.
// This window was used in earlier experiments; final evaluation is model-held-out,
// not genuinely independent research data. All boundaries embargo 32 minutes.
const trainEnd=evalStart+45*86400000,calEnd=evalStart+60*86400000;
const tf={5:[],15:[]},baseTimes=new Set();
for(const n of [5,15]){
 for(let i=0;i+n<=b.length;i++){
  if(b[i].t%(n*ms))continue;const x=b.slice(i,i+n);tf[n].push({t:x[0].t,o:x[0].o,h:Math.max(...x.map(z=>z.h)),l:Math.min(...x.map(z=>z.l)),c:x.at(-1).c,v:x.reduce((s,z)=>s+z.v,0)});
 }
 for(let i=299;i<tf[n].length;i++){const t=tf[n][i].t+n*ms;for(const e of detectEvents(tf[n].slice(i-299,i+1),n+"M","historical",t,0))if(e.type!=="support_loss")baseTimes.add(t);}
}
const rows=[];
for(let i=4500;i<b.length-35;i++){
 const t=b[i].t+ms;if(t<evalStart||t%(5*ms))continue;
 if([trainEnd,calEnd,end].some(x=>t<x&&x-t<=32*ms))continue;
 const f=featuresAt(b.slice(i-60,i+1)),x=rankFeatures(b.slice(i-180,i+1),f);
 if(!x)continue;
 const outcomes=Object.fromEntries([0,1,2].map(d=>[d,observe(b,i,d)]));
 if(Object.values(outcomes).some(v=>v===null))continue;
 const pattern=precursorAt(b.slice(i-60,i+1)).some(e=>e.name==="sell_exhaustion_reclaim");
 rows.push({t,x,y:Number(outcomes[1]==="up"),outcomes,baseline:baseTimes.has(t),pattern});
}
const train=rows.filter(r=>r.t<trainEnd),cal=rows.filter(r=>r.t>=trainEnd&&r.t<calEnd),hold=rows.filter(r=>r.t>=calEnd);
const model=fitRanker(train);for(const r of [...cal,...hold])r.score=scoreRanker(model,r.x);
const calibration=chooseThreshold(cal,15);
const baseline=selectAlerts(hold,r=>r.baseline);
const clock=selectAlerts(hold,r=>r.t%(8*60*ms)===0);
const prior=selectAlerts(hold,r=>r.pattern);
const ranked=calibration.winner?selectAlerts(hold,r=>r.score>=calibration.winner.threshold):[];
const names={baseline,clock,prior,ranked};
console.log(JSON.stringify({period:{start:new Date(evalStart).toISOString(),trainEnd:new Date(trainEnd).toISOString(),calEnd:new Date(calEnd).toISOString(),end:new Date(end).toISOString()},bars:b.length,rows:{train:train.length,cal:cal.length,hold:hold.length},calibration,model,results:Object.fromEntries(Object.entries(names).map(([k,v])=>[k,summarize(hold,v,30)])),notice:"Market observation, not profitability or entry validation. Fixed chronological split with label embargo; prior research reused these dates. Score is uncalibrated model output, not a verified probability. Ideal 5-minute dispatch plus delay. No live signals or delivery."},null,2));
