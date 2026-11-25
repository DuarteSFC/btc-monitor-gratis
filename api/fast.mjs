import {fastReport} from "../fast_tactical.mjs";
export const config={maxDuration:60};
export async function GET(request){
  if(request.method!=="GET")return new Response(null,{status:405});
  try{return Response.json(await fastReport(),{headers:{"Cache-Control":"no-store, max-age=0","CDN-Cache-Control":"no-store","Vercel-CDN-Cache-Control":"no-store"}});}
  catch{return Response.json({error:"fast_market_unavailable"},{status:503,headers:{"Cache-Control":"no-store"}});}
}
