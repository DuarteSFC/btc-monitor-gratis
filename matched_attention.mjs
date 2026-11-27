import {selectAlerts} from "./rank_attention.mjs";
export function matchedThreshold(rows,target){
 if(!rows.length||!Number.isInteger(target)||target<1||rows.some(r=>!Number.isFinite(r.score)))throw Error("Invalid calibration");
 // Threshold choice uses calibration scores and count only, not outcomes.
 const sorted=rows.map(r=>r.score).sort((a,b)=>a-b);
 const qs=Array.from({length:101},(_,i)=>.90+i*.00099);
 const options=qs.map(q=>{const threshold=sorted[Math.min(sorted.length-1,Math.floor(q*sorted.length))];const n=selectAlerts(rows,r=>r.score>=threshold).length;return {threshold,n,q};});
 return options.sort((a,b)=>Math.abs(a.n-target)-Math.abs(b.n-target)||a.n-b.n)[0];
}
export function netBarrier(entry,stop,cost=.0007,rr=2){
 if(![entry,stop,cost,rr].every(Number.isFinite)||!(entry>stop&&stop>0&&cost>=0&&cost<.01&&rr>=2))throw Error("Invalid barrier");
 const risk=entry-stop+cost*(entry+stop);
 const target=(entry*(1+cost)+rr*risk)/(1-cost);
 return {entry,stop,target,risk,cost,rr};
}
export function simulateSelected(b,selected,{delay=1,horizon=60,cost=.0007}={}){
 let until=-1;const trades=[];let skipped=0,uncovered=0;
 for(const r of selected){
  const j=r.i+1+delay;if(j<until){skipped++;continue;}if(j+horizon>b.length){uncovered++;continue;}
  const entry=b[j].o,p=netBarrier(entry,entry*.9975,cost,2);
  let exit=b[j+horizon-1].c,reason="time",used=horizon;
  for(let k=j;k<j+horizon;k++){
   const z=b[k];if(z.l<=p.stop){exit=Math.min(z.o,p.stop);reason="stop";used=k-j+1;break;}
   if(z.h>=p.target){exit=p.target;reason="target";used=k-j+1;break;}
  }
  until=j+used;
  const R=(exit-entry-cost*(entry+exit))/p.risk;
  trades.push({t:r.t,R,reason});
 }
 const n=trades.length,netR=trades.reduce((s,r)=>s+r.R,0);
 const daily={};for(const r of trades){const d=new Date(r.t).toISOString().slice(0,10);const q=daily[d]??(daily[d]={trades:0,netR:0});q.trades++;q.netR+=r.R;}
 return {n,netR,meanR:n?netR/n:null,wins:trades.filter(r=>r.R>0).length,targets:trades.filter(r=>r.reason==="target").length,stops:trades.filter(r=>r.reason==="stop").length,time:trades.filter(r=>r.reason==="time").length,skipped,uncovered,daily};
}
