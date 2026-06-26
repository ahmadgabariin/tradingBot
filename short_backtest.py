"""
SHORT mirror strategies backtest — separated from long strategies
Tests mirror versions of all 5 agent strategies on the short side
$10,000 capital | $500 margin/trade | 50x leverage | 10 pairs | 2 years
"""
import requests, time, math, sys
from fast_backtest import precompute
from paper.competition_agents import PAIRS

CAPITAL  = 10_000.0
MARGIN   = 500.0
LEVERAGE = 50
TF_CANDLES = {"15m": 17520*4, "1h": 17520}

# ── Short signal definitions ───────────────────────────────────────────────────

def s_donchian_short(p, i):
    """Price breaks BELOW Donchian channel low with volume + RSI not oversold + red candle"""
    if i < 25: return False
    return (p["c"][i] < p["don_lo"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.3
            and p["rsi"][i] > 22 and not p["green"][i])

def s_adx_trend_short(p, i):
    """Downtrend: EMA9 < EMA21 < EMA50, price below EMA9, ADX strong, MACD bearish"""
    if i < 60: return False
    downtrend = p["e9"][i] < p["e21"][i] < p["e50"][i] and p["c"][i] < p["e9"][i]
    if not downtrend or p["adx"][i] < 30: return False
    if p["macd_hist"][i] >= 0: return False
    if not (30 < p["rsi"][i] < 70): return False
    recent_hi = max(p["h"][max(0,i-5):i])
    return recent_hi >= p["e9"][i] * 0.99 and not p["green"][i]

def s_macd_bb_short(p, i):
    """MACD cross down + price near upper BB (rejection from top)"""
    if i < 35: return False
    macd_cross_down = p["macd_hist"][i] < 0 and p["macd_hist"][i-1] >= 0
    near_upper = (p["bb_hi"][i] - p["c"][i]) / p["c"][i] * 100 < 2.0
    return (macd_cross_down and near_upper and p["rsi"][i] > 40
            and not p["green"][i] and p["c"][i] < p["e50"][i] * 1.03)

def s_orb_short(p, i):
    """Opening Range Breakout — price breaks BELOW consolidation low"""
    if i < 15: return False
    cons_lo = min(p["l"][i-6:i]) if i >= 6 else p["l"][i]
    cons_hi = max(p["h"][i-6:i]) if i >= 6 else p["h"][i]
    rng_pct = (cons_hi - cons_lo) / cons_lo * 100 if cons_lo > 0 else 99
    return (rng_pct < 1.5 and p["c"][i] < cons_lo
            and p["v"][i] > p["vol_avg"][i] * 1.2 and not p["green"][i])

def s_keltner_short(p, i):
    """Price breaks BELOW Keltner Channel lower band"""
    if i < 25: return False
    atr = p["atr"][i]
    ema20 = p["bb_mid"][i]
    kc_lower = ema20 - 2 * atr
    return (p["c"][i] < kc_lower and p["v"][i] > p["vol_avg"][i] * 1.2
            and not p["green"][i])

# ── Agent short configs ────────────────────────────────────────────────────────
SHORT_AGENTS = {
    "Maniac_Short":  {"emoji": "🔥", "strategy": s_keltner_short,    "tf": "15m", "sl": 0.025, "tp": 0.006},
    "Oracle_Short":  {"emoji": "🔮", "strategy": s_adx_trend_short,  "tf": "1h",  "sl": 0.035, "tp": 0.020},
    "Surgeon_Short": {"emoji": "🏆", "strategy": s_macd_bb_short,    "tf": "1h",  "sl": 0.008, "tp": 0.080},
    "Comet_Short":   {"emoji": "☄️", "strategy": s_orb_short,        "tf": "1h",  "sl": 0.020, "tp": 0.040},
    "Hound_Short":   {"emoji": "🐺", "strategy": s_donchian_short,   "tf": "1h",  "sl": 0.012, "tp": 0.060},
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

# ── SHORT backtest — TP/SL reversed ───────────────────────────────────────────
def backtest_short(cfg):
    tf  = cfg["tf"]
    sl  = cfg["sl"]
    tp  = cfg["tp"]
    sfn = cfg["strategy"]
    n_candles = TF_CANDLES.get(tf, 17520)
    trades = []

    for pair in PAIRS:
        print(f"  {pair}...", flush=True)
        raw = fetch(pair, tf, n_candles)
        if len(raw.get("close", [])) < 100: continue
        p = precompute(raw); n = p["n"]; i = 60

        while i < n - 1:
            if not sfn(p, i): i += 1; continue
            ep   = p["c"][i]
            # SHORT: profit when price goes DOWN
            tp_p = ep * (1 - tp)   # take profit below entry
            sl_p = ep * (1 + sl)   # stop loss above entry
            qty  = (MARGIN * LEVERAGE) / ep

            result = "LOSS"; j = i + 1
            while j < min(i + 300 + 1, n):
                if p["h"][j] >= sl_p: result = "LOSS"; break   # price went UP → stop loss
                if p["l"][j] <= tp_p: result = "WIN";  break   # price went DOWN → take profit
                j += 1

            pnl = qty * (ep - tp_p) if result == "WIN" else qty * (tp_p - sl_p) * -1
            if result == "LOSS": pnl = qty * (ep - sl_p)   # negative since sl_p > ep
            if pnl < -MARGIN: pnl = -MARGIN; result = "LIQ"

            trades.append({"result": result, "pnl": round(pnl, 2)})
            i = j + 1

    return trades

# ── Run ────────────────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print(f"  SHORT MIRROR STRATEGIES — x50 Leverage Backtest")
print(f"  $10,000 capital | $500 margin | 50x | 10 pairs | 2 years")
print(f"  *** SEPARATED from long strategies — short side only ***")
print(f"{'='*70}\n")

results = []
for name, cfg in SHORT_AGENTS.items():
    print(f"Fetching {cfg['emoji']} {name} ({cfg['tf']} | SL={cfg['sl']*100:.1f}% TP={cfg['tp']*100:.1f}%)...", flush=True)
    trades = backtest_short(cfg)
    wins   = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] in ("LOSS","LIQ")]
    total  = len(trades)
    wr     = len(wins)/total*100 if total else 0
    pnl    = sum(t["pnl"] for t in trades)
    avg    = pnl/total if total else 0
    print(f"  → {total} trades | WR={wr:.1f}% | PnL=${pnl:+,.0f}\n", flush=True)
    results.append((name, cfg, total, len(wins), len(losses), wr, pnl, avg))

# ── Summary ───────────────────────────────────────────────────────────────────
results.sort(key=lambda x: -x[6])
print(f"\n{'='*70}")
print(f"  SHORT STRATEGIES SUMMARY")
print(f"{'='*70}")
print(f"  {'Agent':<18} {'TF':>4} {'Trades':>7} {'W':>5} {'L':>5} {'WR%':>7} {'Total PnL':>13}")
print(f"  {'-'*65}")
for name, cfg, total, w, l, wr, pnl, avg in results:
    print(f"  {cfg['emoji']} {name:<16} {cfg['tf']:>4} {total:>7} {w:>5} {l:>5} {wr:>6.1f}%  ${pnl:>+12,.0f}")

print(f"\n  * Short: profit when price goes DOWN")
print(f"  * TP/SL are mirrored from long versions")
