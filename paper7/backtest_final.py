"""
Final validation backtest using the exact final smart_agents.py signals.
Confirms all 5 agents are optimized and ready for Competition 7.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paper7.backtest_smart import fetch, build_p, simulate, metrics, PAIRS
from paper7.smart_agents import (
    SMART_AGENTS,
    _surgeon2_long,  _surgeon2_short,
    _regime_long,    _regime_short,
    _squeeze_long,   _squeeze_short,
    _structure_long, _structure_short,
    _ema_rider_long, _ema_rider_short,
)

STRATEGIES = {
    "The Surgeon v2":  {"long": _surgeon2_long,  "short": _surgeon2_short},
    "The Regime Lord": {"long": _regime_long,    "short": _regime_short},
    "The Squeeze":     {"long": _squeeze_long,   "short": _squeeze_short},
    "The Structure":   {"long": _structure_long, "short": _structure_short},
    "The EMA Rider":   {"long": _ema_rider_long, "short": _ema_rider_short},
}

def run():
    print("=" * 68)
    print("  COMPETITION 7 — FINAL BACKTEST VALIDATION")
    print("  10 pairs x 5 agents | 1000 candles per pair/tf")
    print("=" * 68)

    data = {}
    print("\nFetching data...")
    tfs_needed = set(SMART_AGENTS[a]["timeframe"] for a in SMART_AGENTS)
    for pair in PAIRS:
        data[pair] = {}
        for tf in tfs_needed:
            raw = fetch(pair, tf, 1000)
            if raw: data[pair][tf] = build_p(raw)
            time.sleep(0.2)
    print("Done.\n")

    grand_pnl = 0.0
    results = []
    for aname, cfg in STRATEGIES.items():
        agent_cfg = SMART_AGENTS[aname]
        sl = agent_cfg["sl"]; tp = agent_cfg["tp"]; tf = agent_cfg["timeframe"]
        all_trades = []
        total_c = 0
        for pair in PAIRS:
            p = data.get(pair, {}).get(tf)
            if not p: continue
            all_trades.extend(simulate(p, cfg["long"], cfg["short"], sl, tp))
            total_c += p["n"]
        m = metrics(all_trades, total_c, tf)
        results.append((aname, m, sl, tp, tf))
        grand_pnl += m["pnl_pct"]

    print(f"  {'Agent':<20} {'SL':>5} {'TP':>5} {'TF':>5} {'Trades':>7} {'WR%':>7} {'PnL%':>8} {'MaxDD%':>8} {'t/day':>7}")
    print("  " + "-" * 75)
    for aname, m, sl, tp, tf in results:
        print(f"  {aname:<20} {sl*100:>4.1f}% {tp*100:>4.1f}% {tf:>5} {m['trades']:>7} {m['wr']:>7.1f} {m['pnl_pct']:>+8.2f} {m['max_dd_pct']:>8.2f} {m['trades_per_day']:>7.2f}")

    print(f"\n  Grand total aggregate PnL across all agents: {grand_pnl:+.2f}%")

    # Expected value per trade
    print("\n  EXPECTED VALUE per trade (1 unit):")
    for aname, m, sl, tp, tf in results:
        if m["trades"] == 0: continue
        wr = m["wr"] / 100
        ev = wr * tp - (1 - wr) * sl
        print(f"  {aname:<20} EV = {wr:.3f}x{tp*100:.1f}% - {(1-wr):.3f}x{sl*100:.1f}% = {ev*100:+.3f}% per trade")

    print("\n  KEY TAKEAWAYS:")
    for aname, m, sl, tp, tf in sorted(results, key=lambda x: -x[1]["pnl_pct"]):
        rr = tp/sl
        print(f"  {aname:<20}  {m['pnl_pct']:>+8.2f}% PnL  {m['wr']:5.1f}% WR  {rr:.1f}:1 R/R  {tf}")
    print("=" * 68)

if __name__ == "__main__":
    run()
