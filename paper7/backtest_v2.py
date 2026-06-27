"""
Backtest v2 — test improved/replacement strategies before writing to agents.
"""
import sys, os, time, requests, json, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fast_backtest import precompute
from paper7.backtest_smart import fetch, build_p, simulate, metrics, PAIRS

# ── REVISED SIGNALS ───────────────────────────────────────────────────────────

# Surgeon v2 FIXED — loosened RSI (35 vs 32), just 1-bar turn, removed EMA pos req,
# require volume spike for confirmation
def _surgeon2_long_v2(p, i):
    if i < 50: return False
    return (p["rsi"][i] < 35
            and p["rsi"][i] > p["rsi"][i - 1]
            and p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.2
            and p["adx"][i] > 15)

def _surgeon2_short_v2(p, i):
    if i < 50: return False
    return (p["rsi"][i] > 65
            and p["rsi"][i] < p["rsi"][i - 1]
            and not p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.2
            and p["adx"][i] > 15)


# Regime Lord SAME logic, but 4:1 R/R tested (sl=0.008, tp=0.032)
def _detect_regime(p, i):
    if i < 60: return "NEUTRAL"
    adx = p["adx"][i]
    e9, e21, e50 = p["e9"][i], p["e21"][i], p["e50"][i]
    if adx > 25:
        if e9 > e21 > e50: return "TREND_UP"
        if e9 < e21 < e50: return "TREND_DOWN"
    if adx < 20: return "RANGING"
    return "NEUTRAL"

def _regime_long(p, i):
    if i < 60: return False
    regime = _detect_regime(p, i)
    if regime == "TREND_UP":
        return (p["c"][i] > p["e9"][i]
                and p["macd_hist"][i] > 0
                and p["macd_hist"][i] > p["macd_hist"][i - 1]
                and 45 < p["rsi"][i] < 68
                and p["v"][i] > p["vol_avg"][i] * 1.1
                and p["green"][i])
    if regime == "RANGING":
        return (p["c"][i] < p["bb_lo"][i]
                and p["rsi"][i] < 35
                and p["green"][i]
                and p["v"][i] > p["vol_avg"][i] * 1.1)
    return False

def _regime_short(p, i):
    if i < 60: return False
    regime = _detect_regime(p, i)
    if regime == "TREND_DOWN":
        return (p["c"][i] < p["e9"][i]
                and p["macd_hist"][i] < 0
                and p["macd_hist"][i] < p["macd_hist"][i - 1]
                and 32 < p["rsi"][i] < 55
                and p["v"][i] > p["vol_avg"][i] * 1.1
                and not p["green"][i])
    if regime == "RANGING":
        return (p["c"][i] > p["bb_hi"][i]
                and p["rsi"][i] > 65
                and not p["green"][i]
                and p["v"][i] > p["vol_avg"][i] * 1.1)
    return False


# EMA Pullback — replaces Divergence
# In uptrend: price dips to EMA21, bounces → entry
def _ema_pullback_long(p, i):
    if i < 60: return False
    uptrend   = p["e9"][i] > p["e21"][i] > p["e50"][i]
    near_e21  = p["l"][i] <= p["e21"][i] * 1.006 and p["c"][i] > p["e21"][i]
    rsi_ok    = 35 < p["rsi"][i] < 62
    green     = p["green"][i]
    adx_ok    = p["adx"][i] > 20
    return uptrend and near_e21 and rsi_ok and green and adx_ok

def _ema_pullback_short(p, i):
    if i < 60: return False
    downtrend = p["e9"][i] < p["e21"][i] < p["e50"][i]
    near_e21  = p["h"][i] >= p["e21"][i] * 0.994 and p["c"][i] < p["e21"][i]
    rsi_ok    = 38 < p["rsi"][i] < 65
    red       = not p["green"][i]
    adx_ok    = p["adx"][i] > 20
    return downtrend and near_e21 and rsi_ok and red and adx_ok


# Structure BOS — unchanged (already great), trying wider TP
from paper7.smart_agents import _structure_long, _structure_short
from paper7.smart_agents import _squeeze_long, _squeeze_short

# ── VARIANT TESTS ─────────────────────────────────────────────────────────────

VARIANTS = {
    "Surgeon v2 FIXED (15m)":    {"long": _surgeon2_long_v2,   "short": _surgeon2_short_v2,  "sl": 0.005, "tp": 0.010, "tf": "15m"},
    "Surgeon v2 FIX 2:1 (15m)":  {"long": _surgeon2_long_v2,   "short": _surgeon2_short_v2,  "sl": 0.007, "tp": 0.014, "tf": "15m"},
    "Regime 4:1 (1h)":           {"long": _regime_long,         "short": _regime_short,       "sl": 0.008, "tp": 0.032, "tf": "1h"},
    "Regime 3:1 (1h)":           {"long": _regime_long,         "short": _regime_short,       "sl": 0.008, "tp": 0.024, "tf": "1h"},
    "EMA Pullback 2:1 (1h)":     {"long": _ema_pullback_long,   "short": _ema_pullback_short, "sl": 0.008, "tp": 0.016, "tf": "1h"},
    "EMA Pullback 3:1 (1h)":     {"long": _ema_pullback_long,   "short": _ema_pullback_short, "sl": 0.010, "tp": 0.030, "tf": "1h"},
    "Structure 3:1 (1h)":        {"long": _structure_long,      "short": _structure_short,    "sl": 0.012, "tp": 0.036, "tf": "1h"},
    "Squeeze 2:1 (15m)":         {"long": _squeeze_long,        "short": _squeeze_short,      "sl": 0.008, "tp": 0.016, "tf": "15m"},
}

def run():
    print("=" * 70)
    print("  BACKTEST V2 — STRATEGY VARIANTS")
    print("=" * 70)

    print("\n[1/2] Loading candle data from v1 cache or re-fetching...\n")
    data = {}
    for pair in PAIRS:
        data[pair] = {}
        for tf in ["15m", "1h"]:
            raw = fetch(pair, tf, 1000)
            if raw:
                data[pair][tf] = build_p(raw)
                print(f"  OK {pair} {tf}")
            time.sleep(0.2)

    print("\n[2/2] Running variants...\n")
    summary = []
    for vname, cfg in VARIANTS.items():
        all_trades = []; total_candles = 0
        for pair in PAIRS:
            p = data.get(pair, {}).get(cfg["tf"])
            if not p: continue
            trades = simulate(p, cfg["long"], cfg["short"], cfg["sl"], cfg["tp"])
            all_trades.extend(trades)
            total_candles += p["n"]
        m = metrics(all_trades, total_candles, cfg["tf"])
        print(f"  {vname:<35} trades={m['trades']:3d}  WR={m['wr']:5.1f}%  PnL={m['pnl_pct']:+8.2f}%  DD={m['max_dd_pct']:5.2f}%  t/day={m['trades_per_day']:.2f}")
        summary.append((vname, m))

    print("\nRanked by PnL:")
    for name, m in sorted(summary, key=lambda x: -x[1]["pnl_pct"]):
        print(f"  {m['pnl_pct']:+8.2f}%  {name}")
    return summary

if __name__ == "__main__":
    run()
