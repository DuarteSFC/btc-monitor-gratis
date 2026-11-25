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
