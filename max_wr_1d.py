"""
Max WR search on 1D candles
All R/R combos, all strategies, candle pattern filters
Goal: absolute highest WR with positive EV
8+ years of history
"""
import requests, time, math
from fast_backtest import precompute, STRATS

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

def fetch_max(pair, n=3000):
    all_c = []; end = None
    for _ in range(math.ceil(n / 1000)):
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval=1d&limit=1000"
        if end: url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=20); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            time.sleep(0.1)
        except Exception as e:
            print(f"  error {pair}: {e}"); break
    raw = all_c[-n:]
    return {"open":[float(c[1]) for c in raw],"high":[float(c[2]) for c in raw],
            "low":[float(c[3]) for c in raw],"close":[float(c[4]) for c in raw],
            "vol":[float(c[5]) for c in raw]}

# ── Full R/R grid (all combos including inverted) ─────────────────────────────
SL_TP_GRID = []
for sl in [0.01,0.015,0.02,0.025,0.03,0.04,0.05,0.06,0.07,0.08,0.10]:
    for tp in [0.005,0.008,0.010,0.012,0.015,0.020,0.025,0.030,0.040,
               0.050,0.060,0.080,0.100,0.120,0.150,0.200]:
        if tp < sl * 0.2: continue   # tp must be at least 20% of sl
        SL_TP_GRID.append((sl, tp))
SL_TP_GRID = sorted(set(SL_TP_GRID))

print(f"R/R combos: {len(SL_TP_GRID)}")
print(f"Strategies: {len(STRATS)}")
print(f"Total: {len(SL_TP_GRID)*len(STRATS)} combos on 1D\n")

# ── Fetch ─────────────────────────────────────────────────────────────────────
print("Fetching 1D data (~8 years)...")
raw_data = {}
for pair in PAIRS:
    print(f"  {pair}...", flush=True)
    raw_data[pair] = fetch_max(pair, 3000)
    print(f"  {pair}: {len(raw_data[pair]['close'])} days ({len(raw_data[pair]['close'])/365:.1f}yr)")

pdata = {pair: precompute(raw_data[pair]) for pair in PAIRS}
avg_days = sum(len(raw_data[p]["close"]) for p in PAIRS) / 3
print()

# ── Backtest ──────────────────────────────────────────────────────────────────
def backtest(p, fn, sl, tp, max_hold=60):
    wins = losses = 0
    n = p["n"]; i = 60
    while i < n - 1:
        if not fn(p, i): i += 1; continue
        ep = p["c"][i]; sl_p = ep*(1-sl); tp_p = ep*(1+tp)
        result = None; j = i+1
        while j < min(i+max_hold+1, n):
            if p["l"][j] <= sl_p: result="LOSS"; break
            if p["h"][j] >= tp_p: result="WIN";  break
            j += 1
        if result=="WIN": wins+=1
        else: losses+=1
        i = j+1
    return wins, losses

# ── Run ───────────────────────────────────────────────────────────────────────
all_results = []
total_combos = len(STRATS) * len(SL_TP_GRID)
done = 0

for sname, sfn in STRATS.items():
    for sl, tp in SL_TP_GRID:
        tw = tl = 0
        for pair in PAIRS:
            w, l = backtest(pdata[pair], sfn, sl, tp)
            tw += w; tl += l
        done += 1
        total = tw + tl
        if total < 15: continue
        wr = tw/total
        ev = wr*tp - (1-wr)*sl
        tpm = total/avg_days*30
        be = sl/(sl+tp)
        if ev <= 0: continue
        if not (0.3 <= tpm <= 20): continue
        all_results.append({
            "strat": sname, "sl": sl, "tp": tp,
            "wins": tw, "losses": tl, "total": total,
            "wr": round(wr*100,1), "ev": round(ev*100,3),
            "rr": round(tp/sl,2), "tpm": round(tpm,1),
            "be": round(be*100,1), "days": round(avg_days,0),
        })
    if done % (len(SL_TP_GRID)*5) == 0:
        print(f"  {done}/{total_combos} ({done/total_combos*100:.0f}%)...", flush=True)

all_results.sort(key=lambda x:(x["wr"],x["ev"]), reverse=True)
print(f"\nFound {len(all_results)} profitable results\n")

# ── Top 40 by WR ──────────────────────────────────────────────────────────────
print("="*115)
print("TOP 40 BY WIN RATE — 1D candles, all strategies, all R/R, positive EV")
print("="*115)
print(f"  {'#':<3} {'Strategy':<26} {'SL':>5} {'TP':>6} {'R/R':>6} {'BE%':>5} | "
      f"{'N':>5} {'WR%':>6} {'EV%':>7} {'T/mo':>6}")
print(f"  {'-'*110}")

seen = set(); count = 0
for r in all_results:
    key = (r["strat"],)
    if key in seen: continue
    seen.add(key); count += 1
    rr = f"{r['rr']:.2f}:1" if r['rr'] < 1 else f"{r['rr']:.1f}:1"
    print(f"  {count:<3} {r['strat']:<26} {r['sl']*100:>5.1f} {r['tp']*100:>6.1f} {rr:>6} {r['be']:>4.1f}% | "
          f"{r['total']:>5} {r['wr']:>5.1f}% {r['ev']:>+6.3f}% {r['tpm']:>5.1f}/mo")
    if count >= 40: break

# ── Top 10 detailed ───────────────────────────────────────────────────────────
print(f"\n{'='*115}")
print("TOP 10 DETAILED — best SL/TP per strategy")
print(f"{'='*115}")
seen2=set(); count2=0
for r in all_results:
    if r["strat"] in seen2: continue
    seen2.add(r["strat"]); count2+=1
    print(f"\n  #{count2} {r['strat']}  [{r['sl']*100:.1f}% SL / {r['tp']*100:.1f}% TP  ({r['rr']:.2f}:1 R/R)]")
    print(f"      WR={r['wr']}%  EV={r['ev']:+.3f}%/trade  Breakeven={r['be']}%")
    print(f"      {r['wins']}W / {r['losses']}L = {r['total']} trades over {r['days']:.0f}d  ({r['tpm']:.1f}/mo)")
    if count2 >= 10: break

print(f"\n\nDone. Best WR = {all_results[0]['wr']}% ({all_results[0]['strat']})")
