"""
1-Year Daily Profit Simulation
$10,000 capital, Keltner + Donchian on 10 pairs
Shows real daily/monthly P&L in USD
"""
import requests, time, math
from datetime import datetime, timezone
from collections import defaultdict
from fast_backtest import precompute, STRATS

PAIRS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","AVAXUSDT",
    "LINKUSDT","DOTUSDT","ADAUSDT","XRPUSDT","MATICUSDT"
]

CAPITAL      = 10_000.0
POSITION_PCT = 0.50        # 50% of per-pair allocation per trade
SL           = 0.025
TP           = 0.006
TF           = "15m"
CANDLES      = 35040       # 365 days of 15m

STRATEGIES = {
    "Keltner_Break":  STRATS.get("Keltner_Break")  or next(v for k,v in STRATS.items() if "keltner" in k.lower()),
    "Donchian_Break": STRATS.get("Donchian_Break") or next(v for k,v in STRATS.items() if "donchian" in k.lower() and "strict" not in k.lower()),
}

def fetch(pair, n):
    all_c=[]; end=None
    for _ in range(math.ceil(n/1000)):
        url=f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={TF}&limit=1000"
        if end: url+=f"&endTime={end}"
        try:
            r=requests.get(url,timeout=20); r.raise_for_status()
            batch=r.json()
            if not batch: break
            all_c=batch+all_c
            end=int(batch[0][0])-1
            time.sleep(0.08)
        except Exception as e:
            print(f"  error {pair}: {e}"); break
    raw=all_c[-n:]
    return {
        "open": [float(c[1]) for c in raw],
        "high": [float(c[2]) for c in raw],
        "low":  [float(c[3]) for c in raw],
        "close":[float(c[4]) for c in raw],
        "vol":  [float(c[5]) for c in raw],
        "ts":   [int(c[0])   for c in raw],
    }

def backtest_with_pnl(raw, signal_fn, pair, strategy, pos_size, sl, tp, max_hold=300):
    """Returns list of (date_str, pnl_usd, result)"""
    p = precompute(raw)
    n = p["n"]; i = 60
    trades = []
    while i < n-1:
        if not signal_fn(p, i): i+=1; continue
        ep   = p["c"][i]
        sl_p = ep*(1-sl); tp_p = ep*(1+tp)
        ts   = raw["ts"][i]
        date = datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime("%Y-%m-%d")

        result=None; j=i+1
        while j < min(i+max_hold+1, n):
            if p["l"][j]<=sl_p: result="LOSS"; break
            if p["h"][j]>=tp_p: result="WIN";  break
            j+=1
        if result is None: result="LOSS"

        qty = pos_size / ep
        if result=="WIN":
            pnl = qty * (tp_p - ep)
        else:
            pnl = qty * (sl_p - ep)

        trades.append({"date":date,"pnl":round(pnl,4),"result":result,
                       "pair":pair,"strat":strategy,"ep":ep})
        i=j+1
    return trades

# ── Fetch ──────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  1-YEAR DAILY P&L SIMULATION")
print(f"  Capital: ${CAPITAL:,.0f} | {len(PAIRS)} pairs | {len(STRATEGIES)} strategies")
print(f"  Strategy: Keltner + Donchian | SL={SL*100}% TP={TP*100}%")
print(f"  Position: {POSITION_PCT*100:.0f}% per-pair allocation per trade")
print(f"{'='*60}\n")

# Per-pair allocation
per_pair = CAPITAL / len(PAIRS)  # $1000 per pair
pos_size = per_pair * POSITION_PCT  # $500 per trade per pair
print(f"Per-pair capital: ${per_pair:,.0f}")
print(f"Position per trade: ${pos_size:,.0f}\n")

print("Fetching 1 year of 15m data...")
raw_data = {}
actual_days = {}
for pair in PAIRS:
    print(f"  {pair}...", flush=True)
    raw = fetch(pair, CANDLES)
    raw_data[pair] = raw
    days = len(raw["close"])/96
    actual_days[pair] = days
    print(f"    {len(raw['close'])} candles = {days:.0f} days")

avg_days = sum(actual_days.values())/len(actual_days)
print(f"\nAvg history: {avg_days:.0f} days\n")

# ── Run backtest ───────────────────────────────────────────────────────────────
print("Running backtest...")
all_trades = []
pair_strat_stats = {}

for pair in PAIRS:
    for sname, sfn in STRATEGIES.items():
        trades = backtest_with_pnl(raw_data[pair], sfn, pair, sname, pos_size, SL, TP)
        all_trades.extend(trades)
        w = sum(1 for t in trades if t["result"]=="WIN")
        l = len(trades)-w
        pnl = sum(t["pnl"] for t in trades)
        pair_strat_stats[f"{pair}_{sname}"] = {
            "total":len(trades),"wins":w,"losses":l,
            "wr":round(w/len(trades)*100,1) if trades else 0,
            "pnl":round(pnl,2)
        }
        print(f"  {pair} [{sname}]: {len(trades)} trades | {w}W/{l}L = {w/len(trades)*100:.1f}% WR | ${pnl:+.2f}")

# ── Group by date ──────────────────────────────────────────────────────────────
daily_pnl = defaultdict(float)
daily_trades = defaultdict(int)
daily_wins = defaultdict(int)

for t in all_trades:
    daily_pnl[t["date"]] += t["pnl"]
    daily_trades[t["date"]] += 1
    if t["result"]=="WIN": daily_wins[t["date"]] += 1

sorted_dates = sorted(daily_pnl.keys())

# ── Monthly summary ────────────────────────────────────────────────────────────
monthly_pnl = defaultdict(float)
monthly_trades = defaultdict(int)
monthly_wins = defaultdict(int)
for d in sorted_dates:
    mo = d[:7]
    monthly_pnl[mo] += daily_pnl[d]
    monthly_trades[mo] += daily_trades[d]
    monthly_wins[mo] += daily_wins[d]

print(f"\n{'='*70}")
print(f"MONTHLY BREAKDOWN")
print(f"{'='*70}")
print(f"  {'Month':<10} {'Trades':>7} {'WR%':>6} {'Daily Avg':>10} {'Monthly PnL':>12} {'Cumulative':>12}")
print(f"  {'-'*65}")

cumulative = 0
total_daily_profits = []
for mo in sorted(monthly_pnl.keys()):
    mp = monthly_pnl[mo]
    mt = monthly_trades[mo]
    mw = monthly_wins[mo]
    mwr = mw/mt*100 if mt>0 else 0
    days_in_mo = sum(1 for d in sorted_dates if d.startswith(mo))
    daily_avg = mp/days_in_mo if days_in_mo>0 else 0
    cumulative += mp
    total_daily_profits.extend([daily_pnl[d] for d in sorted_dates if d.startswith(mo)])
    color = "+" if mp>=0 else ""
    print(f"  {mo:<10} {mt:>7} {mwr:>5.1f}% {daily_avg:>+9.2f}$ {mp:>+11.2f}$ {cumulative:>+11.2f}$")

# ── Overall stats ──────────────────────────────────────────────────────────────
total_pnl = sum(daily_pnl.values())
total_t   = len(all_trades)
total_w   = sum(1 for t in all_trades if t["result"]=="WIN")
overall_wr= total_w/total_t*100 if total_t>0 else 0
avg_daily = total_pnl/len(sorted_dates) if sorted_dates else 0
avg_monthly = total_pnl/(avg_days/30) if avg_days>0 else 0

# Best/worst days
best_day  = max(daily_pnl.items(), key=lambda x:x[1])
worst_day = min(daily_pnl.items(), key=lambda x:x[1])
positive_days = sum(1 for v in daily_pnl.values() if v>0)
negative_days = sum(1 for v in daily_pnl.values() if v<0)

print(f"\n{'='*70}")
print(f"OVERALL RESULTS — {avg_days:.0f} days")
print(f"{'='*70}")
print(f"  Total trades:      {total_t:,}  ({total_t/avg_days:.1f}/day)")
print(f"  Win rate:          {overall_wr:.1f}%  ({total_w}W / {total_t-total_w}L)")
print(f"  Total PnL:         ${total_pnl:+,.2f}")
print(f"  Avg daily profit:  ${avg_daily:+.2f}")
print(f"  Avg monthly:       ${avg_monthly:+,.2f}")
print(f"  Best day:          ${best_day[1]:+.2f}  ({best_day[0]})")
print(f"  Worst day:         ${worst_day[1]:+.2f}  ({worst_day[0]})")
print(f"  Positive days:     {positive_days} ({positive_days/len(sorted_dates)*100:.0f}%)")
print(f"  Negative days:     {negative_days} ({negative_days/len(sorted_dates)*100:.0f}%)")
print(f"\n  Starting capital:  ${CAPITAL:,.2f}")
print(f"  Final capital:     ${CAPITAL+total_pnl:,.2f}  ({total_pnl/CAPITAL*100:+.1f}%)")
print(f"\n  To reach $100/day need:  {100/avg_daily:.1f}x more (bigger pos or more pairs)")
print(f"  Position needed for $100/day: ${pos_size*100/avg_daily:,.0f} per trade")
