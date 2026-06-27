"""
Deep backtest for Competition 7 smart agent strategies.
Fetches real Binance data, tests all 5 strategies across all pairs/timeframes.
"""
import sys, os, time, requests, json, math
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fast_backtest import (
    ema_series, rsi_series, macd_series, atr_series, bb_series, adx_series, precompute
)
from paper7.smart_agents import (
    _surgeon2_long, _surgeon2_short,
    _regime_long, _regime_short,
    _squeeze_long, _squeeze_short,
    _structure_long, _structure_short,
    _ema_rider_long, _ema_rider_short,
    SMART_AGENTS, SMART_PAIRS,
)

PAIRS = SMART_PAIRS
TIMEFRAMES = ["5m", "15m", "1h"]
N_CANDLES  = 1000

# ── DATA FETCH ────────────────────────────────────────────────────────────────

def fetch(pair, tf, n=1000):
    all_c = []
    end = None
    for _ in range(math.ceil(n / 1000)):
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit=1000"
        if end: url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=15); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            time.sleep(0.2)
        except Exception as e:
            print(f"  fetch error {pair} {tf}: {e}"); break
    raw = all_c[-n:]
    if not raw:
        return None
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
        "vol":   [float(c[5]) for c in raw],
        "ts":    [int(c[0])   for c in raw],
        "n":     len(raw),
    }

def _calc_swing(raw, lookback=10):
    n = len(raw["close"])
    s_hi = [0.0]*n; s_lo = [0.0]*n
    for i in range(lookback, n):
        s_hi[i] = max(raw["high"][i-lookback:i])
        s_lo[i] = min(raw["low"][i-lookback:i])
    return s_hi, s_lo

def _calc_vwap(raw):
    n = len(raw["close"])
    result, cum_tp, cum_v, prev_day = [0.0]*n, 0.0, 0.0, -1
    for i in range(n):
        day = raw["ts"][i] // 86400000
        if day != prev_day:
            cum_tp = cum_v = 0.0
            prev_day = day
        tp = (raw["high"][i]+raw["low"][i]+raw["close"][i])/3
        cum_tp += tp * raw["vol"][i]; cum_v += raw["vol"][i]
        result[i] = cum_tp/cum_v if cum_v > 0 else tp
    return result

def build_p(raw):
    p = precompute(raw)
    p["raw"] = raw
    p["vwap"] = _calc_vwap(raw)
    p["s_hi"], p["s_lo"] = _calc_swing(raw)
    return p

# ── SIMULATION ────────────────────────────────────────────────────────────────

def simulate(p, sig_long, sig_short, sl_pct, tp_pct, name=""):
    n = p["n"]
    trades = []
    in_long = in_short = False
    entry = sl = tp = 0.0
    entry_i = 0

    for i in range(60, n - 1):
        price = p["c"][i]

        # Check exit
        if in_long:
            if price >= tp:
                pnl = (tp - entry) / entry
                trades.append({"side": "LONG", "result": "TP", "pnl_pct": pnl, "bars": i - entry_i, "i": i})
                in_long = False
            elif price <= sl:
                pnl = (sl - entry) / entry
                trades.append({"side": "LONG", "result": "SL", "pnl_pct": pnl, "bars": i - entry_i, "i": i})
                in_long = False
        elif in_short:
            if price <= tp:
                pnl = (entry - tp) / entry
                trades.append({"side": "SHORT", "result": "TP", "pnl_pct": pnl, "bars": i - entry_i, "i": i})
                in_short = False
            elif price >= sl:
                pnl = (entry - sl) / entry
                trades.append({"side": "SHORT", "result": "SL", "pnl_pct": pnl, "bars": i - entry_i, "i": i})
                in_short = False

        # Check entry (use n-2 pattern like live engine)
        if not in_long and not in_short:
            try:
                go_long  = sig_long(p, i)  if sig_long  else False
                go_short = sig_short(p, i) if sig_short else False
            except Exception:
                go_long = go_short = False

            if go_long:
                entry    = price
                sl       = entry * (1 - sl_pct)
                tp       = entry * (1 + tp_pct)
                in_long  = True
                entry_i  = i
            elif go_short:
                entry    = price
                sl       = entry * (1 + sl_pct)
                tp       = entry * (1 - tp_pct)
                in_short = True
                entry_i  = i

    return trades

def metrics(trades, n_candles, tf_name):
    if not trades:
        return {"trades": 0, "wr": 0, "pnl_pct": 0, "avg_bars": 0, "max_dd_pct": 0, "trades_per_day": 0}
    wins   = [t for t in trades if t["result"] == "TP"]
    losses = [t for t in trades if t["result"] == "SL"]
    total  = len(trades)
    wr     = len(wins) / total * 100

    # cumulative PnL %
    eq = 1.0
    peak = 1.0; max_dd = 0.0
    for t in trades:
        eq *= (1 + t["pnl_pct"])
        if eq > peak: peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd: max_dd = dd

    pnl_pct = (eq - 1) * 100

    bars_per_day = {"5m": 288, "15m": 96, "1h": 24}.get(tf_name, 96)
    candles_covered = n_candles
    days = candles_covered / bars_per_day
    trades_per_day = total / days if days > 0 else 0

    avg_bars = sum(t["bars"] for t in trades) / total

    return {
        "trades":         total,
        "wins":           len(wins),
        "losses":         len(losses),
        "wr":             round(wr, 1),
        "pnl_pct":        round(pnl_pct, 2),
        "avg_bars":       round(avg_bars, 1),
        "max_dd_pct":     round(max_dd, 2),
        "trades_per_day": round(trades_per_day, 2),
    }

# ── MAIN BACKTEST ─────────────────────────────────────────────────────────────

STRATEGIES = {
    "Surgeon v2 (15m)": {
        "long": _surgeon2_long, "short": _surgeon2_short,
        "sl": 0.005, "tp": 0.010, "tf": "15m",
    },
    "Regime Lord (1h)": {
        "long": _regime_long, "short": _regime_short,
        "sl": 0.008, "tp": 0.024, "tf": "1h",
    },
    "Squeeze (15m)": {
        "long": _squeeze_long, "short": _squeeze_short,
        "sl": 0.008, "tp": 0.016, "tf": "15m",
    },
    "Structure BOS (1h)": {
        "long": _structure_long, "short": _structure_short,
        "sl": 0.012, "tp": 0.036, "tf": "1h",
    },
    "EMA Rider (1h)": {
        "long": _ema_rider_long, "short": _ema_rider_short,
        "sl": 0.010, "tp": 0.030, "tf": "1h",
    },
}

def run_full_backtest():
    print("=" * 70)
    print("  COMPETITION 7 — DEEP STRATEGY BACKTEST")
    print(f"  {len(PAIRS)} pairs × {len(STRATEGIES)} strategies")
    print(f"  {N_CANDLES} candles per pair/timeframe")
    print("=" * 70)

    # Fetch data
    print("\n[1/3] Fetching candle data from Binance...\n")
    data = {}
    tfs_needed = list(set(s["tf"] for s in STRATEGIES.values()))
    for pair in PAIRS:
        data[pair] = {}
        for tf in tfs_needed:
            raw = fetch(pair, tf, N_CANDLES)
            if raw:
                data[pair][tf] = build_p(raw)
                print(f"  OK {pair} {tf} -- {raw['n']} candles")
            else:
                print(f"  FAIL {pair} {tf}")
            time.sleep(0.3)

    # Run strategies
    print("\n[2/3] Running strategy simulations...\n")
    results = {}
    for strat_name, cfg in STRATEGIES.items():
        results[strat_name] = {"pairs": {}, "aggregate": None}
        all_trades = []
        total_candles = 0
        print(f"  ── {strat_name} ──")
        for pair in PAIRS:
            p = data.get(pair, {}).get(cfg["tf"])
            if not p:
                continue
            trades = simulate(p, cfg["long"], cfg["short"], cfg["sl"], cfg["tp"], strat_name)
            m = metrics(trades, p["n"], cfg["tf"])
            results[strat_name]["pairs"][pair] = m
            all_trades.extend(trades)
            total_candles += p["n"]
            print(f"    {pair:12s}: {m['trades']:3d} trades | WR {m['wr']:5.1f}% | PnL {m['pnl_pct']:+7.2f}% | MaxDD {m['max_dd_pct']:5.2f}%")
        # Aggregate
        agg = metrics(all_trades, total_candles, cfg["tf"])
        results[strat_name]["aggregate"] = agg
        print(f"    {'AGGREGATE':12s}: {agg['trades']:3d} trades | WR {agg['wr']:5.1f}% | PnL {agg['pnl_pct']:+7.2f}% | MaxDD {agg['max_dd_pct']:5.2f}% | {agg['trades_per_day']:.2f}/day")
        print()

    # Summary
    print("\n[3/3] SUMMARY — Sorted by aggregate PnL%\n")
    print(f"  {'Strategy':<28} {'Trades':>7} {'WR%':>7} {'PnL%':>8} {'MaxDD%':>8} {'T/day':>7}")
    print("  " + "-" * 65)
    ranked = sorted(results.items(), key=lambda x: -x[1]["aggregate"]["pnl_pct"])
    for name, r in ranked:
        a = r["aggregate"]
        print(f"  {name:<28} {a['trades']:>7} {a['wr']:>7.1f} {a['pnl_pct']:>+8.2f} {a['max_dd_pct']:>8.2f} {a['trades_per_day']:>7.2f}")

    # Save results
    out_path = os.path.join(os.path.dirname(__file__), "backtest_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved to {out_path}")
    print("=" * 70)
    return results

if __name__ == "__main__":
    run_full_backtest()
