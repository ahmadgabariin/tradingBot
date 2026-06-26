"""
DEEP HISTORICAL BACKTEST — maximum candles possible per timeframe.
Goes as far back as Binance has data.

Candle limits per TF:
  5m:  20000 candles = ~70 days
  15m: 20000 candles = ~208 days
  1h:  20000 candles = ~833 days (~2.3 years)
  4h:  15000 candles = ~2500 days (~6.8 years)
  1d:  5000  candles = ~13 years (all Binance history)
"""
import requests, time, json, math
from datetime import datetime
from fast_backtest import (
    precompute, backtest, STRATS, PAIRS, SL_TP
)

OUT  = "deep_results.txt"
OUTJ = "deep_results.json"

# Max candles per timeframe (Binance goes back to ~2017 for most pairs)
TF_LIMITS = {
    "5m":  20000,   # ~70 days
    "15m": 20000,   # ~208 days
    "1h":  20000,   # ~833 days (2.3 years)
    "4h":  15000,   # ~2500 days (6.8 years)
    "1d":  5000,    # ~13 years (all history)
}

# All SL/TP including inverted (tight TP for max win rate)
ALL_SL_TP = [
    # Normal 2:1 R/R
    (0.003, 0.006), (0.003, 0.009), (0.004, 0.008), (0.004, 0.012),
    (0.005, 0.010), (0.005, 0.015), (0.006, 0.012), (0.006, 0.018),
    (0.007, 0.014), (0.008, 0.016), (0.008, 0.024), (0.010, 0.020),
    (0.010, 0.030), (0.012, 0.024), (0.015, 0.030), (0.003, 0.012),
    # Inverted (wide SL, tight TP) — high win rate combos
    (0.020, 0.010), (0.030, 0.015), (0.025, 0.010), (0.015, 0.008),
    (0.040, 0.020), (0.050, 0.025), (0.020, 0.015), (0.030, 0.020),
]


def wlog(msg):
    with open(OUT, "a", encoding="utf-8") as f: f.write(msg + "\n")
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode())


def fetch_max(pair, tf, n):
    """Fetch up to n candles going as far back as Binance allows."""
    all_c = []
    end = None
    pages = math.ceil(n / 1000)
    for page in range(pages):
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
            time.sleep(0.2)
        except Exception as e:
            print(f"  fetch error {pair} {tf} page {page}: {e}")
            break
    raw = all_c[-n:]
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
        "vol":   [float(c[5]) for c in raw],
    }


def main():
    t0 = datetime.now()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"DEEP HISTORICAL BACKTEST - {t0.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*80}\n\n")

    total_combos = len(STRATS) * len(TF_LIMITS) * len(ALL_SL_TP) * len(PAIRS)
    wlog(f"Strategies: {len(STRATS)} | Timeframes: {len(TF_LIMITS)} | SL/TP: {len(ALL_SL_TP)} | Pairs: {len(PAIRS)}")
    wlog(f"Total combinations: {total_combos}")
    wlog(f"\nFetching maximum historical data...\n")

    # Fetch all data first
    data = {}
    for tf, n in TF_LIMITS.items():
        data[tf] = {}
        for pair in PAIRS:
            raw = fetch_max(pair, tf, n)
            p = precompute(raw)
            data[tf][pair] = p
            candles = len(raw["close"])
            # Estimate date range
            wlog(f"  {pair} {tf}: {candles} candles fetched")
        wlog("")

    wlog("Data ready. Running backtests...\n")

    all_results = []

    for tf in TF_LIMITS:
        tf_results = []
        wlog(f"{'='*70}")
        wlog(f"TIMEFRAME: {tf}")
        wlog(f"{'='*70}\n")

        for sname, sfn in STRATS.items():
            for sl, tp in ALL_SL_TP:
                wins = losses = 0
                all_pnl = []
                pair_res = {}
                for pair in PAIRS:
                    p = data[tf][pair]
                    w, l, tot, wr, ev = backtest(p, sfn, sl, tp)
                    wins += w; losses += l
                    all_pnl.extend([tp]*w + [-sl]*l)
                    pair_res[pair] = {"wins": w, "losses": l,
                                      "wr": w/(w+l) if (w+l) > 0 else 0}
                total = wins + losses
                if total < 5:
                    continue
                wr = wins / total
                ev = sum(all_pnl) / len(all_pnl) if all_pnl else 0
                r = {"tf": tf, "strat": sname, "sl": sl, "tp": tp,
                     "wins": wins, "losses": losses, "total": total,
                     "wr": wr, "ev": ev, "pair": pair_res}
                all_results.append(r)
                tf_results.append(r)

        # Top 15 for this TF
        tf_results.sort(key=lambda x: (x["wr"], x.get("ev", 0)), reverse=True)
        wlog(f"TOP 15 for {tf}:")
        wlog(f"  {'Strategy':<26} {'SL':>4} {'TP':>4} | {'N':>6} {'WR%':>6} {'EV%':>7}")
        wlog(f"  {'-'*65}")
        shown = set()
        count = 0
        for r in tf_results:
            if r["total"] < 10: continue
            key = r["strat"]
            if key in shown: continue
            shown.add(key)
            wlog(f"  {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
                 f"{r['total']:>6} {r['wr']*100:>6.1f}% {r['ev']*100:>+7.3f}%")
            count += 1
            if count >= 15: break
        wlog("")

        # Save progress after each TF
        with open(OUTJ, "w") as f:
            json.dump(all_results, f, indent=2)

    # Global rankings
    all_results.sort(key=lambda x: (x["wr"], x.get("ev", 0)), reverse=True)

    wlog(f"\n{'='*80}")
    wlog(f"GLOBAL TOP 50 - ALL TIMEFRAMES (min 10 trades)")
    wlog(f"{'='*80}\n")
    wlog(f"  {'TF':<5} {'Strategy':<26} {'SL':>4} {'TP':>4} | {'N':>6} {'WR%':>6} {'EV%':>7}")
    wlog(f"  {'-'*72}")
    shown = set()
    count = 0
    for r in all_results:
        if r["total"] < 10: continue
        key = (r["tf"], r["strat"])
        if key in shown: continue
        shown.add(key)
        wlog(f"  {r['tf']:<5} {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
             f"{r['total']:>6} {r['wr']*100:>6.1f}% {r['ev']*100:>+7.3f}%")
        count += 1
        if count >= 50: break

    # Best per TF
    wlog(f"\n{'='*80}")
    wlog(f"BEST STRATEGY PER TIMEFRAME (min 10 trades)")
    wlog(f"{'='*80}\n")
    for tf in TF_LIMITS:
        tf_top = [r for r in all_results if r["tf"] == tf and r["total"] >= 10]
        if not tf_top:
            wlog(f"  [{tf}] No results")
            continue
        b = tf_top[0]
        wlog(f"  [{tf}] {b['strat']} | SL={b['sl']*100:.1f}% TP={b['tp']*100:.1f}% | "
             f"WR={b['wr']*100:.1f}% EV={b['ev']*100:+.3f}% N={b['total']}")
        for pair, v in b["pair"].items():
            wlog(f"    {pair}: {v['wins']}W/{v['losses']}L = {v['wr']*100:.1f}%")
        wlog("")

    # ABSOLUTE CHAMPION
    top = [r for r in all_results if r["total"] >= 10]
    if top:
        champ = top[0]
        wlog(f"\n{'*'*80}")
        wlog(f"  ABSOLUTE CHAMPION")
        wlog(f"{'*'*80}")
        wlog(f"  Strategy:   {champ['strat']}")
        wlog(f"  Timeframe:  {champ['tf']}")
        wlog(f"  SL:         {champ['sl']*100:.1f}%")
        wlog(f"  TP:         {champ['tp']*100:.1f}%")
        wlog(f"  WIN RATE:   {champ['wr']*100:.1f}%")
        wlog(f"  EV/trade:   {champ['ev']*100:+.3f}%")
        wlog(f"  Trades:     {champ['total']} ({champ['wins']}W / {champ['losses']}L)")
        for pair, v in champ["pair"].items():
            wlog(f"    {pair}: {v['wins']}W/{v['losses']}L = {v['wr']*100:.1f}%")

    # Analysis
    wlog(f"\n[ ANALYSIS ]")
    for threshold in [0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50]:
        cnt = len(set((r["tf"], r["strat"]) for r in all_results
                      if r["wr"] >= threshold and r["total"] >= 10))
        wlog(f"  Unique strategy+TF combos with WR >= {threshold*100:.0f}%: {cnt}")

    elapsed = int((datetime.now() - t0).total_seconds())
    wlog(f"\nDone in {elapsed}s | {len(all_results)} total results")
    with open(OUTJ, "w") as f:
        json.dump(all_results, f, indent=2)
    wlog("Saved to deep_results.json")


if __name__ == "__main__":
    main()
