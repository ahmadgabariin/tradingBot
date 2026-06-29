"""
Competition 9 / 10 — 26 agents: 17 original (comp2) + 9 smart (comp7/8).
All upgraded to ATR dynamic SL/TP + trailing stops.
Agent 26 (The Supertrend) is brand new.

ATR dynamic SL/TP:
  sl = entry - atr_sl_mult * ATR   (LONG)
  tp = entry + atr_tp_mult * ATR   (LONG)
  Adapts to volatility: wider in wild markets, tighter in calm ones.

Trailing stop:
  Every tick: new_sl = price - atr_sl_mult * ATR (LONG)
  If new_sl > current SL → move SL up (locks profit).
"""

# ── ORIGINAL 17 AGENTS — ATR UPGRADED ─────────────────────────────────────────
# Signal logic unchanged. SL/TP now ATR-based instead of fixed %.
# atr_sl_mult / atr_tp_mult chosen to approximate each agent's original R/R spirit.

ORIGINAL_17_ATR = {
    "The Surgeon": {
        "id": "surgeon", "emoji": "🏆", "color": "#FFD700", "bias": "NEUTRAL",
        "strategy": "MACD_BB_Combo", "timeframe": "1h", "sl": 0.008, "tp": 0.080,
        "atr_sl_mult": 2.0, "atr_tp_mult": 8.0, "trailing": True,
        "description": "MACD+BB Combo — ATR dynamic SL/TP. Large TP mult (8×) preserves original big-TP spirit.",
        "personality": {"aggression": 40, "patience": 80, "risk": 50},
    },
    "The Maniac": {
        "id": "maniac", "emoji": "🔥", "color": "#FF4500", "bias": "SHORT",
        "strategy": "Keltner_Break", "timeframe": "15m", "sl": 0.025, "tp": 0.006,
        "atr_sl_mult": 1.0, "atr_tp_mult": 1.5, "trailing": False,
        "description": "Keltner short-side scalper — tight ATR stops, fast exits. No trailing (counter-trend).",
        "personality": {"aggression": 95, "patience": 10, "risk": 70},
    },
    "The Hound": {
        "id": "hound", "emoji": "🐺", "color": "#FF69B4", "bias": "SHORT",
        "strategy": "Donchian_Break", "timeframe": "1h", "sl": 0.012, "tp": 0.060,
        "atr_sl_mult": 2.0, "atr_tp_mult": 6.0, "trailing": True,
        "description": "Donchian channel breakout — ATR SL/TP + trailing. Tracks the break and runs.",
        "personality": {"aggression": 65, "patience": 70, "risk": 60},
    },
    "The Oracle": {
        "id": "oracle", "emoji": "🔮", "color": "#00CED1", "bias": "SHORT",
        "strategy": "ADX_Trend", "timeframe": "1h", "sl": 0.035, "tp": 0.020,
        "atr_sl_mult": 2.5, "atr_tp_mult": 3.0, "trailing": True,
        "description": "ADX trend — wide ATR SL (2.5×) matches original wide stop. Trailing locks gains.",
        "personality": {"aggression": 55, "patience": 85, "risk": 50},
    },
    "The Comet": {
        "id": "comet", "emoji": "☄️", "color": "#9370DB", "bias": "NEUTRAL",
        "strategy": "ORB", "timeframe": "1h", "sl": 0.020, "tp": 0.040,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "description": "Opening range breakout — 2× ATR SL, 4× ATR TP + trailing. Rides the opening move.",
        "personality": {"aggression": 70, "patience": 60, "risk": 65},
    },
    "VWAP": {
        "id": "vwap", "emoji": "📊", "color": "#00FF88", "bias": "BOTH",
        "strategy": "VWAP", "timeframe": "15m", "sl": 0.035, "tp": 0.020,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": True,
        "description": "VWAP cross with volume — ATR SL/TP + trailing on 15m.",
        "personality": {"aggression": 50, "patience": 60, "risk": 55},
    },
    "Mean Reversion": {
        "id": "meanrev", "emoji": "🔄", "color": "#FF8C00", "bias": "BOTH",
        "strategy": "Mean_Reversion", "timeframe": "15m", "sl": 0.025, "tp": 0.025,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": False,
        "description": "BB extreme fade — tight ATR stops. No trailing (mean reversion, not trend).",
        "personality": {"aggression": 35, "patience": 75, "risk": 45},
    },
    "Momentum": {
        "id": "momentum", "emoji": "🚀", "color": "#FF1493", "bias": "BOTH",
        "strategy": "Momentum", "timeframe": "15m", "sl": 0.030, "tp": 0.030,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "description": "EMA+MACD momentum — ATR SL/TP + aggressive trailing. Rides momentum surges.",
        "personality": {"aggression": 80, "patience": 50, "risk": 75},
    },
    "Order Flow": {
        "id": "orderflow", "emoji": "🌊", "color": "#1E90FF", "bias": "BOTH",
        "strategy": "Order_Flow", "timeframe": "15m", "sl": 0.025, "tp": 0.025,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": True,
        "description": "Volume delta flow — ATR SL/TP + trailing on 15m.",
        "personality": {"aggression": 55, "patience": 65, "risk": 55},
    },
    "Liquidity Hunt": {
        "id": "liqhunt", "emoji": "🎯", "color": "#ADFF2F", "bias": "BOTH",
        "strategy": "Liq_Hunt", "timeframe": "1h", "sl": 0.012, "tp": 0.024,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": True,
        "description": "Stop sweep reversal — tight ATR SL (stop was just swept), trailing captures the run.",
        "personality": {"aggression": 60, "patience": 70, "risk": 60},
    },
    "VWAP + Momentum": {
        "id": "vwap_mom", "emoji": "⚡", "color": "#FF6347", "bias": "BOTH",
        "strategy": "VWAP_Momentum", "timeframe": "15m", "sl": 0.030, "tp": 0.025,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "description": "VWAP + trend momentum — ATR SL/TP + trailing. Dual confirmation rides further.",
        "personality": {"aggression": 65, "patience": 70, "risk": 65},
    },
    "VWAP + Order Flow": {
        "id": "vwap_of", "emoji": "💧", "color": "#40E0D0", "bias": "BOTH",
        "strategy": "VWAP_OrderFlow", "timeframe": "15m", "sl": 0.030, "tp": 0.025,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "description": "VWAP cross + volume delta — ATR SL/TP + trailing.",
        "personality": {"aggression": 58, "patience": 72, "risk": 58},
    },
    "MeanRev + Order Flow": {
        "id": "mr_of", "emoji": "🔃", "color": "#DA70D6", "bias": "BOTH",
        "strategy": "MeanRev_OrderFlow", "timeframe": "15m", "sl": 0.015, "tp": 0.030,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": False,
        "description": "BB extreme + volume delta confirmation. No trailing (mean reversion).",
        "personality": {"aggression": 40, "patience": 80, "risk": 50},
    },
    "Liq + Momentum": {
        "id": "liq_mom", "emoji": "🏹", "color": "#F0E68C", "bias": "BOTH",
        "strategy": "Liq_Momentum", "timeframe": "15m", "sl": 0.020, "tp": 0.040,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "description": "Sweep + trend continuation — ATR SL/TP + trailing rides the post-sweep run.",
        "personality": {"aggression": 72, "patience": 65, "risk": 68},
    },
    "VWAP + Liq Hunt": {
        "id": "vwap_liq", "emoji": "🔱", "color": "#98FB98", "bias": "BOTH",
        "strategy": "VWAP_Liq", "timeframe": "15m", "sl": 0.015, "tp": 0.020,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": True,
        "description": "Sweep + VWAP reclaim — tightest ATR SL (rare high-quality setup).",
        "personality": {"aggression": 55, "patience": 85, "risk": 52},
    },
    "VWAP + OF + BB": {
        "id": "vwap_of_bb", "emoji": "🌐", "color": "#DEB887", "bias": "BOTH",
        "strategy": "VWAP_OF_BB", "timeframe": "15m", "sl": 0.030, "tp": 0.030,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "description": "Triple confirmation: VWAP + flow + BB — ATR SL/TP + trailing.",
        "personality": {"aggression": 45, "patience": 88, "risk": 50},
    },
    "All Combined": {
        "id": "allcombined", "emoji": "💎", "color": "#E6E6FA", "bias": "BOTH",
        "strategy": "All_Combined", "timeframe": "15m", "sl": 0.030, "tp": 0.030,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "description": "Every filter: VWAP + flow + EMA + MACD — ATR SL/TP + trailing. Maximum conviction.",
        "personality": {"aggression": 38, "patience": 97, "risk": 42},
    },
}

# ── 9 SMART AGENTS — ATR UPGRADED ─────────────────────────────────────────────

SMART_9_ATR = {
    "The Surgeon v2": {
        "id": "S9-01", "emoji": "🧠", "color": "#00d4ff",
        "strategy": "RSI_Oversold_ATR", "timeframe": "15m",
        "sl": 0.005, "tp": 0.010,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": True,
        "description": "RSI reversal — ATR dynamic SL/TP + trailing. 15m timeframe.",
        "personality": {"aggression": 30, "patience": 90, "risk": 25},
        "bias": "BOTH",
    },
    "The Regime Lord": {
        "id": "S9-02", "emoji": "👑", "color": "#ffd700",
        "strategy": "Regime_ATR", "timeframe": "1h",
        "sl": 0.008, "tp": 0.032,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "description": "Regime-adaptive — ATR dynamic SL/TP + trailing.",
        "personality": {"aggression": 50, "patience": 70, "risk": 40},
        "bias": "BOTH",
    },
    "The Squeeze": {
        "id": "S9-03", "emoji": "💥", "color": "#ff6b35",
        "strategy": "BB_Squeeze_ATR", "timeframe": "5m",
        "sl": 0.008, "tp": 0.032,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "description": "BB squeeze breakout — ATR SL/TP + trailing.",
        "personality": {"aggression": 75, "patience": 85, "risk": 55},
        "bias": "BOTH",
    },
    "The Structure": {
        "id": "S9-04", "emoji": "🏗️", "color": "#a855f7",
        "strategy": "Market_Structure_ATR", "timeframe": "1h",
        "sl": 0.012, "tp": 0.036,
        "atr_sl_mult": 2.5, "atr_tp_mult": 5.0, "trailing": True,
        "description": "Break of Structure — wide ATR SL/TP (2.5×/5×) + trailing.",
        "personality": {"aggression": 40, "patience": 95, "risk": 60},
        "bias": "BOTH",
    },
    "The EMA Rider": {
        "id": "S9-05", "emoji": "📈", "color": "#10b981",
        "strategy": "EMA_Pullback_ATR", "timeframe": "1h",
        "sl": 0.010, "tp": 0.030,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "description": "EMA21 pullback — ATR trailing stop follows the trend.",
        "personality": {"aggression": 45, "patience": 80, "risk": 50},
        "bias": "BOTH",
    },
    "The Confluence": {
        "id": "S9-06", "emoji": "🎯", "color": "#f59e0b",
        "strategy": "MTF_Confluence_ATR", "timeframe": "1h",
        "sl": 0.010, "tp": 0.030,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "description": "Multi-timeframe confluence — ATR SL/TP + trailing.",
        "personality": {"aggression": 25, "patience": 95, "risk": 30},
        "bias": "BOTH",
    },
    "The Keltner": {
        "id": "S9-07", "emoji": "⚡", "color": "#ec4899",
        "strategy": "Keltner_ATR", "timeframe": "1h",
        "sl": 0.008, "tp": 0.024,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": False,
        "description": "Keltner reversion — tight ATR SL. No trailing (counter-trend).",
        "personality": {"aggression": 35, "patience": 85, "risk": 35},
        "bias": "BOTH",
    },
    "The ATR Breakout": {
        "id": "S9-08", "emoji": "🚀", "color": "#8b5cf6",
        "strategy": "ATR_Breakout_Trail", "timeframe": "1h",
        "sl": 0.012, "tp": 0.048,
        "atr_sl_mult": 2.5, "atr_tp_mult": 5.0, "trailing": True,
        "description": "ATR volatility breakout — wide ATR SL + aggressive trailing.",
        "personality": {"aggression": 65, "patience": 90, "risk": 55},
        "bias": "BOTH",
    },
    "The Supertrend": {
        "id": "S9-09", "emoji": "🌊", "color": "#00ffcc",
        "strategy": "Supertrend_Trail", "timeframe": "1h",
        "sl": 0.030, "tp": 0.150,
        "atr_sl_mult": 3.0, "atr_tp_mult": 12.0, "trailing": True,
        "supertrend": True, "st_period": 10, "st_mult": 3.0,
        "description": "Supertrend flip — SL tracks the band. Rides trend until reversal.",
        "personality": {"aggression": 60, "patience": 98, "risk": 50},
        "bias": "BOTH",
    },
}

# ── COMBINED 26 AGENTS ────────────────────────────────────────────────────────

COMP9_AGENTS = {**ORIGINAL_17_ATR, **SMART_9_ATR}

COMP9_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "LINKUSDT", "DOTUSDT", "AVAXUSDT", "POLUSDT",
]

# ── ORIGINAL 5 SET (need STRATS lookup) ───────────────────────────────────────

ORIGINAL_5 = {"The Surgeon", "The Maniac", "The Hound", "The Oracle", "The Comet"}

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

# ── SUPERTREND ────────────────────────────────────────────────────────────────

def calc_supertrend(p, period=10, multiplier=3.0):
    n = p["n"]
    atr = p["atr"]
    hl2 = [(p["h"][i] + p["l"][i]) / 2 for i in range(n)]
    upper = [hl2[i] + multiplier * atr[i] for i in range(n)]
    lower = [hl2[i] - multiplier * atr[i] for i in range(n)]
    fu = [0.0] * n; fl = [0.0] * n; trend = [1] * n
    fu[0] = upper[0]; fl[0] = lower[0]
    for i in range(1, n):
        fu[i] = upper[i] if (upper[i] < fu[i-1] or p["c"][i-1] > fu[i-1]) else fu[i-1]
        fl[i] = lower[i] if (lower[i] > fl[i-1] or p["c"][i-1] < fl[i-1]) else fl[i-1]
        if trend[i-1] == 1:
            trend[i] = 1 if p["c"][i] >= fl[i] else -1
        else:
            trend[i] = -1 if p["c"][i] <= fu[i] else 1
    return trend, fu, fl

# ── SIGNAL FUNCTIONS — 12 NEW ORIGINAL AGENTS ─────────────────────────────────

def _calc_vwap(raw):
    n = len(raw["close"])
    result, cum_tp, cum_v, prev_day = [0.0]*n, 0.0, 0.0, -1
    for i in range(n):
        day = raw["ts"][i] // 86400000
        if day != prev_day:
            cum_tp = cum_v = 0.0
            prev_day = day
        tp = (raw["high"][i]+raw["low"][i]+raw["close"][i])/3
        cum_tp += tp * raw["vol"][i]; cum_v += raw["vol"][i]
        result[i] = cum_tp/cum_v if cum_v > 0 else tp
    return result

def _calc_vol_delta(raw, period=10):
    n = len(raw["close"])
    delta = [raw["vol"][i] if raw["close"][i] >= raw["open"][i] else -raw["vol"][i] for i in range(n)]
    result = [0.0]*n
    for i in range(n):
        s = max(0, i-period+1)
        result[i] = sum(delta[s:i+1])
    return result

def _calc_swing(raw, lookback=10):
    n = len(raw["close"])
    s_hi = [0.0]*n; s_lo = [0.0]*n
    for i in range(lookback, n):
        s_hi[i] = max(raw["high"][i-lookback:i])
        s_lo[i] = min(raw["low"][i-lookback:i])
    return s_hi, s_lo

def _vwap_long(p,i):
    if i<10 or "vwap" not in p: return False
    cross=p["c"][i-1]<p["vwap"][i-1] and p["c"][i]>p["vwap"][i]
    vol=p["v"][i]>p["vol_avg"][i]*1.5
    bp=sum(1 for j in range(max(0,i-3),i) if p["green"][j])
    return cross and vol and p["green"][i] and 35<p["rsi"][i]<65 and bp>=2

def _vwap_short(p,i):
    if i<10 or "vwap" not in p: return False
    cross=p["c"][i-1]>p["vwap"][i-1] and p["c"][i]<p["vwap"][i]
    vol=p["v"][i]>p["vol_avg"][i]*1.5
    sp=sum(1 for j in range(max(0,i-3),i) if not p["green"][j])
    return cross and vol and not p["green"][i] and 35<p["rsi"][i]<65 and sp>=2

def _meanrev_long(p,i):
    if i<20: return False
    return (p["c"][i]<p["bb_lo"][i] and p["rsi"][i]<28 and p["v"][i]>p["vol_avg"][i]*1.3
            and (p["green"][i] or p["c"][i]>p["l"][i]*1.005))

def _meanrev_short(p,i):
    if i<20: return False
    return (p["c"][i]>p["bb_hi"][i] and p["rsi"][i]>72 and p["v"][i]>p["vol_avg"][i]*1.3
            and (not p["green"][i] or p["c"][i]<p["h"][i]*0.995))

def _momentum_long(p,i):
    if i<60: return False
    al=p["e9"][i]>p["e21"][i]>p["e50"][i]; ab=p["c"][i]>p["e9"][i]
    mac=p["macd_hist"][i]>0 and p["macd_hist"][i]>p["macd_hist"][i-1]
    return al and ab and mac and 45<p["rsi"][i]<70 and p["c"][i]>p["c"][i-1]>p["c"][i-2]

def _momentum_short(p,i):
    if i<60: return False
    al=p["e9"][i]<p["e21"][i]<p["e50"][i]; ab=p["c"][i]<p["e9"][i]
    mac=p["macd_hist"][i]<0 and p["macd_hist"][i]<p["macd_hist"][i-1]
    return al and ab and mac and 30<p["rsi"][i]<55 and p["c"][i]<p["c"][i-1]<p["c"][i-2]

def _of_long(p,i):
    if i<15 or "vol_delta" not in p: return False
    return (p["vol_delta"][i]>0 and p["c"][i]>p.get("vwap",[0]*200)[i]
            and p["v"][i]>p["vol_avg"][i]*1.2 and p["rsi"][i]<65
            and p["vol_delta"][i]>p["vol_delta"][i-1] and p["green"][i])

def _of_short(p,i):
    if i<15 or "vol_delta" not in p: return False
    return (p["vol_delta"][i]<0 and p["c"][i]<p.get("vwap",[0]*200)[i]
            and p["v"][i]>p["vol_avg"][i]*1.2 and p["rsi"][i]>35
            and p["vol_delta"][i]<p["vol_delta"][i-1] and not p["green"][i])

def _liq_long(p,i):
    if i<15 or "s_lo" not in p: return False
    swept=p["l"][i]<p["s_lo"][i]*0.999; rev=p["c"][i]>p["s_lo"][i]
    wick=(p["c"][i]-p["l"][i])>(p["h"][i]-p["l"][i])*0.5
    return swept and rev and wick and p["v"][i]>p["vol_avg"][i]*1.4

def _liq_short(p,i):
    if i<15 or "s_hi" not in p: return False
    swept=p["h"][i]>p["s_hi"][i]*1.001; rev=p["c"][i]<p["s_hi"][i]
    wick=(p["h"][i]-p["c"][i])>(p["h"][i]-p["l"][i])*0.5
    return swept and rev and wick and p["v"][i]>p["vol_avg"][i]*1.4

def _vwap_mom_long(p,i):  return _vwap_long(p,i) and p["e9"][i]>p["e21"][i] and p["macd_hist"][i]>0
def _vwap_mom_short(p,i): return _vwap_short(p,i) and p["e9"][i]<p["e21"][i] and p["macd_hist"][i]<0
def _vwap_of_long(p,i):   return _vwap_long(p,i) and p.get("vol_delta",[0]*200)[i]>0
def _vwap_of_short(p,i):  return _vwap_short(p,i) and p.get("vol_delta",[0]*200)[i]<0
def _mr_of_long(p,i):     return _meanrev_long(p,i) and p.get("vol_delta",[0]*200)[i]>0
def _mr_of_short(p,i):    return _meanrev_short(p,i) and p.get("vol_delta",[0]*200)[i]<0
def _liq_mom_long(p,i):   return _liq_long(p,i) and p["e9"][i]>p["e21"][i]
def _liq_mom_short(p,i):  return _liq_short(p,i) and p["e9"][i]<p["e21"][i]
def _vwap_liq_long(p,i):  return _vwap_long(p,i) and _liq_long(p,i)
def _vwap_liq_short(p,i): return _vwap_short(p,i) and _liq_short(p,i)
def _vwap_of_bb_long(p,i):  return _vwap_long(p,i) and _of_long(p,i) and p["c"][i]>p["bb_mid"][i]
def _vwap_of_bb_short(p,i): return _vwap_short(p,i) and _of_short(p,i) and p["c"][i]<p["bb_mid"][i]
def _all_long(p,i):  return _vwap_long(p,i) and _of_long(p,i) and p["e9"][i]>p["e21"][i] and p["macd_hist"][i]>0
def _all_short(p,i): return _vwap_short(p,i) and _of_short(p,i) and p["e9"][i]<p["e21"][i] and p["macd_hist"][i]<0

# ── SIGNAL FUNCTIONS — 9 SMART AGENTS ────────────────────────────────────────

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
    highs = _swing_highs(p, start, i); lows = _swing_lows(p, start, i)
    if len(highs) < 2 or len(lows) < 2: return False
    return (highs[-1][1] > highs[-2][1] and lows[-1][1] > lows[-2][1]
            and p["c"][i] > highs[-2][1]
            and p["v"][i] > p["vol_avg"][i] * 1.15 and p["adx"][i] > 18 and p["rsi"][i] < 75)

def _structure_short(p, i):
    if i < 40: return False
    start = i - 25
    highs = _swing_highs(p, start, i); lows = _swing_lows(p, start, i)
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
    return (p["c"][i] < p["e21"][i] - 2.0 * p["atr"][i] and p["rsi"][i] < 35
            and p["rsi"][i] > p["rsi"][i-1] and p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.1)

def _keltner_short(p, i):
    if i < 30: return False
    return (p["c"][i] > p["e21"][i] + 2.0 * p["atr"][i] and p["rsi"][i] > 65
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
    if i < 15: return False
    trend, fu, fl = calc_supertrend(p, period=10, multiplier=3.0)
    return trend[i] == 1 and trend[i-1] == -1

def _supertrend_short(p, i):
    if i < 15: return False
    trend, fu, fl = calc_supertrend(p, period=10, multiplier=3.0)
    return trend[i] == -1 and trend[i-1] == 1

# ── SIGNAL MAPS ───────────────────────────────────────────────────────────────
# Original 5 use None — engine resolves via STRATS (same as comp2-6)

LONG_SIGNALS_9 = {
    # original 5 — STRATS lookup in engine
    "The Surgeon": None, "The Maniac": None, "The Hound": None,
    "The Oracle": None, "The Comet": None,
    # 12 new original
    "VWAP": _vwap_long, "Mean Reversion": _meanrev_long, "Momentum": _momentum_long,
    "Order Flow": _of_long, "Liquidity Hunt": _liq_long,
    "VWAP + Momentum": _vwap_mom_long, "VWAP + Order Flow": _vwap_of_long,
    "MeanRev + Order Flow": _mr_of_long, "Liq + Momentum": _liq_mom_long,
    "VWAP + Liq Hunt": _vwap_liq_long, "VWAP + OF + BB": _vwap_of_bb_long,
    "All Combined": _all_long,
    # 9 smart
    "The Surgeon v2": _surgeon2_long, "The Regime Lord": _regime_long,
    "The Squeeze": _squeeze_long, "The Structure": _structure_long,
    "The EMA Rider": _ema_rider_long, "The Confluence": _confluence_long,
    "The Keltner": _keltner_long, "The ATR Breakout": _atr_breakout_long,
    "The Supertrend": _supertrend_long,
}

SHORT_SIGNALS_9 = {
    # original 5 short signals (from base_engine.py)
    "The Surgeon": None, "The Maniac": None, "The Hound": None,
    "The Oracle": None, "The Comet": None,
    # 12 new original
    "VWAP": _vwap_short, "Mean Reversion": _meanrev_short, "Momentum": _momentum_short,
    "Order Flow": _of_short, "Liquidity Hunt": _liq_short,
    "VWAP + Momentum": _vwap_mom_short, "VWAP + Order Flow": _vwap_of_short,
    "MeanRev + Order Flow": _mr_of_short, "Liq + Momentum": _liq_mom_short,
    "VWAP + Liq Hunt": _vwap_liq_short, "VWAP + OF + BB": _vwap_of_bb_short,
    "All Combined": _all_short,
    # 9 smart
    "The Surgeon v2": _surgeon2_short, "The Regime Lord": _regime_short,
    "The Squeeze": _squeeze_short, "The Structure": _structure_short,
    "The EMA Rider": _ema_rider_short, "The Confluence": _confluence_short,
    "The Keltner": _keltner_short, "The ATR Breakout": _atr_breakout_short,
    "The Supertrend": _supertrend_short,
}
