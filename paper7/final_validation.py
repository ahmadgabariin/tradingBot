"""Final validation — all 5 agents with optimized config."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paper7.backtest_deep import fetch_cached, build_p, simulate_ts, aggregate, split_by_year, PAIRS_DEEP
from paper7.smart_agents import (
    _surgeon2_long, _surgeon2_short,
    _regime_long, _regime_short,
    _squeeze_long, _squeeze_short,
    _structure_long, _structure_short,
    _ema_rider_long, _ema_rider_short,
)

print("Loading cached data...")
data = {}
for pair in PAIRS_DEEP:
    data[pair] = {}
    for tf in ["5m", "15m", "1h"]:
        raw = fetch_cached(pair, tf)
        if raw:
            data[pair][tf] = build_p(raw)

def run_all(sig_l, sig_s, sl, tp, tf):
    trades = []
    for pair in PAIRS_DEEP:
        p = data.get(pair, {}).get(tf)
        if p:
            trades.extend(simulate_ts(p, sig_l, sig_s, sl, tp))
    return trades

strategies = [
    ("The Surgeon v2",  _surgeon2_long,  _surgeon2_short,  0.005, 0.010, "15m"),
    ("The Regime Lord", _regime_long,    _regime_short,    0.008, 0.032, "1h"),
    ("The Squeeze",     _squeeze_long,   _squeeze_short,   0.008, 0.032, "5m"),
    ("The Structure",   _structure_long, _structure_short, 0.012, 0.036, "1h"),
    ("The EMA Rider",   _ema_rider_long, _ema_rider_short, 0.010, 0.030, "1h"),
]

print()
print("=" * 78)
print("  FINAL VALIDATION -- ALL 5 AGENTS WITH OPTIMIZED CONFIG")
print("=" * 78)

all_ok = True
for sname, sig_l, sig_s, sl, tp, tf in strategies:
    trades = run_all(sig_l, sig_s, sl, tp, tf)
    ov = aggregate(trades)
    by_yr = split_by_year(trades)
    yr_metrics = {yr: aggregate(t) for yr, t in sorted(by_yr.items())}
    py = sum(1 for m in yr_metrics.values() if m["pnl_pct"] > 0)
    ty = len(yr_metrics)
    ok = (py == ty)
    if not ok:
        all_ok = False
    flag = "OK" if ok else "HAS LOSS YEAR"
    print()
    print("  {:20s} [{}] SL={:.1f}% TP={:.1f}%  {:5d}tr  WR={:.1f}%  PnL={:+.2f}%  MaxDD={:.2f}%  {}/{} yrs  [{}]".format(
        sname, tf, sl*100, tp*100, ov["trades"], ov["wr"], ov["pnl_pct"], ov["max_dd_pct"], py, ty, flag
    ))
    for yr, m in yr_metrics.items():
        loss = "  <-- LOSS" if m["pnl_pct"] < 0 else ""
        print("    {}: {:4d}tr  WR={:.1f}%  PnL={:+.2f}%  MaxDD={:.2f}%{}".format(
            yr, m["trades"], m["wr"], m["pnl_pct"], m["max_dd_pct"], loss
        ))

print()
print("=" * 78)
if all_ok:
    print("  ALL 5 AGENTS PROFITABLE EVERY YEAR -- READY TO DEPLOY")
else:
    print("  WARNING: Some agents have losing years -- review before deploy")
print("=" * 78)
