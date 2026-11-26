import {earlyPatterns} from "./early_patterns.mjs";
import {detectEvents} from "./fast_tactical.mjs";
const ms=60000, days=30, end=Math.floor(Date.now()/ms)*ms,start=end-days*86400000;
let cursor=end;const map=new Map();
while(cursor>start){
 const r=await fetch("https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=1m&limit=100&after="+cursor,{signal:AbortSignal.timeout(15000)});
 const j=await r.json();if(!r.ok||j.code!=="0"||!j.data?.length)throw Error("Historical fetch failed");
 const next=Math.min(...j.data.map(z=>+z[0]));if(next>=cursor)throw Error("Pagination stalled");cursor=next;
 for(const z of j.data){const [t,o,h,l,c,v]=z.slice(0,6).map(Number);if(String(z[8])==="1"&&t>=start&&t+ms<=end&&[t,o,h,l,c,v].every(Number.isFinite)&&l>0&&h>=Math.max(o,c)&&l<=Math.min(o,c)&&v>=0)map.set(t,{t,o,h,l,c,v});}
 await new Promise(r=>setTimeout(r,250));
}
const b=[...map.values()].sort((a,b)=>a.t-b.t);
if(b.length<days*1440*.99||b.some((z,i)=>i&&z.t-b[i-1].t!==ms))throw Error("Incomplete historical coverage");
// Observation-only benchmark. No trade plan or account sizing.
// Compare an identical future movement test for baseline and filtered alerts.
const tf5=[],tf15=[];
for(const [n,out] of [[5,tf5],[15,tf15]]){
 for(let i=0;i+n<=b.length;i++){if(b[i].t%(ms*n))continue;const x=b.slice(i,i+n);out.push({t:x[0].t,o:x[0].o,h:Math.max(...x.map(z=>z.h)),l:Math.min(...x.map(z=>z.l)),c:x.at(-1).c,v:x.reduce((s,z)=>s+z.v,0)});}
}
const baseline=new Map(),filtered5=new Map();
for(const [n,big] of [[5,tf5],[15,tf15]])for(let i=299;i<big.length;i++){
 const t=big[i].t+n*ms,history=big.slice(i-299,i+1);
 const es=detectEvents(history,n+"M","OKX historical",t,0);
 if(es.some(e=>["breakout","recovery_impulse","sweep_recovery"].includes(e.type)))baseline.set(t,true);
 if(n===5&&earlyPatterns(history,5*ms).some(e=>e.volumeVs20>=1.5))filtered5.set(t,true);
}
const results={}, last={}, records=[];
const split=end-10*86400000;
function observe(name,i,t){
 // Simulate the actual five-minute dispatcher rather than instantaneous delivery.
 const dispatch=Math.ceil(t/(5*ms))*5*ms;
 const j=i+(dispatch-t)/ms;
 if(j+30>=b.length||j<i||dispatch-(last[name]??-Infinity)<15*ms)return;
 last[name]=dispatch;
 const px=b[j+1].o,up=px*1.005,down=px*.9975;
 let outcome="neither",minutes=null;
 for(let k=j+1;k<=j+30;k++){const z=b[k];if(z.l<=down){outcome="adverse_first";minutes=k-j;break;}if(z.h>=up){outcome="up_first";minutes=k-j;break;}}
 const period=dispatch>=split?"recent10":"earlier";
 const s=(results[name]??={})[period]??={count:0,up_first:0,adverse_first:0,neither:0,sumMinutesUp:0};
 s.count++;s[outcome]++;if(outcome==="up_first")s.sumMinutesUp+=minutes;
 records.push({name,t,dispatch,outcome});
}
let q=0;
for(let i=4499;i<b.length-35;i++){
 const t=b[i].t+ms;
 if(baseline.has(t))observe("V2_baseline",i,t);
 if(filtered5.has(t))observe("5M_volume_filtered",i,t);
 while(q+1<tf5.length&&tf5[q+1].t+5*ms<=t)q++;
 const z=tf5[q],p=tf5.slice(q-5,q);
 if(p.length!==5||z.t+5*ms>t)continue;
 const context=z.c>z.o&&z.c>=p.at(-1).c&&z.l>=Math.min(...p.map(x=>x.l));
 if(!context)continue;
 const es=earlyPatterns(b.slice(i-299,i+1));
 if(es.some(e=>e.volumeVs20>=1.5))observe("1M_with_5M_context",i,t);
}
const baseTimes=records.filter(x=>x.name==="V2_baseline").map(x=>x.dispatch);
const anticipation={};
for(const x of records.filter(x=>x.name!=="V2_baseline")){
 const a=anticipation[x.name]??={alerts:0,precededBaseline:0,sumLeadMinutes:0};a.alerts++;
 const next=baseTimes.find(t=>t>x.dispatch);
 if(next!==undefined&&next-x.dispatch<=30*ms){a.precededBaseline++;a.sumLeadMinutes+=(next-x.dispatch)/ms;}
}
console.log(JSON.stringify({bars:b.length,results,anticipation,notice:"Exploratory observation benchmark: +0.5% before -0.25% in 30m; conservative adverse-first, five-minute polling, 15-minute cooldown per configuration. Not profit, entry, or independent holdout; recent10 already observed in prior analysis. Excludes real dispatch delays."},null,2));
