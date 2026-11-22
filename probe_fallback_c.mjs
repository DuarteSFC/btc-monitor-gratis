const urls={
 gateSpot:"https://api.gateio.ws/api/v4/spot/trades?currency_pair=BTC_USDT&limit=5",
 kucoinHistory:"https://api.kucoin.com/api/v1/market/histories?symbol=BTC-USDT",
 bitfinexUST:"https://api-pub.bitfinex.com/v2/trades/tBTCUST/hist?limit=5",
 krakenUSDT:"https://api.kraken.com/0/public/Trades?pair=XBTUSDT",
 krakenOHLC:"https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60",
 geminiUSDT:"https://api.gemini.com/v1/trades/btcusdt?limit_trades=5"
};
for(const [name,url] of Object.entries(urls)){
try{
 const r=await fetch(url,{signal:AbortSignal.timeout(11000),headers:{"Accept":"application/json","Cache-Control":"no-cache"}});
 const s=await r.text();let j;
 try{j=JSON.parse(s)}catch{j=s.slice(0,650)}
 console.log(JSON.stringify({name,status:r.status,type:r.headers.get("content-type"),sample:JSON.stringify(j).slice(0,1100)}));
}catch(e){console.log(JSON.stringify({name,error:String(e)}))}
}
