import {precursorAt,featuresAt} from "./precursor_research.mjs";
import {detectEvents} from "./fast_tactical.mjs";
const ms=60000, days=30, warmupDays=4;
const offset=Number(process.env.REPLAY_OFFSET_DAYS??0);
if(![0,30,60].includes(offset))throw Error("Unsupported replay window");
const end=Date.parse("2026-11-27T11:36:00Z")-offset*86400000;
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



// Frozen configurations, same reference and outcomes as prior benchmark.
// Compare both absolute and volatility-scaled barriers; report daily dependence.
const tf={5:[],15:[]},baseEvents=[];
for(const n of [5,15]){
 for(let i=0;i+n<=b.length;i++){
  if(b[i].t%(n*ms))continue;const x=b.slice(i,i+n);tf[n].push({t:x[0].t,o:x[0].o,h:Math.max(...x.map(z=>z.h)),l:Math.min(...x.map(z=>z.l)),c:x.at(-1).c,v:x.reduce((s,z)=>s+z.v,0)});
 }
 for(let i=299;i<tf[n].length;i++){const t=tf[n][i].t+n*ms;for(const e of detectEvents(tf[n].slice(i-299,i+1),n+"M","historical",t,0))if(e.type!=="support_loss")baseEvents.push({...e,t:Date.parse(e.closedUtc)});}
}
baseEvents.sort((a,b)=>a.t-b.t);
const names=["clock","V2","compression_rising","sell_exhaustion_reclaim","rising_lows_dry_sell","quiet_retest","compression_context","reclaim_context"];
const stats=Object.fromEntries(names.map(n=>[n,{count:0,last:-Infinity,anticipations:0,leadMinutes:0,matched:new Set(),daily:{},outcomes:{}}]));
const pending=new Map();let q=0,kBase=0;
function evaluate(name,i,t,e,f){
 const s=stats[name];if(t-s.last<32*ms)return;
 s.last=t;s.count++;
 const next=baseEvents.find(x=>x.t>t&&x.t<=t+30*ms&&!s.matched.has(x.id));
 if(name!=="clock"&&name!=="V2"&&next){s.matched.add(next.id);s.anticipations++;s.leadMinutes+=(next.t-t)/ms;}
 const day=new Date(t).toISOString().slice(0,10),d=s.daily[day]??(s.daily[day]={up:0,down:0,neither:0});
 for(const delay of [0,2])for(const mode of ["fixed","scaled"]){
  const j=i+1+delay,px=b[j].o;
  // floor the distance to avoid a microscopic move being labelled meaningful.
  const risk=mode==="fixed"?px*.0025:Math.max(px*.0015,2.5*f.atr);
  const target=px+2*risk,stop=px-risk;
  let outcome="neither",exit=b[j+29].c;
  for(let k=j;k<j+30;k++){if(b[k].l<=stop){outcome="down";exit=Math.min(stop,b[k].o);break;}if(b[k].h>=target){outcome="up";exit=target;break;}}
  const key=mode+"_"+delay,o=s.outcomes[key]??(s.outcomes[key]={up:0,down:0,neither:0,netR:0});
  o[outcome]++;
  // Conservative hypothetical round-trip 14bps, no funding. Not an entry recommendation.
  o.netR+=(exit-px-.0007*(px+exit))/(risk+.0007*(px+stop));
  if(key==="fixed_0")d[outcome]++;
 }
}
for(let i=4500;i<b.length-35;i++){
 const t=b[i].t+ms,w=b.slice(i-60,i+1),f=featuresAt(w);if(!f)continue;
 for(const e of precursorAt(w))pending.set(e.name,e);
 if(t<evalStart||t%(5*ms))continue;
 while(q+1<tf[5].length&&tf[5][q+1].t+5*ms<=t)q++;
 while(kBase<baseEvents.length&&baseEvents[kBase].t<=t-5*ms)kBase++;
 const baseline=baseEvents[kBase];if(baseline&&baseline.t<=t)evaluate("V2",i,t,baseline,f);
 if(t%(30*ms)===0)evaluate("clock",i,t,null,f);
 const p=tf[5].slice(q-12,q),z=tf[5][q],context=p.length===12&&z.t+5*ms<=t&&z.c>=p.at(-1).c&&z.l>=Math.min(...p.slice(-6).map(x=>x.l))&&z.c>=p.reduce((s,x)=>s+x.c,0)/12;
 for(const [name,e] of pending){
  if(t-e.t>4*ms||t<e.t||f.close<e.level-2*e.atr||f.close>e.close+1.5*e.atr){pending.delete(name);continue;}
  evaluate(name,i,t,e,f);
  if(context&&name==="compression_rising")evaluate("compression_context",i,t,e,f);
  if(context&&name==="sell_exhaustion_reclaim")evaluate("reclaim_context",i,t,e,f);
  pending.delete(name);
 }
}
console.log(JSON.stringify({period:{start:new Date(evalStart).toISOString(),end:new Date(end).toISOString(),offsetDays:offset},bars:b.length,results:Object.fromEntries(names.map(n=>[n,{...stats[n],matched:undefined,last:undefined}])),notice:"Exploratory historical research only; fixed and ATR-scaled barriers, delay 0/2 minutes, 14bps hypothetical costs, no funding, no orders. No prospective validation; offset 60 has not been used in this experiment."},null,2));
