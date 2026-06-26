"""
Combined LONG + SHORT backtest for all 5 agents
Both directions running together on same pairs/period
$10,000 capital | $500 margin/trade | 50x leverage | 10 pairs | 2 years
"""
import requests, time, math
from fast_backtest import precompute, STRATS
from paper.competition_agents import AGENTS, PAIRS

CAPITAL  = 10_000.0
MARGIN   = 500.0
LEVERAGE = 50
TF_CANDLES = {"15m": 17520*4, "1h": 17520}

# ── Short signal mirrors ───────────────────────────────────────────────────────
def s_donchian_short(p, i):
    if i < 25: return False
    return (p["c"][i] < p["don_lo"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.3
            and p["rsi"][i] > 22 and not p["green"][i])

def s_adx_trend_short(p, i):
    if i < 60: return False
    downtrend = p["e9"][i] < p["e21"][i] < p["e50"][i] and p["c"][i] < p["e9"][i]
    if not downtrend or p["adx"][i] < 30: return False
    if p["macd_hist"][i] >= 0: return False
    if not (30 < p["rsi"][i] < 70): return False
    recent_hi = max(p["h"][max(0,i-5):i])
    return recent_hi >= p["e9"][i] * 0.99 and not p["green"][i]

def s_macd_bb_short(p, i):
    if i < 35: return False
    macd_cross_down = p["macd_hist"][i] < 0 and p["macd_hist"][i-1] >= 0
    near_upper = (p["bb_hi"][i] - p["c"][i]) / p["c"][i] * 100 < 2.0
    return (macd_cross_down and near_upper and p["rsi"][i] > 40
            and not p["green"][i] and p["c"][i] < p["e50"][i] * 1.03)

def s_orb_short(p, i):
    if i < 15: return False
    cons_lo = min(p["l"][i-6:i]) if i >= 6 else p["l"][i]
    cons_hi = max(p["h"][i-6:i]) if i >= 6 else p["h"][i]
    rng_pct = (cons_hi - cons_lo) / cons_lo * 100 if cons_lo > 0 else 99
    return (rng_pct < 1.5 and p["c"][i] < cons_lo
            and p["v"][i] > p["vol_avg"][i] * 1.2 and not p["green"][i])

def s_keltner_short(p, i):
    if i < 25: return False
    atr = p["atr"][i]
    kc_lower = p["bb_mid"][i] - 2 * atr
    return (p["c"][i] < kc_lower and p["v"][i] > p["vol_avg"][i] * 1.2
            and not p["green"][i])

SHORT_SIGNALS = {
    "The Maniac":  s_keltner_short,
    "The Oracle":  s_adx_trend_short,
    "The Surgeon": s_macd_bb_short,
    "The Comet":   s_orb_short,
    "The Hound":   s_donchian_short,
}

# ── Fetch ──────────────────────────────────────────────────────────────────────
def fetch(pair, tf, n_candles):
    all_c = []; end = None
    for _ in range(math.ceil(n_candles / 1000)):
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit=1000"
        if end: url += f"&endTime={end}"
        try:
            r = requests.get(url, timeout=15); r.raise_for_status()
            batch = r.json()
            if not batch: break
            all_c = batch + all_c
            end = int(batch[0][0]) - 1
            time.sleep(0.05)
        except Exception as e:
            print(f"  err {pair}: {e}", flush=True); break
    raw = all_c[-n_candles:]
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
        "vol":   [float(c[5]) for c in raw],
        "ts":    [int(c[0])   for c in raw],
    }

# ── Combined backtest ──────────────────────────────────────────────────────────
def backtest_combined(agent_name, cfg):
    tf      = cfg["timeframe"]
    sl      = cfg["sl"]
    tp      = cfg["tp"]
    sfn_long  = STRATS.get(cfg["strategy"])
    sfn_short = SHORT_SIGNALS[agent_name]
    n_candles = TF_CANDLES.get(tf, 17520)
    trades = []

    for pair in PAIRS:
        print(f"  {pair}...", flush=True)
        raw = fetch(pair, tf, n_candles)
        if len(raw.get("close", [])) < 100: continue
        p = precompute(raw); n = p["n"]; i = 60

        while i < n - 1:
            long_sig  = sfn_long(p, i)  if sfn_long  else False
            short_sig = sfn_short(p, i) if sfn_short else False

            if not long_sig and not short_sig:
                i += 1; continue

            ep  = p["c"][i]
            qty = (MARGIN * LEVERAGE) / ep

            if long_sig:
                tp_p = ep * (1 + tp); sl_p = ep * (1 - sl)
                result = "LOSS"; j = i + 1
                while j < min(i + 300 + 1, n):
                    if p["l"][j] <= sl_p: result = "LOSS"; break
                    if p["h"][j] >= tp_p: result = "WIN";  break
                    j += 1
                pnl = qty * (tp_p - ep) if result == "WIN" else qty * (sl_p - ep)
                if pnl < -MARGIN: pnl = -MARGIN
                trades.append({"side": "LONG", "result": result, "pnl": round(pnl, 2)})

            if short_sig:
                tp_p = ep * (1 - tp); sl_p = ep * (1 + sl)
                result = "LOSS"; j = i + 1
                while j < min(i + 300 + 1, n):
                    if p["h"][j] >= sl_p: result = "LOSS"; break
                    if p["l"][j] <= tp_p: result = "WIN";  break
                    j += 1
                pnl = qty * (ep - tp_p) if result == "WIN" else qty * (ep - sl_p)
                if pnl < -MARGIN: pnl = -MARGIN
                trades.append({"side": "SHORT", "result": result, "pnl": round(pnl, 2)})

            i = (j + 1) if (long_sig or short_sig) else i + 1

    return trades

# ── Run ────────────────────────────────────────────────────────────────────────
print(f"\n{'='*72}")
print(f"  COMBINED LONG + SHORT — x50 Leverage Backtest")
print(f"  $10,000 capital | $500 margin | 50x | 10 pairs | 2 years")
print(f"{'='*72}\n")

results = []
for agent_name, cfg in AGENTS.items():
    print(f"Fetching {cfg['emoji']} {agent_name} ({cfg['strategy']} {cfg['timeframe']})...", flush=True)
    trades = backtest_combined(agent_name, cfg)

    long_t  = [t for t in trades if t["side"] == "LONG"]
    short_t = [t for t in trades if t["side"] == "SHORT"]
    wins    = [t for t in trades if t["result"] == "WIN"]
    total   = len(trades)
    wr      = len(wins)/total*100 if total else 0
    pnl     = sum(t["pnl"] for t in trades)
    long_pnl  = sum(t["pnl"] for t in long_t)
    short_pnl = sum(t["pnl"] for t in short_t)

    print(f"  → {total} trades (L:{len(long_t)} S:{len(short_t)}) | WR={wr:.1f}% | PnL=${pnl:+,.0f} (L:${long_pnl:+,.0f} S:${short_pnl:+,.0f})\n", flush=True)
    results.append((agent_name, cfg, total, len(long_t), len(short_t), len(wins), wr, pnl, long_pnl, short_pnl))

results.sort(key=lambda x: -x[7])

print(f"\n{'='*72}")
print(f"  COMBINED SUMMARY (LONG + SHORT)")
print(f"{'='*72}")
print(f"  {'Agent':<18} {'TF':>4} {'SL':>6} {'TP':>6} {'Trades':>7} {'WR%':>7} {'Long PnL':>12} {'Short PnL':>12} {'Total PnL':>12}")
print(f"  {'-'*90}")
for agent_name, cfg, total, lt, st, w, wr, pnl, lpnl, spnl in results:
    print(f"  {cfg['emoji']} {agent_name:<16} {cfg['timeframe']:>4} {cfg['sl']*100:>5.1f}% {cfg['tp']*100:>5.1f}% {total:>7} {wr:>6.1f}%  ${lpnl:>+10,.0f}  ${spnl:>+10,.0f}  ${pnl:>+10,.0f}")
