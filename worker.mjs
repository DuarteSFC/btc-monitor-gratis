import {collectContext} from "./context.mjs";
import {fibonacciFromClosedBars} from "./technical_context.mjs";
/**
 * BTC Public Data Gate — datos públicos, sin órdenes ni acceso Quantfury.
 * Cloudflare Worker, también ejecutable en Node 22 para pruebas.
 */
export const SETTINGS={maxAgeMs:60000,futureToleranceMs:10000,minCandles:210,maxPriceGapPct:1,timeoutMs:6500};
const num=x=>Number(x);
const iso=x=>new Date(x).toISOString();
export function validatePrice(p,now=Date.now()){
  if(!p||!(p.price>0)||!Number.isFinite(p.time))return {ok:false,reason:"invalid_ticker"};
  const age=now-p.time;
  return age<=SETTINGS.maxAgeMs&&age>=-SETTINGS.futureToleranceMs?
    {ok:true,ageMs:age}:{ok:false,reason:"stale_or_future",ageMs:age};
}
async function json(url){
  const response=await fetch(url,{headers:{"Accept":"application/json","Cache-Control":"no-cache"},signal:AbortSignal.timeout(SETTINGS.timeoutMs),cf:{cacheTtl:0,cacheEverything:false}});
  if(!response.ok)throw Error("HTTP "+response.status);
  return await response.json();
}
const providers={
  BTCUSDT:[
    ["A","OKX Spot","https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT",j=>{const z=j.data?.[0];if(j.code!=="0"||z?.instId!=="BTC-USDT")throw Error("OKX unexpected");return {price:num(z.last),time:num(z.ts)};}],
    ["B","Bitget Spot","https://api.bitget.com/api/v2/spot/market/tickers?symbol=BTCUSDT",j=>{const z=j.data?.[0];if(z?.symbol!=="BTCUSDT")throw Error("Bitget unexpected");return {price:num(z.lastPr),time:num(z.ts)};}],
    ["C","Gate.io Spot","https://api.gateio.ws/api/v4/spot/trades?currency_pair=BTC_USDT&limit=5",j=>{if(!Array.isArray(j)||!j.length)throw Error("Gate invalid trades");const z=j[0];if(z.currency_pair!=="BTC_USDT")throw Error("Gate wrong instrument");return {price:num(z.price),time:num(z.create_time_ms)};}]
  ],
  BTCUSD:[
    ["A","Coinbase Exchange Spot","https://api.exchange.coinbase.com/products/BTC-USD/ticker",j=>({price:num(j.price),time:Date.parse(j.time)})],
    ["B","Kraken Spot","https://api.kraken.com/0/public/Trades?pair=XBTUSD",j=>{if(j.error?.length)throw Error("Kraken error");const k=Object.keys(j.result||{}).find(x=>x!=="last");const z=j.result?.[k]?.at(-1);if(!z)throw Error("Kraken missing trades");return {price:num(z[0]),time:Math.round(num(z[2])*1000)};}],
    ["C","Bitfinex Spot","https://api-pub.bitfinex.com/v2/trades/tBTCUSD/hist?limit=5",j=>{const z=j?.[0];if(!z)throw Error("Bitfinex missing trades");return {price:num(z[3]),time:num(z[1])};}]
  ]
};
export async function price(pair,now=Date.now(),request=json){
  let errors=[];
  for(const [plan,source,url,parse] of providers[pair]||[]){
    try{
      const p=parse(await request(url)),v=validatePrice(p,now);
      if(!v.ok)throw Error(v.reason);
      return {data:{pair,price:p.price,tradeUtc:iso(p.time),ageSeconds:Math.round(v.ageMs/1000),source,plan,url},attempts:errors};
    }catch(e){errors.push({plan,source,error:String(e.message||e).slice(0,110)});}
  }
  return {data:null,attempts:errors};
}
const frames={
  "1H":{ms:3600000,okx:"1H",bitget:"1h",kraken:60},
  "4H":{ms:14400000,okx:"4H",bitget:"4h",kraken:240},
  "1D":{ms:86400000,okx:"1Dutc",bitget:"1day",kraken:1440}
};
function parsedBars(j,type,ms,now){
  let d;
  if(type==="okx"){
    if(j.code!=="0"||!Array.isArray(j.data))throw Error("OKX candles invalid");
    d=j.data.map(z=>({t:num(z[0]),o:num(z[1]),h:num(z[2]),l:num(z[3]),c:num(z[4]),v:num(z[5]),ok:String(z[8])==="1"}));
  }else if(type==="bitget"){
    if(!Array.isArray(j.data))throw Error("Bitget candles invalid");
    d=j.data.map(z=>({t:num(z[0]),o:num(z[1]),h:num(z[2]),l:num(z[3]),c:num(z[4]),v:num(z[5]),ok:true}));
  }else{
    if(j.error?.length)throw Error("Kraken candles error");
    const k=Object.keys(j.result||{}).find(x=>x!=="last");
    if(!Array.isArray(j.result?.[k]))throw Error("Kraken candles invalid");
    d=j.result[k].map(z=>({t:num(z[0])*1000,o:num(z[1]),h:num(z[2]),l:num(z[3]),c:num(z[4]),v:num(z[6]),ok:true}));
  }
  d=d.filter(z=>z.ok&&z.t+ms<=now+2000).sort((a,b)=>a.t-b.t);
  if(d.length<SETTINGS.minCandles)throw Error("insufficient_candles:"+d.length);
  for(let i=0;i<d.length;i++){
    const z=d[i];
    if(![z.t,z.o,z.h,z.l,z.c,z.v].every(Number.isFinite)||z.l<=0||z.h<Math.max(z.o,z.c)||z.l>Math.min(z.o,z.c)||z.v<0)throw Error("invalid_ohlcv");
    if(i&&z.t-d[i-1].t!==ms)throw Error("gap_or_duplicate");
  }
  if(now-(d.at(-1).t+ms)>1.3*ms)throw Error("stale_closed_candle");
  return d;
}
export async function candles(frame,now=Date.now(),request=json){
  const f=frames[frame];if(!f)throw Error("Invalid timeframe");
  const sources=[
    ["A","OKX BTC/USDT","https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar="+f.okx+"&limit=300","okx"],
    ["B","Bitget BTC/USDT","https://api.bitget.com/api/v2/spot/market/candles?symbol=BTCUSDT&granularity="+f.bitget+"&limit=300","bitget"],
    ["C","Kraken BTC/USD","https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval="+f.kraken,"kraken"]
  ];
  const attempts=[];
  for(const [plan,source,url,type] of sources){
    try{return {data:parsedBars(await request(url),type,f.ms,now),source,plan,attempts,url,frame,intervalMs:f.ms};}
    catch(e){attempts.push({plan,source,error:String(e.message||e).slice(0,115)});}
  }
  return {data:null,frame,attempts};
}
export function ema(x,n){
  if(x.length<n)return null;
  const a=2/(n+1),result=Array(n-1).fill(null);let m=x.slice(0,n).reduce((u,v)=>u+v,0)/n;
  result.push(m);
  for(let i=n;i<x.length;i++){m=a*x[i]+(1-a)*m;result.push(m)}
  return result;
}
export function rsi(x,n=14){
  if(x.length<=n)return null;
  let gain=0,loss=0;
  for(let i=1;i<=n;i++){const d=x[i]-x[i-1];gain+=Math.max(0,d);loss+=Math.max(0,-d)}
  gain/=n;loss/=n;
  for(let i=n+1;i<x.length;i++){const d=x[i]-x[i-1];gain=(gain*(n-1)+Math.max(0,d))/n;loss=(loss*(n-1)+Math.max(0,-d))/n}
  return loss===0?(gain===0?50:100):100-100/(1+gain/loss);
}
export function macd(x){
  const f=ema(x,12),s=ema(x,26);
  if(!f||!s||x.length<35)return null;
  const line=s.map((z,i)=>z===null?null:f[i]-z).filter(z=>z!==null);
  const sig=ema(line,9);
  const m=line.at(-1),v=sig?.at(-1);
  return Number.isFinite(v)?{line:m,signal:v,histogram:m-v}:null;
}
export function atr(bars,n=14){
  if(bars.length<=n)return null;
  const tr=[];
  for(let i=1;i<bars.length;i++){const z=bars[i],p=bars[i-1].c;tr.push(Math.max(z.h-z.l,Math.abs(z.h-p),Math.abs(z.l-p)))}
  let a=tr.slice(0,n).reduce((x,y)=>x+y,0)/n;
  for(let i=n;i<tr.length;i++)a=(a*(n-1)+tr[i])/n;
  return a;
}
export function indicators(bars,ms){
  if(!bars||bars.length<SETTINGS.minCandles)return null;
  const x=bars.map(z=>z.c),z=bars.at(-1),last20=bars.slice(-21,-1);
  const avgVolume=last20.reduce((a,b)=>a+b.v,0)/last20.length;
  const peaks=(field,gt)=>{
    const out=[];
    for(let i=2;i<bars.length-2;i++){
      const v=bars[i][field];
      if([1,2].every(d=>gt(v,bars[i-d][field])&&gt(v,bars[i+d][field])))out.push({date:iso(bars[i].t),value:v});
    }
    return out.slice(-2);
  };
  const highs=peaks("h",(a,b)=>a>b),lows=peaks("l",(a,b)=>a<b);
  let structure="mixed_or_insufficient";
  if(highs.length===2&&lows.length===2){
    if(highs[1].value>highs[0].value&&lows[1].value>lows[0].value)structure="higher_highs_and_lows";
    if(highs[1].value<highs[0].value&&lows[1].value<lows[0].value)structure="lower_highs_and_lows";
  }
  return {lastClosedOpenUtc:iso(z.t),lastClosedEndUtc:iso(z.t+ms),close:z.c,volume:z.v,volumeVs20:avgVolume>0?z.v/avgVolume:null,
    rsi14:rsi(x),macd12_26_9:macd(x),ema20:ema(x,20)?.at(-1),ema50:ema(x,50)?.at(-1),ema200:ema(x,200)?.at(-1),atr14:atr(bars),
    structure,highs,lows,fibonacci:fibonacciFromClosedBars(bars)};
}
export async function derivatives(now,request){
  const errors=[];let funding=null,openInterest=null;
  try{
    const j=await request("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP"),z=j.data?.[0];
    if(j.code!=="0"||!z||!Number.isFinite(num(z.fundingRate)))throw Error("funding_invalid");
    funding={source:"OKX BTC-USDT-SWAP only",rate:num(z.fundingRate),fundingTimeUtc:z.fundingTime?iso(num(z.fundingTime)):null,nextFundingTimeUtc:z.nextFundingTime?iso(num(z.nextFundingTime)):null};
  }catch(e){errors.push("funding: "+String(e.message||e));}
  try{
    const j=await request("https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP"),z=j.data?.[0];
    if(j.code!=="0"||!z||Math.abs(now-num(z.ts))>3600000)throw Error("OI_invalid_or_stale");
    openInterest={source:"OKX BTC-USDT-SWAP only",observedUtc:iso(num(z.ts)),contracts:num(z.oi),btc:num(z.oiCcy),usd:num(z.oiUsd)};
  }catch(e){errors.push("OI: "+String(e.message||e));}
  if(!funding||!openInterest){
    try{
      const j=await request("https://api.bitget.com/api/v2/mix/market/ticker?symbol=BTCUSDT&productType=USDT-FUTURES");
      const z=j.data?.[0],t=num(z?.ts);
      if(j.code!=="00000"||z?.symbol!=="BTCUSDT"||!Number.isFinite(t)||Math.abs(now-t)>120000)
        throw Error("Bitget_derivative_snapshot_invalid_or_stale");
      if(!funding){
        if(!Number.isFinite(num(z.fundingRate)))throw Error("Bitget_funding_missing");
        funding={source:"Bitget BTCUSDT USDT-FUTURES only",rate:num(z.fundingRate),observedUtc:iso(t),
          fundingTimeUtc:null,nextFundingTimeUtc:null,plan:"B"};
      }
      if(!openInterest){
        const btc=num(z.holdingAmount),mark=num(z.markPrice);
        if(!(btc>0&&mark>0))throw Error("Bitget_OI_missing");
        openInterest={source:"Bitget BTCUSDT USDT-FUTURES only",observedUtc:iso(t),
          contracts:null,btc,usd:btc*mark,usdIsEstimate:true,plan:"B"};
      }
    }catch(e){errors.push("Bitget derivatives fallback: "+String(e.message||e));}
  }
  return {funding,openInterest,errors};
}
export async function report(now=Date.now(),request=json){
  const contextPromise=collectContext(now,request);
  const [usdt,usd,...barData]=await Promise.all([
    price("BTCUSDT",now,request),price("BTCUSD",now,request),
    ...Object.keys(frames).map(f=>candles(f,now,request))
  ]);
  const timeframes={};
  for(const d of barData){
    timeframes[d.frame]=d.data?{source:d.source,plan:d.plan,numberClosed:d.data.length,attempts:d.attempts,...indicators(d.data,d.intervalMs)}:
      {status:"unavailable",attempts:d.attempts};
  }
  const discrepancy=usdt.data&&usd.data?Math.abs(usdt.data.price-usd.data.price)/usd.data.price*100:null;
  const completedAt=Date.now();
  const realClock=Math.abs(completedAt-now)<15*60*1000;
  const freshAtOutput=(p)=>!realClock||!p?.data?!!p?.data:(completedAt-Date.parse(p.data.tradeUtc)<=SETTINGS.maxAgeMs&&completedAt-Date.parse(p.data.tradeUtc)>=-SETTINGS.futureToleranceMs);
  const priceOk=discrepancy!==null&&discrepancy<=SETTINGS.maxPriceGapPct&&freshAtOutput(usdt)&&freshAtOutput(usd);
  const technicalOk=Object.values(timeframes).every(z=>Number.isFinite(z.rsi14)&&Number.isFinite(z.atr14)&&Number.isFinite(z.ema200)&&Number.isFinite(z.macd12_26_9?.histogram));
  const context=await contextPromise;
  const contextComplete=Object.values(context.coverage).every(Boolean);
  return {engine:"BTC Public Data Gate",version:"1.1.0",generatedUtc:iso(now),completedUtc:iso(completedAt),
    status:{pricesFreshAndCoherent:priceOk,technicalIndicatorsComputed:technicalOk,contextComplete,eligibleForEntrySignal:false,
      reason:!priceOk?"no_fresh_prices":!technicalOk?"missing_valid_ohlcv":"no_QF_and_incomplete_context"},
    prices:{BTCUSDT:usdt,BTCUSD:usd,discrepancyPct:discrepancy},timeframes,
    derivatives:await derivatives(now,request),context,
    additionalContext:{quantfury:"private_unconnected_requires_fresh_user_snapshot"},
    notice:"Public analysis only. No orders. No position sizing. Suppress entry signals."
  };
}
export default {
  async fetch(request){
    const path=new URL(request.url).pathname;
    if(path==="/health")return new Response(JSON.stringify({ok:true,service:"BTC Public Data Gate",version:"1.1.0"}),{headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
    if(path!=="/report")return new Response("Use /health or /report",{status:404});
    try{return new Response(JSON.stringify(await report(Date.now())),{headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store, max-age=0","Access-Control-Allow-Origin":"*"}})}
    catch(e){return new Response(JSON.stringify({ok:false,error:String(e.message||e)}),{status:503,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}})}
  }
};
