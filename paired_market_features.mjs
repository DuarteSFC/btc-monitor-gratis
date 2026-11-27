// Paired spot and USD-M perpetual trades. No inferred open interest or liquidations.
const sum=(a,f)=>a.reduce((s,z)=>s+f(z),0);
const valid=(z)=>[z.t,z.o,z.h,z.l,z.c,z.q,z.buy,z.n].every(Number.isFinite)&&z.o>0&&z.c>0&&z.l>0&&z.h>=Math.max(z.o,z.c)&&z.l<=Math.min(z.o,z.c)&&z.q>=0&&z.buy>=0&&z.buy<=z.q+1e-6&&Number.isInteger(z.n)&&z.n>=0;
export function pairedFeatures(s,p){
 if(s.length!==61||p.length!==61)return null;
 if(s.some((z,i)=>!valid(z)||!valid(p[i])||z.t!==p[i].t||(i&&z.t-s[i-1].t!==60000)))return null;
 const basis=i=>Math.log(p[i].c/s[i].c);
 const imbalance=(x,n)=>{const a=x.slice(-n),q=sum(a,z=>z.q);return q>0?2*sum(a,z=>z.buy)/q-1:0;};
 const rel=(x,n)=>{const a=x.slice(-n),prior=x.slice(-n-30,-n),base=sum(prior,z=>z.q)/30;return base>0?Math.log1p(sum(a,z=>z.q)/n/base):0;};
 const b=basis(60);
 const priorBasis=Array.from({length:60},(_,i)=>basis(i)).reduce((a,v)=>a+v,0)/60;
 const v=[b,b-priorBasis,b-basis(55),b-basis(45),imbalance(p,5),imbalance(p,30),imbalance(p,5)-imbalance(s,5),imbalance(p,30)-imbalance(s,30),rel(p,5)-rel(s,5),rel(p,15)-rel(s,15)];
 return v.every(Number.isFinite)?v:null;
}
