const urls={
 bybit:"https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT",
 bitgetTicker:"https://api.bitget.com/api/v2/mix/market/ticker?symbol=BTCUSDT&productType=USDT-FUTURES",
 bitgetRate:"https://api.bitget.com/api/v2/mix/market/current-fund-rate?symbol=BTCUSDT&productType=USDT-FUTURES",
 bitgetOI:"https://api.bitget.com/api/v2/mix/market/open-interest?symbol=BTCUSDT&productType=USDT-FUTURES",
 gateContract:"https://api.gateio.ws/api/v4/futures/usdt/contracts/BTC_USDT",
 gateTicker:"https://api.gateio.ws/api/v4/futures/usdt/tickers?contract=BTC_USDT"
};
await Promise.all(Object.entries(urls).map(async([name,url])=>{
 try{const r=await fetch(url,{signal:AbortSignal.timeout(9000),headers:{"Accept":"application/json"}});
 const t=await r.text();let j;try{j=JSON.parse(t)}catch{j=t};
 console.log(JSON.stringify({name,status:r.status,body:JSON.stringify(j).slice(0,2400)}));
 }catch(e){console.log(JSON.stringify({name,error:String(e)}))}
}));
