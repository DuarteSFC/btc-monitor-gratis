import {readFile} from "node:fs/promises";
import {candidates,evaluate} from "./longer_tactical.mjs";
const path=process.argv[2]??"/tmp/tactical-longer",ms=60000;
async function readMonths(months,market){
 const b=[];
 for(const m of months){
  const text=await readFile(path+"/"+market+"/"+m+".csv","utf8");
  for(const line of text.trim().split(/\r?\n/)){
   const a=line.split(",").map(Number);if(a.length!==9||a.some(v=>!Number.isFinite(v)))throw Error("bad public row");
   const [t,o,h,l,c,v,q,n,buy]=a;
   if(l<=0||h<Math.max(o,c)||l>Math.min(o,c)||v<0||q<0||n<0||!Number.isInteger(n)||buy<0||buy>q+1e-6)throw Error("invalid candle");
   if(b.length&&t-b.at(-1).t!==ms)throw Error("archive discontinuity");
   b.push({t,o,h,l,c,v,q,n,buy});
  }
 }
 return b;
}




const months=(y,a,b)=>Array.from({length:b-a+1},(_,i)=>y+"-"+String(a+i).padStart(2,"0"));
const dev=await readMonths(months(2024,1,12),"spot"),stress=await readMonths(months(2026,7,9),"spot");
const dc=candidates(dev),sc=candidates(stress),ts=s=>Date.parse(s+"T00:00:00Z");
const periods={train:{b:dev,c:dc,from:ts("2024-01-01"),to:ts("2024-07-01")},cal:{b:dev,c:dc,from:ts("2024-07-01"),to:ts("2024-10-01")},hold:{b:dev,c:dc,from:ts("2024-10-01"),to:ts("2025-01-01")},stress:{b:stress,c:sc,from:ts("2026-07-01"),to:ts("2026-10-01")}};
const configs=[{delay:1,horizon:240,cost:.0007},{delay:5,horizon:240,cost:.0007},{delay:1,horizon:240,cost:.001},{delay:5,horizon:240,cost:.001},{delay:1,horizon:480,cost:.0007},{delay:5,horizon:480,cost:.0007}];
const results={};
for(const name of Object.keys(dc)){
 results[name]={};
 for(const [key,p] of Object.entries(periods)){
  results[name][key]=configs.map(c=>({config:c,...evaluate(p.b,p.c[name],{...c,from:p.from,to:p.to})}));
 }
}
const eligible=Object.keys(dc).filter(n=>n!=="clock"&&["train","cal"].every(p=>results[n][p].slice(0,4).every(r=>r.n>=25&&r.meanR>0)));
const selected=eligible.sort((a,b)=>Math.min(...results[b].cal.slice(0,4).map(r=>r.meanR))-Math.min(...results[a].cal.slice(0,4).map(r=>r.meanR)))[0]??null;
console.log(JSON.stringify({bars:{dev:dev.length,stress:stress.length},selected,periods:Object.fromEntries(Object.entries(periods).map(([k,p])=>[k,{from:p.from,to:p.to}])),results,notice:"Frozen exploratory hypotheses. Select only on train/cal, minimum 25 trades and positive mean under four primary cost/delay scenarios. Hold and stress are diagnostic, never used to select. Spot candle fills are hypothetical; no funding or account data; costs assumed; no live entry or delivery. Stop from known structure with 0.6% minimum at signal and 1.5% max at entry. 4h primary, 8h sensitivity. 2026 stress reused elsewhere in this line."},null,2));
