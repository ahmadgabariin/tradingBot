"""
Backtest v3 — Per-pair drill-down for the top strategies.
Also tests EMA Pullback with different parameters and per-regime breakdown.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper7.backtest_smart import fetch, build_p, simulate, metrics, PAIRS
from paper7.smart_agents import _structure_long, _structure_short, _squeeze_long, _squeeze_short
from paper7.backtest_v2 import (
    _surgeon2_long_v2, _surgeon2_short_v2,
    _regime_long, _regime_short,
    _ema_pullback_long, _ema_pullback_short,
    _detect_regime,
)

print("Loading data...")
data = {}
for pair in PAIRS:
    data[pair] = {}
    for tf in ["15m", "1h"]:
        raw = fetch(pair, tf, 1000)
        if raw:
            data[pair][tf] = build_p(raw)
        time.sleep(0.2)
print("Done.\n")

# ── PER-PAIR BREAKDOWN ────────────────────────────────────────────────────────

def per_pair_report(label, sig_l, sig_s, sl, tp, tf):
    print(f"\n{'='*60}")
    print(f"  {label}  (SL={sl*100:.1f}%  TP={tp*100:.1f}%  TF={tf})")
    print(f"{'='*60}")
    rows = []
    all_t = []
    for pair in PAIRS:
        p = data.get(pair, {}).get(tf)
        if not p:
            print(f"  {pair}: NO DATA"); continue
        trades = simulate(p, sig_l, sig_s, sl, tp)
        m = metrics(trades, p["n"], tf)
        all_t.extend(trades)
        rows.append((pair, m, trades))
        star = " <-- best" if m["pnl_pct"] > 30 else ""
        long_t  = [t for t in trades if t["side"] == "LONG"]
        short_t = [t for t in trades if t["side"] == "SHORT"]
        lw = len([t for t in long_t  if t["result"] == "TP"])
        sw = len([t for t in short_t if t["result"] == "TP"])
        lwr = f"{lw/len(long_t)*100:.0f}%" if long_t  else "--"
        swr = f"{sw/len(short_t)*100:.0f}%" if short_t else "--"
        print(f"  {pair:12s}: {m['trades']:3d}tr  WR={m['wr']:5.1f}%  L:{lwr:4s}  S:{swr:4s}  PnL={m['pnl_pct']:+7.2f}%  DD={m['max_dd_pct']:4.1f}%{star}")
    agg = metrics(all_t, sum(data[p][tf]["n"] for p in PAIRS if tf in data.get(p,{})), tf)
    print(f"  {'TOTAL':12s}: {agg['trades']:3d}tr  WR={agg['wr']:5.1f}%             PnL={agg['pnl_pct']:+7.2f}%  DD={agg['max_dd_pct']:4.1f}%  t/day={agg['trades_per_day']:.2f}")

# Top 3 strategies per-pair
per_pair_report("STRUCTURE BOS",     _structure_long,     _structure_short,     0.012, 0.036, "1h")
per_pair_report("EMA PULLBACK 3:1",  _ema_pullback_long,  _ema_pullback_short,  0.010, 0.030, "1h")
per_pair_report("SURGEON v2 FIXED",  _surgeon2_long_v2,   _surgeon2_short_v2,   0.005, 0.010, "15m")

# ── SIDE BREAKDOWN (long vs short) for top strategies ─────────────────────────

print(f"\n{'='*60}")
print("  LONG vs SHORT BREAKDOWN")
print(f"{'='*60}")

def side_breakdown(label, sig_l, sig_s, sl, tp, tf):
    all_t = []
    for pair in PAIRS:
        p = data.get(pair, {}).get(tf)
        if not p: continue
        all_t.extend(simulate(p, sig_l,   None,  sl, tp))   # longs only
    long_m  = metrics(all_t, 1, tf)
    all_t2 = []
    for pair in PAIRS:
        p = data.get(pair, {}).get(tf)
        if not p: continue
        all_t2.extend(simulate(p, None,  sig_s, sl, tp))   # shorts only
    short_m = metrics(all_t2, 1, tf)
    print(f"  {label}")
    print(f"    LONG : {long_m['trades']:3d}tr WR={long_m['wr']:5.1f}% PnL={long_m['pnl_pct']:+7.2f}%")
    print(f"    SHORT: {short_m['trades']:3d}tr WR={short_m['wr']:5.1f}% PnL={short_m['pnl_pct']:+7.2f}%")
    print()

side_breakdown("Structure BOS",    _structure_long, _structure_short, 0.012, 0.036, "1h")
side_breakdown("EMA Pullback 3:1", _ema_pullback_long, _ema_pullback_short, 0.010, 0.030, "1h")
side_breakdown("Surgeon v2",       _surgeon2_long_v2, _surgeon2_short_v2, 0.005, 0.010, "15m")
side_breakdown("Squeeze",          _squeeze_long, _squeeze_short, 0.008, 0.016, "15m")

# ── SQUEEZE PARAMETER SWEEP ───────────────────────────────────────────────────

print(f"\n{'='*60}")
print("  SQUEEZE PARAMETER SWEEP")
print(f"{'='*60}")
for sl, tp in [(0.006, 0.012), (0.008, 0.016), (0.008, 0.024), (0.010, 0.020), (0.010, 0.030)]:
    all_t = []
    for pair in PAIRS:
        p = data.get(pair, {}).get("15m")
        if not p: continue
        all_t.extend(simulate(p, _squeeze_long, _squeeze_short, sl, tp))
    m = metrics(all_t, 1, "15m")
    print(f"  SL={sl*100:.1f}% TP={tp*100:.1f}%  R/R={tp/sl:.1f}:1  trades={m['trades']:3d}  WR={m['wr']:5.1f}%  PnL={m['pnl_pct']:+7.2f}%  DD={m['max_dd_pct']:4.1f}%")

print("\nDone.")
