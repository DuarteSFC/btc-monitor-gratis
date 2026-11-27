// Executed buyer-initiated volume is observable; it is not order-book imbalance or proof of absorption.
const sum=(a,f)=>a.reduce((s,z)=>s+f(z),0);
export function flowFeatures(b){
 if(b.length<61)return null;
 const x=b.slice(-61),z=x.at(-1),past=x.slice(0,-1);
 if(x.some((v,i)=>![v.t,v.o,v.h,v.l,v.c,v.v,v.q,v.n,v.buy].every(Number.isFinite)||v.l<=0||v.v<0||v.q<0||v.n<0||!Number.isInteger(v.n)||v.buy<0||v.buy>v.q+1e-6||v.h<Math.max(v.o,v.c)||v.l>Math.min(v.o,v.c)||(i&&v.t-x[i-1].t!==60000)))return null;
 const imbalance=a=>{const total=sum(a,v=>v.q);return total>0?2*sum(a,v=>v.buy)/total-1:0;};
 const prev=past.slice(-30),recent=x.slice(-5),older=past.slice(-10,-5);
 const nBase=sum(prev,v=>v.n)/30,qBase=sum(prev,v=>v.q)/30;
 const f5=imbalance(recent),f30=imbalance(x.slice(-30));
 const ret=Math.log(z.c/x.at(-6).c);
 return [imbalance(x.slice(-3)),f5,f30,f5-imbalance(older),f5-f30,Math.log1p(z.n/Math.max(1,nBase)),Math.log1p(z.q/Math.max(1,qBase)),f5*ret];
}
