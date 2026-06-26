"""
MAX ANNUAL PROFIT - FAST VERSION
Uses numpy for speed, tests all strategies/TFs/RR combos
"""
import requests, time, math, sys
import numpy as np
from fast_backtest import precompute, STRATS

PAIRS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","AVAXUSDT",
    "LINKUSDT","DOTUSDT","ADAUSDT","XRPUSDT","MATICUSDT"
]
CAPITAL  = 10_000.0
POS_SIZE = 500.0

TF_CONFIG = {"15m":35040,"1h":8760,"4h":2190}
CPD       = {"15m":96,"1h":24,"4h":6}

SL_LIST = [0.005,0.008,0.010,0.012,0.015,0.018,0.020,0.025,0.030,0.035,0.040,0.050,0.060,0.070,0.080]
TP_LIST = [0.003,0.005,0.006,0.008,0.010,0.012,0.015,0.018,0.020,0.025,0.030,0.040,0.050,0.060,0.080,0.100,0.120,0.150]

def fetch(pair, tf, n):
    all_c=[]; end=None
    for _ in range(math.ceil(n/1000)):
        url=f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit=1000"
        if end: url+=f"&endTime={end}"
        try:
            r=requests.get(url,timeout=20); r.raise_for_status()
            batch=r.json()
            if not batch: break
            all_c=batch+all_c
            end=int(batch[0][0])-1
            time.sleep(0.06)
        except Exception as e:
            print(f"  err {pair} {tf}: {e}"); break
    raw=all_c[-n:]
    return {"open":[float(c[1]) for c in raw],"high":[float(c[2]) for c in raw],
            "low":[float(c[3]) for c in raw],"close":[float(c[4]) for c in raw],
            "vol":[float(c[5]) for c in raw]}

def get_signals(p, sfn):
    """Get all signal indices for a strategy."""
    n = p["n"]
    sigs = []
    i = 60
    while i < n-1:
        if sfn(p, i): sigs.append(i)
        i += 1
    return np.array(sigs, dtype=np.int32)

def backtest_fast(sigs, p_arr, sl, tp, pos=POS_SIZE, max_hold=300):
    H = p_arr["h"]; L = p_arr["l"]; C = p_arr["c"]
    n = len(C)
    pnl = 0.0; wins = 0; losses = 0
    running = 0.0; peak = 0.0; max_dd = 0.0
    idx = 0
    while idx < len(sigs):
        i = int(sigs[idx])
        ep = C[i]
        sl_p = ep * (1 - sl)
        tp_p = ep * (1 + tp)
        qty = pos / ep
        result = "LOSS"
        end_j = i + 1
        end = min(i + max_hold + 1, n)
        for j in range(i+1, end):
            end_j = j
            if L[j] <= sl_p: result = "LOSS"; break
            if H[j] >= tp_p: result = "WIN";  break
        if result == "WIN":
            pnl_t = qty * (tp_p - ep); wins += 1
        else:
            pnl_t = qty * (sl_p - ep); losses += 1
        pnl += pnl_t
        running += pnl_t
        if running > peak: peak = running
        dd = peak - running
        if dd > max_dd: max_dd = dd
        idx += 1
        while idx < len(sigs) and sigs[idx] <= end_j:
            idx += 1
    return pnl, wins, losses, max_dd

# ── Fetch data ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  MAX ANNUAL PROFIT FAST SEARCH")
print(f"  $10,000 | 10 pairs | {len(STRATS)} strategies")
print(f"{'='*60}\n")

print("Fetching data...", flush=True)
data = {}
for tf in TF_CONFIG:
    data[tf] = {}
    for pair in PAIRS:
        sys.stdout.write(f"  {pair} {tf}...\r"); sys.stdout.flush()
        raw = fetch(pair, tf, TF_CONFIG[tf])
        p = precompute(raw)
        # Convert to numpy for speed
        data[tf][pair] = {
            "p": p,
            "h": np.array(p["h"]),
            "l": np.array(p["l"]),
            "c": np.array(p["c"]),
            "n": p["n"]
        }
print("\nData fetched.\n")

# ── Pre-compute signals ────────────────────────────────────────────────────
print("Pre-computing signals...", flush=True)
signals = {}  # (tf, pair, sname) -> np.array of indices
for tf in TF_CONFIG:
    for pair in PAIRS:
        p = data[tf][pair]["p"]
        for sname, sfn in STRATS.items():
            key = (tf, pair, sname)
            signals[key] = get_signals(p, sfn)
print(f"Done. {len(signals)} signal sets.\n")

# ── Exhaustive search ──────────────────────────────────────────────────────
print("Running backtest...\n", flush=True)
all_results = []
total_combos = len(STRATS) * len(TF_CONFIG) * len(SL_LIST) * len(TP_LIST)
done = 0

for tf in TF_CONFIG:
    days = TF_CONFIG[tf] / CPD[tf]
    for sname in STRATS:
        for sl in SL_LIST:
            for tp in TP_LIST:
                if tp < sl * 0.15: done+=1; continue
                tw = tl = 0
                total_pnl = 0.0
                max_dd = 0.0
                for pair in PAIRS:
                    p_arr = data[tf][pair]
                    sigs = signals[(tf, pair, sname)]
                    if len(sigs) == 0: continue
                    pnl, w, l, dd = backtest_fast(sigs, p_arr, sl, tp)
                    total_pnl += pnl; tw += w; tl += l
                    max_dd = max(max_dd, dd)
                done += 1
                total_t = tw + tl
                if total_t < 10: continue
                wr = tw / total_t
                ev = wr*tp - (1-wr)*sl
                if ev <= 0: continue
                annual_pnl = total_pnl * (365 / days)
                pf = total_pnl / max_dd if max_dd > 0 else 999
                all_results.append({
                    "tf":tf,"strat":sname,"sl":sl,"tp":tp,
                    "wins":tw,"losses":tl,"total":total_t,
                    "wr":round(wr*100,1),"ev":round(ev*100,4),
                    "rr":round(tp/sl,2),
                    "tpd":round(total_t/days,1),
                    "annual_pnl":round(annual_pnl,2),
                    "max_dd":round(max_dd,2),
                    "pf":round(pf,2),
                    "roi":round(annual_pnl/CAPITAL*100,2),
                })
        pct = done/total_combos*100
        print(f"  [{tf}] {sname:<28} {pct:5.1f}%  results so far: {len(all_results)}", flush=True)

all_results.sort(key=lambda x: x["annual_pnl"], reverse=True)
print(f"\nTotal profitable combos: {len(all_results)}\n")

# ── TOP 30 ─────────────────────────────────────────────────────────────────
print("="*120)
print(f"TOP 30 BY ANNUAL DOLLAR PROFIT  ($10k capital, $500/trade, 10 pairs)")
print("="*120)
print(f"  {'#':<3} {'TF':<5} {'Strategy':<26} {'SL%':>5} {'TP%':>6} {'R/R':>6} | "
      f"{'WR%':>6} {'T/d':>5} | {'Annual $':>10} {'ROI%':>7} {'MaxDD$':>8} {'PF':>6}")
print(f"  {'-'*115}")

seen = set(); count = 0
for r in all_results:
    key = (r["tf"], r["strat"])
    if key in seen: continue
    seen.add(key); count += 1
    rr = f"{r['rr']:.1f}:1" if r['rr'] >= 1 else f"1:{1/r['rr']:.1f}"
    pf_s = f"{r['pf']:.1f}" if r['pf'] < 99 else ">99"
    print(f"  {count:<3} {r['tf']:<5} {r['strat']:<26} {r['sl']*100:>5.1f} {r['tp']*100:>6.1f} {rr:>6} | "
          f"{r['wr']:>5.1f}% {r['tpd']:>4.1f}/d | "
          f"${r['annual_pnl']:>+9,.0f} {r['roi']:>+6.1f}% ${r['max_dd']:>7,.0f} {pf_s:>6}")
    if count >= 30: break

# ── TOP 5 DETAILED ─────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print("TOP 5 DETAILED")
print(f"{'='*70}")
seen2 = set(); count2 = 0
for r in all_results:
    key = (r["tf"], r["strat"])
    if key in seen2: continue
    seen2.add(key); count2 += 1
    print(f"\n  #{count2}  [{r['tf']}] {r['strat']}")
    print(f"       SL={r['sl']*100:.1f}%  TP={r['tp']*100:.1f}%  R/R={r['rr']:.2f}:1  WR={r['wr']}%")
    print(f"       Trades: {r['total']} ({r['tpd']:.1f}/day)  EV={r['ev']:+.4f}%")
    print(f"       Annual PnL:  ${r['annual_pnl']:>+,.0f}  ({r['roi']:+.1f}% ROI)")
    print(f"       Monthly avg: ${r['annual_pnl']/12:>+,.0f}/month")
    print(f"       Daily avg:   ${r['annual_pnl']/365:>+,.0f}/day")
    print(f"       Max DD:      ${r['max_dd']:,.0f}  PF={r['pf']:.2f}")
    if count2 >= 5: break

# ── CHAMPION PER TF ────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print("BEST PER TIMEFRAME")
print(f"{'='*70}")
for tf in TF_CONFIG:
    sub = [r for r in all_results if r["tf"]==tf]
    seen3 = set(); top = []
    for r in sub:
        if r["strat"] not in seen3:
            seen3.add(r["strat"]); top.append(r)
        if len(top) >= 3: break
    print(f"\n  [{tf}]")
    for i, r in enumerate(top):
        print(f"    #{i+1} {r['strat']:<28} SL={r['sl']*100:.1f}% TP={r['tp']*100:.1f}%  "
              f"WR={r['wr']:.1f}%  Annual=${r['annual_pnl']:>+,.0f}  "
              f"Daily=${r['annual_pnl']/365:>+.0f}  MaxDD=${r['max_dd']:,.0f}")

# ── $100/day calc ──────────────────────────────────────────────────────────
if all_results:
    b = all_results[0]
    daily = b["annual_pnl"] / 365
    needed = POS_SIZE * (100 / daily) if daily > 0 else 0
    print(f"\n{'='*70}")
    print(f"TO MAKE $100/DAY with best strategy [{b['tf']}] {b['strat']}:")
    print(f"  Current: ${daily:+.2f}/day at $500/trade")
    print(f"  Need:    ${needed:,.0f}/trade = {needed/CAPITAL*100:.0f}% of $10k per trade")
    print(f"  OR:      run on {100/daily:.0f}x more pairs")
