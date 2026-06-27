"""
Extended backtest on 2000 candles — verifies results hold across different market regimes.
Also tests first vs second half separately to check consistency.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paper7.backtest_smart import fetch, build_p, simulate, metrics, PAIRS
from paper7.smart_agents import (
    _surgeon2_long, _surgeon2_short, SMART_AGENTS,
    _regime_long, _regime_short,
    _squeeze_long, _squeeze_short,
    _structure_long, _structure_short,
    _ema_rider_long, _ema_rider_short,
)

STRATEGIES = {
    "Surgeon v2":  {"l": _surgeon2_long,  "s": _surgeon2_short,  "tf": "15m", "sl": 0.005, "tp": 0.010},
    "Regime Lord": {"l": _regime_long,    "s": _regime_short,    "tf": "1h",  "sl": 0.008, "tp": 0.032},
    "Squeeze":     {"l": _squeeze_long,   "s": _squeeze_short,   "tf": "15m", "sl": 0.010, "tp": 0.030},
    "Structure":   {"l": _structure_long, "s": _structure_short, "tf": "1h",  "sl": 0.012, "tp": 0.036},
    "EMA Rider":   {"l": _ema_rider_long, "s": _ema_rider_short, "tf": "1h",  "sl": 0.010, "tp": 0.030},
}

# Use a smaller set of pairs for speed
TEST_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]

def split_p(p, start_frac, end_frac):
    """Return a slice of the precomputed dict."""
    n = p["n"]
    s = int(n * start_frac)
    e = int(n * end_frac)
    keys = ["c", "h", "l", "o", "v", "e9", "e21", "e50", "e200",
            "rsi", "macd_hist", "atr", "bb_lo", "bb_mid", "bb_hi",
            "adx", "vol_avg", "don_hi", "don_lo", "green",
            "vwap", "s_hi", "s_lo", "vol_delta"]
    sliced = {"n": e - s}
    for k in keys:
        if k in p:
            sliced[k] = p[k][s:e]
    return sliced

def run():
    print("=" * 68)
    print("  EXTENDED BACKTEST — 2000 CANDLES, HALF-SPLIT ANALYSIS")
    print(f"  {len(TEST_PAIRS)} pairs (BTC/ETH/SOL/XRP/ADA)")
    print("=" * 68)

    print("\nFetching 2000-candle data...")
    data = {}
    for pair in TEST_PAIRS:
        data[pair] = {}
        for tf in ["15m", "1h"]:
            raw = fetch(pair, tf, 2000)
            if raw: data[pair][tf] = build_p(raw)
            time.sleep(0.25)
    print("Done.\n")

    for sname, cfg in STRATEGIES.items():
        tf = cfg["tf"]; sl = cfg["sl"]; tp = cfg["tp"]
        all_full = []; all_h1 = []; all_h2 = []
        for pair in TEST_PAIRS:
            p = data.get(pair, {}).get(tf)
            if not p: continue
            all_full.extend(simulate(p, cfg["l"], cfg["s"], sl, tp))
            p1 = split_p(p, 0.0, 0.5)
            p2 = split_p(p, 0.5, 1.0)
            all_h1.extend(simulate(p1, cfg["l"], cfg["s"], sl, tp))
            all_h2.extend(simulate(p2, cfg["l"], cfg["s"], sl, tp))

        mf = metrics(all_full, 1, tf)
        m1 = metrics(all_h1, 1, tf)
        m2 = metrics(all_h2, 1, tf)
        print(f"  {sname:<14}  Full: {mf['trades']:3d}tr {mf['wr']:5.1f}%WR {mf['pnl_pct']:+7.2f}%  |  H1(older): {m1['trades']:3d}tr {m1['wr']:5.1f}%WR {m1['pnl_pct']:+7.2f}%  |  H2(recent): {m2['trades']:3d}tr {m2['wr']:5.1f}%WR {m2['pnl_pct']:+7.2f}%")

    print("\n(H1=older half, H2=more recent half of 2000 candles)")
    print("Consistent positive PnL in both halves = strategy works across regimes.")
    print("=" * 68)

if __name__ == "__main__":
    run()
