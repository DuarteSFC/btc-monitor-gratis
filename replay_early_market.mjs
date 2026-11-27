import {attentionAt,chooseAttention} from "./early_market.mjs";
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

// Frozen thresholds: evaluate observed price movement, not trading performance.
const tf={5:[],15:[]}, baseline=[];
for(const n of [5,15]){
 for(let i=0;i+n<=b.length;i++){if(b[i].t%(n*ms))continue;const x=b.slice(i,i+n);tf[n].push({t:x[0].t,o:x[0].o,h:Math.max(...x.map(z=>z.h)),l:Math.min(...x.map(z=>z.l)),c:x.at(-1).c,v:x.reduce((s,z)=>s+z.v,0)});}
 for(let i=299;i<tf[n].length;i++){const t=tf[n][i].t+n*ms;baseline.push(...detectEvents(tf[n].slice(i-299,i+1),n+"M","historical",t,0));}
}
const result={},seen=new Set();let pending=[],last=0;
const startIndex=4500,split=end-10*86400000;
for(let i=startIndex;i<b.length-35;i++){
 const t=b[i].t+ms,e=attentionAt(b.slice(i-23,i+1),"historical",t);if(e)pending.push(e);
 pending=pending.filter(z=>t-Date.parse(z.closedUtc)<=600000);
 if(t%(5*ms))continue;
 const recent=baseline.filter(z=>{const d=Date.parse(z.closedUtc);return d<=t&&t-d<=20*ms});
 const chosen=chooseAttention(pending,recent,seen,last,t);
 for(const z of chosen){
  seen.add(z.id);last=Date.parse(z.closedUtc);
  const s=result[t>=split?"last10":"first20"]??(result[t>=split?"last10":"first20"]={alerts:0,upFirst:0,downFirst:0,neither:0,precedesBaseline:0,leadMinutes:0,delayMinutes:0});
  s.alerts++;s.delayMinutes+=(t-Date.parse(z.closedUtc))/ms;
  const px=b[i+1].o;let o="neither";
  for(let k=i+1;k<=i+30;k++){if(b[k].l<=px*.9975){o="downFirst";break;}if(b[k].h>=px*1.005){o="upFirst";break;}}s[o]++;
  const later=baseline.filter(q=>q.type!=="support_loss"&&Date.parse(q.closedUtc)>t&&Date.parse(q.closedUtc)<=t+30*ms).sort((a,b)=>Date.parse(a.closedUtc)-Date.parse(b.closedUtc))[0];
  if(later){s.precedesBaseline++;s.leadMinutes+=(Date.parse(later.closedUtc)-t)/ms;}
 }
}
console.log(JSON.stringify({bars:b.length,results:result,baselineEvents:baseline.length,notice:"Observation replay only, 5-minute polling, no execution, no profit claims; reused historical period is not independent validation."},null,2));
