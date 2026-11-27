// Historical positioning observations, not proof of long/short openings or real-time publication.
// Require a full lagged 60-minute window, no interpolation across unavailable samples.
export function positionFeatures(byTime,t,lag=10){
 if(!(byTime instanceof Map)||!Number.isFinite(t)||t%300000||![10,15].includes(lag))return null;
 const latest=t-lag*60000,rows=[];
 for(let j=12;j>=0;j--){
  const r=byTime.get(latest-j*300000);
  if(!Array.isArray(r)||r.length!==4||!r.every(v=>Number.isFinite(v)&&v>0))return null;
  rows.push(r);
 }
 const now=rows[12],chg=(i,n)=>Math.log(now[i]/rows[12-n][i]);
 const features=[chg(0,1),chg(0,3),chg(0,6),chg(0,12),Math.log(now[1]),Math.log(now[2]),Math.log(now[3]),chg(1,6),chg(2,6),chg(3,6),Math.log(now[2]/now[3])];
 return features.every(Number.isFinite)?features:null;
}
