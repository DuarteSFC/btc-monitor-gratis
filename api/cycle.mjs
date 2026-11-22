import {GET as reportGET, config as parentConfig} from "./report.mjs";
export const config = parentConfig;
export async function GET(request){
  console.info("BTC_MONITOR_ROUTE_AUDIT:"+"cycle"+" UTC="+new Date().toISOString());
  return await reportGET(request);
}
