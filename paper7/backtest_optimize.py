"""
Optimization pass using the cached 3-5 year data.
Goals:
  1. Fix The Squeeze — find R/R ratio that makes it profitable every year
  2. Improve The Regime Lord — reduce losing months
  3. Validate final configuration year by year
"""
import sys, os, json, time
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fast_backtest import precompute
from paper7.smart_agents import (
    _squeeze_long, _squeeze_short,
    _regime_long, _regime_short,
    _structure_long, _structure_short,
    _surgeon2_long, _surgeon2_short,
    _ema_rider_long, _ema_rider_short,
)
from paper7.backtest_deep import fetch_cached, build_p, simulate_ts, aggregate, split_by_year, PAIRS_DEEP, MONTH_NAMES

# ── LOAD CACHED DATA ──────────────────────────────────────────────────────────

print("Loading cached data...")
data = {}
for pair in PAIRS_DEEP:
    data[pair] = {}
    for tf in ["5m", "15m", "1h"]:
        raw = fetch_cached(pair, tf)
        if raw:
            data[pair][tf] = build_p(raw)
print("Done.\n")

def run_all_pairs(sig_l, sig_s, sl, tp, tf):
    trades = []
    for pair in PAIRS_DEEP:
        p = data.get(pair, {}).get(tf)
        if p:
            trades.extend(simulate_ts(p, sig_l, sig_s, sl, tp))
    return trades

def yearly(trades):
    by_yr = split_by_year(trades)
    return {yr: aggregate(t) for yr, t in sorted(by_yr.items())}

def profitable_years(yr_dict):
    return sum(1 for m in yr_dict.values() if m["pnl_pct"] > 0)

def total_years(yr_dict):
    return len(yr_dict)

# ── 1. SQUEEZE PARAMETER SWEEP ────────────────────────────────────────────────

print("=" * 65)
print("  THE SQUEEZE — Full parameter sweep on 3-year data")
print("=" * 65)
print(f"  {'SL':>5} {'TP':>5} {'R/R':>5}  {'Trades':>7}  {'WR%':>6}  {'PnL%':>9}  {'MaxDD%':>8}  {'Prof yrs':>9}")
print("  " + "-" * 60)

best_squeeze = None
best_squeeze_score = -999

for sl in [0.006, 0.008, 0.010, 0.012]:
    for rr in [2.0, 2.5, 3.0, 3.5, 4.0]:
        tp = sl * rr
        trades = run_all_pairs(_squeeze_long, _squeeze_short, sl, tp, "5m")
        m  = aggregate(trades)
        yr = yearly(trades)
        py = profitable_years(yr)
        ty = total_years(yr)
        flag = " <-- ALL YEARS PROFIT" if py == ty and ty > 0 else ""
        print(f"  {sl*100:>4.1f}% {tp*100:>4.1f}% {rr:>5.1f}x  {m['trades']:>7}  {m['wr']:>6.1f}  {m['pnl_pct']:>+9.2f}  {m['max_dd_pct']:>8.2f}  {py}/{ty}{flag}")
        # Score: profitable years weighted by PnL, penalize MaxDD
        score = py * 10 + m["pnl_pct"] / 100 - m["max_dd_pct"]
        if py == ty and m["pnl_pct"] > best_squeeze_score:
            best_squeeze_score = m["pnl_pct"]
            best_squeeze = (sl, tp, rr, m, yr)

print()
if best_squeeze:
    sl, tp, rr, m, yr = best_squeeze
    print(f"  Best Squeeze config: SL={sl*100:.1f}% TP={tp*100:.1f}% ({rr:.1f}:1 R/R)")
    print(f"  Year breakdown:")
    for y, ym in yr.items():
        print(f"    {y}: {ym['trades']:3d}tr  WR={ym['wr']:5.1f}%  PnL={ym['pnl_pct']:+8.2f}%")

# ── 2. REGIME LORD IMPROVEMENT ────────────────────────────────────────────────

print("\n" + "=" * 65)
print("  THE REGIME LORD — Stricter ADX filter test")
print("=" * 65)

# Import the internal regime detection to build a stricter variant
from paper7.smart_agents import _detect_regime

def _regime_long_strict(p, i):
    """Regime Lord with stricter ADX requirement (25 vs 18) and volume."""
    if i < 60: return False
    regime = _detect_regime(p, i)
    if regime == "TREND_UP":
        return (p["c"][i] > p["e9"][i]
                and p["macd_hist"][i] > 0
                and p["macd_hist"][i] > p["macd_hist"][i - 1]
                and 48 < p["rsi"][i] < 65
                and p["v"][i] > p["vol_avg"][i] * 1.3
                and p["adx"][i] > 25
                and p["green"][i])
    if regime == "RANGING":
        return (p["c"][i] < p["bb_lo"][i]
                and p["rsi"][i] < 30
                and p["green"][i]
                and p["v"][i] > p["vol_avg"][i] * 1.3
                and p["adx"][i] < 18)
    return False

def _regime_short_strict(p, i):
    if i < 60: return False
    regime = _detect_regime(p, i)
    if regime == "TREND_DOWN":
        return (p["c"][i] < p["e9"][i]
                and p["macd_hist"][i] < 0
                and p["macd_hist"][i] < p["macd_hist"][i - 1]
                and 35 < p["rsi"][i] < 52
                and p["v"][i] > p["vol_avg"][i] * 1.3
                and p["adx"][i] > 25
                and not p["green"][i])
    if regime == "RANGING":
        return (p["c"][i] > p["bb_hi"][i]
                and p["rsi"][i] > 70
                and not p["green"][i]
                and p["v"][i] > p["vol_avg"][i] * 1.3
                and p["adx"][i] < 18)
    return False

print(f"\n  {'Version':<22} {'Trades':>7} {'WR%':>6} {'PnL%':>9} {'MaxDD%':>8} {'Prof yrs':>9}")
print("  " + "-" * 58)

for label, sl, tp, sig_l, sig_s in [
    ("Original 4:1",        0.008, 0.032, _regime_long,        _regime_short),
    ("Strict 4:1",          0.008, 0.032, _regime_long_strict,  _regime_short_strict),
    ("Strict 5:1",          0.008, 0.040, _regime_long_strict,  _regime_short_strict),
    ("Strict 6:1",          0.008, 0.048, _regime_long_strict,  _regime_short_strict),
    ("Strict 4:1 tighter",  0.006, 0.024, _regime_long_strict,  _regime_short_strict),
]:
    trades = run_all_pairs(sig_l, sig_s, sl, tp, "1h")
    m  = aggregate(trades)
    yr = yearly(trades)
    py = profitable_years(yr)
    ty = total_years(yr)
    flag = " <--" if py == ty and ty > 0 else ""
    print(f"  {label:<22} {m['trades']:>7} {m['wr']:>6.1f} {m['pnl_pct']:>+9.2f} {m['max_dd_pct']:>8.2f} {py}/{ty}{flag}")

print()
print("  Strict version year breakdown:")
trades_s = run_all_pairs(_regime_long_strict, _regime_short_strict, 0.008, 0.032, "1h")
for y, ym in yearly(trades_s).items():
    print(f"    {y}: {ym['trades']:3d}tr  WR={ym['wr']:5.1f}%  PnL={ym['pnl_pct']:+8.2f}%")

print("  By month (strict):")
by_m = defaultdict(list)
for t in trades_s:
    mo = datetime.fromtimestamp(t["ts"]/1000, tz=timezone.utc).month
    by_m[mo].append(t)
for mo in range(1, 13):
    m = aggregate(by_m.get(mo, []))
    flag = " LOSS" if m["pnl_pct"] < 0 else ""
    print(f"    {MONTH_NAMES[mo]}: {m['trades']:3d}tr  WR={m['wr']:5.1f}%  PnL={m['pnl_pct']:+7.2f}%{flag}")

# ── 3. CONFIRM SURGEON + STRUCTURE + EMA RIDER ARE SOLID ─────────────────────

print("\n" + "=" * 65)
print("  CONFIRMED SOLID AGENTS — Year-by-year summary")
print("=" * 65)

for sname, sig_l, sig_s, sl, tp, tf in [
    ("Surgeon v2",  _surgeon2_long,  _surgeon2_short,  0.005, 0.010, "15m"),
    ("Structure",   _structure_long, _structure_short, 0.012, 0.036, "1h"),
    ("EMA Rider",   _ema_rider_long, _ema_rider_short, 0.010, 0.030, "1h"),
]:
    trades = run_all_pairs(sig_l, sig_s, sl, tp, tf)
    yr = yearly(trades)
    ov = aggregate(trades)
    py = profitable_years(yr)
    ty = total_years(yr)
    print(f"\n  {sname} [{tf}]  overall WR={ov['wr']}%  {py}/{ty} profitable years")
    for y, ym in yr.items():
        flag = "  LOSS" if ym["pnl_pct"] < 0 else ""
        print(f"    {y}: {ym['trades']:4d}tr  WR={ym['wr']:5.1f}%  PnL={ym['pnl_pct']:+9.2f}%  MaxDD={ym['max_dd_pct']:5.2f}%{flag}")

print("\nDone. Use these findings to update smart_agents.py.")
