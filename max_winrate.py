"""
MAX WIN RATE HUNT — tests ultra-tight TP combos specifically designed
to maximize win rate (not EV). Uses fast precomputed indicators.
Win rate can hit 65-80% with tight enough TP.
"""
import requests, time, json, math
from datetime import datetime
from fast_backtest import (
    fetch, precompute, backtest, STRATS, PAIRS, TFS,
    s_ema_stack_pullback, s_hybrid, s_combined_best,
    s_macd_bb_combo, s_ema21_touch_macd, s_trend_continuation,
    s_rsi_oversold, s_bb_bounce, s_engulfing, s_hammer,
    s_confluence, s_macd_cross_filtered
)

OUT = "max_winrate_results.txt"

# Ultra-tight TP for maximum win rate
# At 0.1-0.3% TP, win rates can hit 60-80% on 5m/15m
TIGHT_SL_TP = [
    # Ultra-tight: TP very close, should hit quickly
    (0.002, 0.004), (0.002, 0.006), (0.002, 0.008),
    (0.003, 0.006), (0.003, 0.009), (0.003, 0.012),
    (0.004, 0.008), (0.004, 0.012), (0.004, 0.016),
    (0.005, 0.010), (0.005, 0.015), (0.005, 0.020),
    (0.006, 0.012), (0.006, 0.018),
    (0.008, 0.016), (0.008, 0.024),
    (0.010, 0.020), (0.010, 0.030),
    # Inverted (TP < SL): very high win rate but negative EV usually
    (0.005, 0.003), (0.008, 0.005), (0.010, 0.006),
    (0.015, 0.010), (0.020, 0.010), (0.030, 0.015),
]

# Only test best timeframes for speed
TEST_TFS = ["5m", "15m", "1h", "4h", "1d"]

def wlog(msg):
    with open(OUT, "a", encoding="utf-8") as f: f.write(msg+"\n")
    print(msg)

def main():
    t0 = datetime.now()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"MAX WIN RATE HUNT — {t0.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*80}\n\n")
    wlog(f"Tight SL/TP combos: {len(TIGHT_SL_TP)} | TFs: {TEST_TFS} | Strategies: {len(STRATS)}")

    # Fetch & precompute
    wlog("\nFetching data...")
    data = {}
    for tf in TEST_TFS:
        data[tf] = {}
        for pair in PAIRS:
            raw = fetch(pair, tf, 3000)
            data[tf][pair] = precompute(raw)
            time.sleep(0.25)
    wlog("Done. Running backtests...\n")

    all_results = []
    for tf in TEST_TFS:
        tf_results = []
        for sname, sfn in STRATS.items():
            for sl, tp in TIGHT_SL_TP:
                wins = losses = 0
                all_pnl = []
                pair_res = {}
                for pair in PAIRS:
                    p = data[tf][pair]
                    w, l, tot, wr, ev = backtest(p, sfn, sl, tp)
                    wins += w; losses += l
                    all_pnl.extend([tp]*w + [-sl]*l)
                    pair_res[pair] = {"wins": w, "losses": l,
                                      "wr": w/(w+l) if (w+l)>0 else 0}
                total = wins + losses
                if total < 5: continue
                wr = wins/total
                ev = sum(all_pnl)/len(all_pnl) if all_pnl else 0
                r = {"tf": tf, "strat": sname, "sl": sl, "tp": tp,
                     "wins": wins, "losses": losses, "total": total,
                     "wr": wr, "ev": ev, "pair": pair_res}
                all_results.append(r)
                tf_results.append(r)

        # Top 10 for this TF by win rate
        tf_results.sort(key=lambda x: x["wr"], reverse=True)
        wlog(f"\n[{tf}] TOP 10 BY WIN RATE:")
        wlog(f"  {'Strategy':<26} {'SL':>4} {'TP':>4} | {'N':>5} {'WR%':>6} {'EV%':>7}")
        wlog(f"  {'-'*60}")
        shown = set()
        count = 0
        for r in tf_results:
            key = r["strat"]
            if key in shown: continue
            shown.add(key)
            wlog(f"  {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
                 f"{r['total']:>5} {r['wr']*100:>6.1f}% {r['ev']*100:>+7.3f}%")
            count += 1
            if count >= 10: break

    # GLOBAL RANKINGS
    wlog("\n\n" + "="*80)
    wlog("GLOBAL WIN RATE LEADERBOARD (min 10 trades)")
    wlog("="*80)
    top = [r for r in all_results if r["total"] >= 10]
    top.sort(key=lambda x: x["wr"], reverse=True)
    wlog(f"\n  {'TF':<5} {'Strategy':<26} {'SL':>4} {'TP':>4} | {'N':>5} {'WR%':>6} {'EV%':>7}")
    wlog(f"  {'-'*70}")
    for r in top[:50]:
        marker = " <--*" if r["wr"] >= 0.55 else (" <--" if r["wr"] >= 0.50 else "")
        wlog(f"  {r['tf']:<5} {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
             f"{r['total']:>5} {r['wr']*100:>6.1f}% {r['ev']*100:>+7.3f}%{marker}")

    # Best per TF
    wlog("\n\n" + "="*80)
    wlog("BEST PER TIMEFRAME (by win rate, min 10 trades)")
    wlog("="*80)
    for tf in TEST_TFS:
        tf_top = [r for r in top if r["tf"] == tf]
        if not tf_top: continue
        b = tf_top[0]
        wlog(f"\n  [{tf}] {b['strat']} | SL={b['sl']*100:.1f}% TP={b['tp']*100:.1f}% "
             f"| WR={b['wr']*100:.1f}% EV={b['ev']*100:+.3f}% N={b['total']}")
        for pair, v in b["pair"].items():
            wlog(f"    {pair}: {v['wins']}W/{v['losses']}L = {v['wr']*100:.1f}%")

    # ABSOLUTE CHAMPION (highest win rate)
    if top:
        champ = top[0]
        wlog(f"\n\n{'='*80}")
        wlog(f"***  ABSOLUTE HIGHEST WIN RATE  ***")
        wlog(f"{'='*80}")
        wlog(f"  Strategy:   {champ['strat']}")
        wlog(f"  Timeframe:  {champ['tf']}")
        wlog(f"  SL/TP:      {champ['sl']*100:.1f}% / {champ['tp']*100:.1f}%")
        wlog(f"  WIN RATE:   {champ['wr']*100:.1f}%  <- {champ['wins']}W / {champ['losses']}L")
        wlog(f"  EV/trade:   {champ['ev']*100:+.3f}%")
        wlog(f"  Trades:     {champ['total']}")
        wlog(f"  Per pair:")
        for pair, v in champ["pair"].items():
            wlog(f"    {pair}: {v['wins']}W/{v['losses']}L = {v['wr']*100:.1f}% WR")

    with open("max_winrate.json", "w") as f:
        json.dump(top, f, indent=2)

    elapsed = (datetime.now() - t0).seconds
    wlog(f"\nDone in {elapsed}s | {len(all_results)} combos tested")

if __name__ == "__main__":
    main()
