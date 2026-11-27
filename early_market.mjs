// Public market attention only. No predictive or entry classification.
const MS=60000;
const finite=b=>[b.t,b.o,b.h,b.l,b.c,b.v].every(Number.isFinite)&&b.l>0&&b.h>=Math.max(b.o,b.c)&&b.l<=Math.min(b.o,b.c)&&b.v>=0;
export function attentionAt(bars,source="OKX BTC/USDT",now=Date.now()){
 if(bars.length<24)return null;
 const x=bars.slice(-24),z=x.at(-1),end=z.t+MS;
 if(end>now||x.some((b,i)=>!finite(b)||(i&&b.t-x[i-1].t!==MS)))return null;
 const p=x.slice(-21,-1),avg=p.reduce((s,b)=>s+b.v,0)/20;
 const a=p.reduce((s,b,i)=>s+Math.max(b.h-b.l,Math.abs(b.h-x[i+2].c),Math.abs(b.l-x[i+2].c)),0)/20;
 if(!(avg>0&&a>0))return null;
 const body=z.c-z.o,range=z.h-z.l,v=z.v/avg,loc=range>0?(z.c-z.l)/range:0;
 const tail=x.slice(-3),before=x.slice(-23,-3),avg3=before.reduce((s,b)=>s+b.v,0)/20;
 const delta=z.c-tail[0].o,vol3=avg3>0?tail.reduce((s,b)=>s+b.v,0)/(3*avg3):0;
 let pattern=null,level=null;
 if(v>=4&&body>=.65*a&&loc>=.65){pattern="volume_acceleration";level=z.o;}
 else if(delta>=1.5*a&&vol3>=1.5&&tail.filter(b=>b.c>b.o).length>=2&&z.c>Math.max(...x.slice(-9,-3).map(b=>b.h))&&loc>=.55){pattern="three_minute_acceleration";level=Math.max(...x.slice(-9,-3).map(b=>b.h));}
 if(!pattern)return null;
 return {id:"1M:attention:"+end,frame:"1M",type:"early_attention",pattern,source,closedUtc:new Date(end).toISOString(),level,close:z.c,low:Math.min(...tail.map(b=>b.l)),volumeVs20:v,volume3Vs20:vol3,bodyVsAtr:body/a,threeMinuteMoveVsAtr:delta/a,classification:"observed_market_attention_not_entry"};
}
export function attentionEvents(bars,source,now,windowMs=1200000){
 const out=[];
 for(let i=Math.max(23,bars.length-Math.ceil(windowMs/MS)-1);i<bars.length;i++){
  const end=bars[i].t+MS;if(end>now||now-end>windowMs)continue;
  const e=attentionAt(bars.slice(Math.max(0,i-23),i+1),source,now);if(e)out.push(e);
 }
 return out;
}
// Only the added tier is cooled down. Baseline 5M/15M alerts are never removed.
export function chooseAttention(events,baseline,seen,last,now){
 return events.filter(e=>{const t=Date.parse(e.closedUtc),age=now-t;
  return age>=0&&age<=600000&&!seen.has(e.id)&&(!last||t-last>=600000)&&
   !baseline.some(b=>["breakout","recovery_impulse","sweep_recovery"].includes(b.type)&&Math.abs(Date.parse(b.closedUtc)-t)<=300000);
 }).sort((a,b)=>Date.parse(b.closedUtc)-Date.parse(a.closedUtc)).slice(0,1);
}
