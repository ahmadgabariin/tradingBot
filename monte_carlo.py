"""
MONTE CARLO SIMULATION — stress-tests top strategies from deep_results.json
Simulates 10,000 random trade sequences to find:
  - Real expected return distribution
  - Max drawdown distribution
  - Probability of ruin (losing >50% of account)
  - 95th percentile worst case
  - Kelly criterion optimal position size
"""
import json
import random
import math
from datetime import datetime

SIMULATIONS  = 10000   # number of random runs per strategy
TRADES_SIM   = 200     # trades per simulation run
STARTING_BAL = 1000.0  # starting balance
POSITION_PCT = 0.10    # 10% of balance per trade (fixed fractional)
RUIN_PCT     = 0.50    # ruin = losing 50%+ of starting balance
OUT          = "monte_carlo_results.txt"

def wlog(msg=""):
    with open(OUT, "a", encoding="utf-8") as f: f.write(msg + "\n")
    print(msg)

def simulate(wr, sl, tp, n_trades, starting_bal, pos_pct, n_sims):
    """Run Monte Carlo simulation for a strategy."""
    final_bals   = []
    max_dds      = []
    ruined       = 0
    peak_to_trough = []

    for _ in range(n_sims):
        bal  = starting_bal
        peak = bal
        max_dd = 0.0

        for _ in range(n_trades):
            if bal <= 0:
                break
            pos = bal * pos_pct
            if random.random() < wr:
                bal += pos * tp
            else:
                bal -= pos * sl

            if bal > peak:
                peak = bal
            dd = (peak - bal) / peak * 100
            if dd > max_dd:
                max_dd = dd

        final_bals.append(bal)
        max_dds.append(max_dd)
        if bal < starting_bal * (1 - RUIN_PCT):
            ruined += 1

    final_bals.sort()
    max_dds.sort()

    return {
        "median_bal":    final_bals[n_sims // 2],
        "p5_bal":        final_bals[int(n_sims * 0.05)],   # worst 5%
        "p95_bal":       final_bals[int(n_sims * 0.95)],   # best 5%
        "p1_bal":        final_bals[int(n_sims * 0.01)],   # worst 1%
        "mean_bal":      sum(final_bals) / n_sims,
        "median_dd":     max_dds[n_sims // 2],
        "p95_dd":        max_dds[int(n_sims * 0.95)],      # worst 5% drawdown
        "p99_dd":        max_dds[int(n_sims * 0.99)],
        "ruin_pct":      ruined / n_sims * 100,
        "positive_pct":  sum(1 for b in final_bals if b > starting_bal) / n_sims * 100,
    }

def kelly(wr, sl, tp):
    """Full Kelly criterion — optimal fraction of bankroll to risk per trade."""
    # Kelly = (WR/SL - (1-WR)/TP) ... adjusted for fractional sizing
    b = tp / sl   # ratio of win to loss
    k = (wr * b - (1 - wr)) / b
    return max(0, k)

def main():
    t0 = datetime.now()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"MONTE CARLO SIMULATION - {t0.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*80}\n\n")

    # Load deep results
    try:
        with open("deep_results.json") as f:
            results = json.load(f)
        wlog(f"Loaded {len(results)} results from deep_results.json")
    except FileNotFoundError:
        wlog("deep_results.json not found. Run deep_backtest.py first.")
        return

    # Pick top unique strategy+TF by win rate (min 30 trades for reliability)
    seen = set()
    top_strats = []
    results_sorted = sorted(results, key=lambda x: (x["wr"], x.get("ev", 0)), reverse=True)
    for r in results_sorted:
        key = (r["tf"], r["strat"])
        if key in seen: continue
        if r["total"] < 30: continue
        seen.add(key)
        top_strats.append(r)
        if len(top_strats) >= 20:
            break

    wlog(f"Simulating top {len(top_strats)} strategies ({SIMULATIONS:,} runs each, {TRADES_SIM} trades/run)")
    wlog(f"Starting balance: ${STARTING_BAL:.0f} | Position size: {POSITION_PCT*100:.0f}% per trade")
    wlog(f"Ruin threshold: lose >{RUIN_PCT*100:.0f}% of starting balance\n")

    wlog("=" * 100)
    wlog(f"{'#':<3} {'TF':<5} {'Strategy':<26} {'WR':>6} {'N':>5} | "
         f"{'Median':>8} {'Best5%':>8} {'Worst5%':>8} {'MaxDD50':>8} {'MaxDD95':>8} {'Ruin%':>6} {'Kelly':>6}")
    wlog("-" * 100)

    all_sim = []
    for i, r in enumerate(top_strats):
        wr = r["wr"]; sl = r["sl"]; tp = r["tp"]
        sim = simulate(wr, sl, tp, TRADES_SIM, STARTING_BAL, POSITION_PCT, SIMULATIONS)
        k = kelly(wr, sl, tp)
        sim["strat"] = r["strat"]; sim["tf"] = r["tf"]
        sim["wr"] = wr; sim["sl"] = sl; sim["tp"] = tp
        sim["total"] = r["total"]; sim["kelly"] = k
        all_sim.append(sim)

        wlog(f"{i+1:<3} {r['tf']:<5} {r['strat']:<26} {wr*100:>5.1f}% {r['total']:>5} | "
             f"${sim['median_bal']:>7.0f} ${sim['p95_bal']:>7.0f} ${sim['p5_bal']:>7.0f} "
             f"{sim['median_dd']:>7.1f}% {sim['p95_dd']:>7.1f}% {sim['ruin_pct']:>5.1f}% {k*100:>5.1f}%")

    wlog("=" * 100)

    # Detailed analysis of top 5
    wlog(f"\n\n{'='*80}")
    wlog("DETAILED ANALYSIS - TOP 5 STRATEGIES")
    wlog(f"{'='*80}")
    for i, sim in enumerate(all_sim[:5]):
        wlog(f"\n#{i+1} {sim['strat']} [{sim['tf']}]  WR={sim['wr']*100:.1f}%  SL={sim['sl']*100:.1f}%  TP={sim['tp']*100:.1f}%  Trades in backtest={sim['total']}")
        wlog(f"  Starting balance:      ${STARTING_BAL:.0f}")
        wlog(f"  After {TRADES_SIM} trades:")
        wlog(f"    Median outcome:      ${sim['median_bal']:.0f}  ({(sim['median_bal']/STARTING_BAL-1)*100:+.1f}%)")
        wlog(f"    Mean outcome:        ${sim['mean_bal']:.0f}  ({(sim['mean_bal']/STARTING_BAL-1)*100:+.1f}%)")
        wlog(f"    Best 5% scenario:    ${sim['p95_bal']:.0f}  ({(sim['p95_bal']/STARTING_BAL-1)*100:+.1f}%)")
        wlog(f"    Worst 5% scenario:   ${sim['p5_bal']:.0f}  ({(sim['p5_bal']/STARTING_BAL-1)*100:+.1f}%)")
        wlog(f"    Worst 1% scenario:   ${sim['p1_bal']:.0f}  ({(sim['p1_bal']/STARTING_BAL-1)*100:+.1f}%)")
        wlog(f"  Max drawdown:")
        wlog(f"    Median drawdown:     {sim['median_dd']:.1f}%")
        wlog(f"    95th pct drawdown:   {sim['p95_dd']:.1f}%")
        wlog(f"    99th pct drawdown:   {sim['p99_dd']:.1f}%")
        wlog(f"  Profitable runs:       {sim['positive_pct']:.1f}%")
        wlog(f"  Ruin probability:      {sim['ruin_pct']:.2f}%")
        wlog(f"  Full Kelly size:       {sim['kelly']*100:.1f}% of bankroll per trade")
        wlog(f"  Half Kelly (safer):    {sim['kelly']*50:.1f}% of bankroll per trade")

    # Best overall by different metrics
    wlog(f"\n\n{'='*80}")
    wlog("RANKINGS BY DIFFERENT METRICS")
    wlog(f"{'='*80}")

    by_median = sorted(all_sim, key=lambda x: x["median_bal"], reverse=True)
    by_ruin   = sorted(all_sim, key=lambda x: x["ruin_pct"])
    by_dd     = sorted(all_sim, key=lambda x: x["p95_dd"])
    by_worst  = sorted(all_sim, key=lambda x: x["p5_bal"], reverse=True)

    wlog(f"\n  Best median return after {TRADES_SIM} trades:")
    for s in by_median[:3]:
        wlog(f"    {s['strat']:<26} [{s['tf']}]  ${s['median_bal']:.0f}  (+{(s['median_bal']/STARTING_BAL-1)*100:.0f}%)")

    wlog(f"\n  Lowest ruin probability:")
    for s in by_ruin[:3]:
        wlog(f"    {s['strat']:<26} [{s['tf']}]  Ruin={s['ruin_pct']:.2f}%  Median=${s['median_bal']:.0f}")

    wlog(f"\n  Smallest 95th pct max drawdown:")
    for s in by_dd[:3]:
        wlog(f"    {s['strat']:<26} [{s['tf']}]  MaxDD95={s['p95_dd']:.1f}%  Median=${s['median_bal']:.0f}")

    wlog(f"\n  Best worst-case (5th percentile):")
    for s in by_worst[:3]:
        wlog(f"    {s['strat']:<26} [{s['tf']}]  Worst5%=${s['p5_bal']:.0f}  ({(s['p5_bal']/STARTING_BAL-1)*100:+.0f}%)")

    # RECOMMENDATION
    # Score: normalize median return + low ruin + low drawdown
    for s in all_sim:
        score = (s["median_bal"] / STARTING_BAL) * 0.4 \
              + (1 - s["ruin_pct"] / 100) * 0.3 \
              + (1 - s["p95_dd"] / 100) * 0.3
        s["score"] = score
    best = sorted(all_sim, key=lambda x: x["score"], reverse=True)[0]

    wlog(f"\n\n{'*'*80}")
    wlog(f"  RECOMMENDED STRATEGY FOR LIVE TRADING")
    wlog(f"{'*'*80}")
    wlog(f"  Strategy:         {best['strat']}")
    wlog(f"  Timeframe:        {best['tf']}")
    wlog(f"  Win Rate:         {best['wr']*100:.1f}%")
    wlog(f"  SL / TP:          {best['sl']*100:.1f}% / {best['tp']*100:.1f}%")
    wlog(f"  Backtest trades:  {best['total']}")
    wlog(f"  Median return ({TRADES_SIM} trades): ${best['median_bal']:.0f} ({(best['median_bal']/STARTING_BAL-1)*100:+.1f}%)")
    wlog(f"  Ruin risk:        {best['ruin_pct']:.2f}%")
    wlog(f"  Max drawdown 95%: {best['p95_dd']:.1f}%")
    wlog(f"  Kelly position:   {best['kelly']*100:.1f}% (use {best['kelly']*50:.1f}% half-Kelly for safety)")

    elapsed = int((datetime.now() - t0).total_seconds())
    wlog(f"\nDone in {elapsed}s | {SIMULATIONS*len(top_strats):,} total simulations run")
    wlog("Saved to monte_carlo_results.txt")

if __name__ == "__main__":
    main()
