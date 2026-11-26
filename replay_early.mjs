import {earlyPatterns} from "./early_patterns.mjs";
const ms=60000, days=30, end=Math.floor(Date.now()/ms)*ms,start=end-days*86400000;
let cursor=end;const map=new Map();
while(cursor>start){
 const r=await fetch("https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=1m&limit=100&after="+cursor,{signal:AbortSignal.timeout(15000)});
 const j=await r.json();if(!r.ok||j.code!=="0"||!j.data?.length)throw Error("Historical fetch failed");
 const next=Math.min(...j.data.map(z=>+z[0]));if(next>=cursor)throw Error("Pagination stalled");cursor=next;
 for(const z of j.data){const [t,o,h,l,c,v]=z.slice(0,6).map(Number);if(z[8]==="1"&&t>=start&&t+ms<=end)map.set(t,{t,o,h,l,c,v});}
 await new Promise(r=>setTimeout(r,250));
}
const b=[...map.values()].sort((a,b)=>a.t-b.t);
if(b.length<days*1440*.99||b.some((z,i)=>i&&z.t-b[i-1].t!==ms))throw Error("Incomplete historical coverage");
const stats={};
for(let i=299;i<b.length-61;i++){
 for(const e of earlyPatterns(b.slice(i-299,i+1))){
 const s=stats[e.type]??={alerts:0,trades:0,wins:0,netR:0,blockedUntil:0};s.alerts++;
 if(i<s.blockedUntil)continue;
 const entry=b[i+1].o,stop=Math.min(e.level,b[i].l)-entry*.001,risk=entry-stop;
 if(!(risk>entry*.001&&risk<entry*.02))continue;
 const target=(entry*(1+.0007)+2*risk)/(1-.0007);
 let exit=b[i+60].c,k=i+60;
 for(let j=i+1;j<=i+60;j++){if(b[j].l<=stop){exit=Math.min(stop,b[j].o);k=j;break;}if(b[j].h>=target){exit=target;k=j;break;}}
 const net=(exit-entry-.0007*(entry+exit))/risk;s.trades++;s.wins+=+(net>0);s.netR+=net;s.blockedUntil=k+1;
 }
}
console.log(JSON.stringify({days,bars:b.length,stats,notice:"Exploratory in-sample replay; excludes funding; not a validated strategy."},null,2));
