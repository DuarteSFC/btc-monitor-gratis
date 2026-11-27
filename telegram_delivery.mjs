// Bounded retries for explicit Telegram rejections only. A timeout is ambiguous:
// Telegram may have accepted the message; avoid immediate blind retries.
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
export async function sendAlert({token,chat,message,isFresh=()=>true,request=fetch,sleep=pause,log=()=>{}}){
 if(typeof token!=="string"||!token||typeof chat!=="string"||!chat)return {ok:false,reason:"missing_credentials",attempts:0};
 if(typeof message!=="string"||!message||message.length>4096)return {ok:false,reason:"invalid_message",attempts:0};
 for(let attempt=1;attempt<=3;attempt++){
  if(!isFresh())return {ok:false,reason:"expired_before_send",attempts:attempt-1};
  let res,body;
  try{
   res=await request("https://api.telegram.org/bot"+token+"/sendMessage",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chat_id:chat,text:message,disable_web_page_preview:true}),signal:AbortSignal.timeout(8000)});
   body=await res.json();
  }catch{
   // Do not log request URL, response text, exception, token, chat or message.
   log({attempt,reason:"ambiguous_network_or_response"});
   return {ok:false,reason:"ambiguous_network_or_response",attempts:attempt};
  }
  if(res.ok&&body?.ok===true){
   log({attempt,reason:"api_accepted"});
   return {ok:true,reason:"api_accepted",attempts:attempt};
  }
  const status=Number.isInteger(res.status)&&res.status>=100&&res.status<=599?res.status:null;
  const code=Number.isInteger(body?.error_code)&&body.error_code>=100&&body.error_code<=599?body.error_code:null;
  const retryable=body?.ok===false&&(code===429||status===429||(code>=500&&code<=599)||(status>=500&&status<=599));
  log({attempt,reason:retryable?"explicit_retryable_rejection":"rejected_or_unknown",status,code});
  if(!retryable||attempt===3)return {ok:false,reason:retryable?"retry_limit":"rejected_or_unknown",attempts:attempt,status,code};
  const retryAfter=Number(body?.parameters?.retry_after);
  const wait=Number.isFinite(retryAfter)&&retryAfter>=0?Math.max(1000,Math.ceil(retryAfter*1000)):attempt*1000;
  // Do not block subsequent monitoring for long rate limits; next run can
  // reconsider events still within their original freshness window.
  if(wait>8000)return {ok:false,reason:"retry_after_too_long",attempts:attempt,status,code};
  await sleep(wait);
 }
 return {ok:false,reason:"retry_limit",attempts:3};
}
