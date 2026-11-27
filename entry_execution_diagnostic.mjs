import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {candidates} from "./longer_tactical.mjs";
import {netBarrier} from "./matched_attention.mjs";
const M=60000;
export function commonEpisodes(signals,from,to,horizon=240){
 let next=-Infinity;const out=[];
 for(const r of signals){if(r.t<from||r.t+horizon*M>to||r.t<next)continue;out.push(r);next=r.t+horizon*M;}
 return out;
}
export function replay(b,r,{mode="market",delay=1,horizon=240,cost=.0007}={}){
 const start=r.i+1+delay,end=r.i+1+horizon;
 if(end>b.length)return {kind:"uncovered",R:null};
 const zero=kind=>({kind,R:0});
 for(let k=r.i+1;k<start;k++)if(b[k].l<=r.stop)return zero("invalidated");
 if(b[start].o<=r.stop)return zero("invalidated");
 let j=start,entry=b[j].o;
 if(mode==="limit"){
  entry=r.reference*.9975;
  if((entry-r.stop)/entry<.004||(entry-r.stop)/entry>.015)return zero("riskRejected");
  let found=false;
  // Resting order expires after 30 minutes. Trade through by 2bps; no queue-priority claim.
  for(let k=start;k<Math.min(start+30,end);k++){
   if(b[k].l<=entry*.9998){j=k;found=true;break;}
  }
  if(!found)return zero("expired");
 }
 const d=(entry-r.stop)/entry;
 if(!(d>=.004&&d<=.015)||entry>r.reference+.25*r.atr)return zero("riskRejected");
 const p=netBarrier(entry,r.stop,cost,2);
 let exit=b[end-1].c,kind="time";
 for(let k=j;k<end;k++){
  const z=b[k];
  // Gap after resting order activation is adverse, not a free cancellation.
  if(z.l<=p.stop){exit=Math.min(z.o,p.stop);kind="stop";break;}
  if((mode==="market"||k>j)&&z.h>=p.target){exit=p.target;kind="target";break;}
 }
 return {kind,R:(exit-entry-cost*(entry+exit))/p.risk,wait:j-r.i-1};
}
export function evaluate(b,episodes,options){
 const counts={};let sum=0,n=0,wins=0,wait=0,covered=0,peak=0,drawdown=0;
 for(const r of episodes){
  const z=replay(b,r,options);counts[z.kind]=(counts[z.kind]??0)+1;
  if(z.R===null)continue;covered++;sum+=z.R;peak=Math.max(peak,sum);drawdown=Math.max(drawdown,peak-sum);
  if(["stop","target","time"].includes(z.kind)){n++;wins+=+(z.R>0);wait+=z.wait;}
 }
 return {opportunities:episodes.length,covered,fills:n,wins,counts,netR:sum,meanOpportunityR:covered?sum/covered:null,meanFillR:n?sum/n:null,meanWait:n?wait/n:null,drawdown};
}
export function contiguousSegments(b){
 const out=[];let start=0;
 for(let i=1;i<b.length;i++){
  const d=b[i].t-b[i-1].t;
  if(d<=0||d%M)throw Error("Invalid timestamp sequence");
  if(d>M){out.push(b.slice(start,i));start=i;}
 }
 if(b.length)out.push(b.slice(start));
 return out;
}
function combine(parts){
 const out={opportunities:0,covered:0,fills:0,wins:0,counts:{},netR:0};
 let wait=0;
 for(const p of parts){
  for(const k of ["opportunities","covered","fills","wins","netR"])out[k]+=p[k];
  for(const [k,v] of Object.entries(p.counts))out.counts[k]=(out.counts[k]??0)+v;
  wait+=(p.meanWait??0)*p.fills;
 }
 return {...out,meanOpportunityR:out.covered?out.netR/out.covered:null,meanFillR:out.fills?out.netR/out.fills:null,meanWait:out.fills?wait/out.fills:null,maxSegmentDrawdown:parts.length?Math.max(...parts.map(p=>p.drawdown)):null};
}
function selftest(){
 const b=Array.from({length:300},(_,i)=>({t:i*M,o:100,c:100,h:100.1,l:99.9}));
 const r={t:M,i:0,reference:100,atr:1,stop:99};
 assert.equal(commonEpisodes([r,{...r,t:2*M},{...r,t:241*M}],0,Infinity).length,2);
 assert.equal(replay(b,r,{mode:"limit"}).kind,"expired");
 b[2].l=99.75;assert.equal(replay(b,r,{mode:"limit"}).kind,"expired");
 b[2]={...b[2],l:99.70,h:104};assert.equal(replay(b,r,{mode:"limit"}).kind,"time");
 b[3].h=104;assert.ok(Math.abs(replay(b,r,{mode:"limit"}).R-2)<1e-10);
 b[2].l=98.9;assert.ok(Math.abs(replay(b,r,{mode:"limit"}).R+1)<1e-10);
 b[2].l=99.9;b[3]={...b[3],o:98,l:97};assert.ok(replay(b,r,{mode:"limit"}).R<-1);
 b[1].l=98.8;assert.equal(replay(b,r,{mode:"limit"}).kind,"invalidated");
 assert.equal(replay(b,r,{mode:"market"}).kind,"invalidated");
 assert.equal(evaluate(b,[r],{mode:"limit"}).meanOpportunityR,0);
 assert.equal(replay(b.slice(0,100),r).kind,"uncovered");
 assert.equal(contiguousSegments([{t:0},{t:M},{t:3*M}]).length,2);
 assert.equal(contiguousSegments([{t:0},{t:M},{t:3*M}])[1].length,1);
 assert.equal(combine([{opportunities:2,covered:2,fills:1,wins:1,counts:{target:1,expired:1},netR:2,meanWait:3,drawdown:0}]).meanOpportunityR,1);
 console.log("14 assertions passed: causal episode schedule, penetration, ambiguous fill, gap, cancellation, no-fill accounting.");
}
async function readMonths(path,months){
 const b=[];
 for(const m of months){
  for(const line of (await readFile(path+"/"+m+".csv","utf8")).trim().split(/\r?\n/)){
   const a=line.split(",").map(Number);
   if(a.length!==9||a.some(v=>!Number.isFinite(v)))throw Error("Invalid row");
   const [t,o,h,l,c,v,q,n,buy]=a;
   if(l<=0||h<Math.max(o,c)||l>Math.min(o,c)||v<0||q<0||n<0||!Number.isInteger(n)||buy<0||buy>q+1e-6||!Number.isInteger(t)||t%M||(b.length&&t<=b.at(-1).t))throw Error("Invalid candle or timestamp");
   b.push({t,o,h,l,c,v,q,n,buy});
  }
 }
 return b;
}
async function main(){
 const path=process.argv[2]??"/tmp/tactical-entry",months=(y,a,b)=>Array.from({length:b-a+1},(_,i)=>y+"-"+String(a+i).padStart(2,"0")),ts=s=>Date.parse(s+"T00:00:00Z");
 const periods=[{name:"2022",months:months(2022,1,12),from:ts("2022-01-01"),to:ts("2023-01-01")},{name:"2023",months:months(2023,1,12),from:ts("2023-01-01"),to:ts("2024-01-01")},{name:"2026AprSep",months:months(2026,1,9),from:ts("2026-04-01"),to:ts("2026-10-01")}];
 const results={};
 for(const p of periods){
  const b=await readMonths(path,p.months),segments=contiguousSegments(b);
  const runs=segments.map(b=>({b,c:candidates(b)}));
  const res={bars:b.length,segments:segments.map(s=>({from:new Date(s[0].t).toISOString(),to:new Date(s.at(-1).t+M).toISOString(),bars:s.length})),missingMinutes:(b.at(-1).t-b[0].t)/M+1-b.length};
  for(const name of ["clock","trend_pullback","sweep_reclaim","compression_break"]){
   res[name]=[];
   for(const delay of [1,5])for(const cost of [.0007,.001])for(const mode of ["market","limit"]){
    const config={delay,cost,mode,horizon:240};
    const parts=runs.map(({b,c})=>{
     const episodes=commonEpisodes(c[name],Math.max(p.from,b[0].t),Math.min(p.to,b.at(-1).t+M));
     return evaluate(b,episodes,config);
    });
    res[name].push({config,...combine(parts)});
   }
  }
  results[p.name]=res;
 }
 console.log(JSON.stringify({periods:periods.map(({name,from,to})=>({name,from,to})),results,notice:"Fixed execution diagnostic: common 4h opportunity schedule independent of fill/outcome, 25bp retracement limit, 2bp penetration, 30m expiry, fixed structural stop, exact net 2R target, same fees 14/20bps both methods. Known missing minutes split into contiguous segments; indicators restart and no episode crosses a gap. Drawdown reported per segment, not portfolio. No maker queue evidence, funding or live orders. No 2024-25 data. 2022-23 and 2026 already researched by CICLO LAB; no independent inference. Do not select by best result. No fill = zero; compare mean opportunity and fill R."},null,2));
}
if(process.argv.includes("--selftest"))selftest();else await main();
