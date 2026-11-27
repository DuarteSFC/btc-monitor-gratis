// Research only. A price alert is not a trade.
export function netPlan(entry,stop,target,sideCost=.0007){
 if(![entry,stop,target,sideCost].every(Number.isFinite)||!(entry>stop&&stop>0&&target>entry&&sideCost>=0&&sideCost<.01))return null;
 const grossRisk=entry-stop,risk=grossRisk+sideCost*(entry+stop),reward=target-entry-sideCost*(entry+target);
 if(grossRisk/entry<.002||grossRisk/entry>.015||reward/risk<2)return null;
 return {entry,stop,target,risk,reward,rr:reward/risk};
}
export function simulatePlan(plan,bars,sideCost=.0007){
 if(!plan||!bars.length)return null;
 let exit=bars.at(-1).c,reason="time",used=bars.length,adverse=0,favorable=0;
 for(let i=0;i<bars.length;i++){
  const z=bars[i];adverse=Math.max(adverse,plan.entry-z.l);favorable=Math.max(favorable,z.h-plan.entry);
  // If both barriers occur in the same minute, take the adverse outcome.
  if(z.l<=plan.stop){exit=Math.min(z.o,plan.stop);reason="stop";used=i+1;break;}
  if(z.h>=plan.target){exit=plan.target;reason="target";used=i+1;break;}
 }
 const net=exit-plan.entry-sideCost*(plan.entry+exit);
 return {netR:net/plan.risk,net,reason,used,maeR:adverse/plan.risk,mfeR:favorable/plan.risk};
}
