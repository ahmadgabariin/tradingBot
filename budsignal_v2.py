"""
BUD Signal Clone v2 — Deep Research Edition
Added vs v1:
  - Funding rate (real Binance data, full history) — contrarian extremes
  - Market structure (HH/HL for long, LH/LL for short)
  - RSI divergence detection (price vs RSI direction mismatch)
  - ADX trend strength (only trade when trending)
  - Multi-timeframe: 1D EMA trend filters 4H entries
  - Bollinger Band position (BB squeeze + breakout)
  - Volume profile zones (high-volume price clusters = real S/R)
  - Tighter threshold + signal confluence scoring
  - Both LONG and SHORT
"""
import requests, time, math
from collections import defaultdict

def fetch_klines(symbol, interval, n, futures=True):
    base = "https://fapi.binance.com/fapi/v1" if futures else "https://api.binance.com/api/v3"
    all_c = []; end = None
    limit = 1500 if futures else 1000
    for _ in range(math.ceil(n / limit)):
        url = f"{base}/klines?symbol={symbol}&interval={interval}&limit={limit}"
        if end: url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=20); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            time.sleep(0.08)
        except Exception as e:
            print(f"  klines error {interval}: {e}"); break
    raw = all_c[-n:]
    return {
        "o":  [float(c[1]) for c in raw],
        "h":  [float(c[2]) for c in raw],
        "l":  [float(c[3]) for c in raw],
        "c":  [float(c[4]) for c in raw],
        "v":  [float(c[5]) for c in raw],
        "tv": [float(c[9]) for c in raw],   # taker buy vol
        "ts": [int(c[0])   for c in raw],
        "n":  len(raw),
    }

def fetch_funding_rates(symbol, n=10000):
    """Full history of funding rates — Binance keeps all of it."""
    all_f = []; end = None
    for _ in range(math.ceil(n / 1000)):
        url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1000"
        if end: url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=20); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_f = batch + all_f
            end = int(batch[0]["fundingTime"]) - 1
            time.sleep(0.08)
        except Exception as e:
            print(f"  funding error: {e}"); break
    # returns dict: timestamp -> rate
    return {int(f["fundingTime"]): float(f["fundingRate"]) for f in all_f}

# ── Indicators ─────────────────────────────────────────────────────────────────
def ema_s(vals, period):
    if not vals: return 0
    k = 2/(period+1); v = vals[0]
    for x in vals[1:]: v = x*k+v*(1-k)
    return v

def ema_series(vals, period):
    k = 2/(period+1); v = vals[0]; res = [v]
    for x in vals[1:]: v = x*k+v*(1-k); res.append(v)
    return res

def rsi_val(vals, i, p=14):
    if i < p+1: return 50
    g=l=0.0
    for j in range(i-p+1,i+1):
        d=vals[j]-vals[j-1]
        if d>0: g+=d
        else: l-=d
    ag=g/p; al=l/p
    return 100 if al==0 else 100-100/(1+ag/al)

def atr_val(data, i, p=14):
    trs=[]
    for j in range(max(1,i-p+1),i+1):
        h=data["h"][j];l=data["l"][j];pc=data["c"][j-1]
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(trs)/len(trs) if trs else 0

def adx_val(data, i, p=14):
    if i < p+2: return 20
    pdms=[]; mdms=[]; trs=[]
    for j in range(max(1,i-p*2),i+1):
        h=data["h"][j];l=data["l"][j]
        ph=data["h"][j-1];pl=data["l"][j-1];pc=data["c"][j-1]
        pdms.append(max(h-ph,0) if (h-ph)>(pl-l) else 0)
        mdms.append(max(pl-l,0) if (pl-l)>(h-ph) else 0)
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    atr=sum(trs[-p:])/p
    if atr==0: return 20
    pdi=sum(pdms[-p:])/p/atr*100
    mdi=sum(mdms[-p:])/p/atr*100
    dx=abs(pdi-mdi)/(pdi+mdi)*100 if (pdi+mdi)>0 else 0
    return round(dx,1)

def macd_vals(closes, i):
    if i < 35: return 0,0,0
    sl=closes[max(0,i-80):i+1]
    e12=ema_series(sl,12)[-1]; e26=ema_series(sl,26)[-1]
    ml=e12-e26
    mv=[]
    for j in range(max(26,i-30),i+1):
        s=closes[max(0,j-80):j+1]
        mv.append(ema_series(s,12)[-1]-ema_series(s,26)[-1])
    sig=ema_series(mv,9)[-1] if len(mv)>=9 else ml
    return ml, sig, ml-sig

def bb_vals(closes, i, p=20, mult=2.0):
    if i < p: return closes[i],closes[i],closes[i],0
    s=closes[i-p+1:i+1]
    mid=sum(s)/p
    std=(sum((x-mid)**2 for x in s)/p)**0.5
    return mid-mult*std, mid, mid+mult*std, std*2/mid if mid>0 else 0

def vol_avg(vols, i, p=20):
    s=vols[max(0,i-p):i]
    return sum(s)/len(s) if s else vols[i]

# ── Market Structure ───────────────────────────────────────────────────────────
def market_structure(data, i, lookback=20):
    """
    Detect HH/HL (bullish) or LH/LL (bearish) swing structure.
    Returns: 'bullish', 'bearish', 'neutral'
    """
    if i < lookback+4: return "neutral"
    highs=[]; lows=[]
    for j in range(i-lookback, i):
        if j<2: continue
        if data["h"][j]>data["h"][j-1] and data["h"][j]>data["h"][j+1] if j+1<data["n"] else True:
            highs.append((j,data["h"][j]))
        if data["l"][j]<data["l"][j-1] and data["l"][j]<data["l"][j+1] if j+1<data["n"] else True:
            lows.append((j,data["l"][j]))
    if len(highs)<2 or len(lows)<2: return "neutral"
    hh = highs[-1][1] > highs[-2][1]  # higher high
    hl = lows[-1][1]  > lows[-2][1]   # higher low
    lh = highs[-1][1] < highs[-2][1]  # lower high
    ll = lows[-1][1]  < lows[-2][1]   # lower low
    if hh and hl: return "bullish"
    if lh and ll: return "bearish"
    return "neutral"

# ── RSI Divergence ─────────────────────────────────────────────────────────────
def rsi_divergence(data, i, lookback=20):
    """
    Bullish divergence: price lower low, RSI higher low → long signal
    Bearish divergence: price higher high, RSI lower high → short signal
    Returns: 'bullish', 'bearish', 'none'
    """
    if i < lookback+14: return "none"
    closes=data["c"]
    # Find recent swing low/high
    prev_low_i = i - lookback//2
    prev_high_i= i - lookback//2
    for j in range(i-lookback, i-3):
        if closes[j] < closes[prev_low_i]: prev_low_i=j
        if closes[j] > closes[closes.index(max(closes[i-lookback:i-3]))
                               if hasattr(closes,'index') else prev_high_i]: prev_high_i=j

    # Bullish div: price made new low but RSI didn't
    if closes[i] < closes[prev_low_i]:
        if rsi_val(closes,i) > rsi_val(closes,prev_low_i):
            return "bullish"
    # Bearish div: price made new high but RSI didn't
    if closes[i] > closes[prev_low_i]:
        if rsi_val(closes,i) < rsi_val(closes,prev_low_i):
            return "bearish"
    return "none"

# ── Volume Profile (high-volume price zones) ───────────────────────────────────
def volume_profile_sr(data, i, lookback=60, bins=20):
    """
    Build volume-at-price histogram.
    Returns nearest high-vol support and resistance.
    """
    if i < lookback: return None, None
    price=data["c"][i]
    lo=min(data["l"][i-lookback:i]); hi=max(data["h"][i-lookback:i])
    if hi==lo: return None, None
    bin_size=(hi-lo)/bins
    vol_at=[0.0]*bins
    for j in range(i-lookback, i):
        mid=(data["h"][j]+data["l"][j])/2
        b=int((mid-lo)/bin_size)
        b=max(0,min(bins-1,b))
        vol_at[b]+=data["v"][j]
    # High volume zones
    avg_vol=sum(vol_at)/bins
    hvz_prices=[lo+b*bin_size+bin_size/2 for b,v in enumerate(vol_at) if v>avg_vol*1.5]
    sup=max((p for p in hvz_prices if p<price), default=None)
    res=min((p for p in hvz_prices if p>price), default=None)
    return sup, res

# ── Funding Rate Lookup ────────────────────────────────────────────────────────
def get_funding_at(funding_map, ts):
    """Get nearest funding rate at or before timestamp."""
    # funding every 8h — find closest
    candidates=[t for t in funding_map if t <= ts]
    if not candidates: return 0.0
    return funding_map[max(candidates)]

# ── BUD Signal v2 ──────────────────────────────────────────────────────────────
def bud_signal_v2(data4h, data1d, i, funding_map, d1d_ema_map):
    """
    Multi-factor signal with all enhancements.
    """
    if i < 60: return "WAIT", 0, 0

    closes=data4h["c"]; price=closes[i]
    is_green=price>data4h["o"][i]
    ts=data4h["ts"][i]

    # ── MOMENTUM ──────────────────────────────────────────────────────────────
    sl=closes[max(0,i-250):i+1]
    e9 =ema_series(sl,9)[-1]
    e21=ema_series(sl,21)[-1]
    e50=ema_series(sl,50)[-1]
    e200=ema_series(sl,200)[-1] if len(sl)>=200 else ema_s(sl,len(sl))

    ml,msig,mhist=macd_vals(closes,i)
    _,_,mhist_prev=macd_vals(closes,i-1)
    r=rsi_val(closes,i)
    r_prev=rsi_val(closes,i-1)

    bb_lo,bb_mid,bb_hi,bb_width=bb_vals(closes,i)
    # BB squeeze: width < 75% of 20-bar avg width
    bb_widths=[bb_vals(closes,max(0,i-k),20)[3] for k in range(1,21)]
    bb_avg_w=sum(bb_widths)/len(bb_widths) if bb_widths else bb_width
    bb_squeeze=bb_width < bb_avg_w*0.75

    # ── PRESSURE ──────────────────────────────────────────────────────────────
    tv5 =sum(data4h["tv"][max(0,i-4):i+1])
    v5  =sum(data4h["v"][max(0,i-4):i+1])
    tbr5=tv5/v5 if v5>0 else 0.5

    tv20=sum(data4h["tv"][max(0,i-19):i+1])
    v20 =sum(data4h["v"][max(0,i-19):i+1])
    tbr20=tv20/v20 if v20>0 else 0.5

    va=vol_avg(data4h["v"],i)
    vr=data4h["v"][i]/va if va>0 else 1

    # ── FUNDING RATE (contrarian) ──────────────────────────────────────────────
    fr=get_funding_at(funding_map, ts)
    # Extreme positive funding = longs overloaded = SHORT signal
    # Extreme negative funding = shorts overloaded = LONG signal
    fr_extreme_long  = fr < -0.0005   # shorts overloaded → longs likely to squeeze
    fr_extreme_short = fr >  0.0008   # longs overloaded → shorts likely to squeeze
    fr_neutral_long  = -0.0003 < fr < 0.0002  # healthy for longs
    fr_neutral_short = 0.0002 < fr < 0.0006   # healthy for shorts

    # ── ADX (trend strength) ───────────────────────────────────────────────────
    adx=adx_val(data4h,i)
    trending=adx>22

    # ── MARKET STRUCTURE ──────────────────────────────────────────────────────
    ms=market_structure(data4h,i,30)

    # ── RSI DIVERGENCE ────────────────────────────────────────────────────────
    div="none"
    try: div=rsi_divergence(data4h,i,24)
    except: pass

    # ── VOLUME PROFILE S/R ────────────────────────────────────────────────────
    vp_sup,vp_res=volume_profile_sr(data4h,i,80)

    # ── 1D TREND FILTER ───────────────────────────────────────────────────────
    # Find 1D candle index closest to current 4H candle
    d1_e50=d1d_ema_map.get("e50", price)
    d1_e200=d1d_ema_map.get("e200", price)
    d1_trend_up   = price > d1_e50 > d1_e200*0.98
    d1_trend_down = price < d1_e50

    # ── LONG SCORE ────────────────────────────────────────────────────────────
    ls=0

    # 1D macro trend
    if d1_trend_up: ls+=3
    elif d1_trend_down: ls-=4

    # Momentum
    if e9>e21>e50: ls+=3
    if price>e200: ls+=2
    if mhist>0 and mhist>mhist_prev: ls+=3
    elif mhist>0: ls+=1
    if r<45: ls+=3       # oversold
    elif r<60: ls+=2
    elif r>70: ls-=4
    if r>r_prev and r<65: ls+=1  # RSI turning up
    if is_green: ls+=1

    # Market structure
    if ms=="bullish": ls+=3
    elif ms=="bearish": ls-=3

    # RSI divergence
    if div=="bullish": ls+=3
    elif div=="bearish": ls-=2

    # Pressure
    if tbr5>0.57: ls+=3
    elif tbr5>0.52: ls+=1
    elif tbr5<0.43: ls-=3
    if tbr5>tbr20: ls+=1

    # Funding (contrarian)
    if fr_extreme_long: ls+=3   # shorts squeezed → good for longs
    elif fr_neutral_long: ls+=1
    elif fr_extreme_short: ls-=3

    # ADX
    if trending: ls+=2

    # BB
    if bb_squeeze and price>bb_hi: ls+=2  # squeeze breakout up
    elif price<bb_lo: ls+=2               # price below lower BB = oversold
    elif price>bb_hi and not bb_squeeze: ls-=2  # overbought breakout

    # Volume profile
    if vp_sup and (price-vp_sup)/price<0.015: ls+=2  # at vol support
    if vp_res and (vp_res-price)/price<0.01: ls-=3   # at vol resistance

    # Volume
    if vr>2.0: ls+=2
    elif vr>1.5: ls+=1

    # Blockers
    if e9<e21: ls-=3
    if mhist<0 and mhist<mhist_prev: ls-=2
    if fr_extreme_short: ls-=2

    # ── SHORT SCORE ───────────────────────────────────────────────────────────
    ss=0

    # 1D macro trend
    if d1_trend_down: ss+=3
    elif d1_trend_up: ss-=3

    # Momentum
    if e9<e21<e50: ss+=3
    if price<e200: ss+=2
    if mhist<0 and mhist<mhist_prev: ss+=3
    elif mhist<0: ss+=1
    if r>65: ss+=3       # overbought
    elif r>55: ss+=1
    elif r<35: ss-=4
    if r<r_prev and r>40: ss+=1
    if not is_green: ss+=1

    # Market structure
    if ms=="bearish": ss+=3
    elif ms=="bullish": ss-=3

    # RSI divergence
    if div=="bearish": ss+=3
    elif div=="bullish": ss-=2

    # Pressure (sellers)
    if tbr5<0.43: ss+=3
    elif tbr5<0.48: ss+=1
    elif tbr5>0.57: ss-=3
    if tbr5<tbr20: ss+=1

    # Funding (contrarian)
    if fr_extreme_short: ss+=3  # longs overloaded → good for shorts
    elif fr_neutral_short: ss+=1
    elif fr_extreme_long: ss-=3

    # ADX
    if trending: ss+=2

    # BB
    if bb_squeeze and price<bb_lo: ss+=2  # squeeze breakout down
    elif price>bb_hi: ss+=2               # overbought
    elif price<bb_lo and not bb_squeeze: ss-=2

    # Volume profile
    if vp_res and (vp_res-price)/price<0.015: ss+=2  # at vol resistance
    if vp_sup and (price-vp_sup)/price<0.01: ss-=3   # at vol support

    if vr>2.0: ss+=2
    elif vr>1.5: ss+=1

    # Blockers
    if e9>e21: ss-=3
    if mhist>0 and mhist>mhist_prev: ss-=2
    if fr_extreme_long: ss-=2

    # ── DECISION (high threshold = selective) ─────────────────────────────────
    THRESHOLD=14
    if ls>=THRESHOLD and ls>ss+3:
        return "LONG", ls, ss
    elif ss>=THRESHOLD and ss>ls+3:
        return "SHORT", ls, ss
    return "WAIT", ls, ss

# ── Backtest ───────────────────────────────────────────────────────────────────
def backtest(data4h, data1d, funding_map, sl, tp, max_hold=42):
    wins=losses=0
    lw=ll=sw=sl2=0
    n=data4h["n"]; i=60

    # Pre-compute 1D EMA map for speed (by timestamp)
    closes1d=data1d["c"]
    ts1d=data1d["ts"]
    e50_1d=ema_series(closes1d,50)
    e200_1d=ema_series(closes1d,200) if len(closes1d)>=200 else ema_series(closes1d,len(closes1d))

    # Build ts->ema lookup
    d1d_by_ts={}
    for idx,ts in enumerate(ts1d):
        d1d_by_ts[ts]={"e50":e50_1d[idx],"e200":e200_1d[idx] if idx<len(e200_1d) else e50_1d[idx]}

    def get_1d_ema(ts4h):
        # find latest 1d candle before this 4h ts
        day_ts = ts4h - (ts4h % 86400000)
        candidates=[t for t in d1d_by_ts if t<=day_ts]
        if not candidates: return {"e50":0,"e200":0}
        return d1d_by_ts[max(candidates)]

    while i < n-1:
        d1d_ema=get_1d_ema(data4h["ts"][i])
        sig,ls,ss=bud_signal_v2(data4h,data1d,i,funding_map,d1d_ema)
        if sig=="WAIT": i+=1; continue

        ep=data4h["c"][i]
        sl_p=ep*(1-sl) if sig=="LONG" else ep*(1+sl)
        tp_p=ep*(1+tp) if sig=="LONG" else ep*(1-tp)

        result=None; j=i+1
        while j<min(i+max_hold+1,n):
            if sig=="LONG":
                if data4h["l"][j]<=sl_p: result="LOSS"; break
                if data4h["h"][j]>=tp_p: result="WIN";  break
            else:
                if data4h["h"][j]>=sl_p: result="LOSS"; break
                if data4h["l"][j]<=tp_p: result="WIN";  break
            j+=1

        if result is None: result="LOSS"
        won=result=="WIN"
        if won: wins+=1
        else: losses+=1
        if sig=="LONG":
            if won: lw+=1
            else: ll+=1
        else:
            if won: sw+=1
            else: sl2+=1
        i=j+1

    return wins,losses,lw,ll,sw,sl2

# ── Grid ───────────────────────────────────────────────────────────────────────
SL_TP=[
    # High WR (inverted)
    (0.025,0.008),(0.030,0.010),(0.030,0.012),(0.035,0.012),
    (0.040,0.012),(0.040,0.015),(0.050,0.015),(0.050,0.020),
    # Balanced
    (0.020,0.020),(0.025,0.025),(0.030,0.030),(0.040,0.040),
    # Proper R/R
    (0.020,0.040),(0.025,0.050),(0.030,0.060),(0.030,0.080),
    (0.040,0.080),(0.040,0.100),(0.050,0.100),(0.050,0.150),
]

print("="*70)
print("  BUD Signal Clone v2 — Multi-Factor Deep Backtest")
print("="*70)

print("\nFetching BTC 4H futures (max history)...", flush=True)
d4h=fetch_klines("BTCUSDT","4h",15000,futures=True)
print(f"  4H: {d4h['n']} candles ({d4h['n']/6/365:.1f} years)")

print("Fetching BTC 1D (for macro trend)...", flush=True)
d1d=fetch_klines("BTCUSDT","1d",3000,futures=False)
print(f"  1D: {d1d['n']} candles ({d1d['n']/365:.1f} years)")

print("Fetching funding rate history...", flush=True)
fr_map=fetch_funding_rates("BTCUSDT",10000)
print(f"  Funding: {len(fr_map)} data points ({len(fr_map)*8/24/365:.1f} years)")

days=d4h["n"]/6
print(f"\nRunning backtest on {len(SL_TP)} SL/TP combos...\n")

results=[]
for sl,tp in SL_TP:
    print(f"  SL={sl*100:.1f}% TP={tp*100:.1f}%...", flush=True)
    w,l,lw,ll,sw,sl2=backtest(d4h,d1d,fr_map,sl,tp)
    total=w+l
    if total<15: continue
    wr=w/total
    ev=wr*tp-(1-wr)*sl
    if ev<=0: continue
    tpm=total/days*30
    lt=lw+ll; st=sw+sl2
    results.append({
        "sl":sl,"tp":tp,"wins":w,"losses":l,"total":total,
        "wr":round(wr*100,1),"ev":round(ev*100,3),
        "rr":round(tp/sl,2),"tpm":round(tpm,1),
        "lw":lw,"ll":ll,"sw":sw,"sl2":sl2,"lt":lt,"st":st,
        "long_wr":round(lw/lt*100,1) if lt>0 else 0,
        "short_wr":round(sw/st*100,1) if st>0 else 0,
        "be":round(sl/(sl+tp)*100,1),
    })

results.sort(key=lambda x:(x["wr"],x["ev"]),reverse=True)
print(f"\nFound {len(results)} profitable combos\n")

print("="*120)
print("RESULTS — BUD Signal v2 | BTC 4H + 1D filter + Funding + Structure + Divergence + Volume Profile")
print("="*120)
print(f"  {'#':<3} {'SL':>5} {'TP':>6} {'R/R':>6} {'BE%':>5} | "
      f"{'N':>5} {'WR%':>6} {'EV%':>7} {'T/mo':>5} | "
      f"{'LONG WR':>8} {'L#':>4} | {'SHORT WR':>9} {'S#':>4}")
print(f"  {'-'*115}")

for i,r in enumerate(results[:20],1):
    print(f"  {i:<3} {r['sl']*100:>5.1f} {r['tp']*100:>6.1f} {r['rr']:>5.2f}:1 {r['be']:>4.1f}% | "
          f"{r['total']:>5} {r['wr']:>5.1f}% {r['ev']:>+6.3f}% {r['tpm']:>4.1f}/mo | "
          f"{r['long_wr']:>7.1f}% {r['lt']:>4} | {r['short_wr']:>8.1f}% {r['st']:>4}")

if results:
    b=results[0]
    print(f"\n{'='*70}")
    print(f"BEST RESULT")
    print(f"{'='*70}")
    print(f"  SL={b['sl']*100:.1f}%  TP={b['tp']*100:.1f}%  R/R={b['rr']:.2f}:1")
    print(f"  Overall:  {b['wr']}% WR  ({b['wins']}W/{b['losses']}L)  {b['total']} trades / {days:.0f}d")
    print(f"  LONG:     {b['long_wr']}% WR  ({b['lw']}W/{b['ll']}L)")
    print(f"  SHORT:    {b['short_wr']}% WR  ({b['sw']}W/{b['sl2']}L)")
    print(f"  EV/trade: {b['ev']:+.3f}%")
    print(f"  T/month:  {b['tpm']}")

    pos=0.50; bal=1000.0
    bal_f=bal*(1+pos*b["tp"])**b["wins"]*(1-pos*b["sl"])**b["losses"]
    mo=(bal_f/bal-1)/(days/30)*100
    print(f"\n  $1000 @ 50% pos after {days:.0f}d: ${bal_f:.2f}  ({(bal_f/bal-1)*100:+.1f}% total)")
    print(f"  Avg monthly: {mo:+.2f}%")

print("\nDone.")
