"""
DEEP R/R SEARCH
Goal: highest win rate where TP >= 2x SL (proper risk/reward)
Constraint: SL <= TP/2  =>  breakeven <= 33.3%
Timeframes: 15m, 30m, 1h, 4h
All strategies from fast_backtest
Backtest: non-overlapping, max_hold=500, unresolved=LOSS
"""
import requests, time, math
from datetime import datetime
from fast_backtest import precompute, STRATS

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

TF_CONFIG = {
    "15m": 20000,   # ~208 days
    "30m": 20000,   # ~416 days
    "1h":  20000,   # ~833 days
    "4h":  15000,   # ~2500 days
}
CPD = {"15m": 96, "30m": 48, "1h": 24, "4h": 6}

# R/R grid: TP >= 2x SL only
# breakeven = SL/(SL+TP) <= 33.3%
SL_TP_GRID = []
for sl in [0.003, 0.005, 0.007, 0.008, 0.010, 0.012, 0.015, 0.018, 0.020, 0.025, 0.030]:
    for mult in [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
        tp = round(sl * mult, 4)
        SL_TP_GRID.append((sl, tp))

# Remove duplicates
SL_TP_GRID = list(set(SL_TP_GRID))
SL_TP_GRID.sort()

print(f"R/R combos: {len(SL_TP_GRID)} (all TP >= 2x SL)")
print(f"Strategies: {len(STRATS)}")
print(f"Timeframes: {list(TF_CONFIG.keys())}")
print(f"Total combos: {len(SL_TP_GRID)*len(STRATS)*len(TF_CONFIG)}\n")

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

def backtest(p, fn, sl, tp, max_hold=500):
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

# ── Fetch all data ────────────────────────────────────────────────────────────
print("Fetching data...")
data = {}
days_map = {}
for tf, n in TF_CONFIG.items():
    data[tf] = {}
    for pair in PAIRS:
        print(f"  {pair} {tf}...", flush=True)
        raw = fetch_max(pair, tf, n)
        data[tf][pair] = precompute(raw)
        days_map[(tf, pair)] = len(raw["close"]) / CPD[tf]
print()

# ── Run exhaustive backtest ───────────────────────────────────────────────────
all_results = []
total = len(STRATS) * len(TF_CONFIG) * len(SL_TP_GRID)
done = 0

for tf in TF_CONFIG:
    avg_days = sum(days_map[(tf, p)] for p in PAIRS) / 3
    for sname, sfn in STRATS.items():
        for sl, tp in SL_TP_GRID:
            tw = tl = 0
            for pair in PAIRS:
                w, l = backtest(data[tf][pair], sfn, sl, tp)
                tw += w; tl += l
            done += 1
            total_trades = tw + tl
            if total_trades < 20: continue
            wr = tw / total_trades
            ev = wr * tp - (1 - wr) * sl
            tpd = total_trades / avg_days
            if ev <= 0: continue
            if not (0.2 <= tpd <= 15): continue
            all_results.append({
                "tf": tf, "strat": sname, "sl": sl, "tp": tp,
                "wins": tw, "losses": tl, "total": total_trades,
                "wr": round(wr*100, 2), "ev": round(ev*100, 4),
                "rr": round(tp/sl, 1), "tpd": round(tpd, 2),
                "days": round(avg_days, 0),
                "breakeven": round(sl/(sl+tp)*100, 1),
            })
        if done % (len(SL_TP_GRID) * 3) == 0:
            print(f"  {done}/{total} ({done/total*100:.0f}%)...", flush=True)

print(f"\nFound {len(all_results)} profitable results with TP>=2xSL\n")

# ── Sort by WR ────────────────────────────────────────────────────────────────
all_results.sort(key=lambda x: (x["wr"], x["ev"]), reverse=True)

print("=" * 110)
print(f"TOP 30 BY WIN RATE  (TP >= 2x SL, positive EV, 0.2-15 trades/day, non-overlapping, unresolved=LOSS)")
print("=" * 110)
print(f"  {'#':<3} {'TF':<5} {'Strategy':<26} {'SL':>5} {'TP':>6} {'R/R':>5} | "
      f"{'N':>5} {'WR%':>6} {'EV%':>7} {'T/day':>6} {'Days':>5} {'BE%':>5}")
print(f"  {'-'*105}")

seen = set()
count = 0
for r in all_results:
    key = (r["tf"], r["strat"])
    if key in seen: continue
    seen.add(key)
    count += 1
    rr_str = f"{r['rr']:.1f}:1"
    print(f"  {count:<3} {r['tf']:<5} {r['strat']:<26} {r['sl']*100:>5.2f} {r['tp']*100:>6.2f} {rr_str:>5} | "
          f"{r['total']:>5} {r['wr']:>5.1f}% {r['ev']:>+6.3f}% "
          f"{r['tpd']:>5.1f}/d {r['days']:>5.0f}d {r['breakeven']:>4.1f}%")
    if count >= 30: break

# ── Top per TF ────────────────────────────────────────────────────────────────
print(f"\n{'='*110}")
print("CHAMPION PER TIMEFRAME (best WR with TP>=2xSL)")
print(f"{'='*110}")
for tf in TF_CONFIG:
    tf_res = [r for r in all_results if r["tf"] == tf]
    seen2 = set(); top = []
    for r in tf_res:
        if r["strat"] not in seen2:
            seen2.add(r["strat"]); top.append(r)
        if len(top) >= 5: break
    print(f"\n  [{tf}]  history={tf_res[0]['days'] if tf_res else 0:.0f}d")
    for i, r in enumerate(top):
        print(f"    #{i+1} {r['strat']:<26}  SL={r['sl']*100:.2f}% TP={r['tp']*100:.2f}% ({r['rr']:.1f}:1)  "
              f"WR={r['wr']:.1f}%  EV={r['ev']:+.3f}%  N={r['total']}  {r['tpd']:.1f}/day")

print(f"\n\nDone in {len(all_results)} profitable combos found.")
