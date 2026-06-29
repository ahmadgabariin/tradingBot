"""
Deep backtest for 3 new agents: Confluence, Keltner, ATR Breakout.
3-5 years of data, 5 pairs, yearly + monthly breakdown.
Same standard as original 5 agents — only keep if profitable every year.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paper7.backtest_deep import fetch_cached, build_p, simulate_ts, aggregate, split_by_year, split_by_month, PAIRS_DEEP, MONTH_NAMES
from paper7.smart_agents import (
    _confluence_long, _confluence_short,
    _keltner_long, _keltner_short,
    _atr_breakout_long, _atr_breakout_short,
)
from collections import defaultdict
from datetime import datetime, timezone

print("Loading cached data...")
data = {}
for pair in PAIRS_DEEP:
    data[pair] = {}
    for tf in ["1h"]:
        raw = fetch_cached(pair, tf)
        if raw:
            data[pair][tf] = build_p(raw)
print("Done.\n")

def run_all(sig_l, sig_s, sl, tp, tf):
    trades = []
    for pair in PAIRS_DEEP:
        p = data.get(pair, {}).get(tf)
        if p:
            trades.extend(simulate_ts(p, sig_l, sig_s, sl, tp))
    return trades

def yearly(trades):
    by_yr = split_by_year(trades)
    return {yr: aggregate(t) for yr, t in sorted(by_yr.items())}

def monthly(trades):
    by_mo = split_by_month(trades)
    return {mo: aggregate(t) for mo, t in sorted(by_mo.items())}

def profitable_years(yr_dict):
    return sum(1 for m in yr_dict.values() if m["pnl_pct"] > 0)

strategies = [
    ("The Confluence",   _confluence_long,    _confluence_short,    0.010, 0.030, "1h"),
    ("The Keltner",      _keltner_long,        _keltner_short,       0.008, 0.024, "1h"),
    ("The ATR Breakout", _atr_breakout_long,   _atr_breakout_short,  0.012, 0.048, "1h"),
]

print("=" * 72)
print("  NEW AGENTS — DEEP BACKTEST (5 years, 5 pairs)")
print("=" * 72)

all_pass = True
results = {}

for sname, sig_l, sig_s, sl, tp, tf in strategies:
    trades = run_all(sig_l, sig_s, sl, tp, tf)
    ov  = aggregate(trades)
    yr  = yearly(trades)
    mo  = monthly(trades)
    py  = profitable_years(yr)
    ty  = len(yr)
    ok  = py == ty
    if not ok:
        all_pass = False

    results[sname] = {"ov": ov, "yr": yr, "mo": mo, "py": py, "ty": ty, "ok": ok}

    verdict = "PASS -- all years profitable" if ok else "FAIL -- has losing years"
    print()
    print(f"  {'='*68}")
    print(f"  {sname}  [{tf} | SL={sl*100:.1f}% TP={tp*100:.1f}%]  [{verdict}]")
    print(f"  Overall: {ov['trades']} trades | WR {ov['wr']}% | PnL {ov['pnl_pct']:+.2f}% | MaxDD {ov['max_dd_pct']:.2f}%")
    print(f"  {'='*68}")

    print(f"\n  -- BY YEAR --")
    print(f"  {'Year':<6} {'Trades':>7} {'WR%':>7} {'PnL%':>9} {'MaxDD%':>8}")
    print(f"  {'-'*40}")
    for y, m in yr.items():
        loss = "  <-- LOSS" if m["pnl_pct"] < 0 else ""
        print(f"  {y:<6} {m['trades']:>7} {m['wr']:>7.1f} {m['pnl_pct']:>+9.2f} {m['max_dd_pct']:>8.2f}{loss}")

    print(f"\n  -- BY MONTH (all years combined) --")
    print(f"  {'Month':<6} {'Trades':>7} {'WR%':>7} {'PnL%':>9} {'MaxDD%':>8}")
    print(f"  {'-'*40}")
    for mo_n in range(1, 13):
        m = mo.get(mo_n)
        if not m or m["trades"] == 0:
            print(f"  {MONTH_NAMES[mo_n]:<6} {'—':>7}")
            continue
        loss = "  LOSS" if m["pnl_pct"] < 0 else ""
        print(f"  {MONTH_NAMES[mo_n]:<6} {m['trades']:>7} {m['wr']:>7.1f} {m['pnl_pct']:>+9.2f} {m['max_dd_pct']:>8.2f}{loss}")

print()
print("=" * 72)
print("  SUMMARY")
print("=" * 72)
for sname, r in results.items():
    status = "PASS" if r["ok"] else "FAIL"
    print(f"  [{status}] {sname}: {r['py']}/{r['ty']} profitable years | WR {r['ov']['wr']}% | PnL {r['ov']['pnl_pct']:+.2f}% | MaxDD {r['ov']['max_dd_pct']:.2f}%")

print()
if all_pass:
    print("  ALL 3 NEW AGENTS PASSED -- keep in comp7/comp8")
else:
    print("  SOME AGENTS FAILED -- review before keeping in comp7/comp8")
print("=" * 72)
