"""
The Oracle — ADX_Trend 1h — June 2026 daily breakdown
$10,000 capital, $500 margin/trade, 50x leverage
"""
import requests, time, math, sys
from datetime import datetime, timezone
from collections import defaultdict
from fast_backtest import precompute, STRATS
from paper.competition_agents import PAIRS

CAPITAL  = 10_000.0
MARGIN   = 500.0
LEVERAGE = 50
SL       = 0.035
TP       = 0.020
TF       = "1h"
CANDLES  = 744   # ~31 days to ensure we have full June

sfn = STRATS["ADX_Trend"]

def fetch(pair):
    all_c=[]; end=None
    for _ in range(math.ceil(CANDLES/1000)):
        url=f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={TF}&limit=1000"
        if end: url+=f"&endTime={end}"
        try:
            r=requests.get(url,timeout=30); r.raise_for_status()
            batch=r.json()
            if not batch: break
            all_c=batch+all_c
            end=int(batch[0][0])-1
            time.sleep(0.06)
        except Exception as e:
            print(f"  err {pair}: {e}"); break
    raw=all_c[-CANDLES:]
    return {
        "open": [float(c[1]) for c in raw], "high": [float(c[2]) for c in raw],
        "low":  [float(c[3]) for c in raw], "close":[float(c[4]) for c in raw],
        "vol":  [float(c[5]) for c in raw], "ts":   [int(c[0])   for c in raw],
    }

def backtest(raw):
    p = precompute(raw); n=p["n"]; i=60
    trades=[]
    while i < n-1:
        if not sfn(p,i): i+=1; continue
        ep   = p["c"][i]
        sl_p = ep*(1-SL); tp_p = ep*(1+TP)
        exposure = MARGIN * LEVERAGE
        qty  = exposure/ep
        ts   = raw["ts"][i]
        dt   = datetime.fromtimestamp(ts/1000, tz=timezone.utc)
        date = dt.strftime("%Y-%m-%d")
        result="LOSS"; j=i+1
        while j < min(i+300+1,n):
            if p["l"][j]<=sl_p: result="LOSS"; break
            if p["h"][j]>=tp_p: result="WIN";  break
            j+=1
        pnl = qty*(tp_p-ep) if result=="WIN" else qty*(sl_p-ep)
        if pnl < -MARGIN: pnl=-MARGIN; result="LIQ"
        trades.append({
            "date": date, "result": result, "pnl": round(pnl,2),
            "pair": "", "ep": round(ep,4),
            "tp_p": round(tp_p,4), "sl_p": round(sl_p,4)
        })
        i=j+1
    return trades

# Fetch
print(f"\n{'='*60}")
print(f"  THE ORACLE — June 2026 Daily Breakdown")
print(f"  ADX_Trend | 1h | SL=3.5% | TP=2% | x50 leverage")
print(f"  $10,000 capital | $500 margin/trade | 10 pairs")
print(f"{'='*60}\n")

print("Fetching data...", flush=True)
all_trades = []
for pair in PAIRS:
    sys.stdout.write(f"  {pair}...\r"); sys.stdout.flush()
    raw    = fetch(pair)
    if len(raw.get("close",[])) < 100:
        print(f"  {pair} skipped (not enough data)")
        continue
    trades = backtest(raw)
    for t in trades:
        t["pair"] = pair
        if t["date"].startswith("2026-06"):
            all_trades.append(t)
print("Done.\n")

# Group by day
daily_pnl    = defaultdict(float)
daily_trades = defaultdict(list)

for t in all_trades:
    daily_pnl[t["date"]]    += t["pnl"]
    daily_trades[t["date"]].append(t)

# Print daily breakdown
print(f"  {'Date':<12} {'Trades':>7} {'W':>4} {'L':>4} {'WR%':>6} {'Daily PnL':>11} {'Cumulative':>12}  Pairs traded")
print(f"  {'-'*85}")

cumulative = 0
total_w = total_l = 0

for date in sorted(daily_pnl.keys()):
    trades = daily_trades[date]
    pnl    = daily_pnl[date]
    wins   = [t for t in trades if t["result"]=="WIN"]
    losses = [t for t in trades if t["result"] in ("LOSS","LIQ")]
    wr     = len(wins)/len(trades)*100 if trades else 0
    cumulative += pnl
    total_w += len(wins); total_l += len(losses)
    sign   = "+" if pnl >= 0 else ""
    csign  = "+" if cumulative >= 0 else ""
    pairs  = ", ".join(t["pair"].replace("USDT","") for t in trades)
    status = "WIN " if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT")
    bar    = ("+" * min(10, int(pnl/50))) if pnl > 0 else ("-" * min(10, int(abs(pnl)/50)))
    print(f"  {date:<12} {len(trades):>7} {len(wins):>4} {len(losses):>4} {wr:>5.0f}%  "
          f"{sign}${pnl:>8,.2f}  {csign}${cumulative:>9,.2f}  [{status}] {bar}")
    # Show individual trades
    for t in trades:
        r = "WIN " if t["result"]=="WIN" else "LOSS"
        psign = "+" if t["pnl"]>=0 else ""
        print(f"    {'':12} {'':>7}                    {t['pair'].replace('USDT',''):<6} {r}  {psign}${t['pnl']:>7.2f}  entry={t['ep']}")

# Summary
total = total_w + total_l
print(f"\n{'='*60}")
print(f"  JUNE 2026 SUMMARY")
print(f"{'='*60}")
print(f"  Total trades:  {total}  ({total_w}W / {total_l}L)")
print(f"  Win rate:      {total_w/total*100:.1f}%" if total>0 else "  Win rate: —")
print(f"  Total PnL:     ${cumulative:>+,.2f}")
print(f"  Daily avg:     ${cumulative/max(1,len(daily_pnl)):>+.2f}/day")
print(f"  Winning days:  {sum(1 for v in daily_pnl.values() if v>0)}/{len(daily_pnl)}")
print(f"  Losing days:   {sum(1 for v in daily_pnl.values() if v<0)}/{len(daily_pnl)}")
if daily_pnl:
    best  = max(daily_pnl.items(), key=lambda x:x[1])
    worst = min(daily_pnl.items(), key=lambda x:x[1])
    print(f"  Best day:      {best[0]}  +${best[1]:,.2f}")
    print(f"  Worst day:     {worst[0]}  ${worst[1]:,.2f}")
