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
const stats={}, comparison={}, byPeriod={development:{},holdout:{}};
const holdoutStart=end-10*86400000;
const events=[];
for(const n of [5,15]){
 const big=[];
 for(let i=0;i+n<=b.length;i++){if(b[i].t%(ms*n))continue;const x=b.slice(i,i+n);big.push({t:x[0].t,o:x[0].o,h:Math.max(...x.map(z=>z.h)),l:Math.min(...x.map(z=>z.l)),c:x.at(-1).c,v:x.reduce((s,z)=>s+z.v,0)});}
 for(let i=299;i<big.length;i++){const t=big[i].t+ms*n;for(const e of detectEvents(big.slice(i-299,i+1),n+"M","OKX historical",t,0))if(e.type==="breakout"||e.type==="recovery_impulse")events.push(Date.parse(e.closedUtc));}
}
events.sort((a,b)=>a-b);
let cursorEvent=0;const matched=new Set();
for(let i=299;i<b.length-61;i++){
 const now=b[i].t+ms;
 if(now<b[0].t+300*15*ms)continue;
 while(cursorEvent<events.length&&events[cursorEvent]<=now)cursorEvent++;
 for(const e of earlyPatterns(b.slice(i-299,i+1))){
 const cmp=comparison[e.type]??={alerts:0,precededV2Within30m:0,withoutV2Within30m:0,leadMinutesSum:0,distinctV2Events:0};cmp.alerts++;
 if(events[cursorEvent]!==undefined&&events[cursorEvent]-now<=30*ms){cmp.precededV2Within30m++;cmp.leadMinutesSum+=(events[cursorEvent]-now)/ms;const key=e.type+":"+events[cursorEvent];if(!matched.has(key)){matched.add(key);cmp.distinctV2Events++;}}else cmp.withoutV2Within30m++;
 const period=now>=holdoutStart?"holdout":"development";const group=byPeriod[period][e.type]??={trades:0,wins:0,netR:0};
 const s=stats[e.type]??={alerts:0,trades:0,wins:0,netR:0,blockedUntil:0};s.alerts++;
 if(i<s.blockedUntil)continue;
 const entry=b[i+1].o,stop=Math.min(e.level,b[i].l)-entry*.001,risk=entry-stop;
 if(!(risk>entry*.001&&risk<entry*.02))continue;
 const target=(entry*(1+.0007)+2*(risk+.0007*(entry+stop)))/(1-.0007);
 let exit=b[i+60].c,k=i+60;
 for(let j=i+1;j<=i+60;j++){if(b[j].l<=stop){exit=Math.min(stop,b[j].o);k=j;break;}if(b[j].h>=target){exit=target;k=j;break;}}
 const net=(exit-entry-.0007*(entry+exit))/(risk+.0007*(entry+stop));s.trades++;s.wins+=+(net>0);s.netR+=net;s.blockedUntil=k+1;group.trades++;group.wins+=+(net>0);group.netR+=net;
 }
}
console.log(JSON.stringify({days,bars:b.length,stats,byPeriod,comparison,baselineV2Events:events.length,holdoutStart:new Date(holdoutStart).toISOString(),notice:"Exploratory in-sample replay; excludes funding; not a validated strategy."},null,2));
