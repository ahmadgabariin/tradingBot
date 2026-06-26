"""
FINAL SUMMARY — reads all backtest results and produces the ultimate report.
Run this after fast_backtest.py, max_winrate.py, and extra_strats.py complete.
"""
import json
import sys
from datetime import datetime

def main():
    # Load results
    results = []
    for fname in ["mega_results.json", "max_winrate.json"]:
        try:
            with open(fname) as f:
                batch = json.load(f)
                for r in batch:
                    r["source"] = fname
                results.extend(batch)
            print(f"Loaded {len(batch)} from {fname}")
        except FileNotFoundError:
            print(f"  {fname} not found, skipping")

    if not results:
        print("No results found. Run fast_backtest.py first.")
        return

    print(f"\nTotal results loaded: {len(results)}")

    # Deduplicate (same strat+tf+sl+tp)
    seen = {}
    for r in results:
        key = (r["tf"], r["strat"], r["sl"], r["tp"])
        if key not in seen or r["wr"] > seen[key]["wr"]:
            seen[key] = r
    results = list(seen.values())
    results.sort(key=lambda x: (x["wr"], x.get("ev", 0)), reverse=True)

    out = []
    def p(msg=""):
        out.append(msg)
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode('ascii', 'replace').decode())

    p("=" * 80)
    p(f"FINAL BACKTEST SUMMARY - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    p("=" * 80)

    TFS = ["5m", "15m", "1h", "4h", "1d"]

    # GLOBAL TOP 30 (by win rate, >=10 trades)
    p("\n[ GLOBAL TOP 30 BY WIN RATE (min 10 trades) ]")
    p(f"  {'Rank':<5} {'TF':<5} {'Strategy':<26} {'SL':>4} {'TP':>4} | {'N':>5} {'WR%':>6} {'EV%':>7}")
    p(f"  {'-'*72}")
    top = [r for r in results if r["total"] >= 10]
    shown = set()
    rank = 0
    for r in top:
        key = (r["tf"], r["strat"])
        if key in shown: continue
        shown.add(key)
        rank += 1
        medal = "*** " if rank == 1 else ("**  " if rank <= 3 else "    ")
        p(f"  {medal}#{rank:<3} {r['tf']:<5} {r['strat']:<26} {r['sl']*100:>4.1f} {r['tp']*100:>4.1f} | "
          f"{r['total']:>5} {r['wr']*100:>6.1f}% {r.get('ev',0)*100:>+7.3f}%")
        if rank >= 30: break

    # BEST PER TIMEFRAME
    p("\n\n[ BEST STRATEGY PER TIMEFRAME ]")
    p("-" * 80)
    for tf in TFS:
        tf_top = [r for r in results if r["tf"] == tf and r["total"] >= 10]
        if not tf_top:
            p(f"\n  [{tf}] No results with >=10 trades")
            continue
        # Best by win rate
        tf_top_wr = sorted(tf_top, key=lambda x: (x["wr"], x.get("ev",0)), reverse=True)
        # Best by EV (must be profitable)
        tf_top_ev = sorted([r for r in tf_top if r.get("ev",0) > 0],
                           key=lambda x: x.get("ev",0), reverse=True)
        b_wr = tf_top_wr[0]
        b_ev = tf_top_ev[0] if tf_top_ev else None

        p(f"\n  +-- [{tf}] BEST WIN RATE: {b_wr['strat']}")
        p(f"  |   SL={b_wr['sl']*100:.1f}%  TP={b_wr['tp']*100:.1f}%  "
          f"WIN RATE={b_wr['wr']*100:.1f}%  EV={b_wr.get('ev',0)*100:+.3f}%  N={b_wr['total']}")
        if "pair" in b_wr:
            p(f"  |   " + " | ".join(f"{pair}: {v['wins']}W/{v['losses']}L ({v['wr']*100:.0f}%)"
                                      for pair, v in b_wr["pair"].items()))
        if b_ev and b_ev["strat"] != b_wr["strat"]:
            p(f"  +-- [{tf}] BEST PROFIT: {b_ev['strat']}")
            p(f"  |   SL={b_ev['sl']*100:.1f}%  TP={b_ev['tp']*100:.1f}%  "
              f"WIN RATE={b_ev['wr']*100:.1f}%  EV={b_ev.get('ev',0)*100:+.3f}%  N={b_ev['total']}")
        p(f"  +-- Top 5 by win rate:")
        shown_tf = set()
        count = 0
        for r in tf_top_wr:
            if r["strat"] in shown_tf: continue
            shown_tf.add(r["strat"])
            p(f"       #{count+1} {r['strat']:<26} WR={r['wr']*100:.1f}% "
              f"EV={r.get('ev',0)*100:+.3f}% SL={r['sl']*100:.1f}% TP={r['tp']*100:.1f}% N={r['total']}")
            count += 1
            if count >= 5: break

    # CHAMPION
    if results:
        champ = [r for r in results if r["total"] >= 10][0]
        p(f"\n\n{'*'*80}")
        p(f"  ABSOLUTE CHAMPION")
        p(f"{'*'*80}")
        p(f"  Strategy:   {champ['strat']}")
        p(f"  Timeframe:  {champ['tf']}")
        p(f"  SL:         {champ['sl']*100:.1f}%")
        p(f"  TP:         {champ['tp']*100:.1f}%")
        p(f"  WIN RATE:   {champ['wr']*100:.1f}%")
        p(f"  EV/trade:   {champ.get('ev',0)*100:+.3f}%")
        p(f"  Trades:     {champ['total']} ({champ['wins']}W / {champ['losses']}L)")
        if "pair" in champ:
            p(f"  Per pair:")
            for pair, v in champ["pair"].items():
                p(f"    {pair}: {v['wins']}W/{v['losses']}L = {v['wr']*100:.1f}% WR")

    # ANALYSIS
    p(f"\n\n[ ANALYSIS ]")
    for wr_threshold in [0.65, 0.60, 0.55, 0.50, 0.45, 0.40, 0.35]:
        count_above = len([r for r in results if r["wr"] >= wr_threshold and r["total"] >= 10])
        p(f"  Strategies with WR >= {wr_threshold*100:.0f}%: {count_above}")

    profitable = [r for r in results if r.get("ev",0) > 0 and r["total"] >= 10]
    p(f"\n  Profitable strategies (EV > 0): {len(profitable)}")
    if profitable:
        profitable.sort(key=lambda x: x.get("ev",0), reverse=True)
        p(f"  Best EV: {profitable[0]['strat']} [{profitable[0]['tf']}] "
          f"EV={profitable[0].get('ev',0)*100:+.3f}% WR={profitable[0]['wr']*100:.1f}%")

    # Save
    with open("FINAL_REPORT.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("\nSaved to FINAL_REPORT.txt")

if __name__ == "__main__":
    main()
