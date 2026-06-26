"""
1-Month Backtest for each competition agent
$10,000 capital, $500/trade, 10 pairs
"""
import requests, time, math, sys
from datetime import datetime, timezone
from collections import defaultdict
from fast_backtest import precompute, STRATS
from paper.competition_agents import AGENTS, PAIRS

CAPITAL  = 10_000.0
POS_SIZE = 500.0

TF_CANDLES = {"15m": 2976, "1h": 744, "4h": 186}  # ~31 days

def fetch(pair, tf, n):
    all_c=[]; end=None
    for _ in range(math.ceil(n/1000)):
        url=f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit=1000"
        if end: url+=f"&endTime={end}"
        try:
            r=requests.get(url,timeout=15); r.raise_for_status()
            batch=r.json()
            if not batch: break
            all_c=batch+all_c
            end=int(batch[0][0])-1
            time.sleep(0.07)
        except Exception as e:
            print(f"  err {pair} {tf}: {e}"); break
    raw=all_c[-n:]
    return {
        "open": [float(c[1]) for c in raw], "high": [float(c[2]) for c in raw],
        "low":  [float(c[3]) for c in raw], "close":[float(c[4]) for c in raw],
        "vol":  [float(c[5]) for c in raw], "ts":   [int(c[0])   for c in raw],
    }

def backtest_agent(raw, sfn, sl, tp, pos=POS_SIZE, max_hold=300):
    p = precompute(raw)
    n = p["n"]; i = 60
    trades = []
    while i < n-1:
        if not sfn(p, i): i+=1; continue
        ep   = p["c"][i]
        sl_p = ep*(1-sl); tp_p = ep*(1+tp)
        qty  = pos/ep
        ts   = raw["ts"][i] if "ts" in raw else 0
        date = datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime("%Y-%m-%d") if ts else "?"
        result = "LOSS"; j = i+1
        while j < min(i+max_hold+1, n):
            if p["l"][j] <= sl_p: result="LOSS"; break
            if p["h"][j] >= tp_p: result="WIN";  break
            j+=1
        pnl = qty*(tp_p-ep) if result=="WIN" else qty*(sl_p-ep)
        trades.append({"date":date,"result":result,"pnl":round(pnl,2),"pair":"","ep":ep})
        i = j+1
    return trades

# Fetch data
print("\nFetching 31 days of data...\n")
data = {}
needed_tfs = set(AGENTS[a]["timeframe"] for a in AGENTS)
for tf in needed_tfs:
    data[tf] = {}
    for pair in PAIRS:
        sys.stdout.write(f"  {pair} {tf}...\r"); sys.stdout.flush()
        raw = fetch(pair, tf, TF_CANDLES[tf])
        data[tf][pair] = raw
print("Done.\n")

# Run backtest for each agent
print("="*70)
print(f"  1-MONTH BACKTEST — Each Agent | $10k capital | $500/trade | 10 pairs")
print("="*70)

all_agent_results = {}

for aname, cfg in AGENTS.items():
    sfn = STRATS.get(cfg["strategy"])
    if not sfn:
        print(f"\n  [{aname}] Strategy {cfg['strategy']} not found"); continue

    tf  = cfg["timeframe"]
    sl  = cfg["sl"]
    tp  = cfg["tp"]
    emoji = cfg["emoji"]
    color = cfg["color"]

    all_trades = []
    pair_pnl   = defaultdict(float)
    pair_trades= defaultdict(int)

    for pair in PAIRS:
        raw    = data[tf][pair]
        trades = backtest_agent(raw, sfn, sl, tp)
        for t in trades:
            t["pair"] = pair
        all_trades.extend(trades)
        pair_pnl[pair]    = sum(t["pnl"] for t in trades)
        pair_trades[pair] = len(trades)

    wins   = [t for t in all_trades if t["result"]=="WIN"]
    losses = [t for t in all_trades if t["result"]=="SL"]
    total  = len(all_trades)
    wr     = len(wins)/total*100 if total>0 else 0
    pnl    = sum(t["pnl"] for t in all_trades)
    roi    = pnl/CAPITAL*100
    daily  = pnl/31
    avg_win  = sum(t["pnl"] for t in wins)/len(wins)   if wins   else 0
    avg_loss = sum(t["pnl"] for t in losses)/len(losses) if losses else 0

    # Running balance & max drawdown
    bal = CAPITAL; peak = CAPITAL; max_dd = 0
    for t in sorted(all_trades, key=lambda x: x["date"]):
        bal += t["pnl"]
        if bal > peak: peak = bal
        dd = peak - bal
        if dd > max_dd: max_dd = dd

    best  = max(all_trades, key=lambda t: t["pnl"], default=None)
    worst = min(all_trades, key=lambda t: t["pnl"], default=None)

    all_agent_results[aname] = {
        "pnl": pnl, "roi": roi, "wr": wr, "total": total,
        "daily": daily, "max_dd": max_dd, "final": CAPITAL+pnl
    }

    sign = "+" if pnl >= 0 else ""
    print(f"\n  {emoji} {aname}")
    print(f"     Strategy:  {cfg['strategy']} | {tf} | SL={sl*100:.1f}% TP={tp*100:.1f}%")
    print(f"     Trades:    {total} total ({total/31:.1f}/day)  |  WR: {wr:.1f}%")
    print(f"     Monthly:   ${pnl:>+,.2f}  ({sign}{roi:.2f}% ROI)")
    print(f"     Daily avg: ${daily:>+.2f}/day")
    print(f"     Final bal: ${CAPITAL+pnl:,.2f}")
    print(f"     Max DD:    ${max_dd:,.2f}")
    print(f"     Avg win:   ${avg_win:>+.2f}  |  Avg loss: ${avg_loss:>+.2f}")
    if best:  print(f"     Best:      +${best['pnl']:.2f} on {best['pair']} ({best['date']})")
    if worst: print(f"     Worst:     ${worst['pnl']:.2f} on {worst['pair']} ({worst['date']})")

    # Pair breakdown
    print(f"     Pair PnL:  ", end="")
    sorted_pairs = sorted(pair_pnl.items(), key=lambda x: -x[1])
    for sym, p in sorted_pairs[:5]:
        sign2 = "+" if p >= 0 else ""
        print(f"{sym.replace('USDT','')}: {sign2}${p:.0f}", end="  ")
    print()

# Summary ranking
print(f"\n{'='*70}")
print("  FINAL RANKING — 1 Month")
print(f"{'='*70}")
ranked = sorted(all_agent_results.items(), key=lambda x: -x[1]["pnl"])
for i, (name, r) in enumerate(ranked):
    emoji = AGENTS[name]["emoji"]
    sign  = "+" if r["pnl"] >= 0 else ""
    bar   = "█" * max(0, int(r["roi"]*2)) if r["roi"] > 0 else "▓" * max(0, int(abs(r["roi"])*2))
    color = "WIN" if r["pnl"] >= 0 else "LOSE"
    print(f"  #{i+1} {emoji} {name:<16} ${r['final']:>10,.2f}  ({sign}{r['roi']:.2f}%)  "
          f"WR={r['wr']:.1f}%  Trades={r['total']}  MaxDD=${r['max_dd']:.0f}  [{color}]")

print()
