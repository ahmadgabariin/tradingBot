"""
MAX ANNUAL DOLLAR PROFIT SEARCH
$10,000 capital, 10 pairs, all strategies, all timeframes, all R/R combos
Goal: highest dollar profit per year, lowest risk (max drawdown)
"""
import requests, time, math
from collections import defaultdict
from fast_backtest import precompute, STRATS

PAIRS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","AVAXUSDT",
    "LINKUSDT","DOTUSDT","ADAUSDT","XRPUSDT","MATICUSDT"
]
CAPITAL    = 10_000.0
POS_SIZE   = 500.0   # $500 per trade (5% of capital — conservative)

TF_CONFIG = {
    "15m": 35040,   # 365 days
    "1h":  8760,    # 365 days
    "4h":  2190,    # 365 days
}
CPD = {"15m":96,"1h":24,"4h":6}

# Full R/R grid — every combination
SL_TP = []
for sl in [0.005,0.008,0.010,0.012,0.015,0.018,0.020,0.025,0.030,0.035,0.040,0.050,0.060,0.070,0.080]:
    for tp in [0.003,0.005,0.006,0.008,0.010,0.012,0.015,0.018,0.020,0.025,0.030,0.040,0.050,0.060,0.080,0.100,0.120,0.150]:
        if tp < sl * 0.15: continue
        SL_TP.append((sl,tp))
SL_TP = sorted(set(SL_TP))

def fetch(pair, tf, n):
    all_c=[]; end=None
    limit=1000
    for _ in range(math.ceil(n/limit)):
        url=f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit={limit}"
        if end: url+=f"&endTime={end}"
        try:
            r=requests.get(url,timeout=20); r.raise_for_status()
            batch=r.json()
            if not batch: break
            all_c=batch+all_c
            end=int(batch[0][0])-1
            time.sleep(0.07)
        except Exception as e:
            print(f"  err {pair} {tf}: {e}"); break
    raw=all_c[-n:]
    return {"open":[float(c[1]) for c in raw],"high":[float(c[2]) for c in raw],
            "low":[float(c[3]) for c in raw],"close":[float(c[4]) for c in raw],
            "vol":[float(c[5]) for c in raw]}

def backtest_dollar(p, fn, sl, tp, pos, max_hold=300):
    """Returns (dollar_pnl, wins, losses, max_drawdown)"""
    wins=losses=0
    running=0.0
    peak=0.0
    max_dd=0.0
    n=p["n"]; i=60
    while i<n-1:
        if not fn(p,i): i+=1; continue
        ep=p["c"][i]
        sl_p=ep*(1-sl); tp_p=ep*(1+tp)
        qty=pos/ep
        result=None; j=i+1
        while j<min(i+max_hold+1,n):
            if p["l"][j]<=sl_p: result="LOSS"; break
            if p["h"][j]>=tp_p: result="WIN";  break
            j+=1
        if result is None: result="LOSS"
        if result=="WIN":
            pnl=qty*(tp_p-ep); wins+=1
        else:
            pnl=qty*(sl_p-ep); losses+=1
        running+=pnl
        if running>peak: peak=running
        dd=peak-running
        if dd>max_dd: max_dd=dd
        i=j+1
    return running,wins,losses,max_dd

# ── Fetch all data ─────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print(f"  MAX ANNUAL PROFIT SEARCH")
print(f"  ${CAPITAL:,.0f} capital | {len(PAIRS)} pairs | {len(STRATS)} strategies")
print(f"  {len(TF_CONFIG)} timeframes | {len(SL_TP)} R/R combos")
print(f"  Total combos: {len(STRATS)*len(TF_CONFIG)*len(SL_TP):,}")
print(f"{'='*65}\n")

print("Fetching 365 days of data for all pairs & timeframes...")
data={}
for tf in TF_CONFIG:
    data[tf]={}
    for pair in PAIRS:
        print(f"  {pair} {tf}...", flush=True)
        raw=fetch(pair,tf,TF_CONFIG[tf])
        data[tf][pair]=precompute(raw)
print()

# ── Run exhaustive search ──────────────────────────────────────────────────────
print("Running exhaustive backtest...\n")
all_results=[]
total=len(STRATS)*len(TF_CONFIG)*len(SL_TP)
done=0

for tf in TF_CONFIG:
    days=TF_CONFIG[tf]/CPD[tf]
    for sname,sfn in STRATS.items():
        for sl,tp in SL_TP:
            total_pnl=0.0; tw=0; tl=0; max_dd=0.0
            for pair in PAIRS:
                pnl,w,l,dd=backtest_dollar(data[tf][pair],sfn,sl,tp,POS_SIZE)
                total_pnl+=pnl; tw+=w; tl+=l; max_dd=max(max_dd,dd)
            done+=1
            total_trades=tw+tl
            if total_trades<20: continue
            wr=tw/total_trades
            ev_pct=wr*tp-(1-wr)*sl
            if ev_pct<=0: continue
            tpd=total_trades/days
            # Annualized
            annual_pnl=total_pnl*(365/days)
            annual_dd=max_dd*(365/days)
            profit_factor=total_pnl/max_dd if max_dd>0 else 999
            all_results.append({
                "tf":tf,"strat":sname,"sl":sl,"tp":tp,
                "wins":tw,"losses":tl,"total":total_trades,
                "wr":round(wr*100,1),"ev":round(ev_pct*100,4),
                "rr":round(tp/sl,2),"tpd":round(tpd,1),
                "annual_pnl":round(annual_pnl,2),
                "max_dd":round(max_dd,2),
                "profit_factor":round(profit_factor,2),
                "annual_roi":round(annual_pnl/CAPITAL*100,2),
                "be":round(sl/(sl+tp)*100,1),
            })
        if done % (len(SL_TP)*5)==0:
            print(f"  {done:,}/{total:,} ({done/total*100:.0f}%)...", flush=True)

all_results.sort(key=lambda x:x["annual_pnl"],reverse=True)
print(f"\nFound {len(all_results):,} profitable combos\n")

# ── TOP 30 BY ANNUAL PROFIT ────────────────────────────────────────────────────
print("="*125)
print(f"TOP 30 BY ANNUAL DOLLAR PROFIT  (${CAPITAL:,.0f} capital, ${POS_SIZE:.0f}/trade, 10 pairs)")
print("="*125)
print(f"  {'#':<3} {'TF':<5} {'Strategy':<24} {'SL':>5} {'TP':>6} {'R/R':>6} | "
      f"{'WR%':>6} {'T/day':>6} | {'Annual $':>10} {'ROI%':>7} {'MaxDD$':>8} {'PF':>6}")
print(f"  {'-'*120}")

seen=set(); count=0
for r in all_results:
    key=(r["tf"],r["strat"])
    if key in seen: continue
    seen.add(key); count+=1
    rr=f"{r['rr']:.1f}:1" if r['rr']>=1 else f"1:{1/r['rr']:.1f}"
    pf_str=f"{r['profit_factor']:.1f}" if r['profit_factor']<99 else "∞"
    print(f"  {count:<3} {r['tf']:<5} {r['strat']:<24} {r['sl']*100:>5.1f} {r['tp']*100:>6.1f} {rr:>6} | "
          f"{r['wr']:>5.1f}% {r['tpd']:>5.1f}/d | "
          f"${r['annual_pnl']:>+9,.0f} {r['annual_roi']:>+6.1f}% ${r['max_dd']:>7,.0f} {pf_str:>6}")
    if count>=30: break

# ── TOP 5 DETAILED ─────────────────────────────────────────────────────────────
print(f"\n{'='*80}")
print("TOP 5 DETAILED")
print(f"{'='*80}")
seen2=set(); count2=0
for r in all_results:
    key=(r["tf"],r["strat"])
    if key in seen2: continue
    seen2.add(key); count2+=1
    monthly=r["annual_pnl"]/12
    daily=r["annual_pnl"]/365
    print(f"\n  #{count2}  [{r['tf']}] {r['strat']}")
    print(f"       SL={r['sl']*100:.1f}%  TP={r['tp']*100:.1f}%  ({r['rr']:.2f}:1 R/R)  WR={r['wr']}%")
    print(f"       Trades: {r['total']} ({r['tpd']:.1f}/day)  |  WinRate={r['wr']}%  EV={r['ev']:+.4f}%")
    print(f"       Annual PnL:   ${r['annual_pnl']:>+,.0f}  ({r['annual_roi']:+.1f}% ROI)")
    print(f"       Monthly avg:  ${monthly:>+,.0f}/month")
    print(f"       Daily avg:    ${daily:>+,.0f}/day")
    print(f"       Max drawdown: ${r['max_dd']:,.0f}  (Profit factor: {r['profit_factor']:.2f})")
    if count2>=5: break

# ── CHAMPION PER TIMEFRAME ────────────────────────────────────────────────────
print(f"\n{'='*80}")
print("CHAMPION PER TIMEFRAME  (highest annual profit)")
print(f"{'='*80}")
for tf in TF_CONFIG:
    sub=[r for r in all_results if r["tf"]==tf]
    seen3=set(); top=[]
    for r in sub:
        if r["strat"] not in seen3:
            seen3.add(r["strat"]); top.append(r)
        if len(top)>=3: break
    print(f"\n  [{tf}]")
    for i,r in enumerate(top):
        daily=r["annual_pnl"]/365
        print(f"    #{i+1} {r['strat']:<26} SL={r['sl']*100:.1f}% TP={r['tp']*100:.1f}%  "
              f"WR={r['wr']:.1f}%  Annual=${r['annual_pnl']:>+,.0f}  "
              f"Daily avg=${daily:>+.0f}  MaxDD=${r['max_dd']:,.0f}")

# ── WHAT POSITION SIZE FOR $100/DAY ───────────────────────────────────────────
print(f"\n{'='*80}")
print("WHAT POSITION SIZE GIVES $100/DAY?")
print(f"{'='*80}")
if all_results:
    b=all_results[0]
    daily=b["annual_pnl"]/365
    scale=100/daily if daily>0 else 0
    needed_pos=POS_SIZE*scale
    print(f"\n  Best strategy: [{b['tf']}] {b['strat']}  SL={b['sl']*100:.1f}% TP={b['tp']*100:.1f}%")
    print(f"  Current daily avg: ${daily:+.2f} (with ${POS_SIZE:.0f}/trade)")
    print(f"  To get $100/day:   ${needed_pos:,.0f}/trade = {needed_pos/CAPITAL*100:.0f}% of $10k capital")
    print(f"  Risk per loss:     ${needed_pos*b['sl']:,.0f} ({needed_pos*b['sl']/CAPITAL*100:.1f}% of capital)")
