import {GET as reportGET, config as parentConfig} from "./report.mjs";
import {fastReport} from "../fast_tactical.mjs";
export const config=parentConfig;
export async function GET(request){
  console.info("BTC_MONITOR_ROUTE_AUDIT:tactical UTC="+new Date().toISOString());
  if(request.method!=="GET")return reportGET(request);
  const [response,short]=await Promise.all([reportGET(request),fastReport().catch(()=>null)]);
  if(!response.ok)return response;
  const data=await response.json();
  // Preserve legacy fields and flags. Short-frame failures never invalidate the cycle report.
  return Response.json({...data,shortTactical:short},{headers:response.headers});
}
