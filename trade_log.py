"""
TRADE LOG — replays backtest and shows every individual trade for top strategies.
Includes: date/time, entry price, exit price, result, PnL, running balance.
"""
import json, math, requests, time as _time
from datetime import datetime, timezone
from fast_backtest import precompute, STRATS

OUT = "trade_log.txt"

# Strategies to log (name must match STRATS keys)
LOG_STRATS = [
    "EMA_Ribbon",
    "ADX_Trend",
    "EMA_Stack_Pullback",
    "Confluence",
    "EMA21_Touch_MACD",
    "Donchian_Break",
    "Keltner_Break",
    "Squeeze_Break",
]

# Best SL/TP per strategy from deep_results
BEST_PARAMS = {
    "EMA_Ribbon":        ("5m",  0.050, 0.025),
    "ADX_Trend":         ("5m",  0.050, 0.025),
    "EMA_Stack_Pullback":("5m",  0.050, 0.025),
    "Confluence":        ("5m",  0.050, 0.025),
    "EMA21_Touch_MACD":  ("5m",  0.050, 0.025),
    "Donchian_Break":    ("5m",  0.050, 0.025),
    "Keltner_Break":     ("5m",  0.050, 0.025),
    "Squeeze_Break":     ("15m", 0.050, 0.025),
}

PAIRS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
STARTING_BAL = 1000.0
POSITION_PCT = 0.10

def wlog(msg=""):
    with open(OUT, "a", encoding="utf-8") as f: f.write(msg + "\n")
    print(msg)

def fetch_with_times(pair, tf, n=20000):
    """Fetch candles including open timestamps."""
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
    return all_c[-n:]

def ts_to_str(ms):
    """Convert millisecond timestamp to readable date string."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

def backtest_with_log(raw_candles, p, signal_fn, sl, tp, pair, tf):
    """Run backtest and return list of trade dicts with full details."""
    trades = []
    n = p["n"]
    for i in range(1, n - 1):
        if not signal_fn(p, i):
            continue
        entry_price = p["c"][i]
        entry_time  = ts_to_str(int(raw_candles[i][0]))
        sl_price    = entry_price * (1 - sl)
        tp_price    = entry_price * (1 + tp)

        result = None
        exit_price = None
        exit_time  = None
        candles_held = 0

        for j in range(i + 1, n):
            candles_held += 1
            lo = p["l"][j]
            hi = p["h"][j]
            # Check SL first (conservative)
            if lo <= sl_price:
                result     = "LOSS"
                exit_price = sl_price
                exit_time  = ts_to_str(int(raw_candles[j][0]))
                break
            if hi >= tp_price:
                result     = "WIN"
                exit_price = tp_price
                exit_time  = ts_to_str(int(raw_candles[j][0]))
                break

        if result is None:
            # Trade still open at end of data
            exit_price   = p["c"][-1]
            exit_time    = ts_to_str(int(raw_candles[-1][0]))
            pnl_pct      = (exit_price - entry_price) / entry_price
            result       = "OPEN"
            candles_held = n - i - 1

        pnl_pct = tp if result == "WIN" else (-sl if result == "LOSS" else
                  (exit_price - entry_price) / entry_price)

        trades.append({
            "pair":         pair,
            "entry_time":   entry_time,
            "exit_time":    exit_time,
            "entry_price":  entry_price,
            "exit_price":   exit_price,
            "sl_price":     sl_price,
            "tp_price":     tp_price,
            "result":       result,
            "pnl_pct":      pnl_pct,
            "candles_held": candles_held,
        })

    return trades

def main():
    t0 = datetime.now()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"TRADE LOG - {t0.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*80}\n\n")

    # Fetch data
    wlog("Fetching data...\n")
    raw_data = {}
    precomp  = {}
    fetched_tfs = set()

    needed = {}
    for sname in LOG_STRATS:
        tf, sl, tp = BEST_PARAMS[sname]
        if tf not in needed:
            needed[tf] = set()
        needed[tf].add(sname)

    for tf, strats in needed.items():
        raw_data[tf] = {}
        precomp[tf]  = {}
        n_candles = 20000 if tf in ("5m","15m","1h") else 15000
        for pair in PAIRS:
            raw = fetch_with_times(pair, tf, n_candles)
            d = {
                "open":  [float(c[1]) for c in raw],
                "high":  [float(c[2]) for c in raw],
                "low":   [float(c[3]) for c in raw],
                "close": [float(c[4]) for c in raw],
                "vol":   [float(c[5]) for c in raw],
            }
            raw_data[tf][pair] = raw
            precomp[tf][pair]  = precompute(d)
            wlog(f"  {pair} {tf}: {len(raw)} candles  ({ts_to_str(int(raw[0][0]))} to {ts_to_str(int(raw[-1][0]))})")

    # Run trade logs
    for sname in LOG_STRATS:
        if sname not in STRATS:
            wlog(f"\n[SKIP] {sname} not found in STRATS")
            continue
        tf, sl, tp = BEST_PARAMS[sname]
        sfn = STRATS[sname]

        all_trades = []
        for pair in PAIRS:
            raw = raw_data[tf][pair]
            p   = precomp[tf][pair]
            trades = backtest_with_log(raw, p, sfn, sl, tp, pair, tf)
            all_trades.extend(trades)

        # Sort by entry time
        all_trades.sort(key=lambda x: x["entry_time"])

        wins   = sum(1 for t in all_trades if t["result"] == "WIN")
        losses = sum(1 for t in all_trades if t["result"] == "LOSS")
        opens  = sum(1 for t in all_trades if t["result"] == "OPEN")
        total  = wins + losses
        wr     = wins / total * 100 if total > 0 else 0

        wlog(f"\n{'='*100}")
        wlog(f"STRATEGY: {sname}  |  TF: {tf}  |  SL: {sl*100:.1f}%  TP: {tp*100:.1f}%")
        wlog(f"Total trades: {len(all_trades)}  |  Wins: {wins}  Losses: {losses}  Open: {opens}  |  Win Rate: {wr:.1f}%")
        wlog(f"{'='*100}")
        wlog(f"  {'#':<4} {'Pair':<10} {'Entry Time':<18} {'Exit Time':<18} {'Entry $':>10} {'Exit $':>10} "
             f"{'Result':<6} {'PnL%':>6} {'Bars':>5} {'RunBal':>9}")
        wlog(f"  {'-'*100}")

        bal = STARTING_BAL
        for i, t in enumerate(all_trades):
            pos_size = bal * POSITION_PCT
            pnl_usd  = pos_size * t["pnl_pct"]
            bal     += pnl_usd
            result_str = "WIN  " if t["result"] == "WIN" else ("LOSS " if t["result"] == "LOSS" else "OPEN ")
            pnl_str = f"{t['pnl_pct']*100:>+5.1f}%"
            wlog(f"  {i+1:<4} {t['pair']:<10} {t['entry_time']:<18} {t['exit_time']:<18} "
                 f"${t['entry_price']:>9,.2f} ${t['exit_price']:>9,.2f} "
                 f"{result_str} {pnl_str} {t['candles_held']:>5} ${bal:>8,.2f}")

        # Summary stats
        if all_trades:
            pnl_pcts  = [t["pnl_pct"] for t in all_trades if t["result"] != "OPEN"]
            total_ret = (bal / STARTING_BAL - 1) * 100
            avg_bars  = sum(t["candles_held"] for t in all_trades) / len(all_trades)
            wlog(f"  {'-'*100}")
            wlog(f"  Final balance: ${bal:,.2f}  ({total_ret:+.1f}% total return on $1000 with 10% position sizing)")
            wlog(f"  Avg trade duration: {avg_bars:.1f} candles")
            if pnl_pcts:
                max_loss = min(pnl_pcts) * 100
                max_win  = max(pnl_pcts) * 100
                wlog(f"  Biggest win: {max_win:+.1f}%  |  Biggest loss: {max_loss:+.1f}%")

        # Per-pair breakdown
        wlog(f"\n  Per-pair breakdown:")
        for pair in PAIRS:
            pt = [t for t in all_trades if t["pair"] == pair]
            pw = sum(1 for t in pt if t["result"] == "WIN")
            pl = sum(1 for t in pt if t["result"] == "LOSS")
            pwr = pw/(pw+pl)*100 if (pw+pl) > 0 else 0
            wlog(f"    {pair}: {pw}W / {pl}L = {pwr:.1f}% WR  ({len(pt)} total trades)")

    elapsed = int((datetime.now() - t0).total_seconds())
    wlog(f"\n\nDone in {elapsed}s | Saved to trade_log.txt")

if __name__ == "__main__":
    main()
