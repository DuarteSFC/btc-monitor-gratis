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
 console.log("11 assertions passed: causal episode schedule, penetration, ambiguous fill, gap, cancellation, no-fill accounting.");
}
async function readMonths(path,months){
 const b=[];
 for(const m of months){
  for(const line of (await readFile(path+"/"+m+".csv","utf8")).trim().split(/\r?\n/)){
   const a=line.split(",").map(Number);
   if(a.length!==9||a.some(v=>!Number.isFinite(v)))throw Error("Invalid row");
   const [t,o,h,l,c,v,q,n,buy]=a;
   if(l<=0||h<Math.max(o,c)||l>Math.min(o,c)||v<0||q<0||n<0||!Number.isInteger(n)||buy<0||buy>q+1e-6||(b.length&&t-b.at(-1).t!==M))throw Error("Invalid candle or gap");
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
  const b=await readMonths(path,p.months),c=candidates(b),res={bars:b.length};
  for(const [name,signals] of Object.entries(c)){
   const episodes=commonEpisodes(signals,p.from,p.to);res[name]=[];
   for(const delay of [1,5])for(const cost of [.0007,.001])for(const mode of ["market","limit"]){
    const config={delay,cost,mode,horizon:240};res[name].push({config,...evaluate(b,episodes,config)});
   }
  }
  results[p.name]=res;
 }
 console.log(JSON.stringify({periods:periods.map(({name,from,to})=>({name,from,to})),results,notice:"Fixed execution diagnostic: common 4h opportunity schedule independent of fill/outcome, 25bp retracement limit, 2bp penetration, 30m expiry, fixed structural stop, exact net 2R target, same fees 14/20bps both methods. No maker queue evidence, funding or live orders. No 2024-25 data. 2022-23 and 2026 already researched by CICLO LAB; no independent inference. Do not select by best result. No fill = zero; compare mean opportunity and fill R."},null,2));
}
if(process.argv.includes("--selftest"))selftest();else await main();
