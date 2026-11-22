/**
 * Descriptive Fibonacci anchors only: objective extremes of a fixed lookback.
 * Do not treat levels as buy orders or predictions, nor as Elliott waves.
 */
export function fibonacciFromClosedBars(bars,lookback=90){
  if(!Array.isArray(bars)||bars.length<lookback)return null;
  const b=bars.slice(-lookback);
  let hi=0,lo=0;
  for(let i=1;i<b.length;i++){
    if(b[i].h>b[hi].h)hi=i;
    if(b[i].l<b[lo].l)lo=i;
  }
  const H=b[hi].h,L=b[lo].l,d=H-L;
  if(!(d>0)||hi===lo)return null;
  const direction=hi<lo?"down_leg":"up_leg";
  const ratios=[0.236,0.382,0.5,0.618,0.786];
  return {type:"extreme_lookback_not_verified_impulse",
    lookbackClosedCandles:lookback,
    direction,
    low:{price:L,openUtc:new Date(b[lo].t).toISOString()},
    high:{price:H,openUtc:new Date(b[hi].t).toISOString()},
    retracements:ratios.map(r=>({
      ratio:r,
      level:direction==="down_leg"?L+d*r:H-d*r
    })),
    caution:"Fibonacci anchors are window extremes, not confirmed Elliott swings. Levels are not buy triggers; update every closed candle."
  };
}
