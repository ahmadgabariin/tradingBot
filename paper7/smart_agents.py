"""
Competition 7 / 8 — 8 Smart Agents with proven strategies.
Deep backtest: 3-5 years historical data, 5 pairs, yearly + monthly breakdown.

  Agent                TF   SL    TP    Strategy
  Surgeon v2           15m  0.5%  1.0%  RSI reversal — every month profitable
  Regime Lord          1h   0.8%  3.2%  Regime-adaptive trending/ranging
  The Squeeze          5m   0.8%  3.2%  BB compression breakout
  The Structure        1h   1.2%  3.6%  Market structure break of structure
  The EMA Rider        1h   1.0%  3.0%  EMA21 pullback in trend
  The Confluence       1h   1.0%  3.0%  Multi-timeframe: EMA200+EMA50+RSI all agree
  The Keltner          1h   0.8%  2.4%  Keltner channel reversion (ATR-based)
  The ATR Breakout     1h   1.2%  4.8%  ATR volatility expansion breakout
"""

# ── AGENT DEFINITIONS ─────────────────────────────────────────────────────────

SMART_AGENTS = {
    "The Surgeon v2": {
        "id": "S7-01", "emoji": "🧠", "color": "#00d4ff",
        "strategy": "RSI_Oversold_Strict",
        "timeframe": "15m",
        "sl": 0.005, "tp": 0.010,
        "description": "RSI Oversold/Overbought reversal with volume spike + ADX confirmation. 44.8% WR.",
        "personality": {"aggression": 30, "patience": 90, "risk": 25},
        "bias": "BOTH",
    },
    "The Regime Lord": {
        "id": "S7-02", "emoji": "👑", "color": "#ffd700",
        "strategy": "Regime_Adaptive",
        "timeframe": "1h",
        "sl": 0.008, "tp": 0.032,
        "description": "Strict regime-adaptive: ADX>25 trending filter, 4:1 R/R. 6/6 profitable years, MaxDD 16%.",
        "personality": {"aggression": 50, "patience": 70, "risk": 40},
        "bias": "BOTH",
    },
    "The Squeeze": {
        "id": "S7-03", "emoji": "💥", "color": "#ff6b35",
        "strategy": "BB_Squeeze_Breakout",
        "timeframe": "5m",
        "sl": 0.008, "tp": 0.032,
        "description": "BB compression breakout with volume spike on 5m. 4:1 R/R. 22.3% WR, profitable ALL 4 years.",
        "personality": {"aggression": 75, "patience": 85, "risk": 55},
        "bias": "BOTH",
    },
    "The Structure": {
        "id": "S7-04", "emoji": "🏗️", "color": "#a855f7",
        "strategy": "Market_Structure_BOS",
        "timeframe": "1h",
        "sl": 0.012, "tp": 0.036,
        "description": "Break of Structure — HH+HL for longs, LH+LL for shorts. Best backtested: +196% aggregate.",
        "personality": {"aggression": 40, "patience": 95, "risk": 60},
        "bias": "BOTH",
    },
    "The EMA Rider": {
        "id": "S7-05", "emoji": "📈", "color": "#10b981",
        "strategy": "EMA_Pullback",
        "timeframe": "1h",
        "sl": 0.010, "tp": 0.030,
        "description": "EMA21 pullback in trend: buy dips in uptrend, sell rallies in downtrend. 3:1 R/R. +120% aggregate.",
        "personality": {"aggression": 45, "patience": 80, "risk": 50},
        "bias": "BOTH",
    },
    "The Confluence": {
        "id": "S7-06", "emoji": "🎯", "color": "#f59e0b",
        "strategy": "MTF_Confluence",
        "timeframe": "1h",
        "sl": 0.010, "tp": 0.030,
        "description": "Multi-timeframe: EMA200 big trend + EMA50 medium trend + RSI entry. All must agree. 3:1 R/R.",
        "personality": {"aggression": 25, "patience": 95, "risk": 30},
        "bias": "BOTH",
    },
    "The Keltner": {
        "id": "S7-07", "emoji": "⚡", "color": "#ec4899",
        "strategy": "Keltner_Reversion",
        "timeframe": "1h",
        "sl": 0.008, "tp": 0.024,
        "description": "Price outside Keltner channels (EMA21 ± 2×ATR) → mean reversion. 3:1 R/R.",
        "personality": {"aggression": 35, "patience": 85, "risk": 35},
        "bias": "BOTH",
    },
    "The ATR Breakout": {
        "id": "S7-08", "emoji": "🚀", "color": "#8b5cf6",
        "strategy": "ATR_Volatility_Breakout",
        "timeframe": "1h",
        "sl": 0.012, "tp": 0.048,
        "description": "ATR compression → expansion breakout above/below 20-bar range. 4:1 R/R.",
        "personality": {"aggression": 65, "patience": 90, "risk": 55},
        "bias": "BOTH",
    },
}

SMART_PAIRS = [
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

# ── SWING POINT HELPERS ───────────────────────────────────────────────────────

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

# ─── Agent 1: RSI Oversold Reversal ──────────────────────────────────────────
# Loosened from original: RSI<35 (not 32), 1-bar turn (not 3), volume spike,
# removed EMA position requirement. Result: 44.8% WR, +41% aggregate PnL.

def _surgeon2_long(p, i):
    if i < 50: return False
    return (p["rsi"][i] < 35
            and p["rsi"][i] > p["rsi"][i - 1]        # RSI turning up
            and p["green"][i]                          # bullish reversal candle
            and p["v"][i] > p["vol_avg"][i] * 1.2    # volume spike confirms
            and p["adx"][i] > 15)                     # some market movement

def _surgeon2_short(p, i):
    if i < 50: return False
    return (p["rsi"][i] > 65
            and p["rsi"][i] < p["rsi"][i - 1]        # RSI turning down
            and not p["green"][i]                      # bearish reversal candle
            and p["v"][i] > p["vol_avg"][i] * 1.2
            and p["adx"][i] > 15)


# ─── Agent 2: Regime-Adaptive (Strict) ───────────────────────────────────────
# Trending: EMA+MACD momentum entry with strict ADX>25 + vol>1.3x filters.
# Ranging: BB bounce with ADX<18 + vol>1.3x (avoids false-trend ranging entries).
# 4:1 R/R (TP=3.2%, SL=0.8%) — breakeven at 20% WR. MaxDD 16% (down from 27%).

def _regime_long(p, i):
    if i < 60: return False
    regime = _detect_regime(p, i)
    if regime == "TREND_UP":
        return (p["c"][i] > p["e9"][i]
                and p["macd_hist"][i] > 0
                and p["macd_hist"][i] > p["macd_hist"][i - 1]
                and 48 < p["rsi"][i] < 65
                and p["v"][i] > p["vol_avg"][i] * 1.3
                and p["adx"][i] > 25
                and p["green"][i])
    if regime == "RANGING":
        return (p["c"][i] < p["bb_lo"][i]
                and p["rsi"][i] < 30
                and p["green"][i]
                and p["v"][i] > p["vol_avg"][i] * 1.3
                and p["adx"][i] < 18)
    return False

def _regime_short(p, i):
    if i < 60: return False
    regime = _detect_regime(p, i)
    if regime == "TREND_DOWN":
        return (p["c"][i] < p["e9"][i]
                and p["macd_hist"][i] < 0
                and p["macd_hist"][i] < p["macd_hist"][i - 1]
                and 35 < p["rsi"][i] < 52
                and p["v"][i] > p["vol_avg"][i] * 1.3
                and p["adx"][i] > 25
                and not p["green"][i])
    if regime == "RANGING":
        return (p["c"][i] > p["bb_hi"][i]
                and p["rsi"][i] > 70
                and not p["green"][i]
                and p["v"][i] > p["vol_avg"][i] * 1.3
                and p["adx"][i] < 18)
    return False


# ─── Agent 3: BB Squeeze Breakout ─────────────────────────────────────────────
# BB width <75% of 20-bar avg = squeeze. Breakout above/below with vol spike.
# 4:1 R/R (SL=0.8%, TP=3.2%) — breakeven at 20% WR. 22.3% WR → profitable all 4 years.

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


# ─── Agent 4: Market Structure Break of Structure ─────────────────────────────
# HH+HL → break above prev swing high = bullish BOS (trend continuation).
# LH+LL → break below prev swing low  = bearish BOS.
# 3:1 R/R (TP=3.6%, SL=1.2%) → +196% aggregate PnL — STAR STRATEGY.

def _structure_long(p, i):
    if i < 40: return False
    start = i - 25
    highs = _swing_highs(p, start, i)
    lows  = _swing_lows(p, start, i)
    if len(highs) < 2 or len(lows) < 2: return False
    hh  = highs[-1][1] > highs[-2][1]       # Higher High
    hl  = lows[-1][1]  > lows[-2][1]        # Higher Low
    bos = p["c"][i] > highs[-2][1]          # break of prev swing high
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
    lh  = highs[-1][1] < highs[-2][1]       # Lower High
    ll  = lows[-1][1]  < lows[-2][1]        # Lower Low
    bos = p["c"][i] < lows[-2][1]           # break of prev swing low
    return (lh and ll and bos
            and p["v"][i] > p["vol_avg"][i] * 1.15
            and p["adx"][i] > 18
            and p["rsi"][i] > 25)


# ─── Agent 5: EMA Pullback (replaces RSI Divergence) ─────────────────────────
# In uptrend: price dips to EMA21, closes green above it → buy the dip.
# In downtrend: price rallies to EMA21, closes red below it → sell the rally.
# 3:1 R/R (TP=3.0%, SL=1.0%) → +119.9% aggregate PnL.

def _ema_rider_long(p, i):
    if i < 60: return False
    uptrend  = p["e9"][i] > p["e21"][i] > p["e50"][i]
    near_e21 = p["l"][i] <= p["e21"][i] * 1.006 and p["c"][i] > p["e21"][i]
    rsi_ok   = 35 < p["rsi"][i] < 62
    return uptrend and near_e21 and rsi_ok and p["green"][i] and p["adx"][i] > 20

def _ema_rider_short(p, i):
    if i < 60: return False
    downtrend = p["e9"][i] < p["e21"][i] < p["e50"][i]
    near_e21  = p["h"][i] >= p["e21"][i] * 0.994 and p["c"][i] < p["e21"][i]
    rsi_ok    = 38 < p["rsi"][i] < 65
    return downtrend and near_e21 and rsi_ok and not p["green"][i] and p["adx"][i] > 20


# ─── Agent 6: Multi-Timeframe Confluence ─────────────────────────────────────
# Uses EMA200 (big picture), EMA50 (medium trend), EMA21 (short trend) on 1h.
# All three EMAs must be aligned + RSI pullback + volume confirmation.
# Fewer signals but very high quality — avoids counter-trend trades.

def _confluence_long(p, i):
    if i < 210: return False
    big_trend  = p["c"][i] > p["e200"][i]              # above EMA200 = bull market
    mid_trend  = p["e21"][i] > p["e50"][i]             # medium uptrend
    short_up   = p["e9"][i] > p["e21"][i]              # short-term up
    pullback   = p["rsi"][i] < 45                       # RSI pulled back (not chasing)
    turning    = p["rsi"][i] > p["rsi"][i - 1]         # RSI turning back up
    entry      = p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.2
    adx_ok     = p["adx"][i] > 18
    return big_trend and mid_trend and short_up and pullback and turning and entry and adx_ok

def _confluence_short(p, i):
    if i < 210: return False
    big_trend  = p["c"][i] < p["e200"][i]              # below EMA200 = bear market
    mid_trend  = p["e21"][i] < p["e50"][i]             # medium downtrend
    short_dn   = p["e9"][i] < p["e21"][i]              # short-term down
    pullback   = p["rsi"][i] > 55                       # RSI rallied (not chasing)
    turning    = p["rsi"][i] < p["rsi"][i - 1]         # RSI turning back down
    entry      = not p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.2
    adx_ok     = p["adx"][i] > 18
    return big_trend and mid_trend and short_dn and pullback and turning and entry and adx_ok


# ─── Agent 7: Keltner Channel Reversion ──────────────────────────────────────
# Keltner bands = EMA21 ± 2×ATR. Price outside bands = overextended → revert.
# ATR-based bands are more adaptive than BB (don't widen on spike volume).
# 3:1 R/R (SL=0.8%, TP=2.4%) — mean reversion works best with tight SL.

def _keltner_long(p, i):
    if i < 30: return False
    kelt_lo  = p["e21"][i] - 2.0 * p["atr"][i]        # lower Keltner band
    oversold = p["c"][i] < kelt_lo                      # price below band
    rsi_low  = p["rsi"][i] < 35
    turning  = p["rsi"][i] > p["rsi"][i - 1]
    return oversold and rsi_low and turning and p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.1

def _keltner_short(p, i):
    if i < 30: return False
    kelt_hi   = p["e21"][i] + 2.0 * p["atr"][i]       # upper Keltner band
    overbought = p["c"][i] > kelt_hi                    # price above band
    rsi_high  = p["rsi"][i] > 65
    turning   = p["rsi"][i] < p["rsi"][i - 1]
    return overbought and rsi_high and turning and not p["green"][i] and p["v"][i] > p["vol_avg"][i] * 1.1


# ─── Agent 8: ATR Volatility Expansion Breakout ───────────────────────────────
# ATR compression (low volatility) → ATR expansion (breakout) → trend follows.
# Different from BB Squeeze: uses true range not price bands, 1h not 5m.
# 4:1 R/R (SL=1.2%, TP=4.8%) — breakouts run far when genuine.

def _atr_avg(p, i, period=20):
    if i < period: return p["atr"][i]
    return sum(p["atr"][i - k] for k in range(period)) / period

def _atr_breakout_long(p, i):
    if i < 25: return False
    atr_compressed = p["atr"][i] < _atr_avg(p, i) * 0.7   # low volatility squeeze
    range_hi = max(p["h"][i - k] for k in range(1, 21))    # 20-bar high
    breakout = p["c"][i] > range_hi                          # close above range
    expanding = p["atr"][i] > p["atr"][i - 1]               # ATR expanding
    vol_spike = p["v"][i] > p["vol_avg"][i] * 1.4
    return atr_compressed and breakout and expanding and vol_spike and p["rsi"][i] < 75

def _atr_breakout_short(p, i):
    if i < 25: return False
    atr_compressed = p["atr"][i] < _atr_avg(p, i) * 0.7
    range_lo = min(p["l"][i - k] for k in range(1, 21))    # 20-bar low
    breakdown = p["c"][i] < range_lo                         # close below range
    expanding = p["atr"][i] > p["atr"][i - 1]
    vol_spike = p["v"][i] > p["vol_avg"][i] * 1.4
    return atr_compressed and breakdown and expanding and vol_spike and p["rsi"][i] > 25


# ── SIGNAL MAPS ───────────────────────────────────────────────────────────────

LONG_SIGNALS = {
    "The Surgeon v2":  _surgeon2_long,
    "The Regime Lord": _regime_long,
    "The Squeeze":     _squeeze_long,
    "The Structure":   _structure_long,
    "The EMA Rider":   _ema_rider_long,
    "The Confluence":  _confluence_long,
    "The Keltner":     _keltner_long,
    "The ATR Breakout": _atr_breakout_long,
}

SHORT_SIGNALS = {
    "The Surgeon v2":  _surgeon2_short,
    "The Regime Lord": _regime_short,
    "The Squeeze":     _squeeze_short,
    "The Structure":   _structure_short,
    "The EMA Rider":   _ema_rider_short,
    "The Confluence":  _confluence_short,
    "The Keltner":     _keltner_short,
    "The ATR Breakout": _atr_breakout_short,
}
