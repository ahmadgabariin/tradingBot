"""
STRATEGY LAB — Comprehensive Multi-Strategy Backtest
Jan 1 - June 24 2026 | x50 Leverage | $10,000 | $500 margin | 10 pairs
Strategies: VWAP, Mean Reversion, Momentum, Order Flow, Liquidity Hunting
+ All merged combinations
Timeframes: 15m, 1h
"""
import requests, time, math
from paper.competition_agents import PAIRS

CAPITAL  = 10_000.0
MARGIN   = 500.0
LEVERAGE = 50
START_MS = 1767225600000   # Jan 1 2026 00:00:00 UTC
END_MS   = 1782345599000   # June 24 2026 23:59:59 UTC

TIMEFRAMES = ["15m", "1h"]
TF_MS      = {"5m": 300000, "15m": 900000, "1h": 3600000}
WARMUP_MS  = {"5m": 100*300000, "15m": 100*900000, "1h": 100*3600000}

# ─── DATA FETCHING ────────────────────────────────────────────────────────────

candle_cache = {}

def fetch_range(pair, tf):
    key = f"{pair}_{tf}"
    if key in candle_cache:
        return candle_cache[key]
    all_c = []
    cur = START_MS - WARMUP_MS[tf]
    while cur < END_MS:
        url = (f"https://api.binance.com/api/v3/klines"
               f"?symbol={pair}&interval={tf}&limit=1000"
               f"&startTime={cur}&endTime={END_MS}")
        try:
            r = requests.get(url, timeout=15); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c.extend(batch)
            cur = int(batch[-1][0]) + 1
            if len(batch) < 1000: break
            time.sleep(0.05)
        except Exception as e:
            print(f"    err {pair} {tf}: {e}", flush=True); break
    if not all_c:
        candle_cache[key] = None
        return None
    data = {
        "o":  [float(c[1]) for c in all_c],
        "h":  [float(c[2]) for c in all_c],
        "l":  [float(c[3]) for c in all_c],
        "c":  [float(c[4]) for c in all_c],
        "v":  [float(c[5]) for c in all_c],
        "ts": [int(c[0])   for c in all_c],
    }
    candle_cache[key] = data
    return data

# ─── INDICATORS ───────────────────────────────────────────────────────────────

def ema(data, period):
    result = [0.0] * len(data)
    k = 2 / (period + 1)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = data[i] * k + result[i-1] * (1 - k)
    return result

def rsi(closes, period=14):
    n = len(closes)
    result = [50.0] * n
    gains = losses = 0.0
    for i in range(1, min(period+1, n)):
        d = closes[i] - closes[i-1]
        if d > 0: gains += d
        else: losses -= d
    if period < n:
        ag = gains/period; al = losses/period
        result[period] = 100 - 100/(1+ag/al) if al > 0 else 100
        for i in range(period+1, n):
            d = closes[i] - closes[i-1]
            g = max(d,0); l = max(-d,0)
            ag = (ag*(period-1)+g)/period
            al = (al*(period-1)+l)/period
            result[i] = 100 - 100/(1+ag/al) if al > 0 else 100
    return result

def bollinger(closes, period=20, std_mult=2.0):
    n = len(closes)
    mid = [0.0]*n; hi = [0.0]*n; lo = [0.0]*n
    for i in range(n):
        s = max(0, i-period+1)
        window = closes[s:i+1]
        m = sum(window)/len(window)
        std = math.sqrt(sum((x-m)**2 for x in window)/len(window))
        mid[i] = m; hi[i] = m+std_mult*std; lo[i] = m-std_mult*std
    return mid, hi, lo

def atr(raw, period=14):
    n = len(raw["c"])
    result = [0.0]*n
    for i in range(1, n):
        tr = max(raw["h"][i]-raw["l"][i],
                 abs(raw["h"][i]-raw["c"][i-1]),
                 abs(raw["l"][i]-raw["c"][i-1]))
        result[i] = tr
    # smooth with EMA
    k = 2/(period+1)
    for i in range(1, n):
        result[i] = result[i]*k + result[i-1]*(1-k)
    return result

def macd_hist(closes, fast=12, slow=26, signal=9):
    e_fast = ema(closes, fast)
    e_slow = ema(closes, slow)
    macd_line = [e_fast[i] - e_slow[i] for i in range(len(closes))]
    signal_line = ema(macd_line, signal)
    return [macd_line[i] - signal_line[i] for i in range(len(closes))]

def vol_avg(volumes, period=20):
    n = len(volumes)
    result = [0.0]*n
    for i in range(n):
        s = max(0, i-period+1)
        result[i] = sum(volumes[s:i+1])/(i-s+1)
    return result

def vwap_daily(raw):
    n = len(raw["c"])
    result = [0.0]*n
    cum_tp = cum_v = 0.0
    prev_day = -1
    for i in range(n):
        day = raw["ts"][i] // 86400000
        if day != prev_day:
            cum_tp = cum_v = 0.0
            prev_day = day
        tp = (raw["h"][i]+raw["l"][i]+raw["c"][i])/3
        cum_tp += tp*raw["v"][i]
        cum_v  += raw["v"][i]
        result[i] = cum_tp/cum_v if cum_v > 0 else tp
    return result

def swing_highs_lows(raw, lookback=10):
    n = len(raw["c"])
    s_hi = [0.0]*n
    s_lo = [0.0]*n
    for i in range(lookback, n):
        s_hi[i] = max(raw["h"][i-lookback:i])
        s_lo[i] = min(raw["l"][i-lookback:i])
    return s_hi, s_lo

def cum_vol_delta(raw, period=10):
    n = len(raw["c"])
    delta = [0.0]*n
    for i in range(n):
        # approximate: green candle = buying, red = selling
        d = raw["v"][i] if raw["c"][i] >= raw["o"][i] else -raw["v"][i]
        delta[i] = d
    # cumulative over rolling period
    result = [0.0]*n
    for i in range(n):
        s = max(0, i-period+1)
        result[i] = sum(delta[s:i+1])
    return result

def precompute_all(raw):
    closes = raw["c"]
    p = {}
    p["raw"]      = raw
    p["n"]        = len(closes)
    p["e9"]       = ema(closes, 9)
    p["e21"]      = ema(closes, 21)
    p["e50"]      = ema(closes, 50)
    p["rsi"]      = rsi(closes)
    p["bb_mid"], p["bb_hi"], p["bb_lo"] = bollinger(closes)
    p["atr"]      = atr(raw)
    p["macd"]     = macd_hist(closes)
    p["vol_avg"]  = vol_avg(raw["v"])
    p["vwap"]     = vwap_daily(raw)
    p["s_hi"], p["s_lo"] = swing_highs_lows(raw)
    p["vol_delta"]= cum_vol_delta(raw)
    p["green"]    = [raw["c"][i] > raw["o"][i] for i in range(p["n"])]
    return p

# ─── STRATEGY SIGNALS ─────────────────────────────────────────────────────────

# ── 1. VWAP ──
def vwap_long(p, i):
    if i < 10: return False
    cross = p["raw"]["c"][i-1] < p["vwap"][i-1] and p["raw"]["c"][i] > p["vwap"][i]
    vol_spike = p["raw"]["v"][i] > p["vol_avg"][i] * 1.5
    buy_candle = p["green"][i]
    rsi_ok = 35 < p["rsi"][i] < 65
    buy_pressure = sum(1 for j in range(max(0,i-3),i) if p["green"][j])
    return cross and vol_spike and buy_candle and rsi_ok and buy_pressure >= 2

def vwap_short(p, i):
    if i < 10: return False
    cross = p["raw"]["c"][i-1] > p["vwap"][i-1] and p["raw"]["c"][i] < p["vwap"][i]
    vol_spike = p["raw"]["v"][i] > p["vol_avg"][i] * 1.5
    sell_candle = not p["green"][i]
    rsi_ok = 35 < p["rsi"][i] < 65
    sell_pressure = sum(1 for j in range(max(0,i-3),i) if not p["green"][j])
    return cross and vol_spike and sell_candle and rsi_ok and sell_pressure >= 2

# ── 2. MEAN REVERSION ──
def mean_rev_long(p, i):
    if i < 20: return False
    at_extreme = p["raw"]["c"][i] < p["bb_lo"][i]
    oversold   = p["rsi"][i] < 28
    vol_spike  = p["raw"]["v"][i] > p["vol_avg"][i] * 1.3
    # reversal sign: current candle green or wick below
    reversal   = p["green"][i] or (p["raw"]["c"][i] > p["raw"]["l"][i] * 1.005)
    return at_extreme and oversold and vol_spike and reversal

def mean_rev_short(p, i):
    if i < 20: return False
    at_extreme  = p["raw"]["c"][i] > p["bb_hi"][i]
    overbought  = p["rsi"][i] > 72
    vol_spike   = p["raw"]["v"][i] > p["vol_avg"][i] * 1.3
    reversal    = not p["green"][i] or (p["raw"]["c"][i] < p["raw"]["h"][i] * 0.995)
    return at_extreme and overbought and vol_spike and reversal

# ── 3. MOMENTUM ──
def momentum_long(p, i):
    if i < 60: return False
    aligned = p["e9"][i] > p["e21"][i] > p["e50"][i]
    above   = p["raw"]["c"][i] > p["e9"][i]
    macd_ok = p["macd"][i] > 0 and p["macd"][i] > p["macd"][i-1]
    rsi_ok  = 45 < p["rsi"][i] < 70
    acc     = p["raw"]["c"][i] > p["raw"]["c"][i-1] > p["raw"]["c"][i-2]
    return aligned and above and macd_ok and rsi_ok and acc

def momentum_short(p, i):
    if i < 60: return False
    aligned = p["e9"][i] < p["e21"][i] < p["e50"][i]
    below   = p["raw"]["c"][i] < p["e9"][i]
    macd_ok = p["macd"][i] < 0 and p["macd"][i] < p["macd"][i-1]
    rsi_ok  = 30 < p["rsi"][i] < 55
    dec     = p["raw"]["c"][i] < p["raw"]["c"][i-1] < p["raw"]["c"][i-2]
    return aligned and below and macd_ok and rsi_ok and dec

# ── 4. ORDER FLOW ──
def order_flow_long(p, i):
    if i < 15: return False
    pos_delta   = p["vol_delta"][i] > 0
    above_vwap  = p["raw"]["c"][i] > p["vwap"][i]
    strong_vol  = p["raw"]["v"][i] > p["vol_avg"][i] * 1.2
    rsi_ok      = p["rsi"][i] < 65
    # increasing buying pressure
    delta_accel = p["vol_delta"][i] > p["vol_delta"][i-1]
    return pos_delta and above_vwap and strong_vol and rsi_ok and delta_accel and p["green"][i]

def order_flow_short(p, i):
    if i < 15: return False
    neg_delta   = p["vol_delta"][i] < 0
    below_vwap  = p["raw"]["c"][i] < p["vwap"][i]
    strong_vol  = p["raw"]["v"][i] > p["vol_avg"][i] * 1.2
    rsi_ok      = p["rsi"][i] > 35
    delta_accel = p["vol_delta"][i] < p["vol_delta"][i-1]
    return neg_delta and below_vwap and strong_vol and rsi_ok and delta_accel and not p["green"][i]

# ── 5. LIQUIDITY HUNTING ──
def liq_hunt_long(p, i):
    if i < 15: return False
    # price sweeps below swing low then reverses up (stop hunt)
    swept_low   = p["raw"]["l"][i] < p["s_lo"][i] * 0.999
    reversed_up = p["raw"]["c"][i] > p["s_lo"][i]
    big_wick    = (p["raw"]["c"][i] - p["raw"]["l"][i]) > (p["raw"]["h"][i] - p["raw"]["l"][i]) * 0.5
    vol_spike   = p["raw"]["v"][i] > p["vol_avg"][i] * 1.4
    return swept_low and reversed_up and big_wick and vol_spike

def liq_hunt_short(p, i):
    if i < 15: return False
    # price sweeps above swing high then reverses down (stop hunt)
    swept_high  = p["raw"]["h"][i] > p["s_hi"][i] * 1.001
    reversed_dn = p["raw"]["c"][i] < p["s_hi"][i]
    big_wick    = (p["raw"]["h"][i] - p["raw"]["c"][i]) > (p["raw"]["h"][i] - p["raw"]["l"][i]) * 0.5
    vol_spike   = p["raw"]["v"][i] > p["vol_avg"][i] * 1.4
    return swept_high and reversed_dn and big_wick and vol_spike

# ── MERGED COMBINATIONS ──
def merge_vwap_momentum_long(p, i):
    return vwap_long(p, i) and (p["e9"][i] > p["e21"][i]) and p["macd"][i] > 0

def merge_vwap_momentum_short(p, i):
    return vwap_short(p, i) and (p["e9"][i] < p["e21"][i]) and p["macd"][i] < 0

def merge_vwap_orderflow_long(p, i):
    return vwap_long(p, i) and p["vol_delta"][i] > 0

def merge_vwap_orderflow_short(p, i):
    return vwap_short(p, i) and p["vol_delta"][i] < 0

def merge_meanrev_orderflow_long(p, i):
    return mean_rev_long(p, i) and p["vol_delta"][i] > 0

def merge_meanrev_orderflow_short(p, i):
    return mean_rev_short(p, i) and p["vol_delta"][i] < 0

def merge_liq_momentum_long(p, i):
    return liq_hunt_long(p, i) and (p["e9"][i] > p["e21"][i])

def merge_liq_momentum_short(p, i):
    return liq_hunt_short(p, i) and (p["e9"][i] < p["e21"][i])

def merge_vwap_liq_long(p, i):
    return vwap_long(p, i) and liq_hunt_long(p, i)

def merge_vwap_liq_short(p, i):
    return vwap_short(p, i) and liq_hunt_short(p, i)

def merge_triple_long(p, i):
    return vwap_long(p, i) and order_flow_long(p, i) and p["raw"]["c"][i] > p["bb_mid"][i]

def merge_triple_short(p, i):
    return vwap_short(p, i) and order_flow_short(p, i) and p["raw"]["c"][i] < p["bb_mid"][i]

def merge_all_long(p, i):
    return (vwap_long(p, i) and order_flow_long(p, i) and
            p["e9"][i] > p["e21"][i] and p["macd"][i] > 0)

def merge_all_short(p, i):
    return (vwap_short(p, i) and order_flow_short(p, i) and
            p["e9"][i] < p["e21"][i] and p["macd"][i] < 0)

# ─── STRATEGY CONFIGS ─────────────────────────────────────────────────────────

STRATEGIES = {
    # name: (long_fn, short_fn, [(sl, tp), ...], timeframes)
    "VWAP": (
        vwap_long, vwap_short,
        [(0.020, 0.012), (0.025, 0.015), (0.035, 0.020), (0.030, 0.030)],
        ["15m", "1h"]
    ),
    "Mean Reversion": (
        mean_rev_long, mean_rev_short,
        [(0.015, 0.030), (0.020, 0.040), (0.010, 0.020), (0.025, 0.025)],
        ["15m", "1h"]
    ),
    "Momentum": (
        momentum_long, momentum_short,
        [(0.020, 0.040), (0.025, 0.050), (0.015, 0.030), (0.030, 0.030)],
        ["15m", "1h"]
    ),
    "Order Flow": (
        order_flow_long, order_flow_short,
        [(0.020, 0.020), (0.025, 0.025), (0.015, 0.020), (0.020, 0.030)],
        ["15m", "1h"]
    ),
    "Liquidity Hunt": (
        liq_hunt_long, liq_hunt_short,
        [(0.010, 0.020), (0.015, 0.030), (0.012, 0.024), (0.020, 0.020)],
        ["15m", "1h"]
    ),
    "VWAP + Momentum": (
        merge_vwap_momentum_long, merge_vwap_momentum_short,
        [(0.025, 0.020), (0.030, 0.025), (0.020, 0.040)],
        ["15m", "1h"]
    ),
    "VWAP + Order Flow": (
        merge_vwap_orderflow_long, merge_vwap_orderflow_short,
        [(0.020, 0.015), (0.025, 0.020), (0.030, 0.025)],
        ["15m", "1h"]
    ),
    "MeanRev + Order Flow": (
        merge_meanrev_orderflow_long, merge_meanrev_orderflow_short,
        [(0.015, 0.030), (0.020, 0.040), (0.010, 0.025)],
        ["15m", "1h"]
    ),
    "Liq + Momentum": (
        merge_liq_momentum_long, merge_liq_momentum_short,
        [(0.010, 0.020), (0.015, 0.030), (0.020, 0.040)],
        ["15m", "1h"]
    ),
    "VWAP + Liq Hunt": (
        merge_vwap_liq_long, merge_vwap_liq_short,
        [(0.015, 0.020), (0.020, 0.030), (0.025, 0.025)],
        ["15m", "1h"]
    ),
    "VWAP + OF + BB": (
        merge_triple_long, merge_triple_short,
        [(0.020, 0.020), (0.025, 0.025), (0.030, 0.030)],
        ["15m", "1h"]
    ),
    "All Combined": (
        merge_all_long, merge_all_short,
        [(0.020, 0.020), (0.025, 0.025), (0.030, 0.030)],
        ["15m", "1h"]
    ),
}

# ─── BACKTEST ENGINE ──────────────────────────────────────────────────────────

def run_backtest(long_fn, short_fn, tf, sl, tp):
    trades = []
    for pair in PAIRS:
        raw = fetch_range(pair, tf)
        if not raw or len(raw["c"]) < 100: continue
        p = precompute_all(raw)
        n = p["n"]

        start_i = 60
        for idx, ts in enumerate(raw["ts"]):
            if ts >= START_MS:
                start_i = max(60, idx)
                break

        i = start_i
        while i < n - 1:
            ls = ss = False
            try: ls = long_fn(p, i)
            except: pass
            try: ss = short_fn(p, i)
            except: pass

            if not ls and not ss:
                i += 1; continue

            ep  = raw["c"][i]
            qty = (MARGIN * LEVERAGE) / ep
            j   = i + 1

            if ls:
                tp_p = ep*(1+tp); sl_p = ep*(1-sl)
                result = "LOSS"; j2 = i+1
                while j2 < min(i+500+1, n):
                    if raw["l"][j2] <= sl_p: result = "LOSS"; break
                    if raw["h"][j2] >= tp_p: result = "WIN";  break
                    j2 += 1
                pnl = qty*(tp_p-ep) if result=="WIN" else qty*(sl_p-ep)
                if pnl < -MARGIN: pnl = -MARGIN
                trades.append({"side":"LONG","result":result,"pnl":round(pnl,2)})
                j = j2

            if ss:
                tp_p = ep*(1-tp); sl_p = ep*(1+sl)
                result = "LOSS"; j2 = i+1
                while j2 < min(i+500+1, n):
                    if raw["h"][j2] >= sl_p: result = "LOSS"; break
                    if raw["l"][j2] <= tp_p: result = "WIN";  break
                    j2 += 1
                pnl = qty*(ep-tp_p) if result=="WIN" else qty*(ep-sl_p)
                if pnl < -MARGIN: pnl = -MARGIN
                trades.append({"side":"SHORT","result":result,"pnl":round(pnl,2)})
                j = max(j, j2)

            i = j + 1

    return trades

# ─── MAIN ─────────────────────────────────────────────────────────────────────

print(f"\n{'='*80}", flush=True)
print(f"  STRATEGY LAB — Jan 1 to June 24 2026 — x50 Leverage", flush=True)
print(f"  $10,000 capital | $500 margin | 10 pairs | LONG+SHORT", flush=True)
print(f"{'='*80}\n", flush=True)

# Pre-fetch all candles
print("Pre-fetching candle data...", flush=True)
for tf in TIMEFRAMES:
    for pair in PAIRS:
        key = f"{pair}_{tf}"
        if key not in candle_cache:
            print(f"  {pair} {tf}...", flush=True)
            fetch_range(pair, tf)
print("Done fetching.\n", flush=True)

all_results = []

for strat_name, (long_fn, short_fn, sl_tp_list, tfs) in STRATEGIES.items():
    print(f"\n--- {strat_name} ---", flush=True)
    best_for_strat = None

    for tf in tfs:
        for sl, tp in sl_tp_list:
            trades  = run_backtest(long_fn, short_fn, tf, sl, tp)
            if not trades:
                continue
            wins    = [t for t in trades if t["result"]=="WIN"]
            longs   = [t for t in trades if t["side"]=="LONG"]
            shorts  = [t for t in trades if t["side"]=="SHORT"]
            total   = sum(t["pnl"] for t in trades)
            lpnl    = sum(t["pnl"] for t in longs)
            spnl    = sum(t["pnl"] for t in shorts)
            wr      = round(len(wins)/len(trades)*100,1) if trades else 0
            print(f"  {tf} SL={sl*100:.1f}% TP={tp*100:.1f}% -> {len(trades)} trades | WR={wr}% | PnL=${total:+,.0f}", flush=True)
            rec = (strat_name, tf, sl, tp, len(trades), wr, lpnl, spnl, total)
            all_results.append(rec)
            if best_for_strat is None or total > best_for_strat[8]:
                best_for_strat = rec

    if best_for_strat:
        sn, tf, sl, tp, nt, wr, lp, sp, tot = best_for_strat
        print(f"  >>> BEST: {tf} SL={sl*100:.1f}% TP={tp*100:.1f}% | {nt} trades | WR={wr}% | ${tot:+,.0f}", flush=True)

# ─── FINAL RANKINGS ───────────────────────────────────────────────────────────

# Get best config per strategy
best_per_strat = {}
for rec in all_results:
    sn = rec[0]
    if sn not in best_per_strat or rec[8] > best_per_strat[sn][8]:
        best_per_strat[sn] = rec

ranked = sorted(best_per_strat.values(), key=lambda x: -x[8])

print(f"\n\n{'='*80}", flush=True)
print(f"  FINAL RANKINGS — BEST CONFIG PER STRATEGY", flush=True)
print(f"{'='*80}", flush=True)
print(f"  {'#':<3} {'Strategy':<22} {'TF':<5} {'SL':>5} {'TP':>5} {'Trades':>7} {'WR%':>7} {'Long':>10} {'Short':>10} {'Total':>10}", flush=True)
print(f"  {'-'*88}", flush=True)

for rank, rec in enumerate(ranked, 1):
    sn, tf, sl, tp, nt, wr, lp, sp, tot = rec
    print(f"  {rank:<3} {sn:<22} {tf:<5} {sl*100:>4.1f}% {tp*100:>4.1f}% {nt:>7} {wr:>7}% ${lp:>+8,.0f} ${sp:>+8,.0f} ${tot:>+8,.0f}", flush=True)

print(f"\n  Winner: {ranked[0][0]} ({ranked[0][1]}) — ${ranked[0][8]:+,.0f} PnL | {ranked[0][5]}% WR", flush=True)
print(flush=True)
