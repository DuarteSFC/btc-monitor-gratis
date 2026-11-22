const urls={tftc:"https://www.tftc.io/bitcoin-etf-flows/latest.json",xoomar:"https://xoomar.com/api/markets/liquidations",marketlight:"https://marketlight.ai/bt/api/public/liquidations/summary?symbol=BTCUSDT",credit:"https://api.bitcoincreditstack.com/v1/onchain/indicators/latest",creditPage:"https://www.bitcoincreditstack.com/indicators/onchain-latest"};
for(const [name,url] of Object.entries(urls)){
try{
 const r=await fetch(url,{signal:AbortSignal.timeout(11000),headers:{"Accept":"application/json,text/html","User-Agent":"BTC-Monitor-Free/1.0"}});
 const raw=await r.text();let j;
 try{j=JSON.parse(raw)}catch{console.log(JSON.stringify({name,status:r.status,htmlPreview:raw.slice(0,200)}));continue;}
 if(name==="tftc"){console.log(JSON.stringify({name,status:r.status,meta:{updatedThrough:j.updatedThrough,dateModified:j.dateModified,latestSession:j.latestSession,latestPerFund:j.latestPerFund,recentSessions:j.recentSessions}}).slice(0,7000));}
 if(name==="xoomar"){console.log(JSON.stringify({name,status:r.status,updatedAt:j.updatedAt,dataKeys:Object.keys(j.data||{}),meta:j.meta,topSymbols:j.data?.topSymbols,bySymbol:j.data?.bySymbol,tail:JSON.stringify(j).slice(-600)}).slice(0,5500));}
 if(name==="marketlight"){console.log(JSON.stringify({name,status:r.status,fromMs:j.fromMs,toMs:j.toMs,symbols:j.bySymbol?.slice(0,3),sum:j.total,exchange:j.byExchange}).slice(0,5500));}
 if(name==="credit"){console.log(JSON.stringify({name,status:r.status,keys:Object.keys(j),sample:JSON.stringify(j).slice(0,5800)}));}
}catch(e){console.log(JSON.stringify({name,error:String(e)}))}
}
