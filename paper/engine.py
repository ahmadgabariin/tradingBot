"""
Paper trading engine — live Binance prices, fake money.
No API keys needed. Runs standalone.
"""
import requests
import time
import json
import sqlite3
from datetime import datetime, timezone
from loguru import logger

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
STARTING_BALANCE = 1000.0    # fake USD per pair
MAX_TRADE_PCT    = 0.20      # use 20% of balance per trade
MIN_CONFIDENCE   = 60        # minimum score to trade (only used by STRATEGY="SCORE")

# ── STRATEGY PARAMS ───────────────────────────────────────────────────────────
STRATEGY_PARAMS = {
    "SCORE":          {"tf": "1h",  "sl": 0.030, "tp": 0.015, "candles": 200},
    "SQUEEZE_BREAK":  {"tf": "15m", "sl": 0.025, "tp": 0.020, "candles": 100},
    "KELTNER_BREAK":  {"tf": "15m", "sl": 0.025, "tp": 0.006, "candles": 100},
    "DONCHIAN_BREAK": {"tf": "15m", "sl": 0.025, "tp": 0.006, "candles": 100},
    "ORB":            {"tf": "1h",  "sl": 0.025, "tp": 0.006, "candles": 150},
}

# Active strategies — multiple can run simultaneously, each with own balance
# Can be changed at runtime via dashboard
ACTIVE_STRATEGIES = {"KELTNER_BREAK"}

# Legacy single-strategy compat (used by engine loop sleep calculation)
STRATEGY = "KELTNER_BREAK"
TIMEFRAME = "15m"
STOP_LOSS_PCT = 0.025
TAKE_PROFIT_PCT = 0.006
CANDLE_LIMIT = 100

DB = "paper/paper_trades.db"


# ── Database ──────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy TEXT DEFAULT 'SCORE',
        pair TEXT, action TEXT, price REAL, quantity REAL,
        amount_usd REAL, stop_loss REAL, take_profit REAL,
        confidence INTEGER, reasons TEXT,
        opened_at TEXT, closed_at TEXT,
        exit_price REAL, pnl REAL, pnl_pct REAL, status TEXT
    )""")
    # Migrate existing DB: add strategy column if missing
    try:
        c.execute("ALTER TABLE trades ADD COLUMN strategy TEXT DEFAULT 'SCORE'")
    except Exception:
        pass
    c.execute("""CREATE TABLE IF NOT EXISTS price_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pair TEXT, price REAL, ts TEXT
    )""")
    conn.commit()
    conn.close()


def db_open_trade(strategy, pair, action, price, qty, amount, sl, tp, conf, reasons):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""INSERT INTO trades
        (strategy, pair, action, price, quantity, amount_usd, stop_loss, take_profit,
         confidence, reasons, opened_at, status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (strategy, pair, action, price, qty, amount, sl, tp, conf,
         json.dumps(reasons[:4]), datetime.now(timezone.utc).isoformat(), "open"))
    tid = c.lastrowid
    conn.commit()
    conn.close()
    return tid


def db_close_trade_manual(tid):
    """Close a trade at current market price, marked as manual close."""
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT strategy, pair, price, quantity, amount_usd FROM trades WHERE id=? AND status='open'", (tid,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    strategy, pair, entry_price, qty, amount_usd = row
    try:
        price = fetch_price(pair)
    except Exception:
        return None
    pnl = (price - entry_price) * qty
    pnl_pct = (price - entry_price) / entry_price * 100
    db_close_trade(tid, price, round(pnl, 4), round(pnl_pct, 3), "manual_close")
    # Remove from in-memory portfolio if present
    port = _portfolios.get(strategy)
    if port and pair in port.positions and port.positions[pair].get("tid") == tid:
        port.balances[pair] += amount_usd + pnl
        del port.positions[pair]
    return {"price": price, "pnl": round(pnl, 4), "pnl_pct": round(pnl_pct, 3)}


def db_close_trade(tid, exit_price, pnl, pnl_pct, status):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""UPDATE trades SET
        exit_price=?, pnl=?, pnl_pct=?, status=?, closed_at=?
        WHERE id=?""",
        (exit_price, pnl, pnl_pct, status,
         datetime.now(timezone.utc).isoformat(), tid))
    conn.commit()
    conn.close()


def db_log_price(pair, price):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO price_log (pair, price, ts) VALUES (?,?,?)",
              (pair, price, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def get_stats():
    """Returns stats grouped by strategy, with per-pair breakdown."""
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    stats = {}
    c.execute("SELECT DISTINCT strategy FROM trades")
    strat_names = [r[0] for r in c.fetchall()] or list(ACTIVE_STRATEGIES)
    for strat in strat_names:
        c.execute("""SELECT COUNT(*), SUM(pnl), COUNT(CASE WHEN pnl>0 THEN 1 END)
                     FROM trades WHERE strategy=? AND status!='open'""", (strat,))
        row = c.fetchone()
        total, pnl, wins = row[0] or 0, row[1] or 0.0, row[2] or 0
        c.execute("SELECT COUNT(*) FROM trades WHERE strategy=? AND status='open'", (strat,))
        open_count = c.fetchone()[0]
        c.execute("SELECT pnl FROM trades WHERE strategy=? AND status!='open' ORDER BY id DESC LIMIT 20", (strat,))
        recent = [r[0] for r in c.fetchall()]
        pair_stats = {}
        for pair in PAIRS:
            c.execute("""SELECT COUNT(*), SUM(pnl), COUNT(CASE WHEN pnl>0 THEN 1 END)
                         FROM trades WHERE strategy=? AND pair=? AND status!='open'""", (strat, pair))
            pr = c.fetchone()
            pt, pp, pw = pr[0] or 0, pr[1] or 0.0, pr[2] or 0
            pair_stats[pair] = {
                "total": pt, "wins": pw, "losses": pt - pw,
                "win_rate": round(pw / pt * 100, 1) if pt > 0 else 0.0,
                "total_pnl": round(pp, 2),
            }
        stats[strat] = {
            "total": total, "wins": wins, "losses": total - wins,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
            "total_pnl": round(pnl, 2),
            "open": open_count,
            "recent_pnl": [round(p, 2) for p in recent],
            "pairs": pair_stats,
        }
    conn.close()
    return stats


def get_all_trades(limit=100):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""SELECT strategy, pair, action, price, amount_usd, stop_loss, take_profit,
                        confidence, opened_at, exit_price, pnl, pnl_pct, status, id
                 FROM trades ORDER BY id DESC LIMIT ?""", (limit,))
    cols = ["strategy","pair","action","price","amount_usd","stop_loss","take_profit",
            "confidence","opened_at","exit_price","pnl","pnl_pct","status","id"]
    rows = [dict(zip(cols, r)) for r in c.fetchall()]
    conn.close()
    return rows


# ── Market data (public Binance API — no keys needed) ─────────────────────────

def fetch_candles(pair: str, tf: str = TIMEFRAME, limit: int = CANDLE_LIMIT):
    url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit={limit}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return [[float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])]
            for c in r.json()]   # [open, high, low, close, volume]


def fetch_price(pair: str) -> float:
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={pair}"
    r = requests.get(url, timeout=8)
    return float(r.json()["price"])


# ── Signal engine ─────────────────────────────────────────────────────────────

def ema(values, period):
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def compute_rsi(closes, period=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    if len(gains) < period:
        return 50.0
    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - 100 / (1 + rs), 2)


def compute_macd(closes):
    if len(closes) < 35:
        return 0, 0
    # Build MACD line series over last 20 candles for proper signal line
    macd_series = []
    for i in range(max(26, len(closes) - 20), len(closes) + 1):
        slice_ = closes[:i]
        if len(slice_) < 26:
            continue
        macd_series.append(ema(slice_, 12) - ema(slice_, 26))
    if len(macd_series) < 9:
        return 0, 0
    macd_line   = macd_series[-1]
    signal_line = ema(macd_series, 9)
    histogram   = macd_line - signal_line
    return macd_line, histogram


def compute_atr(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        high = candles[i][1]; low = candles[i][2]; prev_close = candles[i-1][3]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if len(trs) < period:
        return 0
    return sum(trs[-period:]) / period


def compute_adx(candles, period=14):
    """Simple ADX — measures trend strength. >25 = trending, <20 = ranging."""
    if len(candles) < period + 2:
        return 20
    plus_dms, minus_dms, trs = [], [], []
    for i in range(1, len(candles)):
        h, l, ph, pl = candles[i][1], candles[i][2], candles[i-1][1], candles[i-1][2]
        pc = candles[i-1][3]
        plus_dms.append(max(h - ph, 0) if (h - ph) > (pl - l) else 0)
        minus_dms.append(max(pl - l, 0) if (pl - l) > (h - ph) else 0)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[-period:]) / period
    if atr == 0:
        return 20
    pdi = sum(plus_dms[-period:]) / period / atr * 100
    mdi = sum(minus_dms[-period:]) / period / atr * 100
    dx = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0
    return round(dx, 1)


def _ema_series(values, period):
    k = 2 / (period + 1); v = values[0]
    result = [v]
    for x in values[1:]:
        v = x * k + v * (1 - k); result.append(v)
    return result

def _rsi_last(closes, period=14):
    gains = losses = 0.0
    for i in range(-period, 0):
        d = closes[i] - closes[i - 1]
        if d > 0: gains += d
        else: losses -= d
    avg_g = gains / period; avg_l = losses / period
    if avg_l == 0: return 100
    return 100 - 100 / (1 + avg_g / avg_l)

def _vol_avg(vols, period=20):
    return sum(vols[-period:]) / min(period, len(vols))

def _atr_last(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i][1], candles[i][2], candles[i-1][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period: return 0
    return sum(trs[-period:]) / period

def _signal_result(signal, price, reasons):
    return {"signal": signal, "score": 85 if signal == "BUY" else 0,
            "confidence": 85 if signal == "BUY" else 0,
            "rsi": 0, "price": price, "reasons": reasons,
            "nearest_support": None, "nearest_resistance": None}

def analyse_keltner_break(candles):
    """Price breaks above Keltner Channel upper band — 81.7% WR on 15m."""
    if len(candles) < 30:
        return _signal_result("HOLD", candles[-1][3], ["Not enough data"])
    closes = [c[3] for c in candles]
    highs  = [c[1] for c in candles]
    vols   = [c[4] for c in candles]
    price  = closes[-1]
    green  = closes[-1] > candles[-1][0]
    atr    = _atr_last(candles)
    sma20  = sum(closes[-20:]) / 20
    kc_upper = sma20 + 2 * atr
    vol_ratio = vols[-1] / _vol_avg(vols)
    rsi = _rsi_last(closes)
    reasons = [f"Keltner upper={kc_upper:.2f}  price={price:.2f}",
               f"Volume {vol_ratio:.1f}x avg  RSI={rsi:.0f}  green={green}"]
    if price > kc_upper and vol_ratio > 1.2 and green and rsi < 75:
        return _signal_result("BUY", price, ["Keltner breakout"] + reasons)
    return _signal_result("HOLD", price, ["No breakout"] + reasons)

def analyse_donchian_break(candles):
    """Price breaks 20-period Donchian high — 81.3% WR on 15m."""
    if len(candles) < 30:
        return _signal_result("HOLD", candles[-1][3], ["Not enough data"])
    closes = [c[3] for c in candles]
    highs  = [c[1] for c in candles]
    vols   = [c[4] for c in candles]
    price  = closes[-1]
    green  = closes[-1] > candles[-1][0]
    don_hi = max(highs[-21:-1])  # 20-bar high excluding current
    vol_ratio = vols[-1] / _vol_avg(vols)
    rsi = _rsi_last(closes)
    reasons = [f"Donchian high={don_hi:.2f}  price={price:.2f}",
               f"Volume {vol_ratio:.1f}x avg  RSI={rsi:.0f}  green={green}"]
    if price > don_hi and vol_ratio > 1.3 and green and rsi < 78:
        return _signal_result("BUY", price, ["Donchian breakout"] + reasons)
    return _signal_result("HOLD", price, ["No breakout"] + reasons)

def analyse_orb(candles):
    """Opening Range Breakout — price breaks tight consolidation — 81.8% WR on 1h."""
    if len(candles) < 20:
        return _signal_result("HOLD", candles[-1][3], ["Not enough data"])
    closes = [c[3] for c in candles]
    highs  = [c[1] for c in candles]
    lows   = [c[2] for c in candles]
    vols   = [c[4] for c in candles]
    price  = closes[-1]
    green  = closes[-1] > candles[-1][0]
    # Consolidation range over last 6 candles (before current)
    cons_hi = max(highs[-7:-1])
    cons_lo = min(lows[-7:-1])
    rng_pct = (cons_hi - cons_lo) / cons_lo * 100 if cons_lo > 0 else 99
    vol_ratio = vols[-1] / _vol_avg(vols)
    rsi = _rsi_last(closes)
    reasons = [f"Range={rng_pct:.2f}%  breakout above {cons_hi:.2f}",
               f"Volume {vol_ratio:.1f}x avg  RSI={rsi:.0f}  green={green}"]
    if rng_pct < 1.5 and price > cons_hi and vol_ratio > 1.2 and green and rsi < 75:
        return _signal_result("BUY", price, ["ORB breakout"] + reasons)
    return _signal_result("HOLD", price, ["No ORB"] + reasons)


def analyse_squeeze_break(candles):
    """
    Squeeze_Break signal:
    BB bandwidth < 75% of 20-candle avg + price breaks above upper BB
    + green candle + volume spike + RSI < 78
    Returns same dict shape as analyse() for drop-in compatibility.
    """
    if len(candles) < 35:
        return {"signal": "HOLD", "score": 0, "confidence": 0, "rsi": 50,
                "price": candles[-1][3], "reasons": ["Not enough data"],
                "nearest_support": None, "nearest_resistance": None}

    closes = [c[3] for c in candles]
    highs  = [c[1] for c in candles]
    lows   = [c[2] for c in candles]
    vols   = [c[4] for c in candles]
    price  = closes[-1]

    def ema_val(data, period):
        k = 2 / (period + 1); v = data[0]
        for x in data[1:]: v = x * k + v * (1 - k)
        return v

    def bb(closes, period=20, std_mult=2.0):
        s = closes[-period:]
        mid = sum(s) / period
        variance = sum((x - mid) ** 2 for x in s) / period
        dev = variance ** 0.5 * std_mult
        return mid - dev, mid, mid + dev

    def rsi_val(closes, period=14):
        gains = losses = 0.0
        for i in range(-period, 0):
            d = closes[i] - closes[i - 1]
            if d > 0: gains += d
            else: losses -= d
        avg_g = gains / period; avg_l = losses / period
        if avg_l == 0: return 100
        rs = avg_g / avg_l
        return 100 - 100 / (1 + rs)

    bb_lo, bb_mid, bb_hi = bb(closes)
    bb_w = (bb_hi - bb_lo) / bb_mid if bb_mid > 0 else 0

    bb_w_avg = 0.0
    for k in range(1, 21):
        lo_k, mid_k, hi_k = bb(closes[:-k] if k > 0 else closes)
        bb_w_avg += (hi_k - lo_k) / mid_k if mid_k > 0 else 0
    bb_w_avg /= 20

    vol_avg = sum(vols[-20:]) / 20 if len(vols) >= 20 else vols[-1]
    vol_ratio = vols[-1] / vol_avg if vol_avg > 0 else 1
    rsi = rsi_val(closes)
    green = closes[-1] > candles[-1][0]
    squeeze = bb_w < bb_w_avg * 0.75
    breakout = closes[-1] > bb_hi

    reasons = []
    if squeeze:
        reasons.append(f"BB squeeze (width {bb_w:.4f} < avg {bb_w_avg:.4f})")
    if breakout:
        reasons.append(f"Price broke above upper BB ${bb_hi:.2f}")
    if green:
        reasons.append("Green candle")
    if vol_ratio > 1.3:
        reasons.append(f"Volume spike {vol_ratio:.1f}x avg")
    if rsi < 78:
        reasons.append(f"RSI {rsi:.0f} — not overbought")

    if squeeze and breakout and green and vol_ratio > 1.3 and rsi < 78:
        signal = "BUY"
        score = 85
    else:
        signal = "HOLD"
        score = 0
        missing = []
        if not squeeze:  missing.append("no squeeze")
        if not breakout: missing.append("no BB breakout")
        if not green:    missing.append("red candle")
        if vol_ratio <= 1.3: missing.append(f"low volume {vol_ratio:.1f}x")
        if rsi >= 78:    missing.append(f"RSI overbought {rsi:.0f}")
        reasons.append(f"HOLD: {', '.join(missing)}")

    return {
        "signal": signal,
        "score": score,
        "confidence": score,
        "rsi": round(rsi, 1),
        "price": price,
        "reasons": reasons,
        "nearest_support": None,
        "nearest_resistance": None,
    }


def _rsi_series(closes, period=14):
    """Returns last N RSI values for slope detection."""
    rsi_vals = []
    for i in range(period + 5, len(closes) + 1):
        rsi_vals.append(compute_rsi(closes[i - period - 5: i], period))
    return rsi_vals


def analyze(candles) -> dict:
    if len(candles) < 60:
        return {"signal": "HOLD", "score": 0, "confidence": 0, "rsi": 50, "price": candles[-1][3], "reasons": ["Not enough data"], "nearest_support": None, "nearest_resistance": None}

    closes = [c[3] for c in candles]
    highs  = [c[1] for c in candles]
    lows   = [c[2] for c in candles]
    vols   = [c[4] for c in candles]
    price  = closes[-1]

    # Use completed candles for volume (skip last potentially incomplete candle)
    vol_completed = vols[:-1]

    score      = 0
    reasons    = []
    hard_block = False

    # ── EMAs ──────────────────────────────────────────────────────────────────
    e9   = ema(closes, 9)
    e21  = ema(closes, 21)
    e50  = ema(closes, 50)
    e200 = ema(closes, 200) if len(closes) >= 200 else ema(closes, len(closes))

    uptrend = e9 > e21 > e50

    # HARD BLOCK: price down >6% from 30-candle high = crash mode, don't catch knife
    high_30 = max(c[1] for c in candles[-30:]) if len(candles) >= 30 else price
    drawdown = (high_30 - price) / high_30 * 100
    if drawdown > 6.0:
        hard_block = True
        reasons.append(f"BLOCK: In crash -{drawdown:.1f}% from 30-candle high — wait for recovery")

    # HARD BLOCK: price below EMA50 = bear market, never buy
    if price < e50:
        hard_block = True
        reasons.append("BLOCK: Price below EMA50 — macro downtrend, no buy")
    elif not uptrend:
        hard_block = True
        reasons.append("BLOCK: EMAs not aligned — no buy in downtrend")
    else:
        score += 15; reasons.append("Uptrend confirmed: EMA9 > EMA21 > EMA50")

    # Long-term trend filter
    if price > e200:
        score += 10; reasons.append("Price above EMA200 — macro uptrend")
    else:
        score -= 8; reasons.append("Price below EMA200 — macro caution")

    last_low   = candles[-1][2]
    last_high  = candles[-1][1]
    last_open  = candles[-1][0]
    last_close = closes[-1]

    # ── CORE SIGNAL 1: EMA9 x EMA21 golden cross (EMA_Cross_Filtered — 83.5% WR on 1h backtest)
    e9_prev  = ema(closes[:-1], 9)
    ema_cross = e9 > e21 and e9_prev <= ema(closes[:-1], 21)
    if ema_cross and last_close > e50 and last_close > last_open:
        score += 40; reasons.append("EMA9 crossed above EMA21 above EMA50 — primary buy signal")
    elif e9 > e21 > e50:
        score += 15; reasons.append("EMA9 > EMA21 > EMA50 — uptrend aligned")

    # ── CORE SIGNAL 2: EMA21 bounce in uptrend ────────────────────────────────
    # Price dips to EMA21 zone then recovers — classic re-entry in uptrend
    e21_touch = False
    for k in range(-3, 0):
        c_low   = candles[k][2]
        c_close = candles[k][3]
        c_e21   = ema(closes[:len(closes) + k] if k < 0 else closes, 21)
        if c_low <= c_e21 * 1.004 and c_close > c_e21 * 0.998:
            e21_touch = True
            score += 18; reasons.append("EMA21 bounce — pullback to support, recovering")
            break

    # ── CORE SIGNAL 2: Momentum breakout ─────────────────────────────────────
    # Price breaks above highest close of last 20 candles = new momentum high
    lookback_highs = [candles[j][1] for j in range(-21, -1)]
    recent_high_20 = max(lookback_highs) if lookback_highs else price
    if last_close > recent_high_20:
        score += 25; reasons.append(f"Breakout: price above 20-candle high ${recent_high_20:.2f}")
    elif last_close > max(lookback_highs[-10:]):
        score += 12; reasons.append(f"10-candle high breakout")

    if uptrend and not e21_touch and last_close <= recent_high_20:
        dist_above_e21 = (price - e21) / e21 * 100
        if dist_above_e21 > 4.0:
            score -= 15; reasons.append(f"Price {dist_above_e21:.1f}% above EMA21 — overextended")

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi = compute_rsi(closes)
    rsi_prev = compute_rsi(closes[:-1])

    # HARD BLOCK: RSI > 72 = overbought, don't chase
    # Also block if RSI was recently overbought (distribution top pattern)
    rsi_recent_max = max(compute_rsi(closes[:len(closes)-k]) for k in range(0, min(5, len(closes)-15)))
    if rsi_recent_max > 75 and rsi > 60:
        hard_block = True
        reasons.append(f"BLOCK: Recent RSI peak {rsi_recent_max:.0f} — distribution top, wait for reset")
    if rsi > 72:
        hard_block = True
        reasons.append(f"BLOCK: RSI {rsi} overbought — skip")
    elif rsi < 35:
        score += 25; reasons.append(f"RSI {rsi} oversold — strong buy zone")
    elif rsi < 50:
        score += 15; reasons.append(f"RSI {rsi} pullback zone — good entry")
    elif rsi < 65:
        score += 5; reasons.append(f"RSI {rsi} — healthy")
    else:
        score -= 10; reasons.append(f"RSI {rsi} — elevated, entry risk")

    # RSI momentum: turning up from bottom = extra points
    rsi_turning_up = rsi > rsi_prev + 1.0 and rsi < 60
    if rsi_turning_up:
        score += 12; reasons.append(f"RSI recovering {rsi_prev:.0f}→{rsi:.0f}")
    elif rsi < rsi_prev - 3 and rsi > 50:
        score -= 8; reasons.append(f"RSI still falling, wait for floor")

    # ── MACD ──────────────────────────────────────────────────────────────────
    macd_line, histogram = compute_macd(closes)
    _, hist_prev = compute_macd(closes[:-1])

    if histogram > 0 and hist_prev <= 0:
        score += 28; reasons.append("MACD histogram just turned positive — momentum shift")
    elif histogram > 0 and histogram > hist_prev:
        score += 15; reasons.append("MACD histogram positive and rising")
    elif histogram > 0:
        score += 8; reasons.append("MACD histogram positive")
    elif histogram > hist_prev and histogram > -0.01 * abs(macd_line):
        score += 5; reasons.append("MACD histogram improving")
    elif macd_line < 0 and histogram < 0:
        hard_block = True
        reasons.append("BLOCK: MACD fully bearish — no buy")
    else:
        score -= 5; reasons.append("MACD histogram negative")

    # ── Volume (use completed candles only) ───────────────────────────────────
    avg_vol = sum(vol_completed[-20:]) / max(len(vol_completed[-20:]), 1)
    # Compare previous closed candle volume
    last_completed_vol = vol_completed[-1] if vol_completed else 0
    vol_ratio = last_completed_vol / avg_vol if avg_vol > 0 else 1.0

    if vol_ratio > 2.0:
        score += 20; reasons.append(f"Volume spike {vol_ratio:.1f}x — strong conviction")
    elif vol_ratio > 1.3:
        score += 10; reasons.append(f"Good volume {vol_ratio:.1f}x")
    elif vol_ratio > 0.8:
        score += 3; reasons.append(f"Normal volume {vol_ratio:.1f}x")
    elif vol_ratio < 0.4:
        score -= 12; reasons.append(f"Low volume {vol_ratio:.1f}x — weak signal")

    # ── ADX ───────────────────────────────────────────────────────────────────
    adx = compute_adx(candles)
    if adx > 30:
        score += 15; reasons.append(f"ADX {adx} — strong trend, reliable signal")
    elif adx > 20:
        score += 8; reasons.append(f"ADX {adx} — trending")
    elif adx < 12:
        score -= 15; reasons.append(f"ADX {adx} — choppy, skip")
    else:
        reasons.append(f"ADX {adx} — moderate trend")

    # ── ATR ───────────────────────────────────────────────────────────────────
    atr = compute_atr(candles)
    atr_pct = atr / price * 100

    if atr_pct < 0.15:
        score -= 8; reasons.append(f"ATR {atr_pct:.2f}% — too tight, no momentum")
    else:
        reasons.append(f"ATR {atr_pct:.2f}%")

    # ── Support & Resistance ──────────────────────────────────────────────────
    swing_highs, swing_lows = [], []
    window = candles[-60:]
    for i in range(2, len(window) - 2):
        h = window[i][1]; l = window[i][2]
        if h > window[i-1][1] and h > window[i-2][1] and h > window[i+1][1] and h > window[i+2][1]:
            swing_highs.append(h)
        if l < window[i-1][2] and l < window[i-2][2] and l < window[i+1][2] and l < window[i+2][2]:
            swing_lows.append(l)

    nearest_res = min((h for h in swing_highs if h > price), default=None)
    nearest_sup = max((l for l in swing_lows  if l < price), default=None)

    if nearest_res:
        dist_res = (nearest_res - price) / price * 100
        if dist_res < 0.5:
            hard_block = True
            reasons.append(f"BLOCK: At resistance ${nearest_res:.2f} — bad entry")
        elif dist_res < 1.5:
            score -= 12; reasons.append(f"Near resistance {dist_res:.1f}% — risky")
        elif dist_res > TAKE_PROFIT_PCT * 100:
            score += 10; reasons.append(f"Clear {dist_res:.1f}% to resistance — TP reachable")

    if nearest_sup:
        dist_sup = (price - nearest_sup) / price * 100
        if dist_sup < 0.6:
            score += 18; reasons.append(f"At support ${nearest_sup:.2f} — strong floor")
        elif dist_sup < 1.5:
            score += 8; reasons.append(f"Near support ${nearest_sup:.2f}")

    # ── Candle direction filters ───────────────────────────────────────────────
    # HARD BLOCK: last completed candle must be green (price recovering, not falling)
    if last_close < last_open:
        hard_block = True
        reasons.append("BLOCK: Last candle is red — wait for green recovery")
    else:
        # Require meaningful green body (not just a tiny doji)
        body_pct = (last_close - last_open) / last_open * 100
        if body_pct < 0.05:
            hard_block = True
            reasons.append("BLOCK: Candle body too small (doji) — no momentum")
        else:
            score += 8; reasons.append(f"Green candle +{body_pct:.2f}%")

    # Falling knife: last 2 candles both red and each down >0.2%
    if len(candles) >= 3:
        c2 = candles[-2]
        if last_close < last_open and c2[3] < c2[0]:
            if (last_close / last_open - 1) < -0.002 and (c2[3] / c2[0] - 1) < -0.002:
                hard_block = True
                reasons.append("BLOCK: Falling knife — consecutive red candles")

    # ── Candlestick patterns ──────────────────────────────────────────────────
    prev = candles[-2]
    body  = abs(last_close - last_open)
    c_range = last_high - last_low
    if c_range > 0:
        lower_wick = min(last_close, last_open) - last_low
        if lower_wick > body * 2 and last_close > last_open:
            score += 15; reasons.append("Hammer — bullish reversal")
        if (last_close > last_open and prev[3] < prev[0]
                and last_open <= prev[3] and last_close >= prev[0]):
            score += 22; reasons.append("Bullish engulfing — strong reversal")
        if last_close > last_open and body / c_range > 0.6 and vol_ratio > 1.1:
            score += 8; reasons.append("Strong bullish candle")

    # ── Final decision ────────────────────────────────────────────────────────
    if hard_block:
        signal = "HOLD"
        score  = min(score, -1)
    elif score >= MIN_CONFIDENCE:
        signal = "BUY"
    elif score <= -MIN_CONFIDENCE:
        signal = "SELL"
    else:
        signal = "HOLD"

    confidence = min(abs(score), 100)
    return {
        "signal": signal,
        "score": score,
        "confidence": confidence,
        "rsi": rsi,
        "adx": adx,
        "atr_pct": round(atr_pct, 3),
        "price": price,
        "reasons": reasons,
        "nearest_support": nearest_sup,
        "nearest_resistance": nearest_res,
    }


# ── Paper portfolio ───────────────────────────────────────────────────────────

class PaperPortfolio:
    """One portfolio per strategy — each has independent balances and positions."""
    def __init__(self, strategy_key):
        self.strategy  = strategy_key
        self.params    = STRATEGY_PARAMS[strategy_key]
        self.balances  = {p: STARTING_BALANCE for p in PAIRS}
        self.positions = {}  # pair -> {price, qty, amount, sl, tp, tid}

    def open(self, pair, price, confidence, reasons):
        if pair in self.positions:
            return
        p   = self.params
        sl  = round(price * (1 - p["sl"]), 4)
        tp  = round(price * (1 + p["tp"]), 4)
        amt = round(self.balances[pair] * MAX_TRADE_PCT, 2)
        qty = amt / price
        tid = db_open_trade(self.strategy, pair, "BUY", price, qty, amt, sl, tp, confidence, reasons)
        self.positions[pair] = {"price": price, "qty": qty, "amount": amt, "sl": sl, "tp": tp, "tid": tid}
        self.balances[pair] -= amt
        logger.info(f"[{self.strategy}] BUY {pair} @ ${price:.4f} | amt=${amt} SL=${sl} TP=${tp}")

    def check_exits(self, pair, price):
        pos = self.positions.get(pair)
        if not pos:
            return
        status = None
        if price <= pos["sl"]:   status = "stop_loss"
        elif price >= pos["tp"]: status = "take_profit"
        if status:
            pnl     = (price - pos["price"]) * pos["qty"]
            pnl_pct = (price - pos["price"]) / pos["price"] * 100
            self.balances[pair] += pos["amount"] + pnl
            db_close_trade(pos["tid"], price, round(pnl, 4), round(pnl_pct, 3), status)
            del self.positions[pair]
            logger.info(f"[{self.strategy}] CLOSED {pair} @ ${price:.4f} | {status} PnL=${pnl:.2f}")


def get_signal_for(strategy_key, candles):
    if strategy_key == "SQUEEZE_BREAK":  return analyse_squeeze_break(candles)
    if strategy_key == "KELTNER_BREAK":  return analyse_keltner_break(candles)
    if strategy_key == "DONCHIAN_BREAK": return analyse_donchian_break(candles)
    if strategy_key == "ORB":            return analyse_orb(candles)
    return analyze(candles)


# One portfolio per strategy — created on demand
_portfolios: dict[str, PaperPortfolio] = {}

def get_portfolio(strategy_key) -> PaperPortfolio:
    if strategy_key not in _portfolios:
        _portfolios[strategy_key] = PaperPortfolio(strategy_key)
    return _portfolios[strategy_key]


def run_once():
    # Fetch prices once per pair (shared across all strategies)
    prices   = {}
    candles  = {}  # keyed by (pair, tf)
    for pair in PAIRS:
        try:
            prices[pair] = fetch_price(pair)
            db_log_price(pair, prices[pair])
        except Exception as e:
            logger.error(f"Price fetch {pair}: {e}")

    # Run each active strategy independently
    for skey in list(ACTIVE_STRATEGIES):
        params = STRATEGY_PARAMS.get(skey, {})
        tf     = params.get("tf", "1h")
        limit  = params.get("candles", 100)
        port   = get_portfolio(skey)

        for pair in PAIRS:
            try:
                price = prices.get(pair)
                if not price:
                    continue
                port.check_exits(pair, price)

                cache_key = (pair, tf, limit)
                if cache_key not in candles:
                    candles[cache_key] = fetch_candles(pair, tf, limit)
                sig = get_signal_for(skey, candles[cache_key])

                logger.info(f"[{skey}] {pair} ${price:.2f} | {sig['signal']} rsi={sig['rsi']}")
                if sig["signal"] == "BUY" and pair not in port.positions:
                    port.open(pair, price, sig["confidence"], sig["reasons"])
            except Exception as e:
                logger.error(f"[{skey}] {pair} error: {e}")


if __name__ == "__main__":
    logger.add("paper/paper.log", rotation="1 day", level="INFO")
    init_db()
    logger.info(f"Paper trader started | strategy={STRATEGY} | tf={TIMEFRAME} | SL={STOP_LOSS_PCT*100:.1f}% TP={TAKE_PROFIT_PCT*100:.1f}%")
    logger.info(f"Pairs={PAIRS} | balance=${STARTING_BALANCE}/pair")
    logger.info("Fetching live prices from Binance public API...")

    cycle = 0
    while True:
        cycle += 1
        logger.info(f"── Cycle {cycle} ──────────────────────────────")
        run_once()
        stats = get_stats()
        for pair, s in stats.items():
            logger.info(f"  {pair}: {s['total']} trades | WR={s['win_rate']}% | PnL=${s['total_pnl']}")
        time.sleep(60)
