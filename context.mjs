/**
 * Public free market context. All timestamps belong to providers, not to fetch time.
 * Missing/stale readings are NULL and never become zeros or trading signals.
 * No Quantfury credentials, no paid APIs.
 */
const SRC = {
  etf: "https://www.tftc.io/bitcoin-etf-flows/latest.json",
  etfFallback: "https://www.tftc.io/bitcoin-etf-flows/data.json",
  onchain: "https://api.bitcoincreditstack.com/v1/onchain/indicators/latest",
  mvrv: "https://data.explore21.com/v1/metrics/bitcoin-mvrv-ratio/latest",
  realized: "https://data.explore21.com/v1/metrics/bitcoin-realized-price/latest",
  liquidations: "https://marketlight.ai/bt/api/public/liquidations/summary?symbol=BTCUSDT",
  liquidationsFallback: "https://xoomar.com/api/markets/liquidations",
};
const finite=(x)=>Number.isFinite(Number(x))&&x!==null&&x!==undefined&&x!=="";
const n=(x)=>finite(x)?Number(x):null;
const validDate=(date)=>typeof date==="string"&&/^\d{4}-\d\d-\d\d$/.test(date)&&Number.isFinite(Date.parse(date+"T00:00:00Z"));
const dayAge=(date,now)=>validDate(date)?(now-Date.parse(date+"T00:00:00Z"))/86400000:Infinity;
const iso=x=>new Date(x).toISOString();
function roundCheck(d,now,maxAgeMs){
  const t=Date.parse(d);
  return Number.isFinite(t)&&now-t>=-3600000&&now-t<=maxAgeMs;
}
async function req(url){
  const r=await fetch(url,{
    headers:{"Accept":"application/json","Cache-Control":"no-cache","User-Agent":"BTC-Public-Data-Gate/1.1"},
    signal:AbortSignal.timeout(8000),
    cf:{cacheEverything:false,cacheTtl:0}
  });
  if(!r.ok)throw Error("HTTP "+r.status);
  return await r.json();
}
function errorMessage(e){return String(e?.message||e).slice(0,160);}
function etfSession(s,meta,now,from){
  if(!s||!validDate(s.date)||dayAge(s.date,now)>7||dayAge(s.date,now)<0||!finite(s.netFlowUsd))throw Error("ETF_no_recent_settled_session");
  if(meta.updatedThrough&&meta.updatedThrough<s.date)throw Error("ETF_latest_after_reported_update");
  if(s.netFlowUsd===0&&s.perEtfUsd&&Object.values(s.perEtfUsd).every(x=>x===null))throw Error("ETF_incomplete_zero");
  return {date:s.date,netFlowUsd:n(s.netFlowUsd),vendorNetFlowUsd:n(s.vendorNetFlowUsd),
    perEtfUsd:s.perEtfUsd||null,source:"TFTC / SoSoValue (public CC BY 4.0)",sourceUrl:from,
    updatedThrough:meta.updatedThrough||null,dateModified:meta.dateModified||null,unit:"USD",
    completeness:"published_settled_session_vendor_policy",warning:"Vendor can revise flows; date is US trading session not fetch time"};
}
export async function getEtf(now=Date.now(),request=req){
  let attempts=[];
  try{const j=await request(SRC.etf);return {data:etfSession(j.latestSession,j,now,SRC.etf),attempts};}
  catch(e){attempts.push({source:"TFTC latest.json",error:errorMessage(e)});}
  try{
    const j=await request(SRC.etfFallback);
    if(!Array.isArray(j.days))throw Error("ETF_days_missing");
    const d=j.days.filter(x=>validDate(x.date)&&dayAge(x.date,now)<=7&&dayAge(x.date,now)>=0&&finite(x.netFlowUsd)).sort((a,b)=>b.date.localeCompare(a.date))[0];
    return {data:etfSession(d,j,now,SRC.etfFallback),attempts};
  }catch(e){attempts.push({source:"TFTC historical JSON (same publisher)",error:errorMessage(e)});}
  return {data:null,attempts};
}
function parseCredit(j,now){
  if(!j||dayAge(j.date,now)>3||dayAge(j.date,now)<0)throw Error("onchain_date_stale_or_future");
  if(!roundCheck(j.computed_at,now,4*86400000))throw Error("onchain_computation_time_stale");
  const cols=["mvrv","realised_price_usd","sopr","sopr_7d_avg","mvrv_z_score","realised_price_sth_usd"];
  const values=Object.fromEntries(cols.map(c=>[c,n(j[c])]));
  if(!(values.mvrv>0&&values.realised_price_usd>0&&values.sopr>0))throw Error("onchain_incomplete");
  return {date:j.date,computedAtUtc:j.computed_at,source:"Bitcoin Credit Stack",sourceUrl:SRC.onchain,
    attribution:"Bitcoin Credit Stack; CoinGecko, CryptoCompare and Binance for legacy backfills",
    mvrv:values.mvrv,realizedPriceUsd:values.realised_price_usd,
    sopr:values.sopr,sopr7d:values.sopr_7d_avg,
    mvrvZ:values.mvrv_z_score,sthRealizedPriceUsd:values.realised_price_sth_usd,
    methodology:"Provider on-chain daily snapshot; never an intraminute market price"};
}
function parseExplore(j,key,now){
  if(!j?.data?.length)throw Error("Explore21_empty");
  const x=j.data.at(-1);
  if(dayAge(x.date,now)>3||dayAge(x.date,now)<0)throw Error("Explore21_stale");
  if(!finite(x[key])||Number(x[key])<=0)throw Error("Explore21_invalid_metric");
  return {date:x.date,value:n(x[key]),source:"Explore21",sourceUrl:j.chart_url||SRC.mvrv,asOfBlock:n(j.as_of_block)};
}
export async function getOnchain(now=Date.now(),request=req){
  const attempts=[];let primary=null;
  try{primary=parseCredit(await request(SRC.onchain),now);}
  catch(e){attempts.push({source:"Bitcoin Credit Stack (primary SOPR)",error:errorMessage(e)});}
  let mvrv=null,realized=null;
  try{mvrv=parseExplore(await request(SRC.mvrv),"mvrv_ratio",now);}
  catch(e){attempts.push({source:"Explore21 MVRV",error:errorMessage(e)});}
  try{realized=parseExplore(await request(SRC.realized),"realized_price_usd",now);}
  catch(e){attempts.push({source:"Explore21 realized price",error:errorMessage(e)});}
  if(!primary&&mvrv&&realized&&mvrv.date===realized.date){
    primary={date:mvrv.date,computedAtUtc:null,source:"Explore21",sourceUrl:SRC.mvrv,
      attribution:"Data: Explore21 (https://charts.explore21.com), CC BY 4.0",
      mvrv:mvrv.value,realizedPriceUsd:realized.value,sopr:null,sopr7d:null,mvrvZ:null,
      sthRealizedPriceUsd:null,methodology:"SOPR unavailable: cannot infer it from MVRV"};
  }
  const mismatch=primary&&mvrv&&realized&&mvrv.date===primary.date&&realized.date===primary.date?
    {mvrvPct:100*(primary.mvrv/mvrv.value-1),realizedPricePct:100*(primary.realizedPriceUsd/realized.value-1),
      crossCheckDate:primary.date}:null;
  return {data:primary,secondary:{mvrv,realized},crossCheck:mismatch,attempts};
}
function liquidateMarketlight(j,now){
  if(!finite(j.toMs)||now-n(j.toMs)>600000||now-n(j.toMs)<-60000)throw Error("Marketlight_stale");
  if(!finite(j.fromMs)||Math.abs(n(j.toMs)-n(j.fromMs)-86400000)>3600000)throw Error("Marketlight_wrong_window");
  const b=j.bySymbol?.find(x=>x.symbol==="BTCUSDT");
  if(!b||!finite(b.long)||!finite(b.short)||!finite(b.total))throw Error("Marketlight_no_BTC");
  const total=n(b.long)+n(b.short);
  if(Math.abs(total-n(b.total))>Math.max(10,total*0.01))throw Error("Marketlight_sum_mismatch");
  return {windowStartUtc:iso(n(j.fromMs)),windowEndUtc:iso(n(j.toMs)),symbol:"BTCUSDT",
    longUsd:n(b.long),shortUsd:n(b.short),totalUsd:total,exchangeBreakdown:b.byExchange||null,
    coverage:"Reported BTCUSDT liquidations, Binance Futures / Bybit Perp / OKX SWAP only",
    source:"Marketlight",sourceUrl:SRC.liquidations};
}
function liquidateXoomar(j,now){
  const ts=Date.parse(j.updatedAt);
  if(!Number.isFinite(ts)||now-ts>600000||now-ts< -60000)throw Error("Xoomar_stale");
  const b=j.data?.topSymbols?.find(x=>x.symbol==="BTCUSDT");
  if(!b||!finite(b.longUsd)||!finite(b.shortUsd)||!finite(b.totalUsd))throw Error("Xoomar_missing_BTC");
  const total=n(b.longUsd)+n(b.shortUsd);
  if(Math.abs(total-n(b.totalUsd))>Math.max(10,total*0.01))throw Error("Xoomar_sum_mismatch");
  return {windowStartUtc:iso(ts-86400000),windowEndUtc:iso(ts),symbol:"BTCUSDT",
    longUsd:n(b.longUsd),shortUsd:n(b.shortUsd),totalUsd:total,
    exchangeBreakdown:null,coverage:"Reported BTC liquidations, OKX / Gate.io / HTX; excludes other exchanges",
    source:"XOOMAR",sourceUrl:SRC.liquidationsFallback};
}
export async function getLiquidations(now=Date.now(),request=req){
  const attempts=[];
  try{return {data:liquidateMarketlight(await request(SRC.liquidations),now),attempts};}
  catch(e){attempts.push({source:"Marketlight",error:errorMessage(e)});}
  try{return {data:liquidateXoomar(await request(SRC.liquidationsFallback),now),attempts};}
  catch(e){attempts.push({source:"XOOMAR",error:errorMessage(e)});}
  return {data:null,attempts};
}
export async function collectContext(now=Date.now(),request=req){
  const [etf,onchain,liquidations]=await Promise.all([getEtf(now,request),getOnchain(now,request),getLiquidations(now,request)]);
  return {etf,onchain,liquidations,coverage:{
    etf:!!etf.data,
    onchainMvrv:!!onchain.data?.mvrv,
    onchainRealizedPrice:!!onchain.data?.realizedPriceUsd,
    onchainSopr:!!onchain.data?.sopr,
    btcLiquidations24h:!!liquidations.data
  },limitations:["Data from distinct exchanges cannot be summed if coverage overlaps",
    "ETF and on-chain data are daily, not live tickers",
    "Missing values do not equal zero",
    "Derivative liquidation totals are partial exchange coverage, not all-market",
    "No direct Quantfury access; no automated trading"]};
}
