import {candles,price,indicators,atr,rsi,validatePrice} from "./worker.mjs";

import {earlyPatterns} from "./early_patterns.mjs";
import {attentionEvents} from "./early_market.mjs";
// Preserve the existing API contract for hourly consumers.
export const FAST_VERSION="2.0.0";
export const FEATURE_VERSION="2.2.0";
const FRAMES=["5M","15M","1M"];
const msFor=f=>f==="1M"?60000:f==="5M"?300000:900000;
const iso=t=>new Date(t).toISOString();

// Rules are deliberately preliminary, not entries, and use only information
// available at each candle close. Levels use preceding 20 and six closed candles.
export function detectEvents(bars,frame,source,now,lookbackMs=7200000){
  const ms=msFor(frame), events=[];
  for(let i=Math.max(35,bars.length-Math.max(1,Math.ceil(lookbackMs/ms)));i<bars.length;i++){
    const z=bars[i], prev=bars.slice(i-20,i), history=bars.slice(0,i);
    const end=z.t+ms;
    if(end>now||now-end>lookbackMs)continue;
    const low=Math.min(...prev.map(b=>b.l)),high=Math.max(...prev.map(b=>b.h));
    const avg=prev.reduce((s,b)=>s+b.v,0)/20;
    const volume=avg>0?z.v/avg:null, a=atr(history);
    if(!(a>0&&volume!==null))continue;
    const body=z.c-z.o, range=z.h-z.l, recovery=range>0?(z.c-z.l)/range:0;
    const priorRsi=rsi(history.map(b=>b.c)), currentRsi=rsi([...history.map(b=>b.c),z.c]);
    const strength=volume>=1.5||Math.abs(body)>=1.5*a;
    const local=prev.slice(-6), localHigh=Math.max(...local.map(b=>b.h)), localLow=Math.min(...local.map(b=>b.l));
    let type=null,level=null;
    if(z.c<low&&body<0&&strength){type="support_loss";level=low;}
    else if(z.c>high&&body>0&&strength){type="breakout";level=high;}
    else if(z.l<low&&z.c>low&&recovery>=0.65&&body>0&&(volume>=1.2||body>=a)){
      type="sweep_recovery";level=low;
    }
    if(!type && z.c>localHigh && body>0 && volume>=1.5 && body>=0.6*a){type="breakout";level=localHigh;}
    if(!type && z.c<localLow && body<0 && volume>=1.5 && -body>=0.6*a){type="support_loss";level=localLow;}
    if(!type && z.l<localLow && z.c>localLow && recovery>=0.65 && body>0 && volume>=1.2){type="sweep_recovery";level=localLow;}
    if(!type && z.c>prev.at(-1).h&&body>=1.5*a&&volume>=1.2){type="recovery_impulse";level=prev.at(-1).h;}
    if(type)events.push({id:frame+":"+type+":"+end,frame,type,source,closedUtc:iso(end),scope:level===high||level===low?"20_candles" :"local",
      open:z.o,high:z.h,low:z.l,close:z.c,level,volumeVs20:volume,
      atrBefore:a,bodyVsAtr:Math.abs(body)/a,rsi14:currentRsi,rsiChange:currentRsi-priorRsi,
      classification:"preliminary_market_event_not_entry"});
  }
  return events;
}

export async function fastReport(now=Date.now(),request){
  const [usdt,usd,...frames]=await Promise.all([price("BTCUSDT",now,request),price("BTCUSD",now,request),...FRAMES.map(f=>candles(f,now,request))]);
  const done=Date.now(), clock=Math.abs(done-now)<900000?done:now;
  const fresh=p=>p.data&&validatePrice({price:p.data.price,time:Date.parse(p.data.tradeUtc)},clock).ok&&Date.parse(p.data.tradeUtc)<=clock;
  const discrepancy=usdt.data&&usd.data?Math.abs(usdt.data.price-usd.data.price)/usd.data.price*100:null;
  const pricesOk=Boolean(fresh(usdt)&&fresh(usd)&&discrepancy!==null&&discrepancy<=1);
  const timeframes={},events=[],prealerts=[],earlyMarketEvents=[];
  for(const d of frames){
    const last=d.data?.at(-1),ms=msFor(d.frame);
    // Stricter short-frame freshness: no incomplete candles or future close.
    const expected=Math.floor(now/ms)*ms;
    const valid=Boolean(last&&last.t+ms<=now&&last.t+ms>=expected-(now-expected<30000?ms:0));
    if(!valid){timeframes[d.frame]={status:"unavailable_or_stale",attempts:d.attempts};continue;}
    timeframes[d.frame]={source:d.source,plan:d.plan,numberClosed:d.data.length,...indicators(d.data,ms),
      recentClosed:d.data.slice(-Math.ceil(7200000/ms)).map(z=>({openUtc:iso(z.t),closeUtc:iso(z.t+ms),open:z.o,high:z.h,low:z.l,close:z.c,volume:z.v}))};
    if(d.frame!=="1M")events.push(...detectEvents(d.data,d.frame,d.source,now));
    else earlyMarketEvents.push(...attentionEvents(d.data,d.source,now));
    if(d.frame==="1M"||d.frame==="5M")for(let i=Math.max(35,d.data.length-Math.ceil(300000/ms));i<d.data.length;i++)for(const e of earlyPatterns(d.data.slice(0,i+1),ms))prealerts.push({...e,frame:d.frame,source:d.source,id:d.frame+":"+e.type+":"+e.closedUtc});
  }
  const complete=["5M","15M"].every(f=>Number.isFinite(timeframes[f]?.rsi14)&&Number.isFinite(timeframes[f]?.atr14));
  return {version:FAST_VERSION,featureVersion:FEATURE_VERSION,generatedUtc:iso(now),completedUtc:iso(done),status:{pricesFreshAndCoherent:pricesOk,shortIndicatorsComputed:complete,eligibleForEntrySignal:false},
    experimentalPrealertsEnabled:false,prealerts:[],experimental:{classification:"research_only_not_entry",prealerts:pricesOk?prealerts:[]},prices:{BTCUSD:usd,BTCUSDT:usdt,discrepancyPct:discrepancy},timeframes,
    earlyMarketEvents:pricesOk?earlyMarketEvents:[],
    events:pricesOk?events.sort((a,b)=>Date.parse(a.closedUtc)-Date.parse(b.closedUtc)):[],
    notice:"Public market observations only; no broker connection, orders or entry validation."};
}
