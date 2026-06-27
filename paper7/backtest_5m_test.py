"""
Quick test: Surgeon v2 on 5m vs 15m — does 5m actually outperform?
Also tests Squeeze on 5m.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paper7.backtest_smart import fetch, build_p, simulate, metrics, PAIRS
from paper7.smart_agents import _surgeon2_long, _surgeon2_short, _squeeze_long, _squeeze_short

TEST_PAIRS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT","LINKUSDT","DOTUSDT","AVAXUSDT","POLUSDT"]

print("Fetching 5m and 15m data...")
data5 = {}; data15 = {}
for pair in TEST_PAIRS:
    raw5  = fetch(pair, "5m",  1000)
    time.sleep(0.15)
    raw15 = fetch(pair, "15m", 1000)
    time.sleep(0.15)
    if raw5:  data5[pair]  = build_p(raw5)
    if raw15: data15[pair] = build_p(raw15)
print("Done.\n")

print("  SURGEON v2 — 5m vs 15m")
print(f"  {'Param':<22} {'Trades':>7} {'WR%':>6} {'PnL%':>8} {'MaxDD%':>8} {'t/day':>7}")
print("  " + "-" * 60)

for sl, tp in [(0.003, 0.006), (0.004, 0.008), (0.005, 0.010)]:
    all_t = []
    for pair in TEST_PAIRS:
        p = data5.get(pair)
        if not p: continue
        all_t.extend(simulate(p, _surgeon2_long, _surgeon2_short, sl, tp))
    m = metrics(all_t, 1, "5m")
    print(f"  5m  SL={sl*100:.1f}% TP={tp*100:.1f}%      {m['trades']:>7} {m['wr']:>6.1f} {m['pnl_pct']:>+8.2f} {m['max_dd_pct']:>8.2f} {m['trades_per_day']:>7.2f}")

for sl, tp in [(0.005, 0.010), (0.007, 0.014)]:
    all_t = []
    for pair in TEST_PAIRS:
        p = data15.get(pair)
        if not p: continue
        all_t.extend(simulate(p, _surgeon2_long, _surgeon2_short, sl, tp))
    m = metrics(all_t, 1, "15m")
    print(f"  15m SL={sl*100:.1f}% TP={tp*100:.1f}%      {m['trades']:>7} {m['wr']:>6.1f} {m['pnl_pct']:>+8.2f} {m['max_dd_pct']:>8.2f} {m['trades_per_day']:>7.2f}")

print()
print("  SQUEEZE — 5m vs 15m")
print(f"  {'Param':<22} {'Trades':>7} {'WR%':>6} {'PnL%':>8} {'MaxDD%':>8} {'t/day':>7}")
print("  " + "-" * 60)
for sl, tp in [(0.006, 0.012), (0.008, 0.016), (0.010, 0.020)]:
    all_t = []
    for pair in TEST_PAIRS:
        p = data5.get(pair)
        if not p: continue
        all_t.extend(simulate(p, _squeeze_long, _squeeze_short, sl, tp))
    m = metrics(all_t, 1, "5m")
    print(f"  5m  SL={sl*100:.1f}% TP={tp*100:.1f}%      {m['trades']:>7} {m['wr']:>6.1f} {m['pnl_pct']:>+8.2f} {m['max_dd_pct']:>8.2f} {m['trades_per_day']:>7.2f}")

for sl, tp in [(0.010, 0.030)]:
    all_t = []
    for pair in TEST_PAIRS:
        p = data15.get(pair)
        if not p: continue
        all_t.extend(simulate(p, _squeeze_long, _squeeze_short, sl, tp))
    m = metrics(all_t, 1, "15m")
    print(f"  15m SL={sl*100:.1f}% TP={tp*100:.1f}%      {m['trades']:>7} {m['wr']:>6.1f} {m['pnl_pct']:>+8.2f} {m['max_dd_pct']:>8.2f} {m['trades_per_day']:>7.2f}")
