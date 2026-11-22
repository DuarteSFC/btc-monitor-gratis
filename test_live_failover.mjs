import {price,candles} from "./worker.mjs";
import {getOnchain,getLiquidations,getEtf} from "./context.mjs";
const now=Date.now();
async function request(u){
 const r=await fetch(u,{signal:AbortSignal.timeout(10000),headers:{"Accept":"application/json","Cache-Control":"no-cache"}});
 if(!r.ok)throw Error("HTTP_"+r.status);
 return await r.json();
}
const check=async(name,fn)=>{
 try{const out=await fn();console.log(JSON.stringify({name,success:!!out.data,plan:out.plan||out.data?.plan||null,
     source:out.source||out.data?.source||null,count:out.data?.length||null,at:out.data?.tradeUtc||out.data?.date||null,
     attempts:out.attempts?.map(z=>({source:z.source,plan:z.plan,error:z.error})),
     failure:out.data?"": "no_reading" }).slice(0,1900));}
 catch(e){console.log(JSON.stringify({name,error:String(e)}).slice(0,1800))}
};
const noA=async u=>{
 if(u.includes("okx.com")||u.includes("coinbase.com"))throw Error("Injected A failure");
 return request(u);
};
const noAB=async u=>{
 if(u.includes("okx.com")||u.includes("coinbase.com")||u.includes("bitget.com")||u.includes("kraken.com"))throw Error("Injected A+B failures");
 return request(u);
};
for(const p of ["BTCUSD","BTCUSDT"]){
 await check(p+"_plan_B",()=>price(p,now,noA));
 await check(p+"_plan_C",()=>price(p,now,noAB));
}
const noABforCandles=async u=>{if(u.includes("okx.com")||u.includes("bitget.com"))throw Error("Injected A+B failures");return request(u);};
for(const t of ["1H","4H","1D"]){
 await check("candles_"+t+"_B",()=>candles(t,now,noA));
 await check("candles_"+t+"_C",()=>candles(t,now,noABforCandles));
}
await check("liquidations_B",()=>getLiquidations(now,async u=>{if(u.includes("marketlight"))throw Error("Injected A failure");return request(u)}));
await check("onchain_B",()=>getOnchain(now,async u=>{if(u.includes("bitcoincreditstack"))throw Error("Injected A failure");return request(u)}));
await check("etf_B",()=>getEtf(now,async u=>{if(u.includes("latest.json"))throw Error("Injected A failure");return request(u)}));
console.log("IMPORTANT: Test is diagnostic only. Fallbacks do not guarantee round-the-clock access. No trades or alerts.");
