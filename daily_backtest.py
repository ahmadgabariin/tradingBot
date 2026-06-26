"""
DAILY STRATEGY BACKTEST
Goal: 1-5 trades per day, high win rate, long history.

Tests strategies designed for frequent but high-quality signals:
- Uses 15m and 1h timeframes (enough signals, not too noisy)
- Goes back as far as possible (up to 2.3 years on 1h)
- Filters for strategies that give 1-5 signals per day
- Tests multiple R/R ratios to find profitable combinations

Key metric: trades_per_day must be 1-5, WR must beat breakeven for chosen SL/TP.
"""
import requests, time, json, math
from datetime import datetime
from fast_backtest import precompute, STRATS

OUT  = "daily_results.txt"
OUTJ = "daily_results.json"

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

TF_CONFIG = {
    "15m": 20000,   # ~208 days
    "1h":  20000,   # ~833 days (2.3 years)
}

# R/R combos where breakeven WR is achievable (under 65%)
# breakeven = SL / (SL + TP)
SL_TP_DAILY = [
    # Tight — needs ~50% WR to profit
    (0.010, 0.020),  # breakeven 33%
    (0.015, 0.030),  # breakeven 33%
    (0.008, 0.016),  # breakeven 33%
    # Moderate — needs ~50-55% WR
    (0.010, 0.015),  # breakeven 40%
    (0.015, 0.020),  # breakeven 43%
    (0.020, 0.030),  # breakeven 40%
    # Inverted but mild — needs 55-60% WR
    (0.020, 0.015),  # breakeven 57%
    (0.025, 0.020),  # breakeven 56%
    (0.030, 0.020),  # breakeven 60%
    # Standard 1:1
    (0.015, 0.015),  # breakeven 50%
    (0.020, 0.020),  # breakeven 50%
    (0.010, 0.010),  # breakeven 50%
]

def wlog(msg=""):
    with open(OUT, "a", encoding="utf-8") as f: f.write(msg + "\n")
    try: print(msg)
    except UnicodeEncodeError: print(msg.encode("ascii", "replace").decode())

def fetch_max(pair, tf, n):
    all_c = []; end = None
    for page in range(math.ceil(n / 1000)):
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit=1000"
        if end: url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=20); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            time.sleep(0.15)
        except Exception as e:
            print(f"  fetch error {pair} {tf}: {e}"); break
    raw = all_c[-n:]
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
        "vol":   [float(c[5]) for c in raw],
    }

def backtest_realistic(p, signal_fn, sl, tp, max_hold=200):
    """
    Realistic backtest:
    - Non-overlapping (wait for trade to close before next entry)
    - max_hold=200 candles (long enough to see real outcome)
    - Trades not resolved = counted as open (not dropped)
    """
    wins = losses = open_trades = 0
    n = p["n"]
    i = 60
    while i < n - 1:
        if not signal_fn(p, i):
            i += 1; continue
        ep   = p["c"][i]
        sl_p = ep * (1 - sl)
        tp_p = ep * (1 + tp)
        result = None
        j = i + 1
        limit = min(i + max_hold + 1, n)
        while j < limit:
            if p["l"][j] <= sl_p: result = "LOSS"; break
            if p["h"][j] >= tp_p: result = "WIN";  break
            j += 1
        if result == "WIN":   wins += 1;        i = j + 1
        elif result == "LOSS": losses += 1;     i = j + 1
        else:                  open_trades += 1; i = j + 1
    return wins, losses, open_trades

def candles_per_day(tf):
    return {"5m": 288, "15m": 96, "1h": 24, "4h": 6, "1d": 1}[tf]

def main():
    t0 = datetime.now()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"DAILY STRATEGY BACKTEST - {t0.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*80}\n\n")
        f.write("Goal: 1-5 trades/day, high win rate, max history\n")
        f.write("Logic: non-overlapping, max_hold=200 candles\n\n")

    wlog("Fetching data (max history)...")
    data = {}
    candle_days = {}
    for tf, n in TF_CONFIG.items():
        data[tf] = {}
        cpd = candles_per_day(tf)
        for pair in PAIRS:
            raw = fetch_max(pair, tf, n)
            p = precompute(raw)
            data[tf][pair] = p
            days = len(raw["close"]) / cpd
            candle_days[(tf, pair)] = days
            wlog(f"  {pair} {tf}: {len(raw['close'])} candles (~{days:.0f} days)")

    wlog("\nRunning backtests...\n")

    all_results = []

    for tf in TF_CONFIG:
        cpd = candles_per_day(tf)
        wlog(f"\n{'='*80}")
        wlog(f"TIMEFRAME: {tf}  ({cpd} candles/day)")
        wlog(f"{'='*80}")

        tf_results = []
        for sname, sfn in STRATS.items():
            for sl, tp in SL_TP_DAILY:
                wins = losses = opens = 0
                for pair in PAIRS:
                    w, l, o = backtest_realistic(data[tf][pair], sfn, sl, tp)
                    wins += w; losses += l; opens += o

                total = wins + losses
                if total < 10: continue

                wr = wins / total
                ev = wr * tp - (1 - wr) * sl
                breakeven = sl / (sl + tp)
                days = sum(candle_days[(tf, p)] for p in PAIRS) / 3  # avg days
                trades_per_day = total / days

                r = {
                    "tf": tf, "strat": sname, "sl": sl, "tp": tp,
                    "wins": wins, "losses": losses, "opens": opens,
                    "total": total, "wr": wr, "ev": ev,
                    "breakeven": breakeven, "trades_per_day": trades_per_day,
                    "days": days, "profitable": ev > 0,
                }
                tf_results.append(r)
                all_results.append(r)

        # Show top results: profitable + 1-5 trades/day
        profitable_daily = [r for r in tf_results
                           if r["profitable"] and 0.5 <= r["trades_per_day"] <= 7]
        profitable_daily.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)

        wlog(f"\n  PROFITABLE strategies with 1-7 trades/day:")
        wlog(f"  {'Strategy':<26} {'SL':>4} {'TP':>4} | {'N':>5} {'WR%':>6} {'EV%':>7} {'T/day':>6} {'Days':>5}")
        wlog(f"  {'-'*75}")
        shown = set()
        for r in profitable_daily[:20]:
            key = (r["strat"], r["sl"], r["tp"])
            if key in shown: continue
            shown.add(key)
            wlog(f"  {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
                 f"{r['total']:>5} {r['wr']*100:>5.1f}% {r['ev']*100:>+6.3f}% "
                 f"{r['trades_per_day']:>5.1f}/d {r['days']:>5.0f}d")

        if not profitable_daily:
            wlog("  [none — showing best EV regardless of trades/day]")
            best_ev = sorted(tf_results, key=lambda x: x["ev"], reverse=True)[:5]
            for r in best_ev:
                wlog(f"  {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
                     f"{r['total']:>5} {r['wr']*100:>5.1f}% {r['ev']*100:>+6.3f}% "
                     f"{r['trades_per_day']:>5.1f}/d {r['days']:>5.0f}d")

        with open(OUTJ, "w") as f:
            json.dump(all_results, f, indent=2)

    # ── GLOBAL RANKINGS ──────────────────────────────────────────────────────────
    wlog(f"\n\n{'='*80}")
    wlog("GLOBAL TOP 30 — PROFITABLE + DAILY FREQUENCY")
    wlog(f"{'='*80}")
    wlog("(profitable = positive EV per trade, frequency = 0.5-7 trades/day across 3 pairs)")
    wlog(f"\n  {'TF':<5} {'Strategy':<26} {'SL':>4} {'TP':>4} | {'N':>5} {'WR%':>6} {'EV%':>7} {'T/day':>6} {'Days':>5}")
    wlog(f"  {'-'*80}")

    candidates = [r for r in all_results if r["profitable"] and 0.5 <= r["trades_per_day"] <= 7]
    candidates.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)

    shown = set()
    count = 0
    for r in candidates:
        key = (r["tf"], r["strat"])
        if key in shown: continue
        shown.add(key)
        wlog(f"  {r['tf']:<5} {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
             f"{r['total']:>5} {r['wr']*100:>5.1f}% {r['ev']*100:>+6.3f}% "
             f"{r['trades_per_day']:>5.1f}/d {r['days']:>5.0f}d")
        count += 1
        if count >= 30: break

    if not candidates:
        wlog("\n  No profitable daily strategies found.")
        wlog("  Best by EV (ignoring frequency):")
        best = sorted(all_results, key=lambda x: x["ev"], reverse=True)[:10]
        shown2 = set()
        for r in best:
            key = (r["tf"], r["strat"])
            if key in shown2: continue
            shown2.add(key)
            wlog(f"  {r['tf']:<5} {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
                 f"{r['total']:>5} {r['wr']*100:>5.1f}% {r['ev']*100:>+6.3f}% "
                 f"{r['trades_per_day']:>5.1f}/d {r['days']:>5.0f}d")

    # ── CHAMPION ─────────────────────────────────────────────────────────────────
    if candidates:
        champ = candidates[0]
        wlog(f"\n{'*'*80}")
        wlog(f"  BEST DAILY STRATEGY")
        wlog(f"{'*'*80}")
        wlog(f"  Strategy:        {champ['strat']}")
        wlog(f"  Timeframe:       {champ['tf']}")
        wlog(f"  SL / TP:         {champ['sl']*100:.1f}% / {champ['tp']*100:.1f}%")
        wlog(f"  Win Rate:        {champ['wr']*100:.1f}%  (breakeven: {champ['breakeven']*100:.1f}%)")
        wlog(f"  EV per trade:    {champ['ev']*100:+.3f}%")
        wlog(f"  Trades per day:  {champ['trades_per_day']:.1f}  (across {len(PAIRS)} pairs)")
        wlog(f"  Backtest trades: {champ['total']} over {champ['days']:.0f} days")
        wlog(f"  Expected daily:  {champ['ev'] * champ['trades_per_day'] * 100:+.3f}% per day on position")

    elapsed = int((datetime.now() - t0).total_seconds())
    wlog(f"\nDone in {elapsed}s | {len(all_results)} results | Saved to daily_results.json")

if __name__ == "__main__":
    main()
