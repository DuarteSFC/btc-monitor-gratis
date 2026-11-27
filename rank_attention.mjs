// Research-only ranking of future market observations; not an entry strategy.
const clip=(x,l,h)=>Math.max(l,Math.min(h,x));
const sigmoid=x=>1/(1+Math.exp(-clip(x,-40,40)));
const mean=a=>a.reduce((s,x)=>s+x,0)/a.length;
const hi=a=>Math.max(...a.map(z=>z.h)),lo=a=>Math.min(...a.map(z=>z.l));
export function rankFeatures(b,f){
 if(!f||b.length<181)return null;
 const x=b.slice(-181),z=x.at(-1),past=x.slice(0,-1);
 if(x.some((v,i)=>![v.t,v.o,v.h,v.l,v.c,v.v].every(Number.isFinite)||v.l<=0||v.v<0||v.h<Math.max(v.o,v.c)||v.l>Math.min(v.o,v.c)||(i&&v.t-x[i-1].t!==60000)))return null;
 const ret=n=>Math.log(z.c/x.at(-n-1).c);
 const range=n=>Math.log(hi(past.slice(-n))/lo(past.slice(-n)));
 const flow=a=>{const total=a.reduce((s,q)=>s+q.v,0);return total>0?a.reduce((s,q)=>s+q.v*Math.sign(q.c-q.o),0)/total:0;};
 const room=(hi(past.slice(-60))-z.c)/z.c,away=(z.c-lo(past.slice(-20)))/z.c;
 const values=[ret(5),ret(15),ret(60),ret(180),range(15),range(60),f.atrPct,Math.log1p(f.rel),f.closeLoc,f.body,f.compression,f.exhaustion,flow(past.slice(-10)),flow(past.slice(-30,-10)),room,away,Number(f.rising),Number(f.reclaim)];
 return values.every(Number.isFinite)?values:null;
}
export function fitRanker(rows,{iterations=240,lambda=.025,rate=.3}={}){
 if(!rows.length)throw Error("No training rows");
 const n=rows[0].x.length;
 if(!n||rows.some(r=>r.x.length!==n||r.x.some(v=>!Number.isFinite(v))||![0,1].includes(r.y)))throw Error("Invalid training rows");
 const mu=Array.from({length:n},(_,i)=>mean(rows.map(r=>r.x[i])));
 const sd=mu.map((m,i)=>Math.max(1e-8,Math.sqrt(mean(rows.map(r=>(r.x[i]-m)**2)))));
 const xx=rows.map(r=>r.x.map((v,i)=>clip((v-mu[i])/sd[i],-6,6)));
 const p=clip(mean(rows.map(r=>r.y)),1e-5,1-1e-5);
 let intercept=Math.log(p/(1-p));const w=Array(n).fill(0);
 for(let k=0;k<iterations;k++){
  const g=Array(n).fill(0);let bias=0;
  for(let j=0;j<rows.length;j++){
   const x=xx[j],err=sigmoid(intercept+w.reduce((s,v,i)=>s+v*x[i],0))-rows[j].y;
   bias+=err;for(let i=0;i<n;i++)g[i]+=err*x[i];
  }
  intercept-=rate*bias/rows.length;
  for(let i=0;i<n;i++)w[i]-=rate*(g[i]/rows.length+lambda*w[i]);
 }
 return {mu,sd,w,intercept,lambda,trainingRows:rows.length};
}
export function scoreRanker(model,x){
 if(!x||x.length!==model.w.length||x.some(v=>!Number.isFinite(v)))throw Error("Invalid score features");
 return sigmoid(model.intercept+model.w.reduce((s,v,i)=>s+v*clip((x[i]-model.mu[i])/model.sd[i],-6,6),0));
}
// Label at actual dispatch plus additional delay; conservative same-bar ordering.
export function observe(b,i,delay=1){
 const j=i+1+delay;if(j+29>=b.length)return null;
 const px=b[j].o,up=px*1.005,down=px*.9975;
 for(let k=j;k<j+30;k++){if(b[k].l<=down)return "down";if(b[k].h>=up)return "up";}
 return "neither";
}
export function selectAlerts(rows,accept,cooldown=30*60000){
 let last=-Infinity;const selected=[];
 for(const r of rows){if(r.t-last<cooldown||!accept(r))continue;selected.push(r);last=r.t;}
 return selected;
}
export function summarize(rows,selected,days){
 const counts={};for(const d of [0,1,2]){counts[d]={up:0,down:0,neither:0};for(const r of selected)counts[d][r.outcomes[d]]++;}
 // A positive-window episode is a group of positive 5m windows separated by <=30m.
 const positives=rows.filter(r=>r.outcomes[1]==="up");const chosen=new Set(selected.filter(r=>r.outcomes[1]==="up").map(r=>r.t));
 let episodes=0,covered=0,last=-Infinity,hit=false;
 for(const r of positives){if(r.t-last>30*60000){if(hit)covered++;episodes++;hit=false;}if(chosen.has(r.t))hit=true;last=r.t;}if(hit)covered++;
 return {alerts:selected.length,perDay:selected.length/days,outcomes:counts,positiveWindowEpisodes:episodes,coveredPositiveWindowEpisodes:covered};
}
export function chooseThreshold(rows,days){
 const sorted=rows.map(r=>r.score).sort((a,b)=>a-b);
 const options=[.90,.95,.975,.99].map(q=>{
  const threshold=sorted[Math.min(sorted.length-1,Math.floor(q*sorted.length))];
  const selected=selectAlerts(rows,r=>r.score>=threshold);
  const hits=selected.filter(r=>r.outcomes[1]==="up").length;
  return {q,threshold,n:selected.length,perDay:selected.length/days,precision:hits/Math.max(1,selected.length)};
 });
 // Freeze selection on calibration only; no optimization on the final period.
 const eligible=options.filter(o=>o.n>=25&&o.perDay<=3);
 const winner=eligible.sort((a,b)=>b.precision-a.precision||b.n-a.n)[0]??null;
 return {winner,options};
}
