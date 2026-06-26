"""
FAST MEGA BACKTEST — precomputed indicators, vectorized lookups.
Tests 29 strategies × 5 timeframes × 12 SL/TP combos.
20-50x faster than iterative approach.
"""
import requests, time, json, math
from datetime import datetime

PAIRS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS    = ["5m", "15m", "1h", "4h", "1d"]
OUT    = "mega_results.txt"
OUTJ   = "mega_results.json"

# ── DATA ─────────────────────────────────────────────────────────────────────

def fetch(pair, tf, n=3000):
    all_c = []
    end = None
    for _ in range(math.ceil(n / 1000)):
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit=1000"
        if end: url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=15); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            time.sleep(0.25)
        except Exception as e:
            print(f"  fetch error {pair} {tf}: {e}"); break
    raw = all_c[-n:]
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
        "vol":   [float(c[5]) for c in raw],
        "raw":   raw,
    }

# ── INDICATOR PRECOMPUTATION ──────────────────────────────────────────────────

def ema_series(closes, period):
    k = 2 / (period + 1)
    out = [closes[0]]
    for v in closes[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out

def rsi_series(closes, period=14):
    gains = [0.0]; losses = [0.0]
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    out = [50.0] * len(closes)
    for i in range(period, len(closes)):
        ag = sum(gains[i-period+1:i+1]) / period
        al = sum(losses[i-period+1:i+1]) / period
        out[i] = 100 - 100 / (1 + ag/al) if al > 0 else 100.0
    return out

def macd_series(closes, fast=12, slow=26, signal=9):
    ef = ema_series(closes, fast)
    es = ema_series(closes, slow)
    macd = [ef[i] - es[i] for i in range(len(closes))]
    sig  = ema_series(macd, signal)
    hist = [macd[i] - sig[i] for i in range(len(closes))]
    return macd, sig, hist

def atr_series(d, period=14):
    trs = [d["high"][0] - d["low"][0]]
    for i in range(1, len(d["close"])):
        h, l, pc = d["high"][i], d["low"][i], d["close"][i-1]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    out = [0.0] * len(trs)
    out[period-1] = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        out[i] = (out[i-1] * (period-1) + trs[i]) / period
    return out

def bb_series(closes, period=20, std_mult=2.0):
    n = len(closes)
    lo, mid, hi = [0.0]*n, [0.0]*n, [0.0]*n
    for i in range(period-1, n):
        w = closes[i-period+1:i+1]
        m = sum(w)/period
        std = (sum((x-m)**2 for x in w)/period)**0.5
        mid[i] = m; lo[i] = m - std_mult*std; hi[i] = m + std_mult*std
    return lo, mid, hi

def adx_series(d, period=14):
    n = len(d["close"])
    plus_di = [0.0]*n; minus_di = [0.0]*n; adx_out = [20.0]*n
    plus_dm_s = [0.0]*n; minus_dm_s = [0.0]*n; tr_s = [0.0]*n

    for i in range(1, n):
        h,l,ph,pl = d["high"][i],d["low"][i],d["high"][i-1],d["low"][i-1]
        pc = d["close"][i-1]
        up = h - ph; dn = pl - l
        plus_dm  = max(up, 0) if up > dn else 0
        minus_dm = max(dn, 0) if dn > up else 0
        tr = max(h-l, abs(h-pc), abs(l-pc))
        if i < period:
            plus_dm_s[i] = plus_dm_s[i-1] + plus_dm
            minus_dm_s[i] = minus_dm_s[i-1] + minus_dm
            tr_s[i] = tr_s[i-1] + tr
        else:
            plus_dm_s[i] = plus_dm_s[i-1] - plus_dm_s[i-1]/period + plus_dm
            minus_dm_s[i] = minus_dm_s[i-1] - minus_dm_s[i-1]/period + minus_dm
            tr_s[i] = tr_s[i-1] - tr_s[i-1]/period + tr
        if tr_s[i] > 0:
            plus_di[i]  = 100 * plus_dm_s[i] / tr_s[i]
            minus_di[i] = 100 * minus_dm_s[i] / tr_s[i]
        dsum = plus_di[i] + minus_di[i]
        dx = abs(plus_di[i]-minus_di[i])/dsum*100 if dsum > 0 else 0
        adx_out[i] = (adx_out[i-1]*(period-1) + dx)/period if i >= period else dx
    return adx_out

def precompute(d):
    c = d["close"]; h = d["high"]; l = d["low"]; v = d["vol"]
    n = len(c)
    e9   = ema_series(c, 9)
    e21  = ema_series(c, 21)
    e50  = ema_series(c, 50)
    e200 = ema_series(c, 200)
    rsi  = rsi_series(c, 14)
    macd, macd_sig, macd_hist = macd_series(c)
    atr  = atr_series(d, 14)
    bb_lo, bb_mid, bb_hi = bb_series(c, 20)
    adx  = adx_series(d, 14)

    # Rolling 20-bar volume average
    vol_avg = [0.0]*n
    for i in range(20, n):
        vol_avg[i] = sum(v[i-20:i])/20

    # Rolling 20-bar donchian high (of highs, excluding last bar)
    don_hi = [0.0]*n
    don_lo = [float("inf")]*n
    for i in range(20, n):
        don_hi[i] = max(h[i-20:i])
        don_lo[i] = min(l[i-20:i])

    # Candle body/wick analysis
    green  = [c[i] > d["open"][i] for i in range(n)]
    body   = [abs(c[i] - d["open"][i]) for i in range(n)]
    c_rng  = [h[i] - l[i] for i in range(n)]
    l_wick = [min(c[i],d["open"][i]) - l[i] for i in range(n)]
    u_wick = [h[i] - max(c[i],d["open"][i]) for i in range(n)]

    # Rolling 30-bar high for crash detection
    hi30 = [0.0]*n
    for i in range(30, n):
        hi30[i] = max(h[i-30:i])

    # Extra EMAs needed by ribbon/triple strategies
    e4   = ema_series(c, 4)
    e8   = ema_series(c, 8)
    e13  = ema_series(c, 13)
    e55  = ema_series(c, 55)

    # Rolling VWAP (24-bar)
    vwap24 = [0.0]*n
    for i in range(24, n):
        pv = sum(((h[j]+l[j]+c[j])/3)*v[j] for j in range(i-24, i+1))
        tv = sum(v[j] for j in range(i-24, i+1))
        vwap24[i] = pv/tv if tv > 0 else c[i]

    return {
        "c": c, "h": h, "l": l, "v": v, "o": d["open"], "n": n,
        "e4": e4, "e8": e8, "e9": e9, "e13": e13, "e21": e21,
        "e50": e50, "e55": e55, "e200": e200,
        "rsi": rsi, "macd": macd, "macd_sig": macd_sig, "macd_hist": macd_hist,
        "atr": atr, "bb_lo": bb_lo, "bb_mid": bb_mid, "bb_hi": bb_hi,
        "adx": adx, "vol_avg": vol_avg, "vwap24": vwap24,
        "don_hi": don_hi, "don_lo": don_lo,
        "green": green, "body": body, "c_rng": c_rng,
        "l_wick": l_wick, "u_wick": u_wick, "hi30": hi30,
    }

# ── FAST BACKTEST ─────────────────────────────────────────────────────────────

def backtest(p, signal_fn, sl, tp, start=60, max_hold=50):
    wins = losses = 0
    pnl = []
    n = p["n"]
    for i in range(start, n - 1):
        if not signal_fn(p, i):
            continue
        entry = p["c"][i]
        sl_p = entry * (1 - sl)
        tp_p = entry * (1 + tp)
        for j in range(i+1, min(i+max_hold+1, n)):
            if p["l"][j] <= sl_p:
                losses += 1; pnl.append(-sl); break
            if p["h"][j] >= tp_p:
                wins += 1; pnl.append(tp); break
    total = wins + losses
    wr = wins/total if total else 0
    ev = sum(pnl)/len(pnl) if pnl else 0
    return wins, losses, total, wr, ev

# ── STRATEGIES (all use precomputed p[...][i]) ────────────────────────────────

def s_ema_cross(p, i):
    if i < 22: return False
    return (p["e9"][i] > p["e21"][i] and p["e9"][i-1] <= p["e21"][i-1]
            and p["rsi"][i] < 70)

def s_ema_cross_filtered(p, i):
    if i < 52: return False
    cross = p["e9"][i] > p["e21"][i] and p["e9"][i-1] <= p["e21"][i-1]
    return (cross and p["c"][i] > p["e50"][i]
            and p["v"][i] > p["vol_avg"][i] * 0.8
            and p["rsi"][i] < 72 and p["green"][i])

def s_ema_stack_pullback(p, i):
    if i < 55: return False
    uptrend = p["e9"][i] > p["e21"][i] > p["e50"][i]
    if not uptrend: return False
    dist = abs(p["c"][i] - p["e21"][i]) / p["e21"][i] * 100
    return (dist < 1.5 and 28 < p["rsi"][i] < 68
            and p["green"][i]
            and not (p["macd"][i] < 0 and p["macd_hist"][i] < 0))

def s_rsi_oversold(p, i):
    if i < 30: return False
    return (p["rsi"][i] < 30 and p["rsi"][i] > p["rsi"][i-1]
            and p["c"][i] > p["e50"][i])

def s_rsi_oversold_strict(p, i):
    if i < 40: return False
    return (p["rsi"][i] < 35 and p["rsi"][i] > p["rsi"][i-1]
            and p["green"][i] and p["c"][i] > p["e50"][i]
            and not (p["macd"][i] < 0 and p["macd_hist"][i] < 0))

def s_macd_cross(p, i):
    if i < 40: return False
    return (p["macd_hist"][i] > 0 and p["macd_hist"][i-1] <= 0
            and p["rsi"][i] < 70 and p["c"][i] > p["e50"][i])

def s_macd_cross_filtered(p, i):
    if i < 55: return False
    cross = p["macd_hist"][i] > 0 and p["macd_hist"][i-1] <= 0
    return (cross and p["rsi"][i] < 68
            and p["e9"][i] > p["e21"][i] > p["e50"][i]
            and p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 0.7)

def s_bb_bounce(p, i):
    if i < 25: return False
    prev_below = p["l"][i-1] <= p["bb_lo"][i-1]
    curr_above = p["c"][i] > p["bb_lo"][i]
    return (prev_below and curr_above
            and 20 < p["rsi"][i] < 55
            and p["c"][i] > p["e50"][i] * 0.97)

def s_bb_bounce_strict(p, i):
    if i < 30: return False
    low_touch = p["l"][i] <= p["bb_lo"][i] * 1.005
    return (low_touch and p["green"][i] and p["rsi"][i] < 45
            and p["macd_hist"][i] > p["macd_hist"][i-1])

def s_donchian_break(p, i):
    if i < 25: return False
    return (p["c"][i] > p["don_hi"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.3
            and p["rsi"][i] < 78 and p["green"][i])

def s_donchian_break_strict(p, i):
    if i < 55: return False
    return (p["c"][i] > p["don_hi"][i]
            and p["e9"][i] > p["e21"][i] > p["e50"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.5
            and p["rsi"][i] < 75 and p["adx"][i] > 20)

def s_vwap_cross(p, i):
    if i < 30: return False
    vwap = p["vwap24"][i]
    if vwap == 0: return False
    return (p["c"][i-1] < p["vwap24"][i-1] and p["c"][i] > vwap
            and 30 < p["rsi"][i] < 65 and p["c"][i] > p["e21"][i])

def s_triple_ema(p, i):
    if i < 22: return False
    return (p["e4"][i] > p["e9"][i] and p["e4"][i-1] <= p["e9"][i-1]
            and p["e9"][i] > p["e21"][i] and p["rsi"][i] < 70 and p["green"][i])

def s_volume_spike(p, i):
    if i < 25: return False
    return (p["v"][i] > p["vol_avg"][i] * 2.5
            and p["green"][i]
            and p["c_rng"][i] > 0 and p["body"][i]/p["c_rng"][i] > 0.5
            and p["rsi"][i] < 75 and p["c"][i] > p["e21"][i] * 0.95)

def s_three_green(p, i):
    if i < 30: return False
    return (p["green"][i] and p["green"][i-1] and p["green"][i-2]
            and p["c"][i] > p["c"][i-1] > p["c"][i-2]
            and p["v"][i-1] > p["v"][i-2] and p["rsi"][i] < 72
            and p["c"][i] > p["e50"][i])

def s_hammer(p, i):
    if i < 30: return False
    is_hammer = (p["l_wick"][i] > p["body"][i] * 2
                 and p["u_wick"][i] < p["body"][i] * 0.5
                 and p["green"][i])
    if not is_hammer: return False
    swing_lo = min(p["l"][max(0,i-10):i]) if i >= 10 else p["l"][i]
    return (p["l"][i] <= swing_lo * 1.005
            and p["rsi"][i] < 55 and p["c"][i] > p["e50"][i] * 0.96)

def s_engulfing(p, i):
    if i < 25: return False
    prev = i - 1
    return (not p["green"][prev] and p["green"][i]
            and p["o"][i] <= p["c"][prev] and p["c"][i] >= p["o"][prev]
            and p["rsi"][i] < 68 and p["c"][i] > p["e50"][i] * 0.97)

def s_adx_trend(p, i):
    if i < 60: return False
    uptrend = p["e9"][i] > p["e21"][i] > p["e50"][i] and p["c"][i] > p["e9"][i]
    if not uptrend or p["adx"][i] < 30: return False
    if p["macd_hist"][i] <= 0: return False
    if not (30 < p["rsi"][i] < 70): return False
    # Recent touch of EMA9
    recent_lo = min(p["l"][max(0,i-5):i])
    return recent_lo <= p["e9"][i] * 1.01 and p["green"][i]

def s_confluence(p, i):
    if i < 60: return False
    conds = 0
    if p["e9"][i] > p["e21"][i] > p["e50"][i] and p["c"][i] > p["e9"][i]: conds += 1
    if 35 <= p["rsi"][i] <= 60: conds += 1
    if p["macd_hist"][i] > 0 and p["macd_hist"][i] > p["macd_hist"][i-1]: conds += 1
    if p["v"][i] > p["vol_avg"][i] * 1.2: conds += 1
    if p["adx"][i] > 22: conds += 1
    if (p["c"][i]-p["bb_lo"][i])/p["c"][i]*100 < 1.5: conds += 1
    if p["green"][i]: conds += 1
    if p["l_wick"][i] > p["body"][i]*2 and p["green"][i]: conds += 1
    return conds >= 5

def s_hybrid(p, i):
    if i < 60: return False
    return (p["e9"][i] > p["e21"][i] > p["e50"][i]
            and 35 <= p["rsi"][i] <= 60 and p["rsi"][i] > p["rsi"][i-1]
            and not (p["macd_hist"][i] < 0 and p["macd_hist"][i] < p["macd_hist"][i-1])
            and p["green"][i])

def s_squeeze_break(p, i):
    if i < 30: return False
    bb_w = (p["bb_hi"][i] - p["bb_lo"][i]) / p["bb_mid"][i] if p["bb_mid"][i] > 0 else 0
    bb_w_avg = sum((p["bb_hi"][max(0,i-k)] - p["bb_lo"][max(0,i-k)]) / (p["bb_mid"][max(0,i-k)] or 1)
                   for k in range(1, 21)) / 20
    return (bb_w < bb_w_avg * 0.75 and p["c"][i] > p["bb_hi"][i]
            and p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.3
            and p["rsi"][i] < 78)

def s_orb(p, i):  # Opening Range Breakout
    if i < 15: return False
    cons = p["h"][i-6:i]
    if not cons: return False
    cons_hi = max(cons); cons_lo = min(p["l"][i-6:i])
    rng_pct = (cons_hi - cons_lo) / cons_lo * 100 if cons_lo > 0 else 99
    return (rng_pct < 1.5 and p["c"][i] > cons_hi
            and p["v"][i] > p["vol_avg"][i] * 1.2
            and p["green"][i] and p["rsi"][i] < 75)

def s_golden_cross(p, i):
    if i < 210: return False
    return p["e50"][i] > p["e200"][i] and p["e50"][i-1] <= p["e200"][i-1]

def s_ema_ribbon(p, i):
    """EMA 8/13/21/55 all aligned and spreading apart."""
    if i < 60: return False
    e8  = p["e8"][i];  e8p  = p["e8"][i-1]
    e13 = p["e13"][i]; e13p = p["e13"][i-1]
    return (e8 > e13 > p["e21"][i] > p["e50"][i]
            and (e8 - e13) > (e8p - e13p)  # spreading
            and p["rsi"][i] < 70 and p["green"][i])

def s_keltner_break(p, i):
    """Price breaks above Keltner Channel upper band."""
    if i < 25: return False
    atr = p["atr"][i]
    ema20 = p["bb_mid"][i]  # reuse SMA20 as EMA20 approx
    kc_upper = ema20 + 2 * atr
    return (p["c"][i] > kc_upper and p["v"][i] > p["vol_avg"][i] * 1.2
            and p["green"][i] and p["rsi"][i] < 75)

def s_rsi_50_cross(p, i):
    """RSI crosses above 50 in uptrend — momentum turning positive."""
    if i < 30: return False
    return (p["rsi"][i] > 50 and p["rsi"][i-1] <= 50
            and p["e9"][i] > p["e21"][i] and p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 0.8)

def s_price_ema200_cross(p, i):
    """Price crosses above EMA200 — major bullish signal."""
    if i < 205: return False
    return (p["c"][i] > p["e200"][i] and p["c"][i-1] <= p["e200"][i-1]
            and p["v"][i] > p["vol_avg"][i] * 1.2 and p["green"][i])

def s_williams_bounce(p, i):
    """Williams %R oversold bounce (precomputed)."""
    if i < 20: return False
    period = 14
    w = p["h"][i-period:i]; lo = min(p["l"][i-period:i])
    hi = max(w)
    wr = (hi - p["c"][i])/(hi - lo)*-100 if (hi-lo)>0 else -50
    w_prev = p["h"][i-period-1:i-1]; lo_prev = min(p["l"][i-period-1:i-1])
    hi_prev = max(w_prev)
    wr_prev = (hi_prev - p["c"][i-1])/(hi_prev - lo_prev)*-100 if (hi_prev-lo_prev)>0 else -50
    return (wr < -80 and wr > wr_prev and p["c"][i] > p["e50"][i] * 0.97
            and p["rsi"][i] < 50)

def s_cci_bounce(p, i):
    """CCI below -100 turning up."""
    if i < 25: return False
    period = 20
    tps = [(p["h"][j]+p["l"][j]+p["c"][j])/3 for j in range(i-period+1, i+1)]
    m = sum(tps)/period
    md = sum(abs(tp-m) for tp in tps)/period
    cci = (tps[-1]-m)/(0.015*md) if md>0 else 0
    tps_p = [(p["h"][j]+p["l"][j]+p["c"][j])/3 for j in range(i-period, i)]
    m_p = sum(tps_p)/period; md_p = sum(abs(tp-m_p) for tp in tps_p)/period
    cci_p = (tps_p[-1]-m_p)/(0.015*md_p) if md_p>0 else 0
    return cci < -100 and cci > cci_p and p["green"][i] and p["c"][i] > p["e50"][i] * 0.96

def s_combined_best(p, i):
    """Fully combined strict strategy."""
    if i < 65: return False
    # EMAs aligned
    if not (p["e9"][i] > p["e21"][i] > p["e50"][i]): return False
    if p["c"][i] < p["e50"][i]: return False
    # Green candle with body
    if not p["green"][i]: return False
    if p["c_rng"][i] > 0 and p["body"][i]/p["c_rng"][i] < 0.05: return False
    # RSI
    if p["rsi"][i] > 68 or p["rsi"][i] < 28: return False
    if p["rsi"][i] < p["rsi"][i-1] - 5: return False
    # MACD
    if p["macd_hist"][i] < 0 and p["macd_hist"][i] < p["macd_hist"][i-1]: return False
    # Volume
    if p["v"][i] < p["vol_avg"][i] * 0.6: return False
    # ADX
    if p["adx"][i] < 15: return False
    # Not in crash
    if p["hi30"][i] > 0 and (p["hi30"][i]-p["c"][i])/p["hi30"][i] > 0.06: return False
    # Not at resistance
    if i >= 20:
        ress = [p["h"][j] for j in range(i-20, i) if p["h"][j] > p["c"][i]]
        if ress and (min(ress)-p["c"][i])/p["c"][i] < 0.004: return False
    # No recent overbought
    if i >= 5:
        recent_rsi_max = max(p["rsi"][i-k] for k in range(1, min(6, i)))
        if recent_rsi_max > 76 and p["rsi"][i] > 58: return False
    return True

def s_macd_bb_combo(p, i):
    """MACD cross + price near lower BB — dual confirmation."""
    if i < 35: return False
    macd_cross = p["macd_hist"][i] > 0 and p["macd_hist"][i-1] <= 0
    near_lower = (p["c"][i] - p["bb_lo"][i]) / p["c"][i] * 100 < 2.0
    return (macd_cross and near_lower and p["rsi"][i] < 60
            and p["green"][i] and p["c"][i] > p["e50"][i] * 0.97)

def s_ema21_touch_macd(p, i):
    """Price touches EMA21 in uptrend, MACD improving."""
    if i < 35: return False
    if not (p["e9"][i] > p["e21"][i] > p["e50"][i]): return False
    # Any of last 3 candles touched EMA21
    touched = any(p["l"][i-k] <= p["e21"][i-k] * 1.004 and p["c"][i-k] > p["e21"][i-k]
                  for k in range(3))
    if not touched: return False
    if not p["green"][i]: return False
    if p["rsi"][i] > 68: return False
    return p["macd_hist"][i] > p["macd_hist"][i-1]

def s_trend_continuation(p, i):
    """Strong trend (ADX>25) + pullback to EMA + MACD positive."""
    if i < 55: return False
    if p["adx"][i] < 25: return False
    uptrend = p["e9"][i] > p["e21"][i] > p["e50"][i]
    if not uptrend: return False
    # Recent pullback: one of last 5 candles was red
    had_red = any(not p["green"][i-k] for k in range(1, 6))
    if not had_red: return False
    # Now recovering
    if not p["green"][i]: return False
    if p["rsi"][i] > 65: return False
    if p["macd_hist"][i] <= 0: return False
    return p["v"][i] > p["vol_avg"][i] * 0.9

# ── STRATEGY REGISTRY ─────────────────────────────────────────────────────────

STRATS = {
    "EMA_Cross":               s_ema_cross,
    "EMA_Cross_Filtered":      s_ema_cross_filtered,
    "EMA_Stack_Pullback":      s_ema_stack_pullback,
    "RSI_Oversold":            s_rsi_oversold,
    "RSI_Oversold_Strict":     s_rsi_oversold_strict,
    "MACD_Cross":              s_macd_cross,
    "MACD_Cross_Filtered":     s_macd_cross_filtered,
    "BB_Bounce":               s_bb_bounce,
    "BB_Bounce_Strict":        s_bb_bounce_strict,
    "Donchian_Break":          s_donchian_break,
    "Donchian_Break_Strict":   s_donchian_break_strict,
    "VWAP_Cross":              s_vwap_cross,
    "Triple_EMA":              s_triple_ema,
    "Volume_Spike":            s_volume_spike,
    "Three_Green":             s_three_green,
    "Hammer":                  s_hammer,
    "Engulfing":               s_engulfing,
    "ADX_Trend":               s_adx_trend,
    "Confluence":              s_confluence,
    "Hybrid":                  s_hybrid,
    "Squeeze_Break":           s_squeeze_break,
    "ORB":                     s_orb,
    "Golden_Cross":            s_golden_cross,
    "EMA_Ribbon":              s_ema_ribbon,
    "Keltner_Break":           s_keltner_break,
    "RSI_50_Cross":            s_rsi_50_cross,
    "Price_EMA200_Cross":      s_price_ema200_cross,
    "Williams_Bounce":         s_williams_bounce,
    "CCI_Bounce":              s_cci_bounce,
    "Combined_Best":           s_combined_best,
    "MACD_BB_Combo":           s_macd_bb_combo,
    "EMA21_Touch_MACD":        s_ema21_touch_macd,
    "Trend_Continuation":      s_trend_continuation,
}

SL_TP = [
    (0.003, 0.006), (0.003, 0.009), (0.004, 0.008), (0.004, 0.012),
    (0.005, 0.010), (0.005, 0.015), (0.006, 0.012), (0.006, 0.018),
    (0.007, 0.014), (0.008, 0.016), (0.008, 0.024), (0.010, 0.020),
    (0.010, 0.030), (0.012, 0.024), (0.015, 0.030), (0.003, 0.012),
]

# ── MAIN ──────────────────────────────────────────────────────────────────────

def wlog(msg):
    with open(OUT, "a", encoding="utf-8") as f: f.write(msg + "\n")
    print(msg)

def main():
    t0 = datetime.now()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"FAST MEGA BACKTEST — {t0.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*80}\n\n")

    wlog(f"Strategies: {len(STRATS)} | Timeframes: {len(TFS)} | SL/TP: {len(SL_TP)} | Pairs: {PAIRS}")
    wlog(f"Max candles per pair/TF: 3000\n")

    # Fetch data
    wlog("Fetching data...")
    data = {}
    for tf in TFS:
        data[tf] = {}
        for pair in PAIRS:
            raw = fetch(pair, tf, 3000)
            data[tf][pair] = raw
            wlog(f"  {pair} {tf}: {len(raw['close'])} candles")
            time.sleep(0.3)

    # Precompute indicators
    wlog("\nPrecomputing indicators...")
    precomp = {}
    for tf in TFS:
        precomp[tf] = {}
        for pair in PAIRS:
            precomp[tf][pair] = precompute(data[tf][pair])
            wlog(f"  {pair} {tf}: done")

    wlog("\nRunning backtests...\n")
    all_results = []

    for tf in TFS:
        wlog(f"\n{'='*70}")
        wlog(f"TIMEFRAME: {tf}")
        wlog(f"{'='*70}")
        tf_results = []

        for sname, sfn in STRATS.items():
            for sl, tp in SL_TP:
                wins = losses = 0
                all_pnl = []
                pair_res = {}

                for pair in PAIRS:
                    p = precomp[tf][pair]
                    w, l, tot, wr, ev = backtest(p, sfn, sl, tp)
                    wins += w; losses += l
                    all_pnl.extend([tp]*w + [-sl]*l)
                    pair_res[pair] = {"wins": w, "losses": l,
                                      "wr": w/(w+l) if (w+l)>0 else 0}

                total = wins + losses
                if total < 5: continue
                wr = wins/total
                ev = sum(all_pnl)/len(all_pnl) if all_pnl else 0
                r = {"tf": tf, "strat": sname, "sl": sl, "tp": tp,
                     "wins": wins, "losses": losses, "total": total,
                     "wr": wr, "ev": ev, "pair": pair_res}
                all_results.append(r)
                tf_results.append(r)

        tf_results.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)
        wlog(f"\nTOP 10 for {tf}:")
        wlog(f"  {'Strategy':<26} {'SL':>4} {'TP':>4} | {'N':>5} {'WR%':>6} {'EV%':>7}")
        wlog(f"  {'-'*60}")
        for r in tf_results[:10]:
            wlog(f"  {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
                 f"{r['total']:>5} {r['wr']*100:>6.1f}% {r['ev']*100:>+7.3f}%")

    # Global rankings
    wlog("\n\n" + "="*80)
    wlog("GLOBAL TOP 50 — ALL TIMEFRAMES (min 10 trades)")
    wlog("="*80)
    top = [r for r in all_results if r["total"] >= 10]
    top.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)

    wlog(f"\n  {'TF':<5} {'Strategy':<26} {'SL':>4} {'TP':>4} | {'N':>5} {'WR%':>6} {'EV%':>7}")
    wlog(f"  {'-'*70}")
    for r in top[:50]:
        wlog(f"  {r['tf']:<5} {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
             f"{r['total']:>5} {r['wr']*100:>6.1f}% {r['ev']*100:>+7.3f}%")

    # Best per TF
    wlog("\n\n" + "="*80)
    wlog("BEST STRATEGY PER TIMEFRAME (min 10 trades)")
    wlog("="*80)
    for tf in TFS:
        tf_top = [r for r in all_results if r["tf"]==tf and r["total"]>=10]
        if not tf_top:
            wlog(f"\n  [{tf}] No results with ≥10 trades"); continue
        tf_top.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)
        b = tf_top[0]
        wlog(f"\n  ┌─ [{tf}] WINNER: {b['strat']}")
        wlog(f"  │   SL={b['sl']*100:.1f}%  TP={b['tp']*100:.1f}%  "
             f"Trades={b['total']}  WIN RATE={b['wr']*100:.1f}%  EV={b['ev']*100:+.3f}%")
        wlog(f"  │   Per pair: " + " | ".join(
            f"{pair}: {v['wins']}W/{v['losses']}L ({v['wr']*100:.0f}%)"
            for pair, v in b["pair"].items()))
        wlog(f"  └─ Top 5:")
        for i, r in enumerate(tf_top[:5]):
            wlog(f"       #{i+1} {r['strat']:<26} SL={r['sl']*100:.1f}% TP={r['tp']*100:.1f}% "
                 f"WR={r['wr']*100:.1f}% EV={r['ev']*100:+.3f}% N={r['total']}")

    # Absolute champion
    if top:
        wlog("\n\n" + "="*80)
        wlog("★  ABSOLUTE CHAMPION  ★")
        wlog("="*80)
        champ = top[0]
        wlog(f"\n  Strategy:  {champ['strat']}")
        wlog(f"  Timeframe: {champ['tf']}")
        wlog(f"  SL:        {champ['sl']*100:.1f}%")
        wlog(f"  TP:        {champ['tp']*100:.1f}%")
        wlog(f"  WIN RATE:  {champ['wr']*100:.1f}%")
        wlog(f"  EV/trade:  {champ['ev']*100:+.3f}%")
        wlog(f"  Trades:    {champ['total']} ({champ['wins']}W/{champ['losses']}L)")
        wlog(f"  Per pair:")
        for pair, v in champ["pair"].items():
            wlog(f"    {pair}: {v['wins']}W/{v['losses']}L = {v['wr']*100:.1f}% WR")

    # Save JSON
    with open(OUTJ, "w") as f:
        json.dump(sorted(all_results, key=lambda x: x["wr"], reverse=True), f, indent=2)

    elapsed = (datetime.now() - t0).seconds
    wlog(f"\n\nCompleted in {elapsed}s")
    wlog(f"Total combos tested: {len(all_results)}")
    wlog(f"Results in {OUT} and {OUTJ}")

if __name__ == "__main__":
    main()
