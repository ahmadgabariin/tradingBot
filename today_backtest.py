"""
June 25-26 2026 Backtest — last ~25 hours
"""
import requests, time, math
from fast_backtest import precompute, STRATS
from paper.competition_agents import AGENTS, PAIRS

CAPITAL  = 10_000.0
MARGIN   = 500.0
LEVERAGE = 50

START_MS = 1782347449000   # June 25 2026 00:30:49 UTC (first trade 01:00:49 - 30min)
END_MS   = 1782431389000   # June 25 2026 23:49:49 UTC (now)

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

def backtest_agent(agent_name, cfg):
    tf        = cfg["timeframe"]
    sl        = cfg["sl"]
    tp        = cfg["tp"]
    sfn_long  = STRATS.get(cfg["strategy"])
    sfn_short = SHORT_SIGNALS[agent_name]
    trades    = []

    for pair in PAIRS:
        print(f"  {pair}...", flush=True)
        raw = fetch_range(pair, tf)
        if not raw or len(raw["close"]) < 100: continue
        p = precompute(raw); n = p["n"]

        start_i = 60
        for idx, ts in enumerate(raw["ts"]):
            if ts >= START_MS:
                start_i = max(60, idx)
                break

        i = start_i
        while i < n - 1:
            long_sig = short_sig = False
            try: long_sig  = sfn_long(p, i)  if sfn_long  else False
            except: pass
            try: short_sig = sfn_short(p, i) if sfn_short else False
            except: pass

            if not long_sig and not short_sig:
                i += 1; continue

            ep  = p["c"][i]
            qty = (MARGIN * LEVERAGE) / ep
            j   = i + 1

            if long_sig:
                tp_p = ep*(1+tp); sl_p = ep*(1-sl)
                result = "LOSS"; j2 = i+1
                while j2 < min(i+300+1, n):
                    if p["l"][j2] <= sl_p: result = "LOSS"; break
                    if p["h"][j2] >= tp_p: result = "WIN";  break
                    j2 += 1
                pnl = qty*(tp_p-ep) if result=="WIN" else qty*(sl_p-ep)
                if pnl < -MARGIN: pnl = -MARGIN
                trades.append({"side":"LONG","result":result,"pnl":round(pnl,2)})
                j = j2

            if short_sig:
                tp_p = ep*(1-tp); sl_p = ep*(1+sl)
                result = "LOSS"; j2 = i+1
                while j2 < min(i+300+1, n):
                    if p["h"][j2] >= sl_p: result = "LOSS"; break
                    if p["l"][j2] <= tp_p: result = "WIN";  break
                    j2 += 1
                pnl = qty*(ep-tp_p) if result=="WIN" else qty*(ep-sl_p)
                if pnl < -MARGIN: pnl = -MARGIN
                trades.append({"side":"SHORT","result":result,"pnl":round(pnl,2)})
                j = max(j, j2)

            i = j + 1

    return trades

from datetime import datetime, timezone
start_dt = datetime.fromtimestamp(START_MS/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
end_dt   = datetime.fromtimestamp(END_MS/1000,   tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

print(f"\n{'='*68}", flush=True)
print(f"  JUNE 25 00:30 to 23:49 UTC - x50 Leverage", flush=True)
print(f"  From: {start_dt}  To: {end_dt}", flush=True)
print(f"  $10,000 capital | $500 margin | 10 pairs | LONG+SHORT", flush=True)
print(f"{'='*68}\n", flush=True)

results = []
for agent_name, cfg in AGENTS.items():
    print(f"Fetching {cfg['emoji']} {agent_name} ({cfg['strategy']} {cfg['timeframe']})...", flush=True)
    trades = backtest_agent(agent_name, cfg)
    wins   = [t for t in trades if t["result"] == "WIN"]
    longs  = [t for t in trades if t["side"] == "LONG"]
    shorts = [t for t in trades if t["side"] == "SHORT"]
    total_pnl = sum(t["pnl"] for t in trades)
    long_pnl  = sum(t["pnl"] for t in longs)
    short_pnl = sum(t["pnl"] for t in shorts)
    wr = round(len(wins)/len(trades)*100, 1) if trades else 0
    print(f"  → {len(trades)} trades (L:{len(longs)} S:{len(shorts)}) | WR={wr}% | PnL=${total_pnl:+,.0f}\n", flush=True)
    results.append((agent_name, cfg, trades, wr, long_pnl, short_pnl, total_pnl))

print(f"\n{'='*68}", flush=True)
print(f"  SUMMARY (June 25-26)", flush=True)
print(f"{'='*68}", flush=True)
print(f"  {'Agent':<18} {'TF':<5} {'SL':>5} {'TP':>5} {'Trades':>7} {'WR%':>7} {'Long':>10} {'Short':>10} {'Total':>10}", flush=True)
print(f"  {'-'*76}", flush=True)
results.sort(key=lambda x: -x[6])
for agent_name, cfg, trades, wr, long_pnl, short_pnl, total_pnl in results:
    print(f"  {cfg['emoji']} {agent_name:<16} {cfg['timeframe']:<5} {cfg['sl']*100:>4.1f}% {cfg['tp']*100:>4.1f}% {len(trades):>7} {wr:>7}% ${long_pnl:>+8,.0f} ${short_pnl:>+8,.0f} ${total_pnl:>+8,.0f}", flush=True)
print(flush=True)
