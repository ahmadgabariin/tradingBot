"""
Keltner Break on 1D with candlestick pattern filters
Patterns: Hammer, Bullish Engulfing, Morning Star, Marubozu, Doji rejection,
          Three White Soldiers, Piercing Line, Tweezer Bottom
TP always >= 2x SL
Max history on 1d (~8 years)
"""
import requests, time, math

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

def fetch_max(pair, tf="1d", n=3000):
    all_c = []; end = None
    for _ in range(math.ceil(n / 1000)):
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit=1000"
        if end: url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=20); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            time.sleep(0.1)
        except Exception as e:
            print(f"  error {pair}: {e}"); break
    raw = all_c[-n:]
    return {
        "o": [float(c[1]) for c in raw],
        "h": [float(c[2]) for c in raw],
        "l": [float(c[3]) for c in raw],
        "c": [float(c[4]) for c in raw],
        "v": [float(c[5]) for c in raw],
        "n": len(raw)
    }

# ── Indicators ────────────────────────────────────────────────────────────────
def ema(vals, period):
    k = 2/(period+1); v = vals[0]
    for x in vals[1:]: v = x*k + v*(1-k)
    return v

def atr(data, i, period=14):
    trs = []
    for j in range(max(1, i-period+1), i+1):
        h=data["h"][j]; l=data["l"][j]; pc=data["c"][j-1]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs)/len(trs) if trs else 0

def sma(vals, i, period):
    s = vals[max(0,i-period+1):i+1]
    return sum(s)/len(s)

def rsi(vals, i, period=14):
    gains = losses = 0.0
    for j in range(max(1,i-period+1), i+1):
        d = vals[j] - vals[j-1]
        if d > 0: gains += d
        else: losses -= d
    ag = gains/period; al = losses/period
    if al == 0: return 100
    return 100 - 100/(1+ag/al)

def vol_avg(data, i, period=20):
    s = data["v"][max(0,i-period):i]
    return sum(s)/len(s) if s else data["v"][i]

# ── Candlestick Patterns ──────────────────────────────────────────────────────
def pattern_score(data, i):
    """Returns (score, list of pattern names found). Higher = more bullish."""
    if i < 3: return 0, []
    o=data["o"]; h=data["h"]; l=data["l"]; c=data["c"]
    score = 0; patterns = []

    body     = abs(c[i] - o[i])
    c_range  = h[i] - l[i]
    lower_w  = min(c[i],o[i]) - l[i]
    upper_w  = h[i] - max(c[i],o[i])
    is_green = c[i] > o[i]
    is_red   = c[i] < o[i]
    body_pct = body / o[i] * 100 if o[i] > 0 else 0

    # 1. Hammer — small body at top, long lower wick, green preferred
    if c_range > 0 and lower_w >= body * 2 and upper_w <= body * 0.5 and body_pct > 0.1:
        score += 3; patterns.append("Hammer")

    # 2. Bullish Engulfing — current green candle fully engulfs previous red
    if (is_green and c[i-1] < o[i-1] and
        o[i] <= c[i-1] and c[i] >= o[i-1]):
        score += 4; patterns.append("Bullish Engulfing")

    # 3. Morning Star — 3 candles: red, small doji/body, strong green
    if i >= 2:
        red_before  = c[i-2] < o[i-2]
        small_mid   = abs(c[i-1]-o[i-1]) < abs(c[i-2]-o[i-2]) * 0.4
        strong_green= is_green and c[i] > (o[i-2]+c[i-2])/2
        if red_before and small_mid and strong_green:
            score += 5; patterns.append("Morning Star")

    # 4. Marubozu — almost no wicks, strong green body
    if is_green and body_pct > 1.5 and lower_w < body*0.1 and upper_w < body*0.1:
        score += 3; patterns.append("Marubozu")

    # 5. Doji at support rejection — tiny body, long lower wick, previous red
    if c_range > 0 and body < c_range * 0.1 and lower_w > c_range * 0.5 and c[i-1] < o[i-1]:
        score += 3; patterns.append("Doji Rejection")

    # 6. Three White Soldiers — 3 consecutive strong green candles
    if i >= 3:
        g1 = c[i-2] > o[i-2] and (c[i-2]-o[i-2])/o[i-2]*100 > 0.5
        g2 = c[i-1] > o[i-1] and (c[i-1]-o[i-1])/o[i-1]*100 > 0.5
        g3 = is_green and body_pct > 0.5
        opens_mid1 = o[i-1] > o[i-2] and o[i-1] < c[i-2]
        opens_mid2 = o[i]   > o[i-1] and o[i]   < c[i-1]
        if g1 and g2 and g3 and opens_mid1 and opens_mid2:
            score += 4; patterns.append("Three White Soldiers")

    # 7. Piercing Line — previous red, current green opens below prev low, closes above prev midpoint
    if (i >= 1 and is_green and c[i-1] < o[i-1] and
        o[i] < l[i-1] and c[i] > (o[i-1]+c[i-1])/2):
        score += 3; patterns.append("Piercing Line")

    # 8. Tweezer Bottom — two candles with same low, second is green
    if i >= 1 and is_green and abs(l[i]-l[i-1]) < l[i]*0.001:
        score += 2; patterns.append("Tweezer Bottom")

    # 9. Volume confirmation bonus
    va = vol_avg(data, i)
    if data["v"][i] > va * 1.5:
        score += 2; patterns.append(f"Vol spike {data['v'][i]/va:.1f}x")

    # Negative: shooting star on top (bearish — don't trade)
    if c_range > 0 and upper_w >= body * 2 and lower_w <= body * 0.3:
        score -= 5; patterns.append("SHOOTING STAR (bearish)")

    # Negative: bearish engulfing
    if (is_red and c[i-1] > o[i-1] and
        o[i] >= c[i-1] and c[i] <= o[i-1]):
        score -= 4; patterns.append("BEARISH ENGULFING")

    return score, patterns

# ── Keltner Break Signal ──────────────────────────────────────────────────────
def keltner_signal(data, i, min_pattern_score=0):
    """Base Keltner + optional candle pattern filter."""
    if i < 30: return False
    closes = data["c"]
    price  = closes[i]
    green  = price > data["o"][i]
    a      = atr(data, i)
    s20    = sma(closes, i, 20)
    kc_up  = s20 + 2 * a
    va     = vol_avg(data, i)
    vr     = data["v"][i] / va if va > 0 else 1
    r      = rsi(closes, i)
    ps, _  = pattern_score(data, i)

    return (price > kc_up and vr > 1.2 and green
            and r < 75 and ps >= min_pattern_score)

# ── Backtest ──────────────────────────────────────────────────────────────────
def backtest(data, signal_fn, sl, tp, max_hold=30):
    wins = losses = 0
    n = data["n"]; i = 30
    while i < n - 1:
        if not signal_fn(data, i): i += 1; continue
        ep = data["c"][i]; sl_p = ep*(1-sl); tp_p = ep*(1+tp)
        result = None; j = i+1
        while j < min(i+max_hold+1, n):
            if data["l"][j] <= sl_p: result="LOSS"; break
            if data["h"][j] >= tp_p: result="WIN";  break
            j += 1
        if result=="WIN": wins+=1
        else: losses+=1
        i = j+1
    return wins, losses

# ── Grid search ───────────────────────────────────────────────────────────────
SL_TP = [
    (0.03,0.06),(0.03,0.08),(0.03,0.10),(0.03,0.12),(0.03,0.15),
    (0.04,0.08),(0.04,0.10),(0.04,0.12),(0.04,0.15),(0.04,0.20),
    (0.05,0.10),(0.05,0.12),(0.05,0.15),(0.05,0.20),(0.05,0.25),
    (0.06,0.12),(0.06,0.15),(0.06,0.20),(0.06,0.25),(0.06,0.30),
    (0.07,0.15),(0.07,0.20),(0.07,0.25),(0.07,0.30),
    (0.08,0.16),(0.08,0.20),(0.08,0.25),(0.08,0.30),
]

# Pattern filter levels
PATTERN_LEVELS = {
    "No filter":     0,   # pure Keltner
    "Any pattern":   1,   # at least 1 pattern score
    "Good pattern":  3,   # need score >= 3
    "Strong pattern":5,   # need score >= 5
}

print("Fetching 1D candles (max history ~8 years)...\n")
data_all = {}
for pair in PAIRS:
    print(f"  {pair}...", flush=True)
    data_all[pair] = fetch_max(pair, "1d", 3000)
    days = data_all[pair]["n"]
    print(f"  {pair}: {days} candles ({days/365:.1f} years)")
print()

all_results = []
avg_days = sum(data_all[p]["n"] for p in PAIRS) / 3

for pname, min_ps in PATTERN_LEVELS.items():
    for sl, tp in SL_TP:
        tw = tl = 0
        def sig(d, i, _ps=min_ps): return keltner_signal(d, i, _ps)
        for pair in PAIRS:
            w, l = backtest(data_all[pair], sig, sl, tp)
            tw += w; tl += l
        total = tw + tl
        if total < 10: continue
        wr = tw/total
        ev = wr*tp - (1-wr)*sl
        tpm = total/avg_days*30
        if ev <= 0: continue
        all_results.append({
            "filter": pname, "sl": sl, "tp": tp,
            "wins": tw, "losses": tl, "total": total,
            "wr": round(wr*100,1), "ev": round(ev*100,3),
            "rr": round(tp/sl,1), "tpm": round(tpm,1),
            "days": round(avg_days,0),
            "be": round(sl/(sl+tp)*100,1),
        })

all_results.sort(key=lambda x:(x["wr"],x["ev"]), reverse=True)
print(f"Found {len(all_results)} profitable combos\n")

print("="*110)
print("KELTNER BREAK 1D + CANDLE PATTERNS — Sorted by WR  (TP >= 2x SL)")
print("="*110)
print(f"  {'#':<3} {'Filter':<18} {'SL':>5} {'TP':>6} {'R/R':>5} | "
      f"{'N':>5} {'WR%':>6} {'EV%':>7} {'T/mo':>6} {'Days':>5}")
print(f"  {'-'*105}")

seen = set(); count = 0
for r in all_results:
    key = (r["filter"], r["sl"], r["tp"])
    if key in seen: continue
    seen.add(key); count += 1
    print(f"  {count:<3} {r['filter']:<18} {r['sl']*100:>5.1f} {r['tp']*100:>6.1f} {r['rr']:>4.1f}:1 | "
          f"{r['total']:>5} {r['wr']:>5.1f}% {r['ev']:>+6.3f}% "
          f"{r['tpm']:>5.1f}/mo {r['days']:>5.0f}d")
    if count >= 30: break

# Best per filter
print(f"\n{'='*110}")
print("BEST PER CANDLE FILTER")
print(f"{'='*110}")
for fname in PATTERN_LEVELS:
    sub = [r for r in all_results if r["filter"]==fname]
    if not sub: print(f"\n  [{fname}] No results"); continue
    r = sub[0]
    print(f"\n  [{fname}]")
    print(f"    Best: SL={r['sl']*100:.0f}% TP={r['tp']*100:.0f}% ({r['rr']:.1f}:1)  "
          f"WR={r['wr']:.1f}%  EV={r['ev']:+.3f}%  "
          f"{r['wins']}W/{r['losses']}L ({r['total']} trades, {r['days']:.0f}d)  "
          f"{r['tpm']:.1f} trades/mo")
    # top 3
    seen2=set()
    for r2 in sub[:15]:
        k=(r2["sl"],r2["tp"])
        if k in seen2: continue
        seen2.add(k)
        print(f"      SL={r2['sl']*100:.0f}% TP={r2['tp']*100:.0f}%  WR={r2['wr']:.1f}%  "
              f"EV={r2['ev']:+.3f}%  N={r2['total']}  {r2['tpm']:.1f}/mo")
        if len(seen2)>=5: break

# Show what patterns fire most
print(f"\n{'='*60}")
print("SAMPLE — Which patterns appear on Keltner 1D signals?")
print(f"{'='*60}")
pattern_counts = {}
signal_count = 0
for pair in PAIRS:
    d = data_all[pair]
    for i in range(30, d["n"]):
        if keltner_signal(d, i, 0):
            signal_count += 1
            _, pats = pattern_score(d, i)
            for p in pats:
                if "x" not in p:  # skip vol ratio strings
                    pattern_counts[p] = pattern_counts.get(p,0)+1

print(f"Total Keltner 1D signals: {signal_count}")
for pat, cnt in sorted(pattern_counts.items(), key=lambda x:-x[1]):
    pct = cnt/signal_count*100 if signal_count else 0
    print(f"  {pat:<30} {cnt:>4} times  ({pct:.0f}%)")
