"""
Backtest SL=2% / TP=4% for Keltner_Break across max history.
"""
import requests, time, math
from fast_backtest import precompute, STRATS

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
SL = 0.020
TP = 0.040
BREAKEVEN = SL / (SL + TP)

TF_CONFIG = {
    "15m": 20000,   # ~208 days
    "1h":  20000,   # ~833 days
    "4h":  15000,   # ~2500 days
}

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
    return {"open":[float(c[1]) for c in raw], "high":[float(c[2]) for c in raw],
            "low":[float(c[3]) for c in raw], "close":[float(c[4]) for c in raw],
            "vol":[float(c[5]) for c in raw]}

def backtest(p, signal_fn, sl, tp, max_hold=300):
    wins = losses = 0
    n = p["n"]
    i = 60
    while i < n - 1:
        if not signal_fn(p, i):
            i += 1; continue
        ep = p["c"][i]; sl_p = ep*(1-sl); tp_p = ep*(1+tp)
        result = None
        j = i + 1
        while j < min(i + max_hold + 1, n):
            if p["l"][j] <= sl_p: result = "LOSS"; break
            if p["h"][j] >= tp_p: result = "WIN";  break
            j += 1
        if result == "WIN":    wins   += 1; i = j + 1
        elif result == "LOSS": losses += 1; i = j + 1
        else:                  losses += 1; i = j + 1  # timeout = loss
    return wins, losses

CPD = {"15m": 96, "1h": 24, "4h": 6}

print(f"\nBacktest: SL={SL*100:.1f}%  TP={TP*100:.1f}%  Breakeven={BREAKEVEN*100:.1f}%")
print(f"Strategy: KELTNER_BREAK across 3 TFs x 3 pairs")
print(f"Method: non-overlapping, unresolved=LOSS (conservative)\n")

keltner_fn = STRATS.get("Keltner_Break") or STRATS.get("KELTNER_BREAK")
if keltner_fn is None:
    # try case-insensitive
    for k, v in STRATS.items():
        if "keltner" in k.lower():
            keltner_fn = v
            print(f"Using strategy key: {k}")
            break

if keltner_fn is None:
    print("ERROR: Keltner_Break not found in STRATS")
    print("Available:", list(STRATS.keys()))
    exit(1)

for tf, n_candles in TF_CONFIG.items():
    total_w = total_l = 0
    days_list = []
    print(f"== {tf} =====================================")
    for pair in PAIRS:
        print(f"  Fetching {pair} {tf}...", flush=True)
        raw = fetch_max(pair, tf, n_candles)
        days = len(raw["close"]) / CPD[tf]
        days_list.append(days)
        p = precompute(raw)
        w, l = backtest(p, keltner_fn, SL, TP)
        total = w + l
        wr = w/total*100 if total else 0
        print(f"  {pair}: {w}W / {l}L = {wr:.1f}% WR  ({total} trades over {days:.0f}d)")
        total_w += w; total_l += l

    total = total_w + total_l
    wr = total_w/total*100 if total else 0
    avg_days = sum(days_list)/3
    tpd = total / avg_days if avg_days else 0
    ev = (wr/100)*TP - (1-wr/100)*SL
    print(f"  COMBINED: {total_w}W / {total_l}L = {wr:.1f}% WR  EV={ev*100:+.3f}%/trade  {tpd:.1f} trades/day\n")

print(f"\nBreakeven WR needed: {BREAKEVEN*100:.1f}%")
print(f"(vs Keltner SL=2.5%/TP=0.6% breakeven={0.025/(0.025+0.006)*100:.1f}%)")
