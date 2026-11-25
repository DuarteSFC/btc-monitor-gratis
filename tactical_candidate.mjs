import {atr,ema,rsi,macd} from "./worker.mjs";
// Explicit hypothetical costs; never an execution signal.
export function candidate({entry,stop,target,feeBps,slippageBps,confirmed=false}){
 if(![entry,stop,target,feeBps,slippageBps].every(Number.isFinite)||stop<=0||entry<=stop||target<=entry||feeBps<0||slippageBps<0||!confirmed)return null;
 const rate=(feeBps+slippageBps)/10000;
 const risk=entry-stop+(entry+stop)*rate;
 const reward=target-entry-(entry+target)*rate;
 const rr=reward/risk;
 return rr>=2?{entry,stop,target,risk,reward,rr,feeBps,slippageBps,classification:"hypothetical_candidate_not_entry"}:null;
}
export function fromEvents(events,now,feeBps,slippageBps){
 const result=[];
 for(const e of events){
 if(e.frame!=="5M"||!["breakout","sweep_recovery"].includes(e.type)||now-Date.parse(e.closedUtc)>600000||now<Date.parse(e.closedUtc))continue;
 const confirmation=events.find(x=>x.frame==="15M"&&["breakout","sweep_recovery","recovery_impulse"].includes(x.type)&&Date.parse(x.closedUtc)<=Date.parse(e.closedUtc)&&Date.parse(e.closedUtc)-Date.parse(x.closedUtc)<=900000);
 if(!confirmation)continue;
 const target=confirmation.high;
 const c=candidate({entry:e.close,stop:Math.min(e.low,e.level)-0.1*e.atrBefore,target,feeBps,slippageBps,confirmed:true});
 if(c)result.push({...c,id:e.id+":candidate",closedUtc:e.closedUtc,frame:e.frame});
 }
 return result;
}

// Research model: confirmed 5m retest, closed 15m trend, nearest material
// resistance known before the signal. No projected targets or live orders.
export function fromBars({five,fifteen,events,now,feeBps=5,slippageBps=2}){
 const f=five.filter(b=>b.t+300000<=now).slice(-300),g=fifteen.filter(b=>b.t+900000<=now).slice(-300);
 if(f.length<50||g.length<100)return [];
 const z=f.at(-1),end=z.t+300000,last15=g.at(-1);
 if(now-end>=300000||now-(last15.t+900000)>=900000)return [];
 const a=atr(f.slice(0,-1)),a15=atr(g),closes=g.map(b=>b.c);
 const e20=ema(closes,20),r=rsi(closes),m=macd(closes),priorM=macd(closes.slice(0,-1));
 if(!(a>0&&a15>0&&last15.c>=e20?.at(-1)&&e20.at(-1)>=e20.at(-2)&&r>=45&&r<=72&&(m?.histogram>0||m?.histogram>=priorM?.histogram)))return [];
 const levels=[];
 const history=g.slice(-96);
 for(let i=3;i<history.length-3;i++){
  const b=history[i],left=history.slice(i-3,i),right=history.slice(i+1,i+4);
  const prominence=b.h-Math.max(Math.min(...left.map(x=>x.l)),Math.min(...right.map(x=>x.l)));
  if([...left,...right].every(x=>b.h>x.h)&&prominence>=0.5*a15&&b.h>z.c)levels.push(b.h);
 }
 if(!levels.length)return [];
 const target=Math.min(...levels)-0.1*a15;
 const setups=events.filter(e=>e.frame==="5M"&&["breakout","sweep_recovery"].includes(e.type)&&Number.isFinite(e.level)&&end-Date.parse(e.closedUtc)>=300000&&end-Date.parse(e.closedUtc)<=1800000).sort((a,b)=>Date.parse(b.closedUtc)-Date.parse(a.closedUtc));
 for(const e of setups){
  const level=e.level,range=z.h-z.l;
  if(!(range>0&&z.l<=level+0.3*a&&z.l>=level-0.8*a&&z.c>level&&z.c<=level+1.25*a&&z.c>z.o&&(z.c-z.l)/range>=0.6))continue;
  if(f.some(b=>b.t>=Date.parse(e.closedUtc)&&b.t<z.t&&b.c<level-0.25*a))continue;
  const stop=Math.min(z.l,level)-0.2*a;
  const plan=candidate({entry:z.c,stop,target,feeBps,slippageBps,confirmed:true});
  if(plan)return [{...plan,id:e.id+":retest-candidate",setupId:e.id,closedUtc:new Date(end).toISOString(),frame:"5M",level,model:"closed_retest_v1",rsi15:r,atr5:a,atr15:a15}];
 }
 return [];
}
