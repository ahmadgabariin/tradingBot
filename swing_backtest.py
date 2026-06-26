"""
Swing Trade Backtest
Target: hold 3-10 days, TP=10-30%, SL=3-8%
Timeframes: 4h, 1d
Long history, non-overlapping, unresolved=LOSS
"""
import requests, time, math
from fast_backtest import precompute, STRATS

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
CPD   = {"4h": 6, "1d": 1}

TF_CONFIG = {
    "4h": 15000,   # ~2500 days
    "1d": 3000,    # ~3000 days (~8 years)
}

# Swing trade R/R grid: TP=10-30%, SL=3-8%, TP always >= 2x SL
SL_TP_GRID = [
    # SL 3%
    (0.03, 0.10), (0.03, 0.15), (0.03, 0.20),
    # SL 4%
    (0.04, 0.10), (0.04, 0.12), (0.04, 0.15), (0.04, 0.20),
    # SL 5%
    (0.05, 0.10), (0.05, 0.12), (0.05, 0.15), (0.05, 0.20), (0.05, 0.25),
    # SL 6%
    (0.06, 0.12), (0.06, 0.15), (0.06, 0.20), (0.06, 0.25), (0.06, 0.30),
    # SL 7%
    (0.07, 0.15), (0.07, 0.20), (0.07, 0.25), (0.07, 0.30),
    # SL 8%
    (0.08, 0.16), (0.08, 0.20), (0.08, 0.25), (0.08, 0.30),
]

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
            time.sleep(0.1)
        except Exception as e:
            print(f"  fetch error {pair} {tf}: {e}"); break
    raw = all_c[-n:]
    return {"open":[float(c[1]) for c in raw],"high":[float(c[2]) for c in raw],
            "low":[float(c[3]) for c in raw],"close":[float(c[4]) for c in raw],
            "vol":[float(c[5]) for c in raw]}

def backtest(p, fn, sl, tp, max_hold=60):
    """max_hold=60 candles = 10 days on 4h, 60 days on 1d"""
    wins = losses = 0
    n = p["n"]; i = 60
    while i < n - 1:
        if not fn(p, i): i += 1; continue
        ep = p["c"][i]; sl_p = ep*(1-sl); tp_p = ep*(1+tp)
        result = None; j = i + 1
        while j < min(i + max_hold + 1, n):
            if p["l"][j] <= sl_p: result = "LOSS"; break
            if p["h"][j] >= tp_p: result = "WIN";  break
            j += 1
        if result == "WIN": wins += 1
        else: losses += 1
        i = j + 1
    return wins, losses

# Fetch data
print("Fetching swing trade data (4h + 1d, max history)...\n")
data = {}; days_map = {}
for tf, n in TF_CONFIG.items():
    data[tf] = {}
    for pair in PAIRS:
        print(f"  {pair} {tf}...", flush=True)
        raw = fetch_max(pair, tf, n)
        data[tf][pair] = precompute(raw)
        days_map[(tf, pair)] = len(raw["close"]) / CPD[tf]
print()

all_results = []

for tf in TF_CONFIG:
    # max_hold: 60 candles on 4h = 10 days, 30 candles on 1d = 30 days
    max_hold = 60 if tf == "4h" else 30
    avg_days = sum(days_map[(tf, p)] for p in PAIRS) / 3

    for sname, sfn in STRATS.items():
        for sl, tp in SL_TP_GRID:
            tw = tl = 0
            for pair in PAIRS:
                w, l = backtest(data[tf][pair], sfn, sl, tp, max_hold)
                tw += w; tl += l
            total = tw + tl
            if total < 15: continue
            wr = tw / total
            ev = wr * tp - (1 - wr) * sl
            tpm = total / avg_days * 30  # trades per month
            if ev <= 0: continue
            if not (0.5 <= tpm <= 30): continue  # 0.5-30 trades/month
            all_results.append({
                "tf": tf, "strat": sname, "sl": sl, "tp": tp,
                "wins": tw, "losses": tl, "total": total,
                "wr": round(wr*100, 1), "ev": round(ev*100, 3),
                "rr": round(tp/sl, 1), "tpm": round(tpm, 1),
                "days": round(avg_days, 0),
                "be": round(sl/(sl+tp)*100, 1),
                # Monthly return with 50% position size
                "monthly_50": round((wr*(1+0.5*tp) + (1-wr)*(1-0.5*sl) - 1) * tpm * 100, 2),
            })

all_results.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)
print(f"Found {len(all_results)} profitable swing results\n")

print("=" * 115)
print("TOP 25 SWING STRATEGIES  (TP=10-30%, SL=3-8%, positive EV)")
print("=" * 115)
print(f"  {'#':<3} {'TF':<4} {'Strategy':<26} {'SL':>5} {'TP':>5} {'R/R':>5} | "
      f"{'N':>5} {'WR%':>6} {'EV%':>7} {'T/mo':>6} {'Days':>5} | {'Mo% @50%pos':>11}")
print(f"  {'-'*110}")

seen = set(); count = 0
for r in all_results:
    key = (r["tf"], r["strat"])
    if key in seen: continue
    seen.add(key)
    count += 1
    print(f"  {count:<3} {r['tf']:<4} {r['strat']:<26} {r['sl']*100:>5.1f} {r['tp']*100:>5.1f} {r['rr']:>4.1f}:1 | "
          f"{r['total']:>5} {r['wr']:>5.1f}% {r['ev']:>+6.2f}% "
          f"{r['tpm']:>5.1f}/mo {r['days']:>5.0f}d | {r['monthly_50']:>+10.2f}%")
    if count >= 25: break

print(f"\n{'='*115}")
print("CHAMPION PER TIMEFRAME")
print(f"{'='*115}")
for tf in TF_CONFIG:
    tf_res = [r for r in all_results if r["tf"] == tf]
    seen2 = set(); top = []
    for r in tf_res:
        if r["strat"] not in seen2:
            seen2.add(r["strat"]); top.append(r)
        if len(top) >= 5: break
    print(f"\n  [{tf}]  history={tf_res[0]['days'] if tf_res else 0:.0f}d")
    for i, r in enumerate(top):
        print(f"    #{i+1} {r['strat']:<26}  SL={r['sl']*100:.0f}% TP={r['tp']*100:.0f}% ({r['rr']:.1f}:1)  "
              f"WR={r['wr']:.1f}%  EV={r['ev']:+.2f}%  {r['tpm']:.1f} trades/mo  Monthly@50%pos={r['monthly_50']:+.1f}%")
