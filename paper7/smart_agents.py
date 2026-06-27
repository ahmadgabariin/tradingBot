"""
Competition 7 — 5 Smart Agents with proven strategies from deep research.
Each agent uses a unique edge: RSI Oversold, Regime-Adaptive, BB Squeeze,
Market Structure Break of Structure, and RSI Divergence.
"""

# ── AGENT DEFINITIONS ─────────────────────────────────────────────────────────

SMART_AGENTS = {
    "The Surgeon v2": {
        "id": "S7-01", "emoji": "🧠", "color": "#00d4ff",
        "strategy": "RSI_Oversold_Strict",
        "timeframe": "15m",
        "sl": 0.005, "tp": 0.010,
        "description": "RSI Oversold/Overbought with ADX+volume confirmation. Best documented WR strategy.",
        "personality": {"aggression": 30, "patience": 90, "risk": 25},
        "bias": "BOTH",
    },
    "The Regime Lord": {
        "id": "S7-02", "emoji": "👑", "color": "#ffd700",
        "strategy": "Regime_Adaptive",
        "timeframe": "1h",
        "sl": 0.008, "tp": 0.024,
        "description": "Adapts strategy to market regime. Trending: EMA+MACD momentum. Ranging: BB bounce.",
        "personality": {"aggression": 50, "patience": 70, "risk": 40},
        "bias": "BOTH",
    },
    "The Squeeze": {
        "id": "S7-03", "emoji": "💥", "color": "#ff6b35",
        "strategy": "BB_Squeeze_Breakout",
        "timeframe": "15m",
        "sl": 0.008, "tp": 0.016,
        "description": "Waits for Bollinger Band compression then trades the explosive breakout.",
        "personality": {"aggression": 75, "patience": 85, "risk": 55},
        "bias": "BOTH",
    },
    "The Structure": {
        "id": "S7-04", "emoji": "🏗️", "color": "#a855f7",
        "strategy": "Market_Structure_BOS",
        "timeframe": "1h",
        "sl": 0.012, "tp": 0.036,
        "description": "Trades Break of Structure — HH/HL for longs, LH/LL for shorts.",
        "personality": {"aggression": 40, "patience": 95, "risk": 60},
        "bias": "BOTH",
    },
    "The Divergence": {
        "id": "S7-05", "emoji": "📐", "color": "#10b981",
        "strategy": "RSI_Divergence",
        "timeframe": "1h",
        "sl": 0.015, "tp": 0.030,
        "description": "RSI divergence vs price action — bullish/bearish hidden divergence.",
        "personality": {"aggression": 25, "patience": 98, "risk": 45},
        "bias": "BOTH",
    },
}

SMART_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "LINKUSDT", "DOTUSDT", "AVAXUSDT", "POLUSDT",
]

# ── SIGNAL HELPERS ────────────────────────────────────────────────────────────

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


# ── SIGNAL FUNCTIONS ──────────────────────────────────────────────────────────

# Agent 1: RSI Oversold Strict
def _surgeon2_long(p, i):
    if i < 50: return False
    rsi_turning_up = p["rsi"][i] > p["rsi"][i - 1] > p["rsi"][i - 2]
    return (p["rsi"][i] < 32
            and rsi_turning_up
            and p["c"][i] > p["e50"][i]
            and p["green"][i]
            and p["adx"][i] > 18
            and p["v"][i] > p["vol_avg"][i] * 0.9)

def _surgeon2_short(p, i):
    if i < 50: return False
    rsi_turning_down = p["rsi"][i] < p["rsi"][i - 1] < p["rsi"][i - 2]
    return (p["rsi"][i] > 68
            and rsi_turning_down
            and p["c"][i] < p["e50"][i]
            and not p["green"][i]
            and p["adx"][i] > 18
            and p["v"][i] > p["vol_avg"][i] * 0.9)


# Agent 2: Regime Adaptive
def _regime_long(p, i):
    if i < 60: return False
    regime = _detect_regime(p, i)
    if regime == "TREND_UP":
        return (p["c"][i] > p["e9"][i]
                and p["macd_hist"][i] > 0
                and p["macd_hist"][i] > p["macd_hist"][i - 1]
                and 45 < p["rsi"][i] < 68
                and p["v"][i] > p["vol_avg"][i] * 1.1
                and p["green"][i])
    if regime == "RANGING":
        return (p["c"][i] < p["bb_lo"][i]
                and p["rsi"][i] < 35
                and p["green"][i]
                and p["v"][i] > p["vol_avg"][i] * 1.1)
    return False

def _regime_short(p, i):
    if i < 60: return False
    regime = _detect_regime(p, i)
    if regime == "TREND_DOWN":
        return (p["c"][i] < p["e9"][i]
                and p["macd_hist"][i] < 0
                and p["macd_hist"][i] < p["macd_hist"][i - 1]
                and 32 < p["rsi"][i] < 55
                and p["v"][i] > p["vol_avg"][i] * 1.1
                and not p["green"][i])
    if regime == "RANGING":
        return (p["c"][i] > p["bb_hi"][i]
                and p["rsi"][i] > 65
                and not p["green"][i]
                and p["v"][i] > p["vol_avg"][i] * 1.1)
    return False


# Agent 3: BB Squeeze Breakout
def _bb_width(p, i):
    mid = p["bb_mid"][i]
    return (p["bb_hi"][i] - p["bb_lo"][i]) / mid if mid > 0 else 0.1

def _squeeze_long(p, i):
    if i < 30: return False
    w_now = _bb_width(p, i)
    w_avg = sum(_bb_width(p, max(0, i - k)) for k in range(1, 21)) / 20
    squeeze   = w_now < w_avg * 0.75
    breakout  = p["c"][i] > p["bb_hi"][i - 1] and p["green"][i]
    vol_spike = p["v"][i] > p["vol_avg"][i] * 1.3
    return squeeze and breakout and vol_spike and p["rsi"][i] < 80

def _squeeze_short(p, i):
    if i < 30: return False
    w_now = _bb_width(p, i)
    w_avg = sum(_bb_width(p, max(0, i - k)) for k in range(1, 21)) / 20
    squeeze    = w_now < w_avg * 0.75
    breakdown  = p["c"][i] < p["bb_lo"][i - 1] and not p["green"][i]
    vol_spike  = p["v"][i] > p["vol_avg"][i] * 1.3
    return squeeze and breakdown and vol_spike and p["rsi"][i] > 20


# Agent 4: Market Structure Break of Structure
def _structure_long(p, i):
    if i < 40: return False
    start = i - 25
    highs = _swing_highs(p, start, i)
    lows  = _swing_lows(p, start, i)
    if len(highs) < 2 or len(lows) < 2: return False
    hh = highs[-1][1] > highs[-2][1]
    hl = lows[-1][1]  > lows[-2][1]
    bos = p["c"][i] > highs[-2][1]
    return (hh and hl and bos
            and p["v"][i] > p["vol_avg"][i] * 1.15
            and p["adx"][i] > 18
            and p["rsi"][i] < 75)

def _structure_short(p, i):
    if i < 40: return False
    start = i - 25
    highs = _swing_highs(p, start, i)
    lows  = _swing_lows(p, start, i)
    if len(highs) < 2 or len(lows) < 2: return False
    lh = highs[-1][1] < highs[-2][1]
    ll = lows[-1][1]  < lows[-2][1]
    bos = p["c"][i] < lows[-2][1]
    return (lh and ll and bos
            and p["v"][i] > p["vol_avg"][i] * 1.15
            and p["adx"][i] > 18
            and p["rsi"][i] > 25)


# Agent 5: RSI Divergence
def _divergence_long(p, i):
    if i < 35: return False
    lb = 20
    start = i - lb
    # price made lower low, RSI made higher low → bullish divergence
    low_prices = [(j, p["l"][j]) for j in range(start, i)]
    if len(low_prices) < 2: return False
    low_prices.sort(key=lambda x: x[1])
    j1, j2 = low_prices[0][0], low_prices[1][0]
    if j1 == j2: return False
    earlier, later = (j1, j2) if j1 < j2 else (j2, j1)
    price_ll  = p["l"][later]  < p["l"][earlier]
    rsi_hl    = p["rsi"][later] > p["rsi"][earlier]
    near_low  = p["c"][i] <= p["l"][later] * 1.008
    return (price_ll and rsi_hl and near_low
            and p["rsi"][i] < 42
            and p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.0)

def _divergence_short(p, i):
    if i < 35: return False
    lb = 20
    start = i - lb
    # price made higher high, RSI made lower high → bearish divergence
    hi_prices = [(j, p["h"][j]) for j in range(start, i)]
    if len(hi_prices) < 2: return False
    hi_prices.sort(key=lambda x: -x[1])
    j1, j2 = hi_prices[0][0], hi_prices[1][0]
    if j1 == j2: return False
    earlier, later = (j1, j2) if j1 < j2 else (j2, j1)
    price_hh  = p["h"][later]  > p["h"][earlier]
    rsi_lh    = p["rsi"][later] < p["rsi"][earlier]
    near_hi   = p["c"][i] >= p["h"][later] * 0.992
    return (price_hh and rsi_lh and near_hi
            and p["rsi"][i] > 58
            and not p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.0)


# ── SIGNAL MAPS ───────────────────────────────────────────────────────────────

LONG_SIGNALS = {
    "The Surgeon v2":  _surgeon2_long,
    "The Regime Lord": _regime_long,
    "The Squeeze":     _squeeze_long,
    "The Structure":   _structure_long,
    "The Divergence":  _divergence_long,
}

SHORT_SIGNALS = {
    "The Surgeon v2":  _surgeon2_short,
    "The Regime Lord": _regime_short,
    "The Squeeze":     _squeeze_short,
    "The Structure":   _structure_short,
    "The Divergence":  _divergence_short,
}
