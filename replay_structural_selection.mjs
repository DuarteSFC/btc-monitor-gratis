import {precursorAt,featuresAt} from "./precursor_research.mjs";
import {netPlan,simulatePlan} from "./structural_research.mjs";
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




// Frozen follow-up: separate early attention from hypothetical confirmation.
// Existing periods are reused research data, not a fresh out-of-sample claim.
const tf={5:[],60:[]};
for(const n of [5,60]){
 for(let i=0;i+n<=b.length;i++){
  if(b[i].t%(n*ms))continue;const x=b.slice(i,i+n);tf[n].push({t:x[0].t,o:x[0].o,h:Math.max(...x.map(z=>z.h)),l:Math.min(...x.map(z=>z.l)),c:x.at(-1).c,v:x.reduce((s,z)=>s+z.v,0)});
 }
}
const names=["reclaim_5m","reclaim_5m_1h","reclaim_break","reclaim_break_1h","reclaim_retest","reclaim_retest_1h"];
const states=Object.fromEntries(names.map(n=>[n,{qualified:0,variants:{}}]));
const costs=[0,.00035,.0007,.001];
const combos=[];for(const delay of [0,2])for(const horizon of [60,120])for(const cost of costs)combos.push({delay,horizon,cost,key:delay+"_"+horizon+"_"+cost});
for(const s of Object.values(states))for(const c of combos)s.variants[c.key]={eligible:0,rejectedRR:0,trades:0,wins:0,netR:0,maeR:0,targets:0,stops:0,time:0,daily:{},until:0};
let setup=null,q5=0,q60=0,setupCount=0,expired=0,invalidated=0,confirmed=0;
const avg=x=>x.reduce((s,v)=>s+v,0)/x.length;
const maxH=x=>Math.max(...x.map(z=>z.h));
const minL=x=>Math.min(...x.map(z=>z.l));
const setupDaily={};
function qualify(name,i,t,s,f){
 const o=states[name];o.qualified++;
 for(const c of combos){
  const v=o.variants[c.key];if(i<v.until)continue;
  const j=i+1+c.delay,entry=b[j].o;
  v.eligible++;
  // Freeze realistic selection at 7 bps/side for ALL cost sensitivities,
  // so lower costs cannot manufacture additional qualifying opportunities.
  const gate=netPlan(entry,s.stop,s.target,.0007);
  if(!gate||entry>s.lastSignalPrice+f.atr){v.rejectedRR++;continue;}
  const plan={...gate,risk:entry-s.stop+c.cost*(entry+s.stop)};
  const result=simulatePlan(plan,b.slice(j,j+c.horizon),c.cost);
  if(!result)continue;
  v.trades++;v.wins+=+(result.netR>0);v.netR+=result.netR;v.maeR+=result.maeR;
  v.targets+=+(result.reason==="target");v.stops+=+(result.reason==="stop");v.time+=+(result.reason==="time");v.until=j+result.used;
  const day=new Date(t).toISOString().slice(0,10),d=v.daily[day]??(v.daily[day]={trades:0,netR:0,wins:0});d.trades++;d.netR+=result.netR;d.wins+=+(result.netR>0);
 }
}
for(let i=4500;i<b.length-125;i++){
 const t=b[i].t+ms,w=b.slice(i-60,i+1),f=featuresAt(w);if(!f)continue;
 while(q5+1<tf[5].length&&tf[5][q5+1].t+5*ms<=t)q5++;
 while(q60+1<tf[60].length&&tf[60][q60+1].t+60*ms<=t)q60++;
 if(t<evalStart)continue;
 const last5=tf[5][q5],p5=tf[5].slice(q5-12,q5);
 const context=p5.length===12&&last5.t+5*ms<=t&&last5.c>=p5.at(-1).c&&last5.l>=minL(p5.slice(-6))&&last5.c>=avg(p5.map(z=>z.c));
 const hour=tf[60][q60],p60=tf[60].slice(q60-12,q60);
 const regime=p60.length===12&&hour.t+60*ms<=t&&hour.c>=avg(p60.map(z=>z.c))&&hour.c>=p60.at(-1).c;
 const z=b[i];
 if(setup&&z.l<=setup.stop){invalidated++;setup=null;}
 if(setup&&t-setup.t>20*ms){expired++;setup=null;}
 if(!setup&&precursorAt(w).some(e=>e.name==="sell_exhaustion_reclaim")){
  const prior=b.slice(i-60,i),longer=b.slice(i-240,i),stop=z.l-.25*f.atr,trigger=maxH(b.slice(i-6,i)),target=maxH(longer);
  // No future extrema: target, stop and local resistance known at setup.
  if(stop>0&&target>z.c&&longer.length===240){
   setup={t,stop,trigger,target,price:z.c,lastSignalPrice:z.c,breakAt:null,retested:false,used:new Set()};
   setupCount++;
   const d=new Date(t).toISOString().slice(0,10);setupDaily[d]=(setupDaily[d]??0)+1;
  }
 }
 if(!setup)continue;
 if(t>setup.t&&z.c>setup.trigger&&z.c>z.o&&!setup.breakAt){setup.breakAt=t;confirmed++;}
 if(setup.breakAt&&t>setup.breakAt&&z.l<=setup.trigger+.3*f.atr&&z.c>=setup.trigger&&z.c>z.o)setup.retested=true;
 if(t%(5*ms)||!context||z.c>setup.price+2*f.atr)continue;
 setup.lastSignalPrice=z.c;
 const modes=["reclaim_5m",...(setup.breakAt?["reclaim_break"]:[]),...(setup.retested?["reclaim_retest"]:[])];
 for(const m of modes){
  for(const name of regime?[m,m+"_1h"]:[m]){
   if(setup.used.has(name))continue;setup.used.add(name);
   qualify(name,i,t,setup,f);
  }
 }
}
console.log(JSON.stringify({period:{start:new Date(evalStart).toISOString(),end:new Date(end).toISOString(),offsetDays:offset},bars:b.length,setupCount,expired,invalidated,confirmed,setupDaily,results:states,notice:"Research only. Structural levels frozen at setup, 5m dispatch, no overlap within each configuration, net RR at 7bps each side, fixed target from prior 4h high. Reused periods, no live trades, no funding, no predictive validation. Costs sensitivity on identical gate."},null,2));
