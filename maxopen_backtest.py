"""
June 1-24 2026 Backtest — All 5 agents x MAX_OPEN (1,2,3,5,unlimited)
$10,000 capital | $500 margin | x50 leverage | 10 pairs | LONG+SHORT
"""
import requests, time
from fast_backtest import precompute, STRATS
from paper.competition_agents import AGENTS, PAIRS

CAPITAL  = 10_000.0
MARGIN   = 500.0
LEVERAGE = 50

START_MS = 1780272000000   # June 1 2026 00:00:00 UTC
END_MS   = 1782345599000   # June 24 2026 23:59:59 UTC

MAX_OPEN_TESTS = [1, 2, 3, 5, 999]

def s_keltner_short(p, i):
    if i < 25: return False
    kc_lower = p["bb_mid"][i] - 2 * p["atr"][i]
    return p["c"][i] < kc_lower and p["v"][i] > p["vol_avg"][i] * 1.2 and not p["green"][i]

def s_adx_trend_short(p, i):
    if i < 60: return False
    down = p["e9"][i] < p["e21"][i] < p["e50"][i] and p["c"][i] < p["e9"][i]
    if not down or p["adx"][i] < 30 or p["macd_hist"][i] >= 0: return False
    if not (30 < p["rsi"][i] < 70): return False
    return max(p["h"][max(0,i-5):i]) >= p["e9"][i] * 0.99 and not p["green"][i]

def s_macd_bb_short(p, i):
    if i < 35: return False
    cross_down = p["macd_hist"][i] < 0 and p["macd_hist"][i-1] >= 0
    near_upper = (p["bb_hi"][i] - p["c"][i]) / p["c"][i] * 100 < 2.0
    return cross_down and near_upper and p["rsi"][i] > 40 and not p["green"][i]

def s_orb_short(p, i):
    if i < 15: return False
    cons_lo = min(p["l"][i-6:i]); cons_hi = max(p["h"][i-6:i])
    rng_pct = (cons_hi - cons_lo) / cons_lo * 100 if cons_lo > 0 else 99
    return rng_pct < 1.5 and p["c"][i] < cons_lo and p["v"][i] > p["vol_avg"][i] * 1.2 and not p["green"][i]

def s_donchian_short(p, i):
    if i < 25: return False
    return p["c"][i] < p["don_lo"][i] and p["v"][i] > p["vol_avg"][i] * 1.3 and p["rsi"][i] > 22 and not p["green"][i]

SHORT_SIGNALS = {
    "The Maniac":  s_keltner_short,
    "The Oracle":  s_adx_trend_short,
    "The Surgeon": s_macd_bb_short,
    "The Comet":   s_orb_short,
    "The Hound":   s_donchian_short,
}

def fetch_range(pair, tf):
    all_c = []
    warmup = {"15m": 200*15*60*1000, "1h": 200*3600*1000}.get(tf, 200*3600*1000)
    cur_start = START_MS - warmup
    while cur_start < END_MS:
        url = (f"https://api.binance.com/api/v3/klines"
               f"?symbol={pair}&interval={tf}&limit=1000"
               f"&startTime={cur_start}&endTime={END_MS}")
        try:
            r = requests.get(url, timeout=15); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c.extend(batch)
            cur_start = int(batch[-1][0]) + 1
            if len(batch) < 1000: break
            time.sleep(0.05)
        except Exception as e:
            print(f"  err {pair}: {e}", flush=True); break
    if not all_c: return None
    return {
        "open":  [float(c[1]) for c in all_c],
        "high":  [float(c[2]) for c in all_c],
        "low":   [float(c[3]) for c in all_c],
        "close": [float(c[4]) for c in all_c],
        "vol":   [float(c[5]) for c in all_c],
        "ts":    [int(c[0])   for c in all_c],
    }

# cache candle data so we don't re-download for each MAX_OPEN test
candle_cache = {}

def get_candles(pair, tf):
    key = f"{pair}_{tf}"
    if key not in candle_cache:
        candle_cache[key] = fetch_range(pair, tf)
    return candle_cache[key]

def backtest_agent(agent_name, cfg, max_open):
    tf        = cfg["timeframe"]
    sl        = cfg["sl"]
    tp        = cfg["tp"]
    sfn_long  = STRATS.get(cfg["strategy"])
    sfn_short = SHORT_SIGNALS[agent_name]
    trades    = []

    for pair in PAIRS:
        raw = get_candles(pair, tf)
        if not raw or len(raw["close"]) < 100: continue
        p = precompute(raw); n = p["n"]

        start_i = 60
        for idx, ts in enumerate(raw["ts"]):
            if ts >= START_MS:
                start_i = max(60, idx)
                break

        open_count = 0
        i = start_i
        while i < n - 1:
            long_sig = short_sig = False
            try: long_sig  = sfn_long(p, i)  if sfn_long  else False
            except: pass
            try: short_sig = sfn_short(p, i) if sfn_short else False
            except: pass

            if not long_sig and not short_sig:
                i += 1; continue

            if open_count >= max_open:
                i += 1; continue

            ep  = p["c"][i]
            qty = (MARGIN * LEVERAGE) / ep
            j   = i + 1

            if long_sig and open_count < max_open:
                tp_p = ep*(1+tp); sl_p = ep*(1-sl)
                result = "LOSS"; j2 = i+1
                while j2 < min(i+300+1, n):
                    if p["l"][j2] <= sl_p: result = "LOSS"; break
                    if p["h"][j2] >= tp_p: result = "WIN";  break
                    j2 += 1
                pnl = qty*(tp_p-ep) if result=="WIN" else qty*(sl_p-ep)
                if pnl < -MARGIN: pnl = -MARGIN
                trades.append({"side":"LONG","result":result,"pnl":round(pnl,2)})
                open_count += 1
                j = j2
                if result in ("WIN","LOSS"): open_count = max(0, open_count-1)

            if short_sig and open_count < max_open:
                tp_p = ep*(1-tp); sl_p = ep*(1+sl)
                result = "LOSS"; j2 = i+1
                while j2 < min(i+300+1, n):
                    if p["h"][j2] >= sl_p: result = "LOSS"; break
                    if p["l"][j2] <= tp_p: result = "WIN";  break
                    j2 += 1
                pnl = qty*(ep-tp_p) if result=="WIN" else qty*(ep-sl_p)
                if pnl < -MARGIN: pnl = -MARGIN
                trades.append({"side":"SHORT","result":result,"pnl":round(pnl,2)})
                open_count += 1
                j = max(j, j2)
                if result in ("WIN","LOSS"): open_count = max(0, open_count-1)

            i = j + 1

    return trades

print(f"\n{'='*80}", flush=True)
print(f"  JUNE 1-24 2026 - MAX_OPEN TEST - x50 Leverage", flush=True)
print(f"  $10,000 capital | $500 margin | 10 pairs | LONG+SHORT", flush=True)
print(f"{'='*80}\n", flush=True)

# pre-fetch all candles once
print("Pre-fetching candle data for all pairs...", flush=True)
for agent_name, cfg in AGENTS.items():
    tf = cfg["timeframe"]
    for pair in PAIRS:
        key = f"{pair}_{tf}"
        if key not in candle_cache:
            print(f"  {pair} {tf}...", flush=True)
            candle_cache[key] = fetch_range(pair, tf)
print("Done fetching.\n", flush=True)

all_results = []

for agent_name, cfg in AGENTS.items():
    print(f"{cfg['emoji']} {agent_name} ({cfg['strategy']} {cfg['timeframe']})", flush=True)
    print(f"  {'MAX_OPEN':<12} {'Trades':>7} {'WR%':>7} {'Long':>10} {'Short':>10} {'Total':>10}", flush=True)
    print(f"  {'-'*60}", flush=True)

    for mo in MAX_OPEN_TESTS:
        trades  = backtest_agent(agent_name, cfg, mo)
        wins    = [t for t in trades if t["result"] == "WIN"]
        longs   = [t for t in trades if t["side"] == "LONG"]
        shorts  = [t for t in trades if t["side"] == "SHORT"]
        total   = sum(t["pnl"] for t in trades)
        lpnl    = sum(t["pnl"] for t in longs)
        spnl    = sum(t["pnl"] for t in shorts)
        wr      = round(len(wins)/len(trades)*100,1) if trades else 0
        label   = str(mo) if mo < 999 else "unlimited"
        print(f"  {label:<12} {len(trades):>7} {wr:>7}% ${lpnl:>+8,.0f} ${spnl:>+8,.0f} ${total:>+8,.0f}", flush=True)
        all_results.append((agent_name, cfg, mo, trades, wr, lpnl, spnl, total))
    print(flush=True)

print(f"\n{'='*80}", flush=True)
print(f"  BEST MAX_OPEN PER AGENT (by Total PnL)", flush=True)
print(f"{'='*80}", flush=True)
print(f"  {'Agent':<18} {'Best MAX_OPEN':<14} {'Trades':>7} {'WR%':>7} {'Total PnL':>12}", flush=True)
print(f"  {'-'*62}", flush=True)

for agent_name, cfg in AGENTS.items():
    agent_results = [(mo, t, wr, total) for an, c, mo, t, wr, l, s, total in all_results if an == agent_name]
    best = max(agent_results, key=lambda x: x[3])
    mo, trades, wr, total = best
    label = str(mo) if mo < 999 else "unlimited"
    print(f"  {cfg['emoji']} {agent_name:<16} {label:<14} {len(trades):>7} {wr:>7}% ${total:>+10,.0f}", flush=True)
print(flush=True)
