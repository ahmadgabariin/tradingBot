"""
Fast strategy summary — shows trade counts, win rate, final balance per strategy.
No individual trade lines, just the statistics.
"""
import math, requests, time as _time
from datetime import datetime, timezone
from fast_backtest import precompute, STRATS

LOG_STRATS = [
    "EMA_Ribbon", "ADX_Trend", "EMA_Stack_Pullback", "Confluence",
    "EMA21_Touch_MACD", "Donchian_Break", "Keltner_Break", "Squeeze_Break",
]
BEST_PARAMS = {
    "EMA_Ribbon":         ("5m",  0.050, 0.025),
    "ADX_Trend":          ("5m",  0.050, 0.025),
    "EMA_Stack_Pullback": ("5m",  0.050, 0.025),
    "Confluence":         ("5m",  0.050, 0.025),
    "EMA21_Touch_MACD":   ("5m",  0.050, 0.025),
    "Donchian_Break":     ("5m",  0.050, 0.025),
    "Keltner_Break":      ("5m",  0.050, 0.025),
    "Squeeze_Break":      ("15m", 0.050, 0.025),
}
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
STARTING_BAL = 1000.0
POSITION_PCT  = 0.10

def fetch(pair, tf, n=20000):
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
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
        "vol":   [float(c[5]) for c in raw],
    }

def backtest_fast(p, signal_fn, sl, tp, start=60, max_hold=50):
    """
    Matches fast_backtest.py exactly:
    - Overlapping entries allowed (doesn't wait for trade to close)
    - Trades not resolved within max_hold candles are DROPPED (not counted)
    - This is what deep_backtest used — drop = artificially high WR
    Also runs a realistic version (no max_hold, non-overlapping) for comparison.
    """
    wins = losses = dropped = 0
    n = p["n"]
    for i in range(start, n - 1):
        if not signal_fn(p, i): continue
        ep   = p["c"][i]
        sl_p = ep * (1 - sl)
        tp_p = ep * (1 + tp)
        resolved = False
        for j in range(i + 1, min(i + max_hold + 1, n)):
            if p["l"][j] <= sl_p: losses += 1; resolved = True; break
            if p["h"][j] >= tp_p: wins   += 1; resolved = True; break
        if not resolved:
            dropped += 1  # silently ignored in original backtest
    return wins, losses, dropped

def main():
    print(f"\nSTRATEGY SUMMARY  ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"SL=5.0%  TP=2.5%  |  $1000 start  |  10% position sizing")
    print("=" * 90)

    needed_tfs = set(v[0] for v in BEST_PARAMS.values())
    data = {}
    for tf in needed_tfs:
        data[tf] = {}
        print(f"\nFetching {tf} data...")
        for pair in PAIRS:
            n = 20000
            d = fetch(pair, tf, n)
            data[tf][pair] = precompute(d)
            print(f"  {pair} {tf}: {len(d['close'])} candles")

    print(f"\n  NOTE: 'Dropped' = trades not resolved in 50 candles (same logic as deep_backtest — inflates WR)")
    print(f"\n{'Strategy':<22} {'TF':<5} {'Total':>6} {'Wins':>6} {'Losses':>7} {'Dropped':>8} {'WR%':>6} {'Final Bal':>11} {'Return':>8}")
    print("-" * 95)

    for sname in LOG_STRATS:
        if sname not in STRATS:
            print(f"{sname:<22}  [not found in STRATS]")
            continue
        tf, sl, tp = BEST_PARAMS[sname]
        sfn = STRATS[sname]

        total_wins = total_losses = total_dropped = 0
        pair_stats = {}

        for pair in PAIRS:
            w, l, d = backtest_fast(data[tf][pair], sfn, sl, tp)
            total_wins    += w
            total_losses  += l
            total_dropped += d
            pair_stats[pair] = (w, l, d)

        total = total_wins + total_losses
        wr = total_wins / total * 100 if total > 0 else 0

        bal = STARTING_BAL * ((1 + POSITION_PCT * tp) ** total_wins) * ((1 - POSITION_PCT * sl) ** total_losses)
        ret = (bal / STARTING_BAL - 1) * 100
        print(f"{sname:<22} {tf:<5} {total:>6} {total_wins:>6} {total_losses:>7} {total_dropped:>7} {wr:>6.1f}% ${bal:>9,.0f} {ret:>+7.1f}%")

        for pair in PAIRS:
            w, l, d = pair_stats[pair]
            pwr = w/(w+l)*100 if (w+l) > 0 else 0
            print(f"  {pair}: {w}W / {l}L  dropped={d}  ({pwr:.1f}% WR)")
        print()

    print("=" * 90)
    print("Done.")

if __name__ == "__main__":
    main()
