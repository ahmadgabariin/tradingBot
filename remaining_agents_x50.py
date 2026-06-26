"""
Oracle + Comet — x50 leverage backtest (remaining agents)
"""
import requests, time, math, sys
from fast_backtest import precompute, STRATS
from paper.competition_agents import AGENTS, PAIRS

CAPITAL  = 10_000.0
MARGIN   = 500.0
LEVERAGE = 50
TF_CANDLES = {"15m": 17520*4, "1h": 17520, "4h": 17520//4}

def fetch(pair, tf, n_candles):
    all_c = []; end = None
    for _ in range(math.ceil(n_candles / 1000)):
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit=1000"
        if end: url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=15); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            time.sleep(0.05)
        except Exception as e:
            print(f"  err {pair}: {e}", flush=True); break
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
    tf  = cfg["timeframe"]
    sl  = cfg["sl"]
    tp  = cfg["tp"]
    sfn = STRATS.get(cfg["strategy"])
    if not sfn:
        print(f"  Strategy {cfg['strategy']} not found"); return []
    n_candles = TF_CANDLES.get(tf, 17520)
    trades = []
    for pair in PAIRS:
        print(f"  {pair}...", flush=True)
        raw = fetch(pair, tf, n_candles)
        if len(raw.get("close", [])) < 100: continue
        p = precompute(raw); n = p["n"]; i = 60
        while i < n - 1:
            if not sfn(p, i): i += 1; continue
            ep   = p["c"][i]
            sl_p = ep * (1 - sl); tp_p = ep * (1 + tp)
            qty  = (MARGIN * LEVERAGE) / ep
            result = "LOSS"; j = i + 1
            while j < min(i + 300 + 1, n):
                if p["l"][j] <= sl_p: result = "LOSS"; break
                if p["h"][j] >= tp_p: result = "WIN";  break
                j += 1
            pnl = qty * (tp_p - ep) if result == "WIN" else qty * (sl_p - ep)
            if pnl < -MARGIN: pnl = -MARGIN; result = "LIQ"
            trades.append({"result": result, "pnl": round(pnl, 2)})
            i = j + 1
    return trades

for name in ["The Oracle", "The Comet"]:
    cfg = AGENTS[name]
    print(f"\nFetching {cfg['emoji']} {name} ({cfg['strategy']} {cfg['timeframe']})...", flush=True)
    trades = backtest_agent(name, cfg)
    wins   = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] in ("LOSS","LIQ")]
    total  = len(trades)
    wr     = len(wins)/total*100 if total else 0
    pnl    = sum(t["pnl"] for t in trades)
    print(f"  → {total} trades | WR={wr:.1f}% | PnL=${pnl:+,.0f}", flush=True)
