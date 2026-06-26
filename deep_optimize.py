"""
DEEP OPTIMIZER — runs after mega_backtest completes.
Takes the top strategies from mega_results.json, tests them with
fine-grained SL/TP, per-pair breakdown, and statistical confidence.
"""
import json, requests, time, math
from datetime import datetime

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RESULTS_FILE = "deep_results.txt"


# ── Import everything from mega_backtest ────────────────────────────────────
from mega_backtest import (
    fetch_candles_paged, run_backtest, STRATEGIES, TIMEFRAMES
)


def log(msg):
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)


def sharpe(pnl_list):
    if len(pnl_list) < 3:
        return 0
    n = len(pnl_list)
    mean = sum(pnl_list) / n
    var = sum((x - mean) ** 2 for x in pnl_list) / n
    std = var ** 0.5
    return mean / std if std > 0 else 0


def main():
    # Load top results from mega_backtest
    try:
        with open("mega_results.json") as f:
            all_results = json.load(f)
    except FileNotFoundError:
        log("mega_results.json not found — run mega_backtest.py first")
        return

    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        f.write(f"DEEP OPTIMIZATION RESULTS — {started}\n{'='*80}\n\n")

    log(f"Loaded {len(all_results)} results from mega_backtest")

    # Pick top 20 unique strategy+TF combinations by win rate (min 15 trades)
    seen = set()
    top_combos = []
    for r in sorted(all_results, key=lambda x: (x["wr"], x["ev"]), reverse=True):
        if r["total"] < 15:
            continue
        key = (r["strat"], r["tf"])
        if key not in seen:
            seen.add(key)
            top_combos.append(r)
        if len(top_combos) >= 20:
            break

    log(f"Testing top {len(top_combos)} strategy+TF combos with fine-grained SL/TP\n")

    # Fetch fresh data (3000 candles)
    log("Fetching data...")
    all_data = {}
    for tf in set(r["tf"] for r in top_combos):
        all_data[tf] = {}
        for pair in PAIRS:
            all_data[tf][pair] = fetch_candles_paged(pair, tf, 3000)
            log(f"  {pair} {tf}: {len(all_data[tf][pair])} candles")
            time.sleep(0.3)

    # Fine-grained SL/TP grid
    fine_combos = []
    for sl_base in [0.003, 0.004, 0.005, 0.006, 0.007, 0.008, 0.010, 0.012, 0.015]:
        for ratio in [1.5, 2.0, 2.5, 3.0]:
            fine_combos.append((sl_base, round(sl_base * ratio, 4)))

    log(f"\nTesting {len(fine_combos)} SL/TP combos per strategy\n")

    deep_results = []

    for combo in top_combos:
        strat_name = combo["strat"]
        tf = combo["tf"]
        strat_fn = STRATEGIES.get(strat_name)
        if not strat_fn:
            continue

        log(f"\n[{tf}] {strat_name}")
        best_for_this = []

        for sl, tp in fine_combos:
            wins, losses = 0, 0
            all_pnl = []
            pair_results = {}

            for pair in PAIRS:
                candles = all_data[tf].get(pair, [])
                if len(candles) < 70:
                    continue
                res = run_backtest(candles, strat_fn, sl, tp)
                wins += res["wins"]; losses += res["losses"]
                all_pnl.extend(res["pnl_list"])
                pair_results[pair] = res

            total = wins + losses
            if total < 8:
                continue

            wr = wins / total
            ev = sum(all_pnl) / len(all_pnl) if all_pnl else 0
            sh = sharpe(all_pnl)

            result = {
                "strat": strat_name, "tf": tf, "sl": sl, "tp": tp,
                "wins": wins, "losses": losses, "total": total,
                "wr": wr, "ev": ev, "sharpe": sh,
                "pair_breakdown": {
                    p: {
                        "wins": v["wins"], "losses": v["losses"],
                        "wr": v["wins"] / max(v["wins"] + v["losses"], 1)
                    } for p, v in pair_results.items()
                }
            }
            best_for_this.append(result)
            deep_results.append(result)

        if best_for_this:
            best_for_this.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)
            top3 = best_for_this[:3]
            for r in top3:
                breakdown = " | ".join(
                    f"{p}: {v['wins']}W/{v['losses']}L ({v['wr']*100:.0f}%)"
                    for p, v in r["pair_breakdown"].items()
                )
                log(f"  SL={r['sl']*100:.1f}% TP={r['tp']*100:.1f}% → "
                    f"WR={r['wr']*100:.1f}% EV={r['ev']*100:+.3f}% Sharpe={r['sharpe']:.2f} "
                    f"({r['total']} trades)")
                log(f"    {breakdown}")

    # ── FINAL LEADERBOARD ──────────────────────────────────────────────────────
    log("\n\n" + "="*80)
    log("DEEP OPTIMIZATION — FINAL LEADERBOARD (min 15 trades)")
    log("="*80)

    final = [r for r in deep_results if r["total"] >= 15]
    final.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)

    log(f"\n  {'TF':<5} {'Strategy':<28} {'SL':>4} {'TP':>4} | {'N':>5} {'WR%':>6} {'EV%':>7} {'Sharpe':>7}")
    log(f"  {'-'*80}")
    for i, r in enumerate(final[:25]):
        log(f"  {r['tf']:<5} {r['strat']:<28} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
            f"{r['total']:>5} {r['wr']*100:>6.1f}% {r['ev']*100:>+7.3f}% {r['sharpe']:>7.3f}")
        if i == 0:
            log(f"  *** WINNER *** Best per-pair breakdown:")
            for p, v in r["pair_breakdown"].items():
                log(f"      {p}: {v['wins']}W/{v['losses']}L → {v['wr']*100:.1f}% WR")

    with open("deep_results.json", "w") as f:
        json.dump(final, f, indent=2)

    log(f"\nDone. Results in deep_results.txt and deep_results.json")


if __name__ == "__main__":
    main()
