// Independent price impulse benchmark, research only.
const M=60000;
export function impulses(b,{pct=.005,cooldown=30}={}){
 const out=[];let last=-Infinity,previous=false;
 for(let i=4;i<b.length;i++){
  const start=b[i-4].t,finish=b[i].t+M,hit=b[i].c/b[i-4].o-1>=pct;
  if(hit&&!previous&&finish-last>=cooldown*M){
   out.push({start,finish});last=finish;
  }
  previous=hit;
 }
 return out;
}
export function measureLead(alerts,events,{delay=1,lookahead=30}={}){
 const used=new Set(),leads=[];let underway=0,unmatched=0;
 for(const a of alerts){
  const t=a.t+delay*M;
  const i=events.findIndex((e,i)=>!used.has(i)&&e.finish>t&&e.finish-t<=lookahead*M);
  if(i<0){unmatched++;continue;}
  const e=events[i];used.add(i);
  if(t<=e.start)leads.push((e.start-t)/M);
  else underway++;
 }
 leads.sort((a,b)=>a-b);
 return {alerts:alerts.length,events:events.length,early:leads.length,underway,unmatched,precision:alerts.length?leads.length/alerts.length:null,coverage:events.length?leads.length/events.length:null,meanLead:leads.length?leads.reduce((a,b)=>a+b,0)/leads.length:null,medianLead:leads.length?leads[Math.floor((leads.length-1)/2)]:null};
}
