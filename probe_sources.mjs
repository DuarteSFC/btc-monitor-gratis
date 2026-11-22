const endpoints = {
  mvrvLatest: "https://data.explore21.com/v1/metrics/bitcoin-mvrv-ratio/latest",
  realizedLatest: "https://data.explore21.com/v1/metrics/bitcoin-realized-price/latest",
  soprExplore: "https://data.explore21.com/v1/metrics/bitcoin-sopr/latest",
  tftcETF: "https://www.tftc.io/bitcoin-etf-flows/latest.json",
  tftcData: "https://www.tftc.io/bitcoin-etf-flows/data.json",
  marketlight: "https://marketlight.ai/bt/api/public/liquidations/summary?symbol=BTCUSDT",
  xoomar: "https://xoomar.com/api/markets/liquidations",
  bgeoSopr: "https://bitcoin-data.com/v1/sopr/last",
  farside: "https://farside.co.uk/btc/",
};
await Promise.all(Object.entries(endpoints).map(async ([name,url])=>{
  try{
    const r=await fetch(url,{signal:AbortSignal.timeout(10000),headers:{"User-Agent":"BTC-Public-Data-Gate/1.0 (public research)","Accept":"application/json,text/html"}});
    const txt=await r.text();
    let res;
    try{
      const j=JSON.parse(txt);
      res={kind:"json",keys:Object.keys(j).slice(0,20),sample:JSON.stringify(j).slice(0,950)};
    }catch{
      const around=txt.search(/20 Nov 2026|21 Nov 2026|19 Nov 2026|20&nbsp;Nov/i);
      res={kind:"text",sample:txt.slice(Math.max(0,around-150),around>0?around+450:800).replace(/\s+/g," ").slice(0,900)};
    }
    console.log(JSON.stringify({name,status:r.status,type:r.headers.get("content-type"),length:txt.length,utc:new Date().toISOString(),...res}));
  }catch(e){console.log(JSON.stringify({name,error:String(e),utc:new Date().toISOString()}))}
}));
