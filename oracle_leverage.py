"""
The Oracle — ADX_Trend 1h — tested with 50x leverage
$10,000 capital, $500 margin/trade, 50x = $25,000 exposure per trade
"""
import requests, time, math, sys
from datetime import datetime, timezone
from fast_backtest import precompute, STRATS
from paper.competition_agents import PAIRS

CAPITAL   = 10_000.0
MARGIN    = 500.0       # margin per trade (5% of capital)
LEVERAGE  = 50
EXPOSURE  = MARGIN * LEVERAGE  # $25,000 per trade
SL        = 0.035
TP        = 0.020
TF        = "1h"
CANDLES   = 57240       # ~6.5 years (Jan 2020 - Jun 2026)

sfn = STRATS["ADX_Trend"]

def fetch(pair):
    all_c=[]; end=None
    for _ in range(math.ceil(CANDLES/1000)):
        url=f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={TF}&limit=1000"
        if end: url+=f"&endTime={end}"
        try:
            r=requests.get(url,timeout=15); r.raise_for_status()
            batch=r.json()
            if not batch: break
            all_c=batch+all_c
            end=int(batch[0][0])-1
            time.sleep(0.07)
        except Exception as e:
            print(f"  err {pair}: {e}"); break
    raw=all_c[-CANDLES:]
    return {
        "open": [float(c[1]) for c in raw], "high": [float(c[2]) for c in raw],
        "low":  [float(c[3]) for c in raw], "close":[float(c[4]) for c in raw],
        "vol":  [float(c[5]) for c in raw], "ts":   [int(c[0])   for c in raw],
    }

def backtest(raw, get_margin_fn=None):
    p = precompute(raw); n=p["n"]; i=60
    trades=[]
    while i < n-1:
        if not sfn(p,i): i+=1; continue
        ep   = p["c"][i]
        margin = get_margin_fn(i) if get_margin_fn else MARGIN
        exposure = margin * LEVERAGE
        sl_p = ep*(1-SL); tp_p = ep*(1+TP)
        qty  = exposure/ep
        ts   = raw["ts"][i]
        date = datetime.fromtimestamp(ts/1000, tz=timezone.utc).strftime("%Y-%m-%d")
        result="LOSS"; j=i+1
        while j < min(i+300+1,n):
            if p["l"][j]<=sl_p: result="LOSS"; break
            if p["h"][j]>=tp_p: result="WIN";  break
            j+=1
        pnl = qty*(tp_p-ep) if result=="WIN" else qty*(sl_p-ep)
        if pnl < -margin: pnl = -margin; result="LIQ"
        trades.append({"date":date,"result":result,"pnl":round(pnl,2),"pair":"","margin":round(margin,2)})
        i=j+1
    return trades

print(f"\n{'='*65}")
print(f"  THE ORACLE  x{LEVERAGE} LEVERAGE — 1 Month Backtest")
print(f"  Capital: ${CAPITAL:,.0f} | Margin/trade: ${MARGIN:.0f} | Exposure: ${EXPOSURE:,.0f}/trade")
print(f"  SL={SL*100:.1f}% | TP={TP*100:.1f}% | SL$=${EXPOSURE*SL:,.0f} | TP$=${EXPOSURE*TP:,.0f}")
print(f"{'='*65}\n")

print("Fetching data...", flush=True)
raw_data = {}
for pair in PAIRS:
    sys.stdout.write(f"  {pair}...\r"); sys.stdout.flush()
    raw_data[pair] = fetch(pair)
print("\nRunning compound backtest (5% of balance per trade)...\n")

# Collect all raw trades across pairs
all_raw_trades = []
for pair in PAIRS:
    trades = backtest(raw_data[pair])
    for t in trades: t["pair"] = pair
    all_raw_trades.extend(trades)

# Sort chronologically then apply compound sizing
all_raw_trades.sort(key=lambda t: t["date"])
compound_balance = CAPITAL
all_trades = []
pair_pnl = {p: {"pnl":0.0,"trades":0,"wins":0} for p in PAIRS}

for t in all_raw_trades:
    margin   = max(10, compound_balance * 0.05)
    exposure = margin * LEVERAGE
    if t["result"] == "WIN":
        pnl = round(exposure * TP, 2)
    else:
        pnl = -round(margin, 2)
    compound_balance = max(0, compound_balance + pnl)
    t["pnl"] = pnl; t["margin"] = round(margin,2); t["balance_after"] = round(compound_balance,2)
    all_trades.append(t)
    pair_pnl[t["pair"]]["pnl"]    += pnl
    pair_pnl[t["pair"]]["trades"] += 1
    if t["result"] == "WIN": pair_pnl[t["pair"]]["wins"] += 1
    if compound_balance <= 0: print("  *** ACCOUNT WIPED ***"); break

print(f"\nDone.\n")

# Sort by date and track running balance
all_trades.sort(key=lambda t: t["date"])
running = CAPITAL; peak = CAPITAL; max_dd = 0; liquidated = False

for t in all_trades:
    running += t["pnl"]
    if running > peak: peak = running
    dd = peak - running
    if dd > max_dd: max_dd = dd
    if running <= 0:
        liquidated = True
        break

wins   = [t for t in all_trades if t["result"]=="WIN"]
losses = [t for t in all_trades if t["result"]=="SL"]
liqs   = [t for t in all_trades if t["result"]=="LIQ"]
total  = len(all_trades)
wr     = len(wins)/total*100 if total>0 else 0
pnl    = sum(t["pnl"] for t in all_trades)
roi    = pnl/CAPITAL*100
final  = max(0, CAPITAL+pnl)

print(f"  Trades:      {total} ({total/31:.1f}/day)")
print(f"  Win Rate:    {wr:.1f}%  ({len(wins)}W / {len(losses)}L / {len(liqs)} Liquidated)")
print(f"  Monthly PnL: ${pnl:>+,.2f}  ({roi:>+.2f}% ROI)")
print(f"  Daily avg:   ${pnl/31:>+.2f}/day")
print(f"  Final bal:   ${final:>,.2f}")
print(f"  Max DD:      ${max_dd:>,.2f}  ({max_dd/CAPITAL*100:.1f}% of capital)")
print(f"  Avg win:     ${sum(t['pnl'] for t in wins)/len(wins):>+.2f}" if wins else "  Avg win: —")
print(f"  Avg loss:    ${sum(t['pnl'] for t in losses)/len(losses):>+.2f}" if losses else "  Avg loss: —")
if wins:
    best = max(all_trades, key=lambda t: t["pnl"])
    worst= min(all_trades, key=lambda t: t["pnl"])
    print(f"  Best trade:  +${best['pnl']:.2f} on {best['pair']} ({best['date']})")
    print(f"  Worst trade: ${worst['pnl']:.2f} on {worst['pair']} ({worst['date']})")

print(f"\n  {'='*50}")
print(f"  COMPARE: No Leverage vs x{LEVERAGE} Leverage")
print(f"  {'='*50}")
print(f"  No leverage:  +$117.50  (+1.18%)  MaxDD=$25")
print(f"  x{LEVERAGE} leverage:  ${pnl:>+,.2f}  ({roi:>+.2f}%)  MaxDD=${max_dd:,.0f}")
print(f"  Multiplier:   x{abs(pnl/117.5):.1f}" if pnl != 0 else "")


# Monthly breakdown
from collections import defaultdict
monthly_pnl    = defaultdict(float)
monthly_trades = defaultdict(int)
monthly_wins   = defaultdict(int)
monthly_liqs   = defaultdict(int)
for t in all_trades:
    mo = t["date"][:7]
    monthly_pnl[mo]    += t["pnl"]
    monthly_trades[mo] += 1
    if t["result"] == "WIN": monthly_wins[mo] += 1
    if t["result"] == "LIQ": monthly_liqs[mo] += 1

print(f"\n  MONTHLY BREAKDOWN BY YEAR (x{LEVERAGE} leverage):")
cumulative = 0
years = sorted(set(mo[:4] for mo in monthly_pnl.keys()))
MONTH_NAMES = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

for year in years:
    year_pnl    = sum(monthly_pnl[f"{year}-{m:02d}"] for m in range(1,13) if f"{year}-{m:02d}" in monthly_pnl)
    year_trades = sum(monthly_trades[f"{year}-{m:02d}"] for m in range(1,13) if f"{year}-{m:02d}" in monthly_trades)
    year_liqs   = sum(monthly_liqs[f"{year}-{m:02d}"] for m in range(1,13) if f"{year}-{m:02d}" in monthly_liqs)
    ysign = "+" if year_pnl >= 0 else ""
    print(f"\n  {'='*65}")
    print(f"  {year}   |  Annual PnL: {ysign}${year_pnl:>10,.0f}  |  Trades: {year_trades}  |  LIQs: {year_liqs}")
    print(f"  {'='*65}")
    print(f"  {'Month':<6} {'Trades':>7} {'WR%':>6} {'LIQ':>6}  {'Monthly PnL':>12}  {'Cumulative':>12}  Status")
    print(f"  {'-'*62}")
    for m in range(1, 13):
        mo = f"{year}-{m:02d}"
        if mo not in monthly_pnl:
            print(f"  {MONTH_NAMES[m]:<6} {'—':>7} {'—':>6} {'—':>6}  {'no data':>12}  {'':>12}")
            continue
        mp  = monthly_pnl[mo]
        mt  = monthly_trades[mo]
        mw  = monthly_wins[mo]
        ml  = monthly_liqs[mo]
        mwr = mw/mt*100 if mt>0 else 0
        cumulative += mp
        sign  = "+" if mp >= 0 else ""
        csign = "+" if cumulative >= 0 else ""
        liq_s = f"{ml}LIQ" if ml > 0 else ""
        status = "WIN" if mp > 0 else ("FLAT" if mp == 0 else "LOSS")
        bar = ("+" * min(15, int(mp/500))) if mp > 0 else ("-" * min(15, int(abs(mp)/500)))
        print(f"  {MONTH_NAMES[m]:<6} {mt:>7} {mwr:>5.0f}% {liq_s:>6}  {sign}${mp:>9,.0f}  {csign}${cumulative:>9,.0f}  {status} {bar}")

print(f"\n  PAIR BREAKDOWN:")
for pair, d in sorted(pair_pnl.items(), key=lambda x: -x[1]["pnl"]):
    sym  = pair.replace("USDT","")
    sign = "+" if d["pnl"]>=0 else ""
    wr_p = d["wins"]/d["trades"]*100 if d["trades"]>0 else 0
    bar  = ("+" if d["pnl"]>=0 else "-") * min(20, int(abs(d["pnl"])/50))
    print(f"  {sym:<6}  {sign}${d['pnl']:>8,.2f}  {d['trades']:>3} trades  WR={wr_p:.0f}%  {bar}")
