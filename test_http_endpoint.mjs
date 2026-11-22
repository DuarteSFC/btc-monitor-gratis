const base=process.env.BTC_MONITOR_URL||"https://btc-monitor-gratis.vercel.app";
const u=new URL(base);if(u.protocol!=="https:")throw Error("HTTPS required");
const now=Date.now();
async function get(path){
 const r=await fetch(base+path+"?nonce="+now,{signal:AbortSignal.timeout(110000),headers:{"Cache-Control":"no-cache"}});
 const txt=await r.text();let body;
 try{body=JSON.parse(txt)}catch{throw Error("bad JSON "+path+" HTTP "+r.status+": "+txt.slice(0,700))}
 if(!r.ok)throw Error("HTTP "+r.status+" "+path+": "+JSON.stringify(body).slice(0,800));
 return {body,headers:r.headers,status:r.status};
}
const health=await get("/api/health");
if(health.body.ok!==true)throw Error("health_check_failed");
const {body:r,headers}=await get("/api/report");
const age=Date.now()-Date.parse(r.generatedUtc);
const completedAge=Date.now()-Date.parse(r.completedUtc);
if(!Number.isFinite(age)||age>150000||age< -10000)throw Error("REPORT_STALE "+age);
if(!Number.isFinite(completedAge)||completedAge>150000||completedAge< -10000)throw Error("REPORT_COMPLETE_STALE "+completedAge);
if(!r.status?.pricesFreshAndCoherent)throw Error("Prices not fresh "+JSON.stringify(r.prices).slice(0,1700));
if(!r.status?.technicalIndicatorsComputed)throw Error("Technicals missing "+JSON.stringify(r.timeframes).slice(0,1700));
if(!r.status?.contextComplete)throw Error("ETF/onchain/liquidations missing "+JSON.stringify(r.context.coverage));
if(r.status.eligibleForEntrySignal!==false)throw Error("Unsafe automatic entry gate");
for(const p of ["BTCUSDT","BTCUSD"]){
 const z=r.prices?.[p]?.data;
 if(!z||Date.now()-Date.parse(z.tradeUtc)>120000)throw Error("Ticker too old "+p);
}
const summary={utc:new Date().toISOString(),url:base,health:health.body,
  status:r.status,generatedUtc:r.generatedUtc,completedUtc:r.completedUtc,
  prices:Object.fromEntries(["BTCUSDT","BTCUSD"].map(p=>[p,r.prices[p].data])),
  frames:Object.fromEntries(Object.entries(r.timeframes).map(([k,v])=>[k,{source:v.source,rsi14:v.rsi14,macdHistogram:v.macd12_26_9?.histogram,ema200:v.ema200,lastClosedEndUtc:v.lastClosedEndUtc}])),
  etf:r.context.etf.data?.date,onchain:r.context.onchain.data?.date,
  liquidations:r.context.liquidations.data?.windowEndUtc,cacheControl:headers.get("cache-control")};
console.log(JSON.stringify(summary,null,2));
if(!/no-store/.test(headers.get("cache-control")||""))throw Error("Missing no-store header");
