"""
BUD Signal Clone — Deep Backtest
Replicates: Pressure (OI/order flow) + Momentum (EMA/MACD/RSI) + Liquidity (S/R levels)
Timeframe: 4H BTC (both LONG and SHORT)
Max history available
"""
import requests, time, math
from datetime import datetime

PAIR = "BTCUSDT"
TF   = "4h"
N    = 15000   # ~6800 days worth, Binance caps at actual available

def fetch_futures(pair, tf, n):
    """Fetch futures OHLCV — more volume/OI-relevant than spot."""
    all_c = []; end = None
    url_base = f"https://fapi.binance.com/fapi/v1/klines?symbol={pair}&interval={tf}&limit=1500"
    for _ in range(math.ceil(n / 1500)):
        url = url_base + (f"&endTime={end}" if end else "")
        try:
            r = requests.get(url, timeout=20); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            time.sleep(0.1)
        except Exception as e:
            print(f"  futures error: {e}"); break
    raw = all_c[-n:]
    return {
        "o": [float(c[1]) for c in raw],
        "h": [float(c[2]) for c in raw],
        "l": [float(c[3]) for c in raw],
        "c": [float(c[4]) for c in raw],
        "v": [float(c[5]) for c in raw],         # volume
        "tv": [float(c[9]) for c in raw],         # taker buy volume (order flow proxy)
        "qv": [float(c[7]) for c in raw],         # quote volume
        "n": len(raw),
        "ts": [int(c[0]) for c in raw],
    }

# ── Indicators ────────────────────────────────────────────────────────────────
def ema_series(vals, period):
    k = 2/(period+1); v = vals[0]; res = [v]
    for x in vals[1:]: v = x*k+v*(1-k); res.append(v)
    return res

def macd_hist(closes, i):
    if i < 35: return 0, 0
    sl = closes[max(0,i-60):i+1]
    e12 = ema_series(sl, 12)[-1]
    e26 = ema_series(sl, 26)[-1]
    ml  = e12 - e26
    # signal line (9-period EMA of MACD)
    macd_vals = []
    for j in range(max(26, i-20), i+1):
        s = closes[max(0,j-60):j+1]
        macd_vals.append(ema_series(s,12)[-1] - ema_series(s,26)[-1])
    sig = ema_series(macd_vals, 9)[-1] if len(macd_vals) >= 9 else ml
    return ml, ml - sig

def rsi(vals, i, period=14):
    if i < period+1: return 50
    gains = losses = 0.0
    for j in range(i-period+1, i+1):
        d = vals[j]-vals[j-1]
        if d>0: gains+=d
        else: losses-=d
    ag=gains/period; al=losses/period
    if al==0: return 100
    return 100-100/(1+ag/al)

def atr(data, i, period=14):
    trs=[]
    for j in range(max(1,i-period+1),i+1):
        h=data["h"][j];l=data["l"][j];pc=data["c"][j-1]
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(trs)/len(trs) if trs else 0

def vol_avg(vols, i, period=20):
    s=vols[max(0,i-period):i]
    return sum(s)/len(s) if s else vols[i]

def sma(vals, i, period):
    s=vals[max(0,i-period+1):i+1]
    return sum(s)/len(s)

# ── PRESSURE: Order Flow (taker buy volume ratio) ─────────────────────────────
def pressure(data, i, period=10):
    """
    Taker buy ratio = taker_buy_vol / total_vol
    >0.55 = buyers dominating (bullish pressure)
    <0.45 = sellers dominating (bearish pressure)
    """
    if i < period: return 0.5
    tv_sum = sum(data["tv"][max(0,i-period+1):i+1])
    v_sum  = sum(data["v"][max(0,i-period+1):i+1])
    return tv_sum / v_sum if v_sum > 0 else 0.5

# ── LIQUIDITY: Key price levels where stops cluster ───────────────────────────
def liquidity_levels(data, i, lookback=100):
    """
    Find price levels with high volume (liquidation magnets).
    Returns (nearest_support, nearest_resistance) above/below current price.
    """
    if i < lookback: return None, None
    price = data["c"][i]
    # Price clustering — find highs and lows that repeated (swing points)
    highs = []; lows = []
    window = list(range(max(0,i-lookback), i))
    for j in window:
        if j < 2: continue
        # Swing high
        if data["h"][j] >= data["h"][j-1] and data["h"][j] >= data["h"][j+1] if j+1 < data["n"] else True:
            highs.append(data["h"][j])
        # Swing low
        if data["l"][j] <= data["l"][j-1] and data["l"][j] <= data["l"][j+1] if j+1 < data["n"] else True:
            lows.append(data["l"][j])

    # Nearest resistance above
    res = min((h for h in highs if h > price), default=None)
    # Nearest support below
    sup = max((l for l in lows if l < price), default=None)
    return sup, res

# ── BUD SIGNAL Logic ──────────────────────────────────────────────────────────
def bud_signal(data, i):
    """
    Replicates BUD Signal 3-factor logic:
    1. PRESSURE  — taker buy/sell ratio (order flow)
    2. MOMENTUM  — EMA alignment + MACD + RSI
    3. LIQUIDITY — distance to key S/R levels

    Returns: "LONG", "SHORT", or "WAIT"
    """
    if i < 50: return "WAIT"

    closes = data["c"]
    price  = closes[i]
    is_green = price > data["o"][i]

    # ── MOMENTUM ──────────────────────────────────────────────────────────────
    e9  = ema_series(closes[max(0,i-50):i+1], 9)[-1]
    e21 = ema_series(closes[max(0,i-50):i+1], 21)[-1]
    e50 = ema_series(closes[max(0,i-100):i+1], 50)[-1]
    e200= ema_series(closes[max(0,i-200):i+1], 200)[-1] if i >= 200 else sma(closes,i,200)

    ml, hist = macd_hist(closes, i)
    _, hist_prev = macd_hist(closes, i-1)
    r = rsi(closes, i)

    # ── PRESSURE (order flow) ─────────────────────────────────────────────────
    tbr = pressure(data, i, 5)   # 5-bar taker buy ratio
    tbr_slow = pressure(data, i, 20)

    # ── LIQUIDITY ─────────────────────────────────────────────────────────────
    sup, res = liquidity_levels(data, i, 80)
    a = atr(data, i)
    va = vol_avg(data["v"], i)
    vr = data["v"][i] / va if va > 0 else 1

    # ── SCORE LONG ────────────────────────────────────────────────────────────
    long_score = 0

    # Momentum
    if e9 > e21 > e50: long_score += 2          # uptrend aligned
    if price > e200:   long_score += 1           # above macro trend
    if hist > 0 and hist > hist_prev: long_score += 2   # MACD rising
    elif hist > 0:     long_score += 1
    if 40 < r < 65:    long_score += 2           # RSI healthy, not overbought
    elif r < 40:       long_score += 3           # RSI oversold — bounce zone
    if is_green:       long_score += 1

    # Pressure (order flow — bulls dominating)
    if tbr > 0.55:     long_score += 2
    if tbr > tbr_slow: long_score += 1           # pressure accelerating

    # Liquidity (price near support = good long entry)
    if sup and (price - sup) / price < 0.02:
        long_score += 2   # sitting on support
    if res and (res - price) / price > 0.03:
        long_score += 1   # clear room to resistance

    # Volume confirmation
    if vr > 1.5: long_score += 1

    # Blockers for LONG
    if r > 72:         long_score -= 4           # overbought
    if e9 < e21:       long_score -= 3           # bearish cross
    if hist < 0 and hist < hist_prev: long_score -= 2  # MACD falling
    if tbr < 0.42:     long_score -= 2           # heavy selling pressure
    if res and (res - price) / price < 0.01:
        long_score -= 3   # at resistance — bad long entry

    # ── SCORE SHORT ───────────────────────────────────────────────────────────
    short_score = 0

    # Momentum bearish
    if e9 < e21 < e50: short_score += 2
    if price < e200:   short_score += 1
    if hist < 0 and hist < hist_prev: short_score += 2
    elif hist < 0:     short_score += 1
    if r > 60 and r < 80: short_score += 2      # RSI elevated — reversal zone
    elif r >= 80:      short_score += 3          # overbought
    if not is_green:   short_score += 1

    # Pressure (sellers dominating)
    if tbr < 0.45:     short_score += 2
    if tbr < tbr_slow: short_score += 1

    # Liquidity (price near resistance = good short entry)
    if res and (res - price) / price < 0.02:
        short_score += 2
    if sup and (price - sup) / price > 0.03:
        short_score += 1

    if vr > 1.5: short_score += 1

    # Blockers for SHORT
    if r < 35:         short_score -= 4
    if e9 > e21:       short_score -= 3
    if hist > 0 and hist > hist_prev: short_score -= 2
    if tbr > 0.58:     short_score -= 2
    if sup and (price - sup) / price < 0.01:
        short_score -= 3

    # ── DECISION ─────────────────────────────────────────────────────────────
    THRESHOLD = 6
    if long_score >= THRESHOLD and long_score > short_score:
        return "LONG"
    elif short_score >= THRESHOLD and short_score > long_score:
        return "SHORT"
    return "WAIT"


# ── Backtest ──────────────────────────────────────────────────────────────────
def backtest(data, sl, tp, max_hold=60):
    """
    Both LONG and SHORT trades.
    Non-overlapping, max_hold=60 candles (10 days on 4H), unresolved=LOSS.
    """
    wins = losses = 0
    long_w = long_l = short_w = short_l = 0
    trades = []
    n = data["n"]; i = 50

    while i < n - 1:
        sig = bud_signal(data, i)
        if sig == "WAIT": i += 1; continue

        ep = data["c"][i]
        if sig == "LONG":
            sl_p = ep * (1 - sl); tp_p = ep * (1 + tp)
        else:  # SHORT
            sl_p = ep * (1 + sl); tp_p = ep * (1 - tp)

        result = None; j = i + 1
        while j < min(i + max_hold + 1, n):
            if sig == "LONG":
                if data["l"][j] <= sl_p: result = "LOSS"; break
                if data["h"][j] >= tp_p: result = "WIN";  break
            else:
                if data["h"][j] >= sl_p: result = "LOSS"; break
                if data["l"][j] <= tp_p: result = "WIN";  break
            j += 1

        if result is None: result = "LOSS"
        won = result == "WIN"
        if won: wins += 1
        else:   losses += 1

        if sig == "LONG":
            if won: long_w += 1
            else:   long_l += 1
        else:
            if won: short_w += 1
            else:   short_l += 1

        trades.append({"sig": sig, "result": result, "ep": ep, "candle": i})
        i = j + 1

    return wins, losses, long_w, long_l, short_w, short_l, trades


# ── Grid search ───────────────────────────────────────────────────────────────
SL_TP = [
    # Tight SL — high WR inverted
    (0.015,0.008),(0.020,0.010),(0.025,0.010),(0.025,0.012),
    (0.030,0.010),(0.030,0.015),(0.035,0.015),(0.040,0.020),
    # Balanced 1:1
    (0.015,0.015),(0.020,0.020),(0.025,0.025),(0.030,0.030),
    # Proper 2:1+
    (0.015,0.030),(0.020,0.040),(0.025,0.050),(0.030,0.060),
    (0.020,0.060),(0.025,0.060),(0.030,0.080),(0.040,0.080),
    # Swing
    (0.050,0.100),(0.060,0.120),(0.050,0.150),(0.040,0.120),
]

print("="*70)
print("  BUD SIGNAL CLONE — Deep Backtest on BTC 4H Futures")
print("="*70)
print(f"\nFetching BTC 4H futures (max history)...")
data = fetch_futures("BTCUSDT", "4h", 15000)
days = data["n"] / 6
print(f"Got {data['n']} candles = {days:.0f} days ({days/365:.1f} years)\n")

all_results = []

for sl, tp in SL_TP:
    w, l, lw, ll, sw, sl2, trades = backtest(data, sl, tp)
    total = w + l
    if total < 20: continue
    wr = w/total
    ev = wr*tp - (1-wr)*sl
    if ev <= 0: continue
    tpm = total/days*30
    all_results.append({
        "sl":sl,"tp":tp,"wins":w,"losses":l,"total":total,
        "wr":round(wr*100,1),"ev":round(ev*100,3),
        "rr":round(tp/sl,2),"tpm":round(tpm,1),
        "lw":lw,"ll":ll,"sw":sw,"sl2":sl2,
        "long_wr":round(lw/(lw+ll)*100,1) if (lw+ll)>0 else 0,
        "short_wr":round(sw/(sw+sl2)*100,1) if (sw+sl2)>0 else 0,
        "be":round(sl/(sl+tp)*100,1),
    })

all_results.sort(key=lambda x:(x["wr"],x["ev"]),reverse=True)

print(f"Found {len(all_results)} profitable combos\n")
print("="*115)
print("BUD SIGNAL CLONE RESULTS — BTC 4H, Both LONG+SHORT")
print("="*115)
print(f"  {'#':<3} {'SL':>5} {'TP':>6} {'R/R':>6} {'BE%':>5} | "
      f"{'N':>5} {'WR%':>6} {'EV%':>7} {'T/mo':>5} | "
      f"{'LONG WR':>8} {'L trades':>8} | {'SHORT WR':>9} {'S trades':>8}")
print(f"  {'-'*110}")

for i,r in enumerate(all_results[:20],1):
    lt = r["lw"]+r["ll"]; st = r["sw"]+r["sl2"]
    print(f"  {i:<3} {r['sl']*100:>5.1f} {r['tp']*100:>6.1f} {r['rr']:>5.2f}:1 {r['be']:>4.1f}% | "
          f"{r['total']:>5} {r['wr']:>5.1f}% {r['ev']:>+6.3f}% {r['tpm']:>4.1f}/mo | "
          f"{r['long_wr']:>7.1f}% {lt:>8} | {r['short_wr']:>8.1f}% {st:>8}")

# Best result deep dive
if all_results:
    b = all_results[0]
    print(f"\n{'='*70}")
    print(f"BEST RESULT DEEP DIVE")
    print(f"{'='*70}")
    print(f"  SL={b['sl']*100:.1f}%  TP={b['tp']*100:.1f}%  R/R={b['rr']:.2f}:1")
    print(f"  Overall WR:  {b['wr']}%  ({b['wins']}W/{b['losses']}L)")
    print(f"  LONG  WR:    {b['long_wr']}%  ({b['lw']}W/{b['ll']}L)")
    print(f"  SHORT WR:    {b['short_wr']}%  ({b['sw']}W/{b['sl2']}L)")
    print(f"  EV/trade:    {b['ev']:+.3f}%")
    print(f"  Trades/mo:   {b['tpm']}")
    print(f"  History:     {days:.0f} days ({days/365:.1f} years)")
    print(f"  Breakeven:   {b['be']}% WR needed")

    # Monthly P&L simulation $1000, 50% position
    pos = 0.50
    bal = 1000.0
    w_gain = 1 + pos*b["tp"]
    l_loss = 1 - pos*b["sl"]
    bal_after = bal * (w_gain**b["wins"]) * (l_loss**b["losses"])
    monthly_pct = (bal_after/bal - 1) / (days/30) * 100
    print(f"\n  $1000 simulation (50% pos size):")
    print(f"  After {days:.0f} days: ${bal_after:.2f}  ({(bal_after/bal-1)*100:+.1f}% total)")
    print(f"  Avg monthly: {monthly_pct:+.2f}%")

print(f"\nDone.")
