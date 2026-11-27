import {attentionAt,chooseAttention} from "./early_market.mjs";
import {detectEvents} from "./fast_tactical.mjs";
const ms=60000, days=30, warmupDays=4;
const offset=Number(process.env.REPLAY_OFFSET_DAYS??0);
if(![0,30].includes(offset))throw Error("Unsupported replay window");
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


// Frozen observation configurations. No orders; selection uses only closed bars.
// Equal dispatch cadence and 30-minute non-overlap within each configuration.
const tf={5:[],15:[]},baseline=[];
for(const n of [5,15]){
 for(let i=0;i+n<=b.length;i++){
  if(b[i].t%(n*ms))continue;const x=b.slice(i,i+n);
  tf[n].push({t:x[0].t,o:x[0].o,h:Math.max(...x.map(z=>z.h)),l:Math.min(...x.map(z=>z.l)),c:x.at(-1).c,v:x.reduce((s,z)=>s+z.v,0)});
 }
 for(let i=299;i<tf[n].length;i++){
  const t=tf[n][i].t+n*ms;
  baseline.push(...detectEvents(tf[n].slice(i-299,i+1),n+"M","historical",t,0));
 }
}
baseline.sort((a,b)=>Date.parse(a.closedUtc)-Date.parse(b.closedUtc));
const bullish=e=>["breakout","recovery_impulse","sweep_recovery"].includes(e.type);
const strong=e=>(e.volumeVs20>=6&&e.bodyVsAtr>=1.2)||(e.volume3Vs20>=2.2&&e.threeMinuteMoveVsAtr>=2.5);
const groups=["regular30m_control","V2_bullish","V22_raw","V22_strong","V22_5M_context","V22_strong_context","V22_reclaim"];
const state=Object.fromEntries(groups.map(name=>[name,{last:-Infinity,seen:new Set(),matched:new Set(),results:{alerts:0,precedesDistinctBaseline:0,leadMinutes:0,deliveryLagMinutes:0,outcomes:{"0":{up:0,down:0,neither:0},"1":{up:0,down:0,neither:0},"2":{up:0,down:0,neither:0}},daily:{}}}]));
function observe(name,i,t,e){
 const s=state[name];if(t-s.last<30*ms)return;
 s.last=t;const v=s.results;v.alerts++;
 if(e){const closed=Date.parse(e.closedUtc);if(closed>t)throw Error("Future event");s.seen.add(e.id);v.deliveryLagMinutes+=(t-closed)/ms;}
 const next=baseline.find(x=>bullish(x)&&Date.parse(x.closedUtc)>t&&Date.parse(x.closedUtc)<=t+30*ms&&!s.matched.has(x.id));
 if(name!=="V2_bullish"&&name!=="regular30m_control"&&next){s.matched.add(next.id);v.precedesDistinctBaseline++;v.leadMinutes+=(Date.parse(next.closedUtc)-t)/ms;}
 for(const delay of [0,1,2]){
  const j=i+1+delay,px=b[j].o;let result="neither";
  for(let k=j;k<j+30;k++){if(b[k].l<=px*.9975){result="down";break;}if(b[k].h>=px*1.005){result="up";break;}}
  v.outcomes[delay][result]++;
  if(delay===0){const date=new Date(t).toISOString().slice(0,10);const daily=v.daily[date]??(v.daily[date]={up:0,down:0,neither:0});daily[result]++;}
 }
}
let pending=[],q=0,baseIndex=0;
for(let i=4500;i<b.length-34;i++){
 const t=b[i].t+ms,e=attentionAt(b.slice(i-23,i+1),"historical",t);
 if(e){
  const before=b.slice(i-22,i-2),tail=b.slice(i-2,i+1);
  const low=Math.min(...before.map(z=>z.l));
  pending.push({...e,reclaim:Math.min(...tail.map(z=>z.l))<low&&e.close>low});
 }
 pending=pending.filter(z=>t-Date.parse(z.closedUtc)<=600000);
 if(t<evalStart||t%(5*ms))continue;
 while(q+1<tf[5].length&&tf[5][q+1].t+5*ms<=t)q++;
 while(baseIndex<baseline.length&&Date.parse(baseline[baseIndex].closedUtc)<t-20*ms)baseIndex++;
 const recent=[];for(let k=baseIndex;k<baseline.length&&Date.parse(baseline[k].closedUtc)<=t;k++)recent.push(baseline[k]);
 const last5=tf[5][q],p=tf[5].slice(q-20,q),mean=p.reduce((s,z)=>s+z.c,0)/20;
 const context=p.length===20&&last5.t+5*ms<=t&&last5.c>last5.o&&last5.c>mean&&last5.c>=p.at(-1).c&&last5.l>=Math.min(...p.slice(-6).map(z=>z.l));
 if(t%(30*ms)===0)observe("regular30m_control",i,t,null);
 const newBase=recent.filter(z=>bullish(z)&&Date.parse(z.closedUtc)>t-5*ms);
 if(newBase.length)observe("V2_bullish",i,t,newBase.at(-1));
 const variants={V22_raw:pending,V22_strong:pending.filter(strong),V22_5M_context:context?pending:[],V22_strong_context:context?pending.filter(strong):[],V22_reclaim:pending.filter(z=>z.reclaim)};
 for(const [name,events] of Object.entries(variants)){
  const s=state[name];if(t-s.last<30*ms)continue;
  const chosen=chooseAttention(events,recent,s.seen,0,t);
  if(chosen.length)observe(name,i,t,chosen[0]);
 }
}
console.log(JSON.stringify({period:{start:new Date(evalStart).toISOString(),end:new Date(end).toISOString(),offsetDays:offset},bars:b.length,warmupDays,baselineBullishEvents:baseline.filter(e=>bullish(e)&&Date.parse(e.closedUtc)>=evalStart).length,results:Object.fromEntries(groups.map(name=>[name,state[name].results])),notice:"Observation benchmark, not profits or entry validation. Same 30-minute cooldown, five-minute ideal dispatch, 0/1/2-minute added delay. Down first if both barriers hit in a candle. Historical windows are chronological, not prospective; thresholds chosen after earlier research. Daily data for dependence-aware analysis."},null,2));
