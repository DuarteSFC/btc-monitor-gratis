// Research-only B07 benchmark. Actual imported production rules, historical
// spot replay semantics retained; no network, no production changes.
import {readFileSync,writeFileSync} from "node:fs";
import {detectEvents} from "../fast_tactical.mjs";
import {fromEvents,candidate} from "../tactical_candidate.mjs";
const ms=300000, bigms=900000;
function load(name){
 const rows=readFileSync("lab-b07-"+name+".csv","utf8").trim().split("\n").slice(1);
 const groups=[];let last=null,g=[];
 for(const line of rows){
  const [t,o,h,l,c,v,s]=line.split(",").map(Number);
  if(![t,o,h,l,c,v,s].every(Number.isFinite)||l<=0||h<Math.max(o,c)||l>Math.min(o,c)||v<0)throw Error("bad bar");
  if(last&&(s!==last.s||t-last.t!==ms)){groups.push(g);g=[];}
  const b={t,o,h,l,c,v,s};g.push(b);last=b;
 }
 if(g.length)groups.push(g);return groups;
}
function replay(groups,start,end,fee,slip){
 const trades=[];let equity=10000,peak=equity,dd=0,total=0,skipped=0,events5=0,paired=0,unknown=0;
 const a=Date.parse(start),b=Date.parse(end);
 for(const bars of groups){
  if(bars.length<925)continue;
  const big=[];for(let i=0;i+2<bars.length;i++){const x=bars[i],y=bars[i+1],z=bars[i+2];if(x.t%bigms===0)big.push({t:x.t,o:x.o,h:Math.max(x.h,y.h,z.h),l:Math.min(x.l,y.l,z.l),c:z.c,v:x.v+y.v+z.v});}
  const fifteen=[];for(let i=299;i<big.length;i++){const now=big[i].t+bigms;fifteen.push(...detectEvents(big.slice(i-299,i+1),"15M","verified spot benchmark",now,0));}
  let j=0,blockedUntil=0;
  for(let i=900;i<bars.length;i++){
   const now=bars[i].t+ms;if(now<a||now>=b-25*ms||now<blockedUntil)continue;
   while(j<fifteen.length&&Date.parse(fifteen[j].closedUtc)<now-bigms)j++;
   const available=[];for(let k=j;k<fifteen.length&&Date.parse(fifteen[k].closedUtc)<=now;k++)available.push(fifteen[k]);
   const events=detectEvents(bars.slice(i-299,i+1),"5M","verified spot benchmark",now,0);
   const longs=events.filter(e=>["breakout","sweep_recovery"].includes(e.type));events5+=longs.length;
   paired+=longs.filter(e=>available.some(x=>["breakout","sweep_recovery","recovery_impulse"].includes(x.type)&&Date.parse(x.closedUtc)<=Date.parse(e.closedUtc)&&Date.parse(e.closedUtc)-Date.parse(x.closedUtc)<=bigms)).length;
   const signal=fromEvents([...available,...events],now,fee,slip)[0];if(!signal)continue;
   total++;
   if(i+1>=bars.length){unknown++;continue;}
   const entry=bars[i+1].o;
   if(Math.abs(entry-signal.entry)>0.15*(signal.entry-signal.stop)){skipped++;continue;}
   const plan=candidate({...signal,entry,confirmed:true});if(!plan){skipped++;continue;}
   if(i+24>=bars.length){unknown++;break;}
   let exit=bars[i+24].c,outcome="timeout",last=i+24;
   for(let k=i+1;k<=i+24;k++){const z=bars[k];if(z.l<=plan.stop){exit=Math.min(z.o,plan.stop);outcome="stop";last=k;break;}if(z.h>=plan.target){exit=plan.target;outcome="target";last=k;break;}}
   const rate=(fee+slip)/10000;
   const R=(exit-entry-(entry+exit)*rate)/plan.risk;
   const qty=Math.min(.0025*equity/plan.risk,equity/(entry*(1+rate)));
   const pnl=qty*plan.risk*R;equity+=pnl;peak=Math.max(peak,equity);dd=Math.max(dd,(peak-equity)/peak);
   trades.push({time:new Date(now).toISOString(),R,pnl,entry,exit,stop:plan.stop,target:plan.target,outcome});blockedUntil=bars[last].t+ms;
  }
 }
 const n=trades.length,win=trades.filter(x=>x.R>0),loss=trades.filter(x=>x.R<0);
 const sum=trades.reduce((s,x)=>s+x.R,0),den=-loss.reduce((s,x)=>s+x.R,0);
 return {n,mean:n?sum/n:null,pf:den?win.reduce((s,x)=>s+x.R,0)/den:null,win:n?win.length/n:null,equity,dd,unknown,events5,paired,candidates:total,skipped,records:trades};
}
const results={};
for(const [name,start,end] of [["2022-23","2022-01-01","2024-01-01"],["2026","2026-04-01","2026-10-01"]]){
 const groups=load(name);results[name]={};
 for(const [cost,fee,slip] of [["normal",5,2],["stress",8,4]]){
  const q=replay(groups,start,end,fee,slip);results[name][cost]=q;
  const {records,...summary}=q;console.log("B07="+JSON.stringify({period:name,cost,...summary}));
 }
}
writeFileSync("lab-b07.json",JSON.stringify({results,limitations:"Exact detectEvents and fromEvents/candidate imports, same 300-bar windows and next-5m-open/24-bar timeout/stop-first logic as historical_tactical; verified Binance spot instead of OKX, gap segmentation and capital sizing added. Original candidate gate re-evaluated at entry. Spot proxy excludes funding, not directly comparable to futures models. No live execution, no holdout, no tuning."},null,2));
