"""
All 5 agents — x50 leverage backtest
$10,000 capital | $500 margin/trade | 50x leverage | 10 pairs
"""
import requests, time, math, sys
from datetime import datetime, timezone
from collections import defaultdict
from fast_backtest import precompute, STRATS
from paper.competition_agents import AGENTS, PAIRS

CAPITAL  = 10_000.0
MARGIN   = 500.0
LEVERAGE = 50
TF_CANDLES = {"15m": 17520*4, "1h": 17520, "4h": 17520//4}  # ~2 years

def fetch(pair, tf, n_candles):
    all_c = []; end = None
    for _ in range(math.ceil(n_candles / 1000)):
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit=1000"
        if end: url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=30); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            time.sleep(0.06)
        except Exception as e:
            print(f"  err {pair}: {e}"); break
    raw = all_c[-n_candles:]
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
        "vol":   [float(c[5]) for c in raw],
        "ts":    [int(c[0])   for c in raw],
    }

def backtest_agent(agent_name, cfg):
    tf     = cfg["timeframe"]
    sl     = cfg["sl"]
    tp     = cfg["tp"]
    sfn    = STRATS.get(cfg["strategy"])
    if not sfn:
        print(f"  Strategy {cfg['strategy']} not found, skipping")
        return []

    n_candles = TF_CANDLES.get(tf, 57240)
    trades = []

    for pair in PAIRS:
        print(f"  {pair}...", flush=True)
        raw = fetch(pair, tf, n_candles)
        if len(raw.get("close", [])) < 100:
            continue
        p = precompute(raw)
        n = p["n"]
        i = 60
        while i < n - 1:
            if not sfn(p, i): i += 1; continue
            ep     = p["c"][i]
            sl_p   = ep * (1 - sl)
            tp_p   = ep * (1 + tp)
            exposure = MARGIN * LEVERAGE
            qty    = exposure / ep
            ts     = raw["ts"][i]
            dt     = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            year   = dt.strftime("%Y")
            month  = dt.strftime("%Y-%m")
            result = "LOSS"; j = i + 1
            while j < min(i + 300 + 1, n):
                if p["l"][j] <= sl_p: result = "LOSS"; break
                if p["h"][j] >= tp_p: result = "WIN";  break
                j += 1
            pnl = qty * (tp_p - ep) if result == "WIN" else qty * (sl_p - ep)
            if pnl < -MARGIN: pnl = -MARGIN; result = "LIQ"
            trades.append({"year": year, "month": month, "result": result,
                           "pnl": round(pnl, 2), "pair": pair})
            i = j + 1
    return trades

# ── Run ───────────────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"  ALL 5 AGENTS — x50 Leverage Backtest (~6.5 years)")
print(f"  $10,000 capital | $500 margin/trade | 50x = $25,000 exposure")
print(f"{'='*70}\n")

results = {}
for agent_name, cfg in AGENTS.items():
    emoji = cfg["emoji"]
    print(f"Fetching {emoji} {agent_name} ({cfg['strategy']} {cfg['timeframe']})...")
    trades = backtest_agent(agent_name, cfg)
    results[agent_name] = trades
    wins   = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] in ("LOSS","LIQ")]
    total  = len(trades)
    wr     = len(wins)/total*100 if total else 0
    pnl    = sum(t["pnl"] for t in trades)
    print(f"  → {total} trades | WR={wr:.1f}% | PnL=${pnl:+,.0f}\n")

# ── Summary table ─────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"  SUMMARY — x50 Leverage | All agents | ~6.5 years | 10 pairs")
print(f"{'='*70}")
print(f"  {'Agent':<18} {'Trades':>7} {'W':>5} {'L':>5} {'WR%':>7} {'Total PnL':>13} {'Avg/trade':>11}")
print(f"  {'-'*68}")

ranked = []
for agent_name, trades in results.items():
    cfg    = AGENTS[agent_name]
    wins   = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] in ("LOSS","LIQ")]
    total  = len(trades)
    wr     = len(wins)/total*100 if total else 0
    pnl    = sum(t["pnl"] for t in trades)
    avg    = pnl/total if total else 0
    ranked.append((agent_name, cfg, total, len(wins), len(losses), wr, pnl, avg))

ranked.sort(key=lambda x: -x[6])

for agent_name, cfg, total, w, l, wr, pnl, avg in ranked:
    sign = "+" if pnl >= 0 else ""
    print(f"  {cfg['emoji']} {agent_name:<16} {total:>7} {w:>5} {l:>5} {wr:>6.1f}%  ${pnl:>+12,.0f}  ${avg:>+9,.0f}")

print(f"\n  * Each win  ≈ +$500  (2% of $25,000 for Oracle)")
print(f"  * Each loss ≈ -$875  (3.5% of $25,000 for Oracle)")
print(f"  * Different per agent based on their SL/TP settings")
