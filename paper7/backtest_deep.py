"""
Deep historical backtest — 4-5 years of data.
Yearly + monthly breakdown for all 5 Competition 7 agents.
Caches fetched data to disk to avoid re-downloading.
"""
import sys, os, time, requests, json, math
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fast_backtest import precompute
from paper7.smart_agents import (
    _surgeon2_long, _surgeon2_short,
    _regime_long, _regime_short,
    _squeeze_long, _squeeze_short,
    _structure_long, _structure_short,
    _ema_rider_long, _ema_rider_short,
    SMART_AGENTS,
)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

PAIRS_DEEP = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]

STRATEGIES = {
    "The Structure":   {"l": _structure_long,  "s": _structure_short,  "tf": "1h"},
    "The EMA Rider":   {"l": _ema_rider_long,  "s": _ema_rider_short,  "tf": "1h"},
    "The Regime Lord": {"l": _regime_long,     "s": _regime_short,     "tf": "1h"},
    "The Surgeon v2":  {"l": _surgeon2_long,   "s": _surgeon2_short,   "tf": "15m"},
    "The Squeeze":     {"l": _squeeze_long,    "s": _squeeze_short,    "tf": "5m"},
}

N_CANDLES = {
    "1h":  5 * 366 * 24,       # ~5 years
    "15m": 4 * 366 * 96,       # ~4 years
    "5m":  3 * 366 * 288,      # ~3 years
}

# ── CACHED FETCH ──────────────────────────────────────────────────────────────

def fetch_cached(pair, tf):
    n = N_CANDLES[tf]
    cache_file = os.path.join(CACHE_DIR, f"{pair}_{tf}_{n}.json")
    if os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < 3600 * 6:
            with open(cache_file) as f:
                data = json.load(f)
            print(f"  [cache] {pair} {tf} — {data['n']} candles")
            return data

    print(f"  [fetch] {pair} {tf} — need {n} candles ({math.ceil(n/1000)} API calls)...")
    all_c = []
    end = None
    for batch_i in range(math.ceil(n / 1000)):
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit=1000"
        if end:
            url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            if (batch_i + 1) % 10 == 0:
                oldest = datetime.fromtimestamp(int(batch[0][0]) / 1000, tz=timezone.utc)
                print(f"    batch {batch_i+1:3d}/{math.ceil(n/1000)} — oldest candle: {oldest.strftime('%Y-%m-%d')}")
            time.sleep(0.22)
        except Exception as e:
            print(f"    error: {e}")
            time.sleep(2)

    raw = all_c[-n:]
    if not raw:
        return None

    data = {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
        "vol":   [float(c[5]) for c in raw],
        "ts":    [int(c[0])   for c in raw],
        "n":     len(raw),
    }
    with open(cache_file, "w") as f:
        json.dump(data, f)
    print(f"    saved {data['n']} candles")
    return data

def _calc_swing(raw, lookback=10):
    n = len(raw["close"])
    s_hi = [0.0] * n
    s_lo = [0.0] * n
    for i in range(lookback, n):
        s_hi[i] = max(raw["high"][i - lookback:i])
        s_lo[i] = min(raw["low"][i  - lookback:i])
    return s_hi, s_lo

def _calc_vwap(raw):
    n = len(raw["close"])
    result, cum_tp, cum_v, prev_day = [0.0] * n, 0.0, 0.0, -1
    for i in range(n):
        day = raw["ts"][i] // 86400000
        if day != prev_day:
            cum_tp = cum_v = 0.0
            prev_day = day
        tp = (raw["high"][i] + raw["low"][i] + raw["close"][i]) / 3
        cum_tp += tp * raw["vol"][i]
        cum_v  += raw["vol"][i]
        result[i] = cum_tp / cum_v if cum_v > 0 else tp
    return result

def build_p(raw):
    p = precompute(raw)
    p["raw"] = raw
    p["n"]   = raw["n"]
    p["ts"]  = raw["ts"]
    p["vwap"]         = _calc_vwap(raw)
    p["s_hi"], p["s_lo"] = _calc_swing(raw)
    return p

# ── SIMULATION WITH TIMESTAMPS ────────────────────────────────────────────────

def simulate_ts(p, sig_long, sig_short, sl_pct, tp_pct):
    n   = p["n"]
    ts  = p["ts"]
    trades = []
    in_long = in_short = False
    entry = sl = tp = entry_ts = 0

    for i in range(60, n - 1):
        price = p["c"][i]
        cur_ts = ts[i]

        if in_long:
            if price >= tp:
                close_ts = ts[i]
                pnl = (tp - entry) / entry
                trades.append({"side": "LONG", "result": "TP", "pnl_pct": pnl, "ts": close_ts})
                in_long = False
            elif price <= sl:
                close_ts = ts[i]
                pnl = (sl - entry) / entry
                trades.append({"side": "LONG", "result": "SL", "pnl_pct": pnl, "ts": close_ts})
                in_long = False
        elif in_short:
            if price <= tp:
                close_ts = ts[i]
                pnl = (entry - tp) / entry
                trades.append({"side": "SHORT", "result": "TP", "pnl_pct": pnl, "ts": close_ts})
                in_short = False
            elif price >= sl:
                close_ts = ts[i]
                pnl = (entry - sl) / entry
                trades.append({"side": "SHORT", "result": "SL", "pnl_pct": pnl, "ts": close_ts})
                in_short = False

        if not in_long and not in_short:
            try:
                go_long  = sig_long(p, i)  if sig_long  else False
                go_short = sig_short(p, i) if sig_short else False
            except Exception:
                go_long = go_short = False

            if go_long:
                entry   = price
                sl      = entry * (1 - sl_pct)
                tp      = entry * (1 + tp_pct)
                in_long = True
                entry_ts = cur_ts
            elif go_short:
                entry    = price
                sl       = entry * (1 + sl_pct)
                tp       = entry * (1 - tp_pct)
                in_short = True
                entry_ts = cur_ts

    return trades

# ── AGGREGATION ───────────────────────────────────────────────────────────────

def aggregate(trades):
    if not trades:
        return {"trades": 0, "wins": 0, "losses": 0, "wr": 0.0,
                "pnl_pct": 0.0, "max_dd_pct": 0.0, "ev": 0.0}
    wins   = [t for t in trades if t["result"] == "TP"]
    losses = [t for t in trades if t["result"] == "SL"]
    total  = len(trades)
    wr     = len(wins) / total * 100

    eq = 1.0; peak = 1.0; max_dd = 0.0
    for t in trades:
        eq *= (1 + t["pnl_pct"])
        if eq > peak: peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd: max_dd = dd

    avg_w = sum(t["pnl_pct"] for t in wins)   / len(wins)   if wins   else 0
    avg_l = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    ev    = wr / 100 * avg_w + (1 - wr / 100) * avg_l

    return {
        "trades":     total,
        "wins":       len(wins),
        "losses":     len(losses),
        "wr":         round(wr, 1),
        "pnl_pct":    round((eq - 1) * 100, 2),
        "max_dd_pct": round(max_dd, 2),
        "ev":         round(ev * 100, 3),
    }

def split_by_year(trades):
    by_year = defaultdict(list)
    for t in trades:
        yr = datetime.fromtimestamp(t["ts"] / 1000, tz=timezone.utc).year
        by_year[yr].append(t)
    return dict(by_year)

def split_by_month(trades):
    by_month = defaultdict(list)
    for t in trades:
        mo = datetime.fromtimestamp(t["ts"] / 1000, tz=timezone.utc).month
        by_month[mo].append(t)
    return dict(by_month)

MONTH_NAMES = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
               7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}

# ── MAIN ──────────────────────────────────────────────────────────────────────

def run():
    print("=" * 70)
    print("  COMPETITION 7 — DEEP HISTORICAL BACKTEST")
    print("  1h agents: ~5 years  |  15m agent: ~4 years  |  5m agent: ~3 years")
    print(f"  Pairs: {', '.join(PAIRS_DEEP)}")
    print("=" * 70)

    print("\n[PHASE 1] Fetching / loading cached data...\n")
    tfs_needed = set(cfg["tf"] for cfg in STRATEGIES.values())
    data = {}
    for pair in PAIRS_DEEP:
        data[pair] = {}
        for tf in tfs_needed:
            raw = fetch_cached(pair, tf)
            if raw:
                data[pair][tf] = build_p(raw)
            time.sleep(0.1)

    print("\n[PHASE 2] Running strategies...\n")

    all_results = {}
    for sname, cfg in STRATEGIES.items():
        agent_cfg = SMART_AGENTS[sname]
        sl = agent_cfg["sl"]; tp = agent_cfg["tp"]; tf = cfg["tf"]
        all_trades = []

        for pair in PAIRS_DEEP:
            p = data.get(pair, {}).get(tf)
            if not p:
                continue
            trades = simulate_ts(p, cfg["l"], cfg["s"], sl, tp)
            all_trades.extend(trades)

        by_year  = split_by_year(all_trades)
        by_month = split_by_month(all_trades)

        all_results[sname] = {
            "sl": sl, "tp": tp, "tf": tf,
            "overall":  aggregate(all_trades),
            "by_year":  {yr: aggregate(t) for yr, t in sorted(by_year.items())},
            "by_month": {mo: aggregate(t) for mo, t in sorted(by_month.items())},
            "total_trades": len(all_trades),
        }
        print(f"  {sname}: {len(all_trades)} total trades across {len(PAIRS_DEEP)} pairs")

    print("\n[PHASE 3] Results\n")

    for sname, r in all_results.items():
        ov = r["overall"]
        print(f"\n{'='*68}")
        print(f"  {sname}  [{r['tf']}  SL={r['sl']*100:.1f}%  TP={r['tp']*100:.1f}%]")
        print(f"  Overall: {ov['trades']} trades | WR {ov['wr']}% | PnL {ov['pnl_pct']:+.2f}% | MaxDD {ov['max_dd_pct']:.2f}%")
        print(f"{'='*68}")

        print(f"\n  -- BY YEAR --")
        print(f"  {'Year':<6} {'Trades':>7} {'WR%':>7} {'PnL%':>9} {'MaxDD%':>8} {'EV/tr':>8}")
        print(f"  {'-'*47}")
        for yr, m in sorted(r["by_year"].items()):
            print(f"  {yr:<6} {m['trades']:>7} {m['wr']:>7.1f} {m['pnl_pct']:>+9.2f} {m['max_dd_pct']:>8.2f} {m['ev']:>+8.3f}%")

        print(f"\n  -- BY MONTH (all years combined) --")
        print(f"  {'Month':<6} {'Trades':>7} {'WR%':>7} {'PnL%':>9} {'MaxDD%':>8}")
        print(f"  {'-'*40}")
        for mo in range(1, 13):
            m = r["by_month"].get(mo)
            if not m or m["trades"] == 0:
                print(f"  {MONTH_NAMES[mo]:<6} {'—':>7}")
                continue
            print(f"  {MONTH_NAMES[mo]:<6} {m['trades']:>7} {m['wr']:>7.1f} {m['pnl_pct']:>+9.2f} {m['max_dd_pct']:>8.2f}")

    # Save results
    out_path = os.path.join(os.path.dirname(__file__), "deep_results.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n\nResults saved to {out_path}")
    print("=" * 70)
    return all_results

if __name__ == "__main__":
    run()
