"""
Competition 9 — 9 agents: all 8 from comp7/8 upgraded to ATR dynamic SL/TP
+ trailing stops + Agent 9 (The Supertrend) as trend-following trailer.

ATR dynamic SL/TP:
  sl = entry - atr_sl_mult * ATR   (LONG), entry + atr_sl_mult * ATR (SHORT)
  tp = entry + atr_tp_mult * ATR   (LONG), entry - atr_tp_mult * ATR (SHORT)
  4:1 R/R maintained (tp_mult = 2 * sl_mult) but adapts to volatility.

Trailing stop:
  Every tick: new_sl = price - atr_sl_mult * ATR (LONG)
  If new_sl > current SL → move SL up (locks in profit).

Supertrend (Agent 9):
  upper = HL2 + 3 * ATR(10)  |  lower = HL2 - 3 * ATR(10)
  Signal: trend flips bullish → LONG, flips bearish → SHORT
  SL = Supertrend line (dynamic), TP = 8% (very far — trailing stop exits first)
"""

# ── AGENT DEFINITIONS ──────────────────────────────────────────────────────────

COMP9_AGENTS = {
    "The Surgeon v2": {
        "id": "S9-01", "emoji": "🧠", "color": "#00d4ff",
        "strategy": "RSI_Oversold_ATR",
        "timeframe": "15m",
        "sl": 0.005, "tp": 0.010,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0,
        "trailing": True,
        "description": "RSI reversal — ATR dynamic SL/TP + trailing stop. 15m timeframe.",
        "personality": {"aggression": 30, "patience": 90, "risk": 25},
        "bias": "BOTH",
    },
    "The Regime Lord": {
        "id": "S9-02", "emoji": "👑", "color": "#ffd700",
        "strategy": "Regime_ATR",
        "timeframe": "1h",
        "sl": 0.008, "tp": 0.032,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0,
        "trailing": True,
        "description": "Regime-adaptive with ATR dynamic SL/TP. Trailing stop locks gains in trending moves.",
        "personality": {"aggression": 50, "patience": 70, "risk": 40},
        "bias": "BOTH",
    },
    "The Squeeze": {
        "id": "S9-03", "emoji": "💥", "color": "#ff6b35",
        "strategy": "BB_Squeeze_ATR",
        "timeframe": "5m",
        "sl": 0.008, "tp": 0.032,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0,
        "trailing": True,
        "description": "BB squeeze breakout — ATR SL/TP + trailing. Breakouts can run far.",
        "personality": {"aggression": 75, "patience": 85, "risk": 55},
        "bias": "BOTH",
    },
    "The Structure": {
        "id": "S9-04", "emoji": "🏗️", "color": "#a855f7",
        "strategy": "Market_Structure_ATR",
        "timeframe": "1h",
        "sl": 0.012, "tp": 0.036,
        "atr_sl_mult": 2.5, "atr_tp_mult": 5.0,
        "trailing": True,
        "description": "Break of Structure — wide ATR SL/TP (2.5×/5×) + trailing. Handles big moves.",
        "personality": {"aggression": 40, "patience": 95, "risk": 60},
        "bias": "BOTH",
    },
    "The EMA Rider": {
        "id": "S9-05", "emoji": "📈", "color": "#10b981",
        "strategy": "EMA_Pullback_ATR",
        "timeframe": "1h",
        "sl": 0.010, "tp": 0.030,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0,
        "trailing": True,
        "description": "EMA21 pullback — ATR trailing stop follows the trend until it ends.",
        "personality": {"aggression": 45, "patience": 80, "risk": 50},
        "bias": "BOTH",
    },
    "The Confluence": {
        "id": "S9-06", "emoji": "🎯", "color": "#f59e0b",
        "strategy": "MTF_Confluence_ATR",
        "timeframe": "1h",
        "sl": 0.010, "tp": 0.030,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0,
        "trailing": True,
        "description": "Multi-timeframe confluence — ATR SL/TP + trailing. High-quality entries ride the trend.",
        "personality": {"aggression": 25, "patience": 95, "risk": 30},
        "bias": "BOTH",
    },
    "The Keltner": {
        "id": "S9-07", "emoji": "⚡", "color": "#ec4899",
        "strategy": "Keltner_ATR",
        "timeframe": "1h",
        "sl": 0.008, "tp": 0.024,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0,
        "trailing": False,
        "description": "Keltner reversion — tight ATR SL (1.5×) for mean reversion. No trailing (counter-trend).",
        "personality": {"aggression": 35, "patience": 85, "risk": 35},
        "bias": "BOTH",
    },
    "The ATR Breakout": {
        "id": "S9-08", "emoji": "🚀", "color": "#8b5cf6",
        "strategy": "ATR_Breakout_Trail",
        "timeframe": "1h",
        "sl": 0.012, "tp": 0.048,
        "atr_sl_mult": 2.5, "atr_tp_mult": 5.0,
        "trailing": True,
        "description": "ATR volatility breakout — wide ATR SL + aggressive trailing. Designed for big momentum moves.",
        "personality": {"aggression": 65, "patience": 90, "risk": 55},
        "bias": "BOTH",
    },
    "The Supertrend": {
        "id": "S9-09", "emoji": "🌊", "color": "#00ffcc",
        "strategy": "Supertrend_Trail",
        "timeframe": "1h",
        "sl": 0.030, "tp": 0.150,
        "atr_sl_mult": 3.0, "atr_tp_mult": 12.0,
        "trailing": True,
        "supertrend": True,
        "st_period": 10, "st_mult": 3.0,
        "description": "Supertrend flip signal — price crosses Supertrend line. SL = Supertrend band. Rides trend until reversal.",
        "personality": {"aggression": 60, "patience": 98, "risk": 50},
        "bias": "BOTH",
    },
}

COMP9_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "LINKUSDT", "DOTUSDT", "AVAXUSDT", "POLUSDT",
]

# ── REGIME DETECTION ──────────────────────────────────────────────────────────

def _detect_regime(p, i):
    if i < 60: return "NEUTRAL"
    adx = p["adx"][i]
    e9, e21, e50 = p["e9"][i], p["e21"][i], p["e50"][i]
    if adx > 25:
        if e9 > e21 > e50: return "TREND_UP"
        if e9 < e21 < e50: return "TREND_DOWN"
    if adx < 20: return "RANGING"
    return "NEUTRAL"

def _swing_highs(p, start, end):
    out = []
    for j in range(start + 1, end - 1):
        if p["h"][j] > p["h"][j - 1] and p["h"][j] > p["h"][j + 1]:
            out.append((j, p["h"][j]))
    return out

def _swing_lows(p, start, end):
    out = []
    for j in range(start + 1, end - 1):
        if p["l"][j] < p["l"][j - 1] and p["l"][j] < p["l"][j + 1]:
            out.append((j, p["l"][j]))
    return out

# ── SUPERTREND CALCULATION ─────────────────────────────────────────────────────

def calc_supertrend(p, period=10, multiplier=3.0):
    """Returns (trend[], final_upper[], final_lower[]).
    trend[i] = 1 (bullish) or -1 (bearish)."""
    n = p["n"]
    atr = p["atr"]
    hl2 = [(p["h"][i] + p["l"][i]) / 2 for i in range(n)]

    upper = [hl2[i] + multiplier * atr[i] for i in range(n)]
    lower = [hl2[i] - multiplier * atr[i] for i in range(n)]

    fu = [0.0] * n
    fl = [0.0] * n
    trend = [1] * n

    fu[0] = upper[0]
    fl[0] = lower[0]

    for i in range(1, n):
        fu[i] = upper[i] if (upper[i] < fu[i-1] or p["c"][i-1] > fu[i-1]) else fu[i-1]
        fl[i] = lower[i] if (lower[i] > fl[i-1] or p["c"][i-1] < fl[i-1]) else fl[i-1]

        if trend[i-1] == 1:
            trend[i] = 1 if p["c"][i] >= fl[i] else -1
        else:
            trend[i] = -1 if p["c"][i] <= fu[i] else 1

    return trend, fu, fl

# ── SIGNAL FUNCTIONS ──────────────────────────────────────────────────────────

def _surgeon2_long(p, i):
    if i < 50: return False
    return (p["rsi"][i] < 35 and p["rsi"][i] > p["rsi"][i-1]
            and p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.2 and p["adx"][i] > 15)

def _surgeon2_short(p, i):
    if i < 50: return False
    return (p["rsi"][i] > 65 and p["rsi"][i] < p["rsi"][i-1]
            and not p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.2 and p["adx"][i] > 15)

def _regime_long(p, i):
    if i < 60: return False
    regime = _detect_regime(p, i)
    if regime == "TREND_UP":
        return (p["c"][i] > p["e9"][i] and p["macd_hist"][i] > 0
                and p["macd_hist"][i] > p["macd_hist"][i-1]
                and 48 < p["rsi"][i] < 65 and p["v"][i] > p["vol_avg"][i] * 1.3
                and p["adx"][i] > 25 and p["green"][i])
    if regime == "RANGING":
        return (p["c"][i] < p["bb_lo"][i] and p["rsi"][i] < 30
                and p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.3 and p["adx"][i] < 18)
    return False

def _regime_short(p, i):
    if i < 60: return False
    regime = _detect_regime(p, i)
    if regime == "TREND_DOWN":
        return (p["c"][i] < p["e9"][i] and p["macd_hist"][i] < 0
                and p["macd_hist"][i] < p["macd_hist"][i-1]
                and 35 < p["rsi"][i] < 52 and p["v"][i] > p["vol_avg"][i] * 1.3
                and p["adx"][i] > 25 and not p["green"][i])
    if regime == "RANGING":
        return (p["c"][i] > p["bb_hi"][i] and p["rsi"][i] > 70
                and not p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.3 and p["adx"][i] < 18)
    return False

def _bb_width(p, i):
    mid = p["bb_mid"][i]
    return (p["bb_hi"][i] - p["bb_lo"][i]) / mid if mid > 0 else 0.1

def _squeeze_long(p, i):
    if i < 30: return False
    w_now = _bb_width(p, i)
    w_avg = sum(_bb_width(p, max(0, i - k)) for k in range(1, 21)) / 20
    return (w_now < w_avg * 0.75 and p["c"][i] > p["bb_hi"][i-1]
            and p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.3 and p["rsi"][i] < 80)

def _squeeze_short(p, i):
    if i < 30: return False
    w_now = _bb_width(p, i)
    w_avg = sum(_bb_width(p, max(0, i - k)) for k in range(1, 21)) / 20
    return (w_now < w_avg * 0.75 and p["c"][i] < p["bb_lo"][i-1]
            and not p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.3 and p["rsi"][i] > 20)

def _structure_long(p, i):
    if i < 40: return False
    start = i - 25
    highs = _swing_highs(p, start, i)
    lows  = _swing_lows(p, start, i)
    if len(highs) < 2 or len(lows) < 2: return False
    return (highs[-1][1] > highs[-2][1] and lows[-1][1] > lows[-2][1]
            and p["c"][i] > highs[-2][1]
            and p["v"][i] > p["vol_avg"][i] * 1.15 and p["adx"][i] > 18 and p["rsi"][i] < 75)

def _structure_short(p, i):
    if i < 40: return False
    start = i - 25
    highs = _swing_highs(p, start, i)
    lows  = _swing_lows(p, start, i)
    if len(highs) < 2 or len(lows) < 2: return False
    return (highs[-1][1] < highs[-2][1] and lows[-1][1] < lows[-2][1]
            and p["c"][i] < lows[-2][1]
            and p["v"][i] > p["vol_avg"][i] * 1.15 and p["adx"][i] > 18 and p["rsi"][i] > 25)

def _ema_rider_long(p, i):
    if i < 60: return False
    return (p["e9"][i] > p["e21"][i] > p["e50"][i]
            and p["l"][i] <= p["e21"][i] * 1.006 and p["c"][i] > p["e21"][i]
            and 35 < p["rsi"][i] < 62 and p["green"][i] and p["adx"][i] > 20)

def _ema_rider_short(p, i):
    if i < 60: return False
    return (p["e9"][i] < p["e21"][i] < p["e50"][i]
            and p["h"][i] >= p["e21"][i] * 0.994 and p["c"][i] < p["e21"][i]
            and 38 < p["rsi"][i] < 65 and not p["green"][i] and p["adx"][i] > 20)

def _confluence_long(p, i):
    if i < 210: return False
    return (p["c"][i] > p["e200"][i] and p["e21"][i] > p["e50"][i]
            and p["e9"][i] > p["e21"][i] and p["rsi"][i] < 45
            and p["rsi"][i] > p["rsi"][i-1] and p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.2 and p["adx"][i] > 18)

def _confluence_short(p, i):
    if i < 210: return False
    return (p["c"][i] < p["e200"][i] and p["e21"][i] < p["e50"][i]
            and p["e9"][i] < p["e21"][i] and p["rsi"][i] > 55
            and p["rsi"][i] < p["rsi"][i-1] and not p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.2 and p["adx"][i] > 18)

def _keltner_long(p, i):
    if i < 30: return False
    kelt_lo = p["e21"][i] - 2.0 * p["atr"][i]
    return (p["c"][i] < kelt_lo and p["rsi"][i] < 35
            and p["rsi"][i] > p["rsi"][i-1] and p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.1)

def _keltner_short(p, i):
    if i < 30: return False
    kelt_hi = p["e21"][i] + 2.0 * p["atr"][i]
    return (p["c"][i] > kelt_hi and p["rsi"][i] > 65
            and p["rsi"][i] < p["rsi"][i-1] and not p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.1)

def _atr_avg(p, i, period=20):
    if i < period: return p["atr"][i]
    return sum(p["atr"][i - k] for k in range(period)) / period

def _atr_breakout_long(p, i):
    if i < 25: return False
    return (p["atr"][i] < _atr_avg(p, i) * 0.7
            and p["c"][i] > max(p["h"][i-k] for k in range(1, 21))
            and p["atr"][i] > p["atr"][i-1]
            and p["v"][i] > p["vol_avg"][i] * 1.4 and p["rsi"][i] < 75)

def _atr_breakout_short(p, i):
    if i < 25: return False
    return (p["atr"][i] < _atr_avg(p, i) * 0.7
            and p["c"][i] < min(p["l"][i-k] for k in range(1, 21))
            and p["atr"][i] > p["atr"][i-1]
            and p["v"][i] > p["vol_avg"][i] * 1.4 and p["rsi"][i] > 25)

def _supertrend_long(p, i):
    """Supertrend flips bullish: trend was -1 at i-1, now 1 at i."""
    if i < 15: return False
    trend, fu, fl = calc_supertrend(p, period=10, multiplier=3.0)
    return trend[i] == 1 and trend[i-1] == -1

def _supertrend_short(p, i):
    """Supertrend flips bearish: trend was 1 at i-1, now -1 at i."""
    if i < 15: return False
    trend, fu, fl = calc_supertrend(p, period=10, multiplier=3.0)
    return trend[i] == -1 and trend[i-1] == 1

# ── SIGNAL MAPS ───────────────────────────────────────────────────────────────

LONG_SIGNALS_9 = {
    "The Surgeon v2":  _surgeon2_long,
    "The Regime Lord": _regime_long,
    "The Squeeze":     _squeeze_long,
    "The Structure":   _structure_long,
    "The EMA Rider":   _ema_rider_long,
    "The Confluence":  _confluence_long,
    "The Keltner":     _keltner_long,
    "The ATR Breakout": _atr_breakout_long,
    "The Supertrend":  _supertrend_long,
}

SHORT_SIGNALS_9 = {
    "The Surgeon v2":  _surgeon2_short,
    "The Regime Lord": _regime_short,
    "The Squeeze":     _squeeze_short,
    "The Structure":   _structure_short,
    "The EMA Rider":   _ema_rider_short,
    "The Confluence":  _confluence_short,
    "The Keltner":     _keltner_short,
    "The ATR Breakout": _atr_breakout_short,
    "The Supertrend":  _supertrend_short,
}
