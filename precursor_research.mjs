// Research only: pre-impulse observations, not live entry signals.
// Features use closed, consecutive 1M bars. No future labels or live account data.
const mean=a=>a.reduce((s,v)=>s+v,0)/a.length;
const hi=a=>Math.max(...a.map(z=>z.h)),lo=a=>Math.min(...a.map(z=>z.l));
const rng=a=>hi(a)-lo(a);
const vol=a=>mean(a.map(z=>z.v));
export function featuresAt(b){
 if(b.length<61)return null;
 const x=b.slice(-61),z=x.at(-1),p=x.slice(0,-1);
 if(x.some((v,i)=>![v.t,v.o,v.h,v.l,v.c,v.v].every(Number.isFinite)||v.l<=0||v.v<0||v.h<Math.max(v.o,v.c)||v.l>Math.min(v.o,v.c)||(i&&v.t-x[i-1].t!==60000)))return null;
 const tr=p.slice(1).map((v,i)=>Math.max(v.h-v.l,Math.abs(v.h-p[i].c),Math.abs(v.l-p[i].c)));
 const a=mean(tr.slice(-20)),v=vol(p.slice(-30));
 if(!(a>0&&v>0))return null;
 const last=p.slice(-10),prior=p.slice(-30,-10),recent=x.slice(-5),older=p.slice(-15,-4);
 const rel=z.v/v,body=(z.c-z.o)/a,closeLoc=(z.c-z.l)/Math.max(z.h-z.l,1e-12);
 const priorLow=lo(prior),localLow=lo(last),localHigh=hi(last),longHigh=hi(p);
 const compression=rng(last)/Math.max(rng(prior),1e-12);
 const trend=(p.at(-1).c-p[0].c)/a;
 const drift=(z.c-x.at(-6).c)/a;
 const exhaustion=vol(last.filter(q=>q.c<q.o).length?last.filter(q=>q.c<q.o):last)/v;
 const bullCount=recent.filter(q=>q.c>q.o).length;
 return {t:z.t+60000,close:z.c,atr:a,atrPct:a/z.c,rel,body,closeLoc,trend,drift,compression,exhaustion,bullCount,localLow,localHigh,priorLow,longHigh,
  rising:lo(p.slice(-5))>lo(p.slice(-10,-5))&&localLow>=priorLow,
  reclaim:z.l<localLow&&z.c>localLow&&closeLoc>=.65,
  retest:z.l<=hi(older)&&z.c>hi(older)&&closeLoc>=.6,
  nearTop:(localHigh-z.c)/a,
  room:(longHigh-z.c)/a,
  priorSell:(p.at(-11).c-p.at(-1).c)/a,
  pressure:mean(last.map(q=>(q.c-q.o)/a)),
  lowVol:vol(last)/v};
}
export function precursorAt(b){
 const f=featuresAt(b);if(!f)return [];
 const out=[];
 const add=(name,level)=>out.push({name,level,close:f.close,atr:f.atr,t:f.t,classification:"research_only"});
 // Avoid chasing: no isolated large body or large five-minute price displacement.
 if(f.body>1.3||f.drift>2.5||f.rel>4||f.body<=0)return out;
 if(f.compression<=.65&&f.rising&&f.nearTop>=-.3&&f.nearTop<=1.2&&f.lowVol<=1&&f.room>=1)add("compression_rising",f.localHigh);
 if(f.priorSell>=1.8&&f.reclaim&&f.rel>=.8&&f.room>=2)add("sell_exhaustion_reclaim",f.localLow);
 if(f.rising&&f.exhaustion<=.8&&f.bullCount>=3&&f.closeLoc>=.6&&f.room>=2&&f.trend>=-3)add("rising_lows_dry_sell",f.localLow);
 if(f.retest&&f.rising&&f.rel>=.7&&f.room>=1.5&&f.trend>0)add("quiet_retest",f.localLow);
 return out;
}
