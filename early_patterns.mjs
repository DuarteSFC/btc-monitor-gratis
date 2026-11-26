// Experimental observations only; no entry or execution.
import {atr,rsi} from "./worker.mjs";
export function earlyPatterns(bars,ms=60000){
 if(bars.length<36||!Number.isFinite(ms)||ms<=0)return [];
 if(bars.slice(-36).some(b=>![b.t,b.o,b.h,b.l,b.c,b.v].every(Number.isFinite)||b.l<=0||b.h<Math.max(b.o,b.c)||b.l>Math.min(b.o,b.c)||b.v<0))return [];
 const z=bars.at(-1),p=bars.slice(-21,-1),a=atr(bars.slice(0,-1));
 if(!(a>0)||bars.slice(-36).some((b,i,s)=>i&&b.t-s[i-1].t!==ms))return [];
 const high=Math.max(...p.map(b=>b.h)),low=Math.min(...p.map(b=>b.l)),v=z.v/(p.reduce((s,b)=>s+b.v,0)/20);
 if(!Number.isFinite(v))return [];
 const recent=p.slice(-6),older=p.slice(-12,-6),lo=x=>Math.min(...x.map(b=>b.l)),hi=x=>Math.max(...x.map(b=>b.h));
 const rising=lo(recent)>lo(older), bullish=z.c>z.o, range=z.h-z.l, recovery=range>0&&(z.c-z.l)/range>=.65;
 const out=[];const add=(type,level)=>out.push({type,level,closedUtc:new Date(z.t+ms).toISOString(),close:z.c,volumeVs20:v,classification:"experimental_prealert_not_entry"});
 if(bullish&&rising&&z.c>recent.at(-1).h&&rsi(bars.map(b=>b.c))>45&&z.c<high)add("early_reversal",lo(recent));
 if(z.l<low&&z.c>low&&bullish&&recovery&&v>=1.2)add("sweep_recovery",low);
 if(rising&&hi(recent)-lo(recent)<.75*(hi(older)-lo(older))&&high-z.c>=0&&high-z.c<a&&z.c>z.o)add("compression",high);
 if(rising&&hi(older)-lo(older)>3*a&&z.l<=hi(older)&&z.c>hi(older)&&bullish&&recovery)add("continuation",hi(older));
 return out;
}
