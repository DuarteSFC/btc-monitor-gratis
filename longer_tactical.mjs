import {netBarrier} from "./matched_attention.mjs";
const M=60000,avg=a=>a.reduce((s,v)=>s+v,0)/a.length;
export function aggregate(b,n){
 const out=[];
 for(let i=0;i+n<=b.length;i++){
  if(b[i].t%(n*M))continue;
  const x=b.slice(i,i+n);
  if(x.some((z,j)=>z.t!==x[0].t+j*M))throw Error("Noncontiguous bars");
  out.push({t:x[0].t,end:x[0].t+n*M,o:x[0].o,h:Math.max(...x.map(z=>z.h)),l:Math.min(...x.map(z=>z.l)),c:x.at(-1).c,v:x.reduce((s,z)=>s+z.v,0),i:i+n-1});
 }
 return out;
}
export function emaSeries(b,n){
 let e=null;return b.map(z=>{e=e===null?z.c:e+(z.c-e)*2/(n+1);return e;});
}
export function candidates(b){
 const five=aggregate(b,5),quarter=aggregate(b,15),hour=aggregate(b,60);
 const e20=emaSeries(hour,20),e50=emaSeries(hour,50),q20=emaSeries(quarter,20);
 const out={clock:[],trend_pullback:[],sweep_reclaim:[],compression_break:[]};
 let h=0,q=0;
 for(let k=60;k<five.length;k++){
  const z=five[k],t=z.end;
  while(h+1<hour.length&&hour[h+1].end<=t)h++;
  while(q+1<quarter.length&&quarter[q+1].end<=t)q++;
  if(h<200||q<40||hour[h].end>t||quarter[q].end>t)continue;
  const atr=avg(quarter.slice(q-13,q+1).map((a,j)=>{const prev=quarter[q-14+j].c;return Math.max(a.h-a.l,Math.abs(a.h-prev),Math.abs(a.l-prev));}));
  if(!(atr>0))continue;
  const prev=five.slice(k-12,k),last=five.slice(k-6,k),p=z.c,high=Math.max(...prev.map(a=>a.h)),low=Math.min(...prev.map(a=>a.l));
  const bullish=hour[h].c>e20[h]&&e20[h]>e50[h]&&e20[h]>e20[h-6];
  const body=z.c-z.o,loc=(z.c-z.l)/Math.max(1e-9,z.h-z.l);
  const recentLow=Math.min(z.l,...last.map(a=>a.l));
  const make=(support)=>({t,i:z.i,reference:p,atr,stop:Math.min(p*.994,support-.15*atr)});
  if(t%(8*60*M)===0)out.clock.push(make(p*.994+.15*atr));
  // Three frozen hypotheses: no tuning on held-out periods.
  if(bullish&&recentLow<=q20[q]&&p>q20[q]&&body>0&&loc>=.65&&p<=q20[q]+atr&&p>last.at(-1).h)out.trend_pullback.push(make(recentLow));
  if(hour[h].c>=e50[h]&&z.l<low&&p>low&&body>0&&loc>=.65&&body<=1.2*atr)out.sweep_reclaim.push(make(z.l));
  if(bullish&&high-low<=2*atr&&p>high&&body>0&&body<=atr&&loc>=.65&&z.v>=avg(prev.map(a=>a.v)))out.compression_break.push(make(recentLow));
 }
 return out;
}
export function evaluate(b,signals,{delay=1,horizon=240,cost=.0007,from=-Infinity,to=Infinity}={}){
 let until=-1;const trades=[];let skipped=0,rejected=0,boundary=0;
 for(const r of signals){
  if(r.t<from||r.t>=to)continue;
  const j=r.i+1+delay;
  if(j<until){skipped++;continue;}
  if(j+horizon>b.length||b[j+horizon-1].t+M>to){boundary++;continue;}
  const entry=b[j].o,d=(entry-r.stop)/entry;
  if(!(d>=.004&&d<=.015)||entry>r.reference+.25*r.atr){rejected++;continue;}
  const p=netBarrier(entry,r.stop,cost,2);
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
 const daily={};let equity=0,peak=0,drawdown=0;
 for(const r of trades){const d=new Date(r.t).toISOString().slice(0,10);const q=daily[d]??(daily[d]={n:0,netR:0});q.n++;q.netR+=r.R;equity+=r.R;peak=Math.max(peak,equity);drawdown=Math.max(drawdown,peak-equity);}
 return {n,netR,meanR:n?netR/n:null,wins:trades.filter(r=>r.R>0).length,targets:trades.filter(r=>r.reason==="target").length,stops:trades.filter(r=>r.reason==="stop").length,time:trades.filter(r=>r.reason==="time").length,drawdown,skipped,rejected,boundary,daily};
}
