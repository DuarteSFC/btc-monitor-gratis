import {report} from "../worker.mjs";
export const config={maxDuration:60};
export default async function handler(request){
  if(request.method!=="GET")return new Response(JSON.stringify({error:"method_not_allowed"}),{status:405,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
  try{
    const snapshot=await report(Date.now());
    return new Response(JSON.stringify(snapshot),{status:200,headers:{
      "Content-Type":"application/json; charset=utf-8",
      "Cache-Control":"no-store, no-cache, must-revalidate",
      "CDN-Cache-Control":"no-store","Vercel-CDN-Cache-Control":"no-store",
      "Access-Control-Allow-Origin":"*"
    }});
  }catch(e){
    return new Response(JSON.stringify({ok:false,error:String(e?.message||e),generatedUtc:new Date().toISOString()}),
      {status:503,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
  }
}
