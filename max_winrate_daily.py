"""
MAX WIN RATE DAILY SEARCH
Exhaustive search: every strategy x every R/R combo x every timeframe
Goal: highest REAL win rate with 1-7 trades/day and positive EV

Timeframes: 15m (208d), 1h (833d), 4h (2500d)
Strategies: all 33 from fast_backtest
R/R: 40+ combos from ultra-tight to inverted
Backtest: non-overlapping, max_hold=300 candles, no dropped trades
"""
import requests, time, json, math
from datetime import datetime
from fast_backtest import precompute, STRATS

OUT  = "max_winrate_daily.txt"
OUTJ = "max_winrate_daily.json"
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

TF_CONFIG = {
    "15m": 20000,   # ~208 days
    "1h":  20000,   # ~833 days (2.3 years)
    "4h":  15000,   # ~2500 days (6.8 years)
}

# Exhaustive R/R grid
# Format: (SL%, TP%)  breakeven = SL/(SL+TP)
SL_TP_GRID = [
    # 2:1 R/R — breakeven 33%
    (0.010, 0.020), (0.015, 0.030), (0.020, 0.040),
    (0.008, 0.016), (0.012, 0.024),

    # 1.5:1 R/R — breakeven 40%
    (0.010, 0.015), (0.015, 0.022), (0.020, 0.030),
    (0.008, 0.012), (0.025, 0.037),

    # 1:1 R/R — breakeven 50%
    (0.005, 0.005), (0.008, 0.008), (0.010, 0.010),
    (0.012, 0.012), (0.015, 0.015), (0.020, 0.020),
    (0.025, 0.025), (0.030, 0.030),

    # Slightly inverted 1:1.2 — breakeven ~55%
    (0.012, 0.010), (0.015, 0.012), (0.018, 0.015),
    (0.020, 0.016), (0.025, 0.020), (0.030, 0.025),

    # Inverted 1.5:1 — breakeven ~60%
    (0.015, 0.010), (0.018, 0.012), (0.020, 0.013),
    (0.022, 0.015), (0.025, 0.016), (0.030, 0.020),
    (0.035, 0.023), (0.040, 0.026),

    # Inverted 2:1 — breakeven 66.7%
    (0.020, 0.010), (0.030, 0.015), (0.040, 0.020),
    (0.050, 0.025), (0.025, 0.012), (0.035, 0.017),

    # Inverted 3:1 — breakeven 75%
    (0.030, 0.010), (0.045, 0.015), (0.060, 0.020),

    # Ultra-tight TP — very high WR possible
    (0.020, 0.005), (0.030, 0.008), (0.040, 0.010),
    (0.050, 0.012), (0.025, 0.006), (0.015, 0.004),
]

CPD = {"5m": 288, "15m": 96, "1h": 24, "4h": 6, "1d": 1}

def wlog(msg=""):
    with open(OUT, "a", encoding="utf-8") as f: f.write(msg + "\n")
    try: print(msg)
    except UnicodeEncodeError: print(msg.encode("ascii","replace").decode())

def fetch_max(pair, tf, n):
    all_c = []; end = None
    for _ in range(math.ceil(n / 1000)):
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit=1000"
        if end: url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=20); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            time.sleep(0.12)
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

def backtest_real(p, signal_fn, sl, tp, max_hold=300):
    """
    Fully realistic: non-overlapping, no dropped trades.
    max_hold=300 gives enough time to resolve without inflating WR.
    Unresolved trades after 300 candles are counted as losses (worst case).
    """
    wins = losses = 0
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
        if result == "WIN":   wins += 1;   i = j + 1
        elif result == "LOSS": losses += 1; i = j + 1
        else:
            # Still open after max_hold — count as loss (conservative)
            losses += 1; i = j + 1
    return wins, losses

def main():
    t0 = datetime.now()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"MAX WIN RATE DAILY SEARCH - {t0.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Strategies: {len(STRATS)} | TFs: {list(TF_CONFIG)} | R/R combos: {len(SL_TP_GRID)}\n")
        f.write(f"Total combinations: {len(STRATS)*len(TF_CONFIG)*len(SL_TP_GRID)*len(PAIRS)}\n")
        f.write(f"Backtest: non-overlapping, max_hold=300, unresolved=LOSS (conservative)\n{'='*80}\n\n")

    wlog(f"Strategies: {len(STRATS)} | TFs: {list(TF_CONFIG)} | R/R: {len(SL_TP_GRID)} combos")
    wlog(f"Fetching max historical data...\n")

    data = {}
    days_map = {}
    for tf, n in TF_CONFIG.items():
        data[tf] = {}
        cpd = CPD[tf]
        for pair in PAIRS:
            raw = fetch_max(pair, tf, n)
            data[tf][pair] = precompute(raw)
            days = len(raw["close"]) / cpd
            days_map[(tf, pair)] = days
            wlog(f"  {pair} {tf}: {len(raw['close'])} candles (~{days:.0f} days)")
        wlog("")

    wlog("Running exhaustive backtest...\n")

    all_results = []
    total_combos = len(STRATS) * len(TF_CONFIG) * len(SL_TP_GRID)
    done = 0

    for tf in TF_CONFIG:
        cpd = CPD[tf]
        avg_days = sum(days_map[(tf, p)] for p in PAIRS) / 3

        for sname, sfn in STRATS.items():
            for sl, tp in SL_TP_GRID:
                wins = losses = 0
                pair_stats = {}
                for pair in PAIRS:
                    w, l = backtest_real(data[tf][pair], sfn, sl, tp)
                    wins += w; losses += l
                    pair_stats[pair] = {"w": w, "l": l,
                        "wr": w/(w+l)*100 if (w+l)>0 else 0}

                done += 1
                total = wins + losses
                if total < 15: continue  # too few trades

                wr = wins / total
                ev = wr * tp - (1 - wr) * sl
                breakeven = sl / (sl + tp)
                trades_per_day = total / avg_days

                # Only keep if: profitable + 0.3-10 trades/day
                if ev <= 0: continue
                if not (0.3 <= trades_per_day <= 10): continue

                all_results.append({
                    "tf": tf, "strat": sname, "sl": sl, "tp": tp,
                    "wins": wins, "losses": losses, "total": total,
                    "wr": round(wr, 5), "ev": round(ev, 6),
                    "breakeven": round(breakeven, 4),
                    "trades_per_day": round(trades_per_day, 2),
                    "days": round(avg_days, 0),
                    "pair_stats": pair_stats,
                })

            if done % (len(SL_TP_GRID) * 5) == 0:
                pct = done / total_combos * 100
                print(f"  {pct:.0f}% done ({done}/{total_combos})...", flush=True)

    wlog(f"\nFound {len(all_results)} profitable daily-frequency results.")

    # ── SORT BY WIN RATE ──────────────────────────────────────────────────────
    all_results.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)

    with open(OUTJ, "w") as f:
        json.dump(all_results, f, indent=2)

    # ── TOP 50 BY WIN RATE ────────────────────────────────────────────────────
    wlog(f"\n{'='*100}")
    wlog(f"TOP 50 BY WIN RATE  (profitable, 0.3-10 trades/day, non-overlapping, unresolved=LOSS)")
    wlog(f"{'='*100}")
    wlog(f"  {'#':<3} {'TF':<5} {'Strategy':<26} {'SL':>5} {'TP':>5} | "
         f"{'N':>5} {'WR%':>6} {'EV%':>7} {'T/day':>6} {'Days':>5} {'BE%':>6}")
    wlog(f"  {'-'*95}")

    shown = set()
    count = 0
    for r in all_results:
        key = (r["tf"], r["strat"])
        if key in shown: continue
        shown.add(key)
        count += 1
        wlog(f"  {count:<3} {r['tf']:<5} {r['strat']:<26} {r['sl']*100:>5.1f} {r['tp']*100:>5.1f} | "
             f"{r['total']:>5} {r['wr']*100:>5.1f}% {r['ev']*100:>+6.3f}% "
             f"{r['trades_per_day']:>5.1f}/d {r['days']:>5.0f}d {r['breakeven']*100:>5.1f}%")
        if count >= 50: break

    # ── TOP 10 WITH PER-PAIR BREAKDOWN ────────────────────────────────────────
    wlog(f"\n{'='*100}")
    wlog(f"TOP 10 DETAILED  (per-pair win rate breakdown)")
    wlog(f"{'='*100}")
    shown2 = set()
    count2 = 0
    for r in all_results:
        key = (r["tf"], r["strat"])
        if key in shown2: continue
        shown2.add(key)
        count2 += 1
        wlog(f"\n  #{count2}  {r['strat']} [{r['tf']}]  SL={r['sl']*100:.1f}%  TP={r['tp']*100:.1f}%")
        wlog(f"      WR={r['wr']*100:.1f}%  EV={r['ev']*100:+.3f}%/trade  "
             f"Breakeven={r['breakeven']*100:.1f}%  Trades={r['total']}  "
             f"{r['trades_per_day']:.1f}/day  {r['days']:.0f}d history")
        for pair, ps in r["pair_stats"].items():
            wlog(f"      {pair}: {ps['w']}W / {ps['l']}L = {ps['wr']:.1f}% WR")
        if count2 >= 10: break

    # ── BY TIMEFRAME CHAMPIONS ────────────────────────────────────────────────
    wlog(f"\n{'='*100}")
    wlog(f"CHAMPION PER TIMEFRAME")
    wlog(f"{'='*100}")
    for tf in TF_CONFIG:
        tf_res = [r for r in all_results if r["tf"] == tf]
        if not tf_res:
            wlog(f"\n  [{tf}] No profitable results"); continue
        seen_s = set(); top = []
        for r in tf_res:
            if r["strat"] not in seen_s:
                seen_s.add(r["strat"]); top.append(r)
            if len(top) >= 3: break
        wlog(f"\n  [{tf}]  Top 3:")
        for i, r in enumerate(top):
            wlog(f"    #{i+1} {r['strat']:<26}  WR={r['wr']*100:.1f}%  "
                 f"EV={r['ev']*100:+.3f}%  SL={r['sl']*100:.1f}%/TP={r['tp']*100:.1f}%  "
                 f"N={r['total']}  {r['trades_per_day']:.1f}/day")

    # ── ABSOLUTE CHAMPION ─────────────────────────────────────────────────────
    if all_results:
        c = all_results[0]
        wlog(f"\n\n{'*'*80}")
        wlog(f"  ABSOLUTE CHAMPION")
        wlog(f"{'*'*80}")
        wlog(f"  Strategy:        {c['strat']}")
        wlog(f"  Timeframe:       {c['tf']}")
        wlog(f"  SL / TP:         {c['sl']*100:.1f}% / {c['tp']*100:.1f}%")
        wlog(f"  Win Rate:        {c['wr']*100:.2f}%  (breakeven {c['breakeven']*100:.1f}%)")
        wlog(f"  EV per trade:    {c['ev']*100:+.4f}%")
        wlog(f"  Total trades:    {c['total']} over {c['days']:.0f} days")
        wlog(f"  Trades per day:  {c['trades_per_day']:.1f}  (across 3 pairs)")
        wlog(f"  History covered: {c['days']:.0f} days")
        for pair, ps in c["pair_stats"].items():
            wlog(f"    {pair}: {ps['w']}W / {ps['l']}L = {ps['wr']:.1f}% WR")

    elapsed = int((datetime.now() - t0).total_seconds())
    wlog(f"\n\nDone in {elapsed}s | {len(all_results)} profitable results | Saved to max_winrate_daily.json")

if __name__ == "__main__":
    main()
