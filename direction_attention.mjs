// Research only: direction of the first material impulse after receipt.
const M=60000;
export function directionEvents(b){
 const out=[];let last=-Infinity,previous=0;
 for(let i=4;i<b.length;i++){
  const change=b[i].c/b[i-4].o-1,dir=change>=.005?1:change<=-.005?-1:0;
  const finish=b[i].t+M;
  if(dir&&dir!==previous&&finish-last>=30*M){
   out.push({start:b[i-4].t,finish,dir});last=finish;
  }
  previous=dir;
 }
 return out;
}
export function eventLabel(events,t,delay=1){
 const receipt=t+delay*M;
 const e=events.find(e=>e.finish>receipt&&e.finish<=receipt+30*M);
 if(!e)return {kind:"none",event:null};
 if(e.start<receipt)return {kind:"underway",event:e};
 return {kind:e.dir===1?"up":"down",event:e};
}
export function causalSelect(rows,threshold,cap=3){
 let last=-Infinity,day=-1,n=0;const out=[];
 for(const r of rows){
  const d=Math.floor(r.t/86400000);
  if(d!==day){day=d;n=0;}
  if(n>=cap||r.t-last<30*M||r.score<threshold)continue;
  out.push(r);last=r.t;n++;
 }
 return out;
}
export function countGate(rows,target=28){
 const sorted=rows.map(r=>r.score).sort((a,b)=>a-b);
 if(!sorted.length)throw Error("Empty calibration");
 return Array.from({length:101},(_,i)=>{
  const q=.90+i*.00099,threshold=sorted[Math.min(sorted.length-1,Math.floor(q*sorted.length))];
  return {q,threshold,n:causalSelect(rows,threshold).length};
 }).sort((a,b)=>Math.abs(a.n-target)-Math.abs(b.n-target)||a.n-b.n)[0];
}
export function auditDirection(rows,events,delay=1){
 const counts={up:0,down:0,underway:0,none:0,duplicate:0},used=new Set(),leads=[],daily={};
 for(const r of rows){
  const l=eventLabel(events,r.t,delay);
  let kind=l.kind;
  if(l.event&&used.has(l.event.finish))kind="duplicate";
  else if(l.event){used.add(l.event.finish);if(kind==="up")leads.push((l.event.start-r.t-delay*M)/M);}
  counts[kind]++;
  const day=new Date(r.t).toISOString().slice(0,10),d=daily[day]??(daily[day]={alerts:0,up:0,down:0});
  d.alerts++;d.up+=+(kind==="up");d.down+=+(kind==="down");
 }
 const totalUp=events.filter(e=>e.dir===1).length;
 return {alerts:rows.length,counts,totalUp,precision:rows.length?counts.up/rows.length:null,coverage:totalUp?counts.up/totalUp:null,meanLead:leads.length?leads.reduce((a,b)=>a+b,0)/leads.length:null,daily};
}
