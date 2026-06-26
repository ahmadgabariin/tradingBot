"""
Reads deep_results.json, picks the absolute best strategy,
prints a detailed report, then patches engine.py SL/TP/timeframe.
"""
import json, re

def main():
    try:
        with open("deep_results.json") as f:
            results = json.load(f)
    except FileNotFoundError:
        print("deep_results.json not found")
        return

    if not results:
        print("No results found")
        return

    # Best by win rate (min 15 trades)
    top = [r for r in results if r["total"] >= 15]
    top.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)

    if not top:
        print("Not enough trades in any result")
        return

    best = top[0]
    print("\n" + "="*60)
    print("BEST STRATEGY FOUND")
    print("="*60)
    print(f"  Strategy:   {best['strat']}")
    print(f"  Timeframe:  {best['tf']}")
    print(f"  SL:         {best['sl']*100:.1f}%")
    print(f"  TP:         {best['tp']*100:.1f}%")
    print(f"  Win Rate:   {best['wr']*100:.1f}%")
    print(f"  EV/trade:   {best['ev']*100:+.3f}%")
    print(f"  Trades:     {best['total']} ({best['wins']}W / {best['losses']}L)")
    print()
    print("  Per-pair breakdown:")
    for pair, v in best.get("pair_breakdown", {}).items():
        print(f"    {pair}: {v['wins']}W/{v['losses']}L = {v['wr']*100:.1f}% WR")

    print("\n  Patching engine.py with best SL/TP/timeframe...")

    with open("paper/engine.py", "r") as f:
        code = f.read()

    code = re.sub(r"STOP_LOSS_PCT\s*=\s*[\d.]+",
                  f"STOP_LOSS_PCT    = {best['sl']}", code)
    code = re.sub(r"TAKE_PROFIT_PCT\s*=\s*[\d.]+",
                  f"TAKE_PROFIT_PCT  = {best['tp']}", code)
    code = re.sub(r'TIMEFRAME\s*=\s*"[^"]*"',
                  f'TIMEFRAME        = "{best["tf"]}"', code)

    with open("paper/engine.py", "w") as f:
        f.write(code)

    print(f"  engine.py updated: SL={best['sl']*100:.1f}% TP={best['tp']*100:.1f}% TF={best['tf']}")

    # Also write a summary report
    with open("BEST_STRATEGY.txt", "w") as f:
        f.write("BEST STRATEGY — AUTO-SELECTED FROM BACKTEST\n")
        f.write("="*50 + "\n\n")
        f.write(f"Strategy:   {best['strat']}\n")
        f.write(f"Timeframe:  {best['tf']}\n")
        f.write(f"SL:         {best['sl']*100:.1f}%\n")
        f.write(f"TP:         {best['tp']*100:.1f}%\n")
        f.write(f"Win Rate:   {best['wr']*100:.1f}%\n")
        f.write(f"EV/trade:   {best['ev']*100:+.3f}%\n")
        f.write(f"Trades:     {best['total']} ({best['wins']}W / {best['losses']}L)\n\n")
        f.write("Top 10 strategies overall:\n")
        for i, r in enumerate(top[:10]):
            f.write(f"  #{i+1} [{r['tf']}] {r['strat']} "
                    f"SL={r['sl']*100:.1f}% TP={r['tp']*100:.1f}% "
                    f"WR={r['wr']*100:.1f}% EV={r['ev']*100:+.3f}%\n")

    print("\nSummary written to BEST_STRATEGY.txt")
    print("Run `python paper/run.py` to start trading with the best settings!")

if __name__ == "__main__":
    main()
