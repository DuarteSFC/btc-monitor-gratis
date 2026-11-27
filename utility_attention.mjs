// Research-only expected net risk units regression. Not a calibrated probability.
const mean=a=>a.reduce((s,v)=>s+v,0)/a.length;
const clip=(x,l,h)=>Math.max(l,Math.min(h,x));
export function fitUtility(rows,lambda=.1){
 if(!rows.length||!Number.isFinite(lambda)||lambda<=0)throw Error("Invalid fit");
 const n=rows[0].x.length;
 if(!n||rows.some(r=>r.x.length!==n||r.x.some(v=>!Number.isFinite(v))||!Number.isFinite(r.y)))throw Error("Invalid training rows");
 const mu=Array.from({length:n},(_,i)=>mean(rows.map(r=>r.x[i])));
 const sd=mu.map((m,i)=>Math.max(1e-8,Math.sqrt(mean(rows.map(r=>(r.x[i]-m)**2)))));
 const xx=rows.map(r=>r.x.map((v,i)=>clip((v-mu[i])/sd[i],-6,6)));
 let bias=mean(rows.map(r=>r.y));const w=Array(n).fill(0);
 for(let k=0;k<350;k++){
  const g=Array(n).fill(0);let gb=0;
  for(let j=0;j<rows.length;j++){
   const x=xx[j],err=bias+w.reduce((s,v,i)=>s+v*x[i],0)-rows[j].y;
   gb+=err;for(let i=0;i<n;i++)g[i]+=err*x[i];
  }
  bias-=.025*gb/rows.length;
  for(let i=0;i<n;i++)w[i]-=.025*(g[i]/rows.length+lambda*w[i]);
 }
 if(![bias,...w].every(Number.isFinite))throw Error("Nonfinite fit");
 return {mu,sd,w,bias,lambda};
}
export function scoreUtility(m,x){
 if(x.length!==m.w.length||x.some(v=>!Number.isFinite(v)))throw Error("Invalid scoring row");
 return m.bias+m.w.reduce((s,v,i)=>s+v*clip((x[i]-m.mu[i])/m.sd[i],-6,6),0);
}
export function utilityLabel(b,i,netBarrier,delay=1,horizon=60,cost=.0007){
 const j=i+1+delay;if(j+horizon>b.length)return null;
 const entry=b[j].o,p=netBarrier(entry,entry*.9975,cost,2);
 let exit=b[j+horizon-1].c;
 for(let k=j;k<j+horizon;k++){
  const z=b[k];if(z.l<=p.stop){exit=Math.min(z.o,p.stop);break;}
  if(z.h>=p.target){exit=p.target;break;}
 }
 return (exit-entry-cost*(entry+exit))/p.risk;
}
