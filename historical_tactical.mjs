// Read-only historical replay. Public OKX spot data. No account or orders.
import {detectEvents} from "./fast_tactical.mjs";
import {fromBars,candidate} from "./tactical_candidate.mjs";
const ms=300000, days=90, cutoff=Math.floor(Date.now()/ms)*ms, first=cutoff-days*86400000;
const data=new Map();
let after=cutoff;
for(let p=0;p<280&&after>first;p++){
 const url="https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=5m&limit=100&after="+after;
 let j;
 for(let n=0;n<3;n++){try{const r=await fetch(url,{signal:AbortSignal.timeout(10000)});if(!r.ok)throw Error("HTTP "+r.status);j=await r.json();if(j.code!=="0")throw Error("OKX code "+j.code);break;}catch(e){if(n===2)throw e;await new Promise(r=>setTimeout(r,1000*(n+1)));}}
 if(!j.data?.length)break;
 const next=Math.min(...j.data.map(z=>Number(z[0])));
 if(!(next<after))throw Error("Pagination stalled");
 after=next;
 for(const z of j.data){const [t,o,h,l,c,v]=z.slice(0,6).map(Number);if(String(z[8])==="1"&&t+ms<=cutoff&&t>=first&&[t,o,h,l,c,v].every(Number.isFinite)&&l>0&&h>=Math.max(o,c)&&l<=Math.min(o,c)&&v>=0)data.set(t,{t,o,h,l,c,v});}
 await new Promise(r=>setTimeout(r,150));
}
const bars=[...data.values()].sort((a,b)=>a.t-b.t);
if(bars.length<days*288*0.98)throw Error("Insufficient historical coverage: "+bars.length);
for(let i=1;i<bars.length;i++)if(bars[i].t-bars[i-1].t!==ms)throw Error("Historical gap");
const big=[];for(let i=0;i+2<bars.length;i++){const a=bars[i],b=bars[i+1],c=bars[i+2];if(a.t%900000===0)big.push({t:a.t,o:a.o,h:Math.max(a.h,b.h,c.h),l:Math.min(a.l,b.l,c.l),c:c.c,v:a.v+b.v+c.v});}
let j=0,blockedUntil=0,total=0,skipped=0,detectorEvents=0;const trades=[],events5=[],seenSetups=new Set();
for(let i=900;i+25<bars.length;i++){
 const now=bars[i].t+ms;
 const five=bars.slice(i-299,i+1);
 const detected=detectEvents(five,"5M","OKX historical",now,0);
 detectorEvents+=detected.length;events5.push(...detected);
 while(events5.length&&Date.parse(events5[0].closedUtc)<now-1800000)events5.shift();
 while(j+1<big.length&&big[j+1].t+900000<=now)j++;
 if(now<blockedUntil)continue;
 const signal=fromBars({five,fifteen:big.slice(Math.max(0,j-299),j+1),events:events5,now,feeBps:5,slippageBps:2})[0];
 if(!signal||seenSetups.has(signal.setupId))continue;
 seenSetups.add(signal.setupId);total++;
 const entry=bars[i+1].o;
 if(Math.abs(entry-signal.entry)>0.15*(signal.entry-signal.stop)){skipped++;continue;}
 const plan=candidate({...signal,entry,confirmed:true});if(!plan){skipped++;continue;}
 let exit=bars[i+24].c,outcome="timeout",end=i+24,mae=0,mfe=0;
 for(let k=i+1;k<=i+24;k++){const b=bars[k];mae=Math.max(mae,entry-b.l);mfe=Math.max(mfe,b.h-entry);if(b.l<=plan.stop){exit=Math.min(b.o,plan.stop);outcome="stop";end=k;break;}if(b.h>=plan.target){exit=plan.target;outcome="target";end=k;break;}}
 const rate=(plan.feeBps+plan.slippageBps)/10000;
 const pnl=exit-entry-(entry+exit)*rate;
 trades.push({utc:new Date(now).toISOString(),entry,stop:plan.stop,target:plan.target,exit,outcome,netR:pnl/plan.risk,maeR:mae/plan.risk,mfeR:mfe/plan.risk});
 blockedUntil=bars[end].t+ms;
}
const wins=trades.filter(t=>t.netR>0).length;
const segments=[0,1,2].map(k=>{const from=first+k*30*86400000,to=from+30*86400000;const ts=trades.filter(t=>Date.parse(t.utc)>=from&&Date.parse(t.utc)<to);return {from:new Date(from).toISOString(),to:new Date(to).toISOString(),completed:ts.length,wins:ts.filter(t=>t.netR>0).length,netR:ts.reduce((s,t)=>s+t.netR,0)};});
const summary={source:"OKX BTC-USDT spot 5m closed candles; 15m aggregated",from:new Date(bars[0].t).toISOString(),to:new Date(bars.at(-1).t+ms).toISOString(),bars:bars.length,detectorEvents,model:"closed_retest_v1",segments,hypotheticalCandidates:total,skipped,completed:trades.length,wins,losses:trades.filter(t=>t.netR<0).length,netR:trades.reduce((s,t)=>s+t.netR,0),minimumSampleMet:trades.length>=30,notice:"Non-overlapping next-open fills, stop-first on ambiguous candles, 24-bar timeout, assumed 7 bps each side; excludes funding and is not an out-of-sample validation. MAE/MFE include full exit candle."};
console.log(JSON.stringify({summary,trades},null,2));
