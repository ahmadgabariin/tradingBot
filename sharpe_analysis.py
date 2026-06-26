"""
SHARPE / SORTINO / BUY-AND-HOLD COMPARISON
Uses analytical Sharpe from binomial trade distribution (avoids zero-variance
inflation on 100% WR strategies). Also adds confidence intervals.

Sharpe  = (mean_excess_return) / std(returns)  * sqrt(n_trades_per_year)
Sortino = (mean_excess_return) / downside_std   * sqrt(n_trades_per_year)
"""
import json, math, random, requests, time as _time
from datetime import datetime

PAIRS        = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
STARTING_BAL = 1000.0
POSITION_PCT = 0.10
RF_ANNUAL    = 0.03
OUT          = "sharpe_results.txt"

# Trades per year per timeframe (approximate)
TRADES_PER_YEAR = {"5m": 105120, "15m": 35040, "1h": 8760, "4h": 2190, "1d": 365}

def wlog(msg=""):
    with open(OUT, "a", encoding="utf-8") as f: f.write(msg + "\n")
    print(msg)

def fetch(pair, tf, n=3000):
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
            _time.sleep(0.15)
        except Exception as e:
            print(f"  fetch error {pair} {tf}: {e}"); break
    raw = all_c[-n:]
    return [float(c[4]) for c in raw]

def rf_per_trade(tf):
    tpy = TRADES_PER_YEAR.get(tf, 365)
    return RF_ANNUAL / tpy

def analytical_sharpe_sortino(wr, sl, tp, tf, n_backtest_trades):
    """
    Compute Sharpe & Sortino analytically from binomial trade distribution.
    Each trade = +tp with prob wr, or -sl with prob (1-wr).
    Position sizing = POSITION_PCT of balance (fixed fraction approx).
    """
    rf_t = rf_per_trade(tf)
    tpy  = TRADES_PER_YEAR.get(tf, 365)

    # Per-trade return (as fraction of position, scaled by position size)
    # We treat each trade return as: +tp*POSITION_PCT or -sl*POSITION_PCT
    r_win  = tp  * POSITION_PCT
    r_loss = -sl * POSITION_PCT

    mean_r  = wr * r_win + (1 - wr) * r_loss
    excess  = mean_r - rf_t

    # Variance of binomial return distribution
    var = wr * (r_win - mean_r)**2 + (1 - wr) * (r_loss - mean_r)**2
    std = math.sqrt(var) if var > 1e-12 else None

    # Downside variance (only losing trades contribute below rf)
    down_var = 0.0
    if r_win < rf_t:
        down_var += wr * (r_win - rf_t)**2
    if r_loss < rf_t:
        down_var += (1 - wr) * (r_loss - rf_t)**2
    down_std = math.sqrt(down_var) if down_var > 1e-12 else None

    ann = math.sqrt(tpy)  # annualization factor

    if std is None:
        # Zero variance = 100% WR: Sharpe is technically infinite.
        # Use a conservative estimate based on sample size uncertainty.
        # With n trades at 100% WR, the 95% CI lower bound on true WR is:
        # approx 1 - (3/n) by rule of 3 (no failures observed)
        wr_lower = max(0, 1 - 3.0 / max(n_backtest_trades, 1))
        mean_r_low = wr_lower * r_win + (1 - wr_lower) * r_loss
        var_low = wr_lower * (r_win - mean_r_low)**2 + (1 - wr_lower) * (r_loss - mean_r_low)**2
        std_low = math.sqrt(var_low) if var_low > 1e-12 else 1e-9
        sharpe_conservative = (mean_r_low - rf_t) / std_low * ann
        sharpe  = sharpe_conservative
        sortino = sharpe_conservative  # same since all downside is from wr_lower losses
        note = f"(100% WR conservative est., 95%CI WR>={wr_lower*100:.1f}%)"
    else:
        sharpe  = (excess / std)  * ann if std  > 1e-12 else float("inf")
        sortino = (excess / down_std) * ann if down_std > 1e-12 else float("inf")
        note = ""

    return sharpe, sortino, mean_r, std, note

def buy_hold_sharpe(closes, tf):
    """Sharpe/Sortino for buy-and-hold."""
    if len(closes) < 2:
        return 0, 0, 0
    rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
    total_ret = (closes[-1] - closes[0]) / closes[0] * 100
    rf_t = rf_per_trade(tf)
    n    = len(rets)
    mean = sum(rets) / n
    excess = mean - rf_t
    var  = sum((r - mean)**2 for r in rets) / n
    std  = math.sqrt(var) if var > 0 else 1e-9
    neg  = [r for r in rets if r < rf_t]
    if neg:
        down_var = sum((r - rf_t)**2 for r in neg) / len(neg)
        down_std = math.sqrt(down_var)
    else:
        down_std = 1e-9
    tpy  = TRADES_PER_YEAR.get(tf, 365)
    ann  = math.sqrt(tpy)
    sharpe  = excess / std  * ann
    sortino = excess / down_std * ann
    return total_ret, sharpe, sortino

def main():
    t0 = datetime.now()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"SHARPE / SORTINO / BUY-AND-HOLD - {t0.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*80}\n\n")

    with open("deep_results.json") as f:
        results = json.load(f)
    wlog(f"Loaded {len(results)} strategy results\n")

    # Top 5 per timeframe (min 30 trades) — covers all TFs
    seen = set()
    top_strats = []
    for tf_filter in ["5m", "15m", "1h", "4h", "1d"]:
        tf_added = 0
        for r in sorted(results, key=lambda x: (x["wr"], x.get("ev",0)), reverse=True):
            if r["tf"] != tf_filter: continue
            key = (r["tf"], r["strat"])
            if key in seen or r["total"] < 30: continue
            seen.add(key)
            top_strats.append(r)
            tf_added += 1
            if tf_added >= 5: break

    # Fetch price data
    wlog("Fetching price data for buy-and-hold...")
    # Maximum candles = maximum history
    tf_candles = {"5m": 20000, "15m": 20000, "1h": 20000, "4h": 15000, "1d": 5000}
    needed_tfs = set(r["tf"] for r in top_strats)
    price_data = {}
    for tf in needed_tfs:
        price_data[tf] = {}
        for pair in PAIRS:
            closes = fetch(pair, tf, tf_candles.get(tf, 3000))
            price_data[tf][pair] = closes

    # ── BUY AND HOLD ──────────────────────────────────────────────────────────
    tf_history = {"5m": "~70 days", "15m": "~208 days", "1h": "~2.3 years", "4h": "~6.8 years", "1d": "~8-13 years"}
    wlog(f"\n{'='*95}")
    wlog("BUY AND HOLD — MAXIMUM HISTORICAL DATA")
    wlog(f"{'='*95}")
    wlog(f"  {'Asset':<14} {'TF':<5} {'History':<14} {'Candles':>7} {'Total Return':>13} {'Sharpe':>9} {'Sortino':>9}")
    wlog(f"  {'-'*70}")

    bah_avg = {}
    for tf in ["5m", "15m", "1h", "4h", "1d"]:
        if tf not in needed_tfs: continue
        hist = tf_history.get(tf, "?")
        tf_sharpes = []; tf_sortinos = []; tf_rets = []
        for pair in PAIRS:
            closes = price_data[tf].get(pair, [])
            n_candles = len(closes)
            ret, sh, so = buy_hold_sharpe(closes, tf)
            tf_sharpes.append(sh); tf_sortinos.append(so); tf_rets.append(ret)
            wlog(f"  {pair:<14} {tf:<5} {hist:<14} {n_candles:>7} {ret:>+12.1f}% {sh:>9.2f} {so:>9.2f}")
        avg_sh = sum(tf_sharpes)/len(tf_sharpes)
        avg_so = sum(tf_sortinos)/len(tf_sortinos)
        avg_ret = sum(tf_rets)/len(tf_rets)
        bah_avg[tf] = {"sharpe": avg_sh, "sortino": avg_so, "ret": avg_ret, "hist": hist}
        wlog(f"  {'--- AVG ---':<14} {tf:<5} {hist:<14} {'':>7} {avg_ret:>+12.1f}% {avg_sh:>9.2f} {avg_so:>9.2f}")
        wlog("")

    # ── STRATEGY ANALYSIS ─────────────────────────────────────────────────────
    wlog(f"\n{'='*110}")
    wlog("STRATEGY vs BUY-AND-HOLD  (analytical Sharpe from trade distribution)")
    wlog(f"{'='*110}")
    wlog(f"  {'Strategy':<26} {'TF':<5} {'WR':>6} {'N':>5} | {'Sharpe':>9} {'Sortino':>9} {'B&H Sh':>8} {'B&H So':>8} {'Edge':>7} {'Beats?':>7}")
    wlog(f"  {'-'*105}")

    strat_rows = []
    for r in top_strats:
        tf = r["tf"]; wr = r["wr"]; sl = r["sl"]; tp = r["tp"]; n = r["total"]
        sh, so, mean_r, std, note = analytical_sharpe_sortino(wr, sl, tp, tf, n)
        bsh = bah_avg.get(tf, {}).get("sharpe", 0)
        bso = bah_avg.get(tf, {}).get("sortino", 0)
        edge = sh - bsh
        beats = "YES ***" if edge > 0 else "no"
        strat_rows.append({
            "strat": r["strat"], "tf": tf, "wr": wr, "sl": sl, "tp": tp, "n": n,
            "sharpe": sh, "sortino": so, "bah_sharpe": bsh, "bah_sortino": bso,
            "edge": edge, "mean_r": mean_r, "note": note
        })
        sh_str  = f"{sh:>9.2f}" if sh < 9999 else f"{'inf':>9}"
        so_str  = f"{so:>9.2f}" if so < 9999 else f"{'inf':>9}"
        wlog(f"  {r['strat']:<26} {tf:<5} {wr*100:>5.1f}% {n:>5} | {sh_str} {so_str} {bsh:>8.2f} {bso:>8.2f} {edge:>+7.2f} {beats:>7}")
        if note:
            wlog(f"  {'':>70} {note}")

    # ── RANKINGS ──────────────────────────────────────────────────────────────
    wlog(f"\n\n{'='*80}")
    wlog("RANKINGS")
    wlog(f"{'='*80}")

    by_sharpe  = sorted(strat_rows, key=lambda x: x["sharpe"],  reverse=True)
    by_sortino = sorted(strat_rows, key=lambda x: x["sortino"], reverse=True)
    by_edge    = sorted(strat_rows, key=lambda x: x["edge"],    reverse=True)
    by_mean_r  = sorted(strat_rows, key=lambda x: x["mean_r"],  reverse=True)

    wlog("\n  Top 5 by Sharpe Ratio (annualized):")
    for i, s in enumerate(by_sharpe[:5]):
        sh_str = f"{s['sharpe']:.2f}" if s['sharpe'] < 9999 else "inf"
        wlog(f"    #{i+1} {s['strat']:<26} [{s['tf']}]  Sharpe={sh_str}  N={s['n']}  WR={s['wr']*100:.1f}%")

    wlog("\n  Top 5 by Sortino Ratio (annualized):")
    for i, s in enumerate(by_sortino[:5]):
        so_str = f"{s['sortino']:.2f}" if s['sortino'] < 9999 else "inf"
        wlog(f"    #{i+1} {s['strat']:<26} [{s['tf']}]  Sortino={so_str}  N={s['n']}  WR={s['wr']*100:.1f}%")

    wlog("\n  Top 5 by Edge over Buy-and-Hold:")
    for i, s in enumerate(by_edge[:5]):
        sh_str = f"{s['sharpe']:.2f}" if s['sharpe'] < 9999 else "inf"
        wlog(f"    #{i+1} {s['strat']:<26} [{s['tf']}]  Edge={s['edge']:+.2f}  Strategy Sharpe={sh_str}  B&H={s['bah_sharpe']:.2f}")

    wlog("\n  Top 5 by mean return per trade (as % of account):")
    for i, s in enumerate(by_mean_r[:5]):
        wlog(f"    #{i+1} {s['strat']:<26} [{s['tf']}]  Mean={s['mean_r']*100:+.4f}%/trade  WR={s['wr']*100:.1f}%")

    # ── VERDICT ───────────────────────────────────────────────────────────────
    beats_bah = [s for s in strat_rows if s["edge"] > 0]
    best_sh   = by_sharpe[0]
    best_edge = by_edge[0]

    wlog(f"\n\n{'*'*80}")
    wlog(f"  VERDICT")
    wlog(f"{'*'*80}")
    wlog(f"\n  All {len(strat_rows)} strategies tested BEAT buy-and-hold: {len(beats_bah)}/{len(strat_rows)}")
    wlog(f"\n  Buy-and-Hold Sharpe by timeframe (longer = more reliable):")
    for tf in ["5m", "15m", "1h", "4h", "1d"]:
        if tf not in bah_avg: continue
        b = bah_avg[tf]
        wlog(f"    [{tf}] {b.get('hist','?'):<14}  Sharpe={b['sharpe']:.2f}  Sortino={b['sortino']:.2f}  Return={b['ret']:+.1f}%")

    wlog(f"\n  BEST SHARPE STRATEGY:")
    sh_str = f"{best_sh['sharpe']:.2f}" if best_sh['sharpe'] < 9999 else "very high (100% WR)"
    wlog(f"    {best_sh['strat']} [{best_sh['tf']}]")
    wlog(f"    WR={best_sh['wr']*100:.1f}%  SL={best_sh['sl']*100:.1f}%  TP={best_sh['tp']*100:.1f}%  N={best_sh['n']} trades")
    wlog(f"    Sharpe={sh_str}  vs B&H={best_sh['bah_sharpe']:.2f}")
    wlog(f"    Mean return per trade: {best_sh['mean_r']*100:+.4f}% of account")

    wlog(f"\n  MOST STATISTICALLY TRUSTWORTHY (largest sample + high Sharpe):")
    # Filter to N>=100 then sort by sharpe
    large_n = sorted([s for s in strat_rows if s["n"] >= 100], key=lambda x: x["sharpe"], reverse=True)
    if large_n:
        b = large_n[0]
        sh_str = f"{b['sharpe']:.2f}" if b['sharpe'] < 9999 else "very high"
        wlog(f"    {b['strat']} [{b['tf']}]")
        wlog(f"    WR={b['wr']*100:.1f}%  N={b['n']} trades  Sharpe={sh_str}  Sortino={b['sortino']:.2f}")
        wlog(f"    vs B&H Sharpe={b['bah_sharpe']:.2f}  Edge={b['edge']:+.2f}")

    wlog(f"\n  Sharpe interpretation:")
    wlog(f"    > 1.0 = good  |  > 2.0 = very good  |  > 3.0 = excellent  |  > 5.0 = exceptional")
    wlog(f"    Buy-and-hold crypto typically: -1.0 to +1.5 (very volatile, bear phases drag it down)")

    elapsed = int((datetime.now() - t0).total_seconds())
    wlog(f"\nDone in {elapsed}s | Saved to sharpe_results.txt")

if __name__ == "__main__":
    main()
