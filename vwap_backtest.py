"""
VWAP + Order Flow Agent — Timeframe Comparison Backtest
June 1-24 2026 | x50 Leverage | $10,000 capital | $500 margin | 10 pairs
Tests: 5m, 15m, 1h
"""
import requests, time, math
from paper.competition_agents import PAIRS

CAPITAL  = 10_000.0
MARGIN   = 500.0
LEVERAGE = 50
START_MS = 1767225600000   # Jan 1 2026 00:00:00 UTC
END_MS   = 1782345599000   # June 24 2026 23:59:59 UTC

TIMEFRAMES = {
    "5m":  {"sl": 0.015, "tp": 0.008, "ms": 5*60*1000,  "warmup": 100*5*60*1000},
    "15m": {"sl": 0.025, "tp": 0.012, "ms": 15*60*1000, "warmup": 100*15*60*1000},
    "1h":  {"sl": 0.035, "tp": 0.020, "ms": 3600*1000,  "warmup": 100*3600*1000},
}

def fetch_range(pair, tf, start_ms, end_ms, warmup_ms):
    all_c = []
    cur = start_ms - warmup_ms
    while cur < end_ms:
        url = (f"https://api.binance.com/api/v3/klines"
               f"?symbol={pair}&interval={tf}&limit=1000"
               f"&startTime={cur}&endTime={end_ms}")
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
    if not all_c: return None
    return {
        "o":  [float(c[1]) for c in all_c],
        "h":  [float(c[2]) for c in all_c],
        "l":  [float(c[3]) for c in all_c],
        "c":  [float(c[4]) for c in all_c],
        "v":  [float(c[5]) for c in all_c],
        "ts": [int(c[0])   for c in all_c],
    }

def compute_vwap(raw):
    """VWAP resets daily at midnight UTC."""
    n = len(raw["c"])
    vwap = [0.0] * n
    cum_tp_vol = 0.0
    cum_vol    = 0.0
    prev_day   = -1

    for i in range(n):
        day = raw["ts"][i] // 86400000
        if day != prev_day:
            cum_tp_vol = 0.0
            cum_vol    = 0.0
            prev_day   = day
        tp = (raw["h"][i] + raw["l"][i] + raw["c"][i]) / 3.0
        cum_tp_vol += tp * raw["v"][i]
        cum_vol    += raw["v"][i]
        vwap[i] = cum_tp_vol / cum_vol if cum_vol > 0 else tp

    return vwap

def compute_vol_avg(raw, period=20):
    n = len(raw["v"])
    avg = [0.0] * n
    for i in range(n):
        s = max(0, i - period)
        avg[i] = sum(raw["v"][s:i+1]) / (i - s + 1)
    return avg

def compute_rsi(raw, period=14):
    n = len(raw["c"])
    rsi = [50.0] * n
    gains = losses = 0.0
    for i in range(1, min(period+1, n)):
        d = raw["c"][i] - raw["c"][i-1]
        if d > 0: gains += d
        else: losses -= d
    if period < n:
        ag = gains / period; al = losses / period
        rsi[period] = 100 - 100/(1 + ag/al) if al > 0 else 100
        for i in range(period+1, n):
            d = raw["c"][i] - raw["c"][i-1]
            g = max(d, 0); l = max(-d, 0)
            ag = (ag*(period-1) + g) / period
            al = (al*(period-1) + l) / period
            rsi[i] = 100 - 100/(1 + ag/al) if al > 0 else 100
    return rsi

def signal_long(raw, vwap, vol_avg, rsi, i):
    """VWAP + Order Flow LONG:
    - Price crosses above VWAP (was below, now above)
    - Strong buying volume (green candle + vol spike)
    - RSI 35-65 (not extreme)
    - Price momentum up (close > open)
    """
    if i < 5: return False
    cross_above = raw["c"][i-1] < vwap[i-1] and raw["c"][i] > vwap[i]
    buying_vol  = raw["v"][i] > vol_avg[i] * 1.5 and raw["c"][i] > raw["o"][i]
    rsi_ok      = 35 < rsi[i] < 65
    # order flow: buying pressure in last 3 candles
    buy_pressure = sum(1 for j in range(max(0,i-3), i) if raw["c"][j] > raw["o"][j])
    return cross_above and buying_vol and rsi_ok and buy_pressure >= 2

def signal_short(raw, vwap, vol_avg, rsi, i):
    """VWAP + Order Flow SHORT:
    - Price crosses below VWAP (was above, now below)
    - Strong selling volume (red candle + vol spike)
    - RSI 35-65 (not extreme)
    - Price momentum down (close < open)
    """
    if i < 5: return False
    cross_below  = raw["c"][i-1] > vwap[i-1] and raw["c"][i] < vwap[i]
    selling_vol  = raw["v"][i] > vol_avg[i] * 1.5 and raw["c"][i] < raw["o"][i]
    rsi_ok       = 35 < rsi[i] < 65
    # order flow: selling pressure in last 3 candles
    sell_pressure = sum(1 for j in range(max(0,i-3), i) if raw["c"][j] < raw["o"][j])
    return cross_below and selling_vol and rsi_ok and sell_pressure >= 2

def backtest_vwap(tf_name, cfg):
    sl = cfg["sl"]; tp = cfg["tp"]
    warmup = cfg["warmup"]
    trades = []

    for pair in PAIRS:
        print(f"    {pair}...", flush=True)
        raw = fetch_range(pair, tf_name, START_MS, END_MS, warmup)
        if not raw or len(raw["c"]) < 50: continue

        vwap    = compute_vwap(raw)
        vol_avg = compute_vol_avg(raw)
        rsi     = compute_rsi(raw)
        n       = len(raw["c"])

        start_i = 20
        for idx, ts in enumerate(raw["ts"]):
            if ts >= START_MS:
                start_i = max(20, idx)
                break

        i = start_i
        while i < n - 1:
            ls = signal_long(raw, vwap, vol_avg, rsi, i)
            ss = signal_short(raw, vwap, vol_avg, rsi, i)

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

print(f"\n{'='*70}", flush=True)
print(f"  VWAP + ORDER FLOW — TIMEFRAME COMPARISON", flush=True)
print(f"  Jan 1 - June 24 2026 | x50 Leverage | $10,000 | $500 margin | 10 pairs", flush=True)
print(f"{'='*70}\n", flush=True)

results = []
for tf_name, cfg in TIMEFRAMES.items():
    print(f"Testing {tf_name} (SL={cfg['sl']*100:.1f}% TP={cfg['tp']*100:.1f}%)...", flush=True)
    trades  = backtest_vwap(tf_name, cfg)
    wins    = [t for t in trades if t["result"] == "WIN"]
    longs   = [t for t in trades if t["side"] == "LONG"]
    shorts  = [t for t in trades if t["side"] == "SHORT"]
    total   = sum(t["pnl"] for t in trades)
    lpnl    = sum(t["pnl"] for t in longs)
    spnl    = sum(t["pnl"] for t in shorts)
    wr      = round(len(wins)/len(trades)*100, 1) if trades else 0
    print(f"  -> {len(trades)} trades (L:{len(longs)} S:{len(shorts)}) | WR={wr}% | PnL=${total:+,.0f}\n", flush=True)
    results.append((tf_name, cfg, trades, wr, lpnl, spnl, total))

print(f"\n{'='*70}", flush=True)
print(f"  VWAP + ORDER FLOW — SUMMARY", flush=True)
print(f"{'='*70}", flush=True)
print(f"  {'TF':<6} {'SL':>5} {'TP':>5} {'Trades':>7} {'WR%':>7} {'Long':>10} {'Short':>10} {'Total':>10}", flush=True)
print(f"  {'-'*65}", flush=True)
results.sort(key=lambda x: -x[6])
for tf_name, cfg, trades, wr, lpnl, spnl, total in results:
    print(f"  {tf_name:<6} {cfg['sl']*100:>4.1f}% {cfg['tp']*100:>4.1f}% {len(trades):>7} {wr:>7}% ${lpnl:>+8,.0f} ${spnl:>+8,.0f} ${total:>+8,.0f}", flush=True)

best = max(results, key=lambda x: x[6])
print(f"\n  Best timeframe: {best[0]} with ${best[6]:+,.0f} PnL and {best[3]}% WR", flush=True)
print(flush=True)
