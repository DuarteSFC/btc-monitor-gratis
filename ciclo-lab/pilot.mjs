// CICLO LAB: isolated pilot, NOT the previous Python engine or a live signal.
import {writeFileSync,mkdirSync} from "node:fs";
import {createHash} from "node:crypto";
const MS=300000,DAYS=60,N=DAYS*288,cutoff=Math.floor(Date.now()/MS)*MS,first=cutoff-N*MS;
let after=cutoff, map=new Map();
for(let p=0;p<195&&after>first;p++){
 let data;
 for(let n=0;n<4;n++){try{
  const u="https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=5m&limit=100&after="+after;
  const r=await fetch(u,{signal:AbortSignal.timeout(12000)});if(!r.ok)throw Error("HTTP "+r.status);const j=await r.json();if(j.code!=="0"||!Array.isArray(j.data)||!j.data.length)throw Error("Invalid page");data=j.data;break;
 }catch(e){if(n===3)throw e;await new Promise(r=>setTimeout(r,1000*(n+1)));}}
 const next=Math.min(...data.map(z=>Number(z[0])));if(!(next<after))throw Error("Pagination stalled");after=next;
 for(const z of data){const [t,o,h,l,c,v]=z.slice(0,6).map(Number);if(String(z[8])!=="1"||t<first||t>=cutoff)continue;if(![t,o,h,l,c,v].every(Number.isFinite)||t%MS||l<=0||h<Math.max(o,c)||l>Math.min(o,c)||v<0)throw Error("Invalid candle");map.set(t,{t,o,h,l,c,v});}
 await new Promise(r=>setTimeout(r,150));
}
const b=[...map.values()].sort((a,b)=>a.t-b.t);
if(b.length!==N||b.some((x,i)=>x.t!==first+i*MS))throw Error("Missing candles "+b.length+" / "+N);
mkdirSync("lab-output",{recursive:true});
const csv="timestamp,open,high,low,close,volume\n"+b.map(x=>[x.t,x.o,x.h,x.l,x.c,x.v].join(",")).join("\n")+"\n";
writeFileSync("lab-output/okx_btc_usdt_5m.csv",csv);
const hash=createHash("sha256").update(csv).digest("hex");
const ema=(a,x,n)=>a+(x-a)*2/(n+1);
let e20=b[0].c,e50=e20,atr=0,ag=0,al=0,vp=0,vol=0,day=-1,seed=74217;
const feat=[];
for(let i=0;i<b.length;i++){
 const x=b[i],p=b[Math.max(0,i-1)],d=x.c-p.c, tr=Math.max(x.h-x.l,Math.abs(x.h-p.c),Math.abs(x.l-p.c));
 e20=ema(e20,x.c,20);e50=ema(e50,x.c,50);
 if(i<14){atr+=tr/14;ag+=Math.max(d,0)/14;al+=Math.max(-d,0)/14;}else{atr=(13*atr+tr)/14;ag=(13*ag+Math.max(d,0))/14;al=(13*al+Math.max(-d,0))/14;}
 const rsi=al===0?(ag===0?50:100):100-100/(1+ag/al);
 const today=Math.floor(x.t/86400000);if(today!==day){day=today;vp=0;vol=0;}vp+=(x.h+x.l+x.c)/3*x.v;vol+=x.v;const vwap=vol?vp/vol:x.c;
 const win=b.slice(Math.max(0,i-20),i),hi=win.length?Math.max(...win.map(z=>z.h)):x.h,lo=win.length?Math.min(...win.map(z=>z.l)):x.l;
 const atrMean=i>=50?feat.slice(i-50,i).reduce((s,f)=>s+f.atr,0)/50:atr;
 const vmean=win.length?win.reduce((s,z)=>s+z.v,0)/win.length:x.v;
 seed=(Math.imul(1664525,seed)+1013904223)>>>0;
 feat.push({e20,e50,atr,rsi,vwap,hi,lo,atrMean,vmean,random:seed/4294967296});
}
const rules={
 B01:(i,x,f,p,q)=>f.random<.03,
 B02:(i,x,f,p,q)=>f.e20>f.e50&&p.c<=q.e20&&x.c>f.e20,
 B03:(i,x,f,p,q)=>q.rsi<=30&&f.rsi>30,
 B04:(i,x,f,p,q)=>Math.floor(x.t/86400000)===Math.floor(p.t/86400000)&&p.c<=q.vwap&&x.c>f.vwap&&x.v>=f.vmean,
 B05:(i,x,f,p,q)=>q.atr<.8*q.atrMean&&x.c>f.hi&&x.v>=1.5*f.vmean,
 B06:(i,x,f,p,q)=>x.l<f.lo&&x.c>f.lo&&x.c>x.o
};
const rate=.0007, maxBars=48, initial=10000;
function run(rule,start,end){
 let eq=initial,peak=eq,dd=0,last=start-1;const trades=[];
 for(let i=Math.max(start,200);i+maxBars<end;i++){
  if(i<last||!rule(i,b[i],feat[i],b[i-1],feat[i-1]))continue;
  const entry=b[i+1].o,stop=entry-1.5*feat[i].atr;if(!(stop>0&&stop<entry))continue;
  const risk=entry-stop+rate*(entry+stop),target=(entry*(1+rate)+2*risk)/(1-rate);
  const qty=Math.min(eq*.0025/risk,eq/(entry*(1+rate)));if(qty<=0)break;
  let exit=b[i+maxBars].c,reason="timeout",j=i+maxBars;
  for(let k=i+1;k<=i+maxBars;k++){const z=b[k];if(z.l<=stop){exit=Math.min(z.o,stop);reason="stop";j=k;break;}if(z.h>=target){exit=target;reason="target";j=k;break;}}
  const gross=(exit-entry)*qty,cost=rate*(entry+exit)*qty,pnl=gross-cost,R=(gross-cost)/(qty*risk);
  eq+=pnl;peak=Math.max(peak,eq);dd=Math.max(dd,(peak-eq)/peak);last=j;
  trades.push({signal:b[i].t,entryTime:b[i+1].t,exitTime:b[j].t,entry,stop,target,exit,reason,R,pnl,cost});
 }
 const n=trades.length,win=trades.filter(t=>t.pnl>0),loss=trades.filter(t=>t.pnl<0),gain=win.reduce((s,t)=>s+t.pnl,0),lost=-loss.reduce((s,t)=>s+t.pnl,0),totalR=trades.reduce((s,t)=>s+t.R,0);
 return {summary:{n,winRate:n?win.length/n:null,netR:totalR,meanR:n?totalR/n:null,profitFactor:lost?gain/lost:null,netPnl:eq-initial,maxClosedEquityDrawdown:dd,totalCost:trades.reduce((s,t)=>s+t.cost,0),targetHits:trades.filter(t=>t.reason==="target").length},trades};
}
const split=Math.floor(N*.8),summary={},all={};
for(const [id,rule] of Object.entries(rules)){const a=run(rule,0,split),z=run(rule,split,N);summary[id]={development:a.summary,forward:z.summary};all[id]={development:a.trades,forward:z.trades};}
const report={source:"OKX BTC-USDT spot",from:new Date(first).toISOString(),to:new Date(cutoff).toISOString(),candles:N,sha256:hash,forwardFrom:new Date(b[split].t).toISOString(),assumptions:{riskFraction:.0025,stopATR:1.5,targetNetR:2,roundTripBps:14,maxBars,spotNotionalCap:true,stopFirst:true,closedEquityDrawdown:true},limitations:"5m next-open proxy, not exact 1m latency; only 60 days, forward slice not final holdout; B07 unavailable; no statistical inference, funding or intrabar drawdown; B01 fixed 3% per bar not matched to strategies; exploratory independent reimplementation",summary};
writeFileSync("lab-output/report.json",JSON.stringify(report,null,2));writeFileSync("lab-output/trades.json",JSON.stringify(all));
console.log(JSON.stringify(report));
