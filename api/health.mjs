export default function handler(){
  return Response.json({ok:true,service:"BTC Public Data Gate",version:"1.1.0",
    note:"This only checks web application deployment, not live market data."},
    {headers:{"Cache-Control":"no-store"}});
}
