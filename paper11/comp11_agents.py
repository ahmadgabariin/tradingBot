"""
Competition 11 — 15 agents with UPGRADED exit techniques only.
No agent is included unless it gets a real exit upgrade over comp9.

  chandelier   (6): Liquidity Hunt, Liq+Momentum, VWAP+Liq Hunt, Surgeon V2, The Squeeze, ATR Breakout
  parabolic    (2): Momentum, The Regime Lord
  supertrend   (5): The Hound, The Comet, The Structure, EMA Rider, The Supertrend
  keltner_exit (2): Mean Reversion, MeanRev+Order Flow
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np


def calc_supertrend(p, period=10, multiplier=3.0):
    highs  = np.array(p["h"][:p["n"]])
    lows   = np.array(p["l"][:p["n"]])
    closes = np.array(p["c"][:p["n"]])
    trs = np.maximum(highs[1:] - lows[1:],
          np.maximum(np.abs(highs[1:] - closes[:-1]),
                     np.abs(lows[1:]  - closes[:-1])))
    atr = np.zeros(len(closes))
    atr[1] = trs[0]
    for i in range(2, len(closes)):
        atr[i] = (atr[i-1] * (period-1) + trs[i-1]) / period
    hl2 = (highs + lows) / 2
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    fu = upper.copy(); fl = lower.copy()
    trend = np.ones(len(closes), dtype=int)
    for i in range(1, len(closes)):
        fu[i] = min(upper[i], fu[i-1]) if closes[i-1] > fu[i-1] else upper[i]
        fl[i] = max(lower[i], fl[i-1]) if closes[i-1] < fl[i-1] else lower[i]
        if trend[i-1] == 1:
            trend[i] = -1 if closes[i] < fl[i] else 1
        else:
            trend[i] = 1 if closes[i] > fu[i] else -1
    return trend, fu, fl


COMP11_AGENTS = {
    # ── CHANDELIER (6) ────────────────────────────────────────────────────────
    "Liquidity Hunt": {
        "id": "liqhunt", "emoji": "🎯", "color": "#ADFF2F", "bias": "BOTH",
        "strategy": "Liq_Hunt", "timeframe": "1h", "sl": 0.012, "tp": 0.024,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": True,
        "exit_mode": "chandelier",
        "description": "Stop sweep — Chandelier exit anchors to the post-sweep spike peak.",
        "personality": {"aggression": 60, "patience": 70, "risk": 60},
    },
    "Liq + Momentum": {
        "id": "liq_mom", "emoji": "🏹", "color": "#F0E68C", "bias": "BOTH",
        "strategy": "Liq_Momentum", "timeframe": "15m", "sl": 0.020, "tp": 0.040,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "exit_mode": "chandelier",
        "description": "Sweep + momentum — Chandelier captures the post-sweep run peak.",
        "personality": {"aggression": 72, "patience": 65, "risk": 68},
    },
    "VWAP + Liq Hunt": {
        "id": "vwap_liq", "emoji": "🔱", "color": "#98FB98", "bias": "BOTH",
        "strategy": "VWAP_Liq", "timeframe": "15m", "sl": 0.015, "tp": 0.020,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": True,
        "exit_mode": "chandelier",
        "description": "Sweep + VWAP reclaim — Chandelier, high-quality setup captures max spike.",
        "personality": {"aggression": 55, "patience": 85, "risk": 52},
    },
    "The Surgeon v2": {
        "id": "S9-01", "emoji": "🧠", "color": "#00d4ff", "bias": "BOTH",
        "strategy": "RSI_Oversold_ATR", "timeframe": "15m", "sl": 0.005, "tp": 0.010,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": True,
        "exit_mode": "chandelier",
        "description": "RSI reversal — Chandelier anchors to the spike top after reversal.",
        "personality": {"aggression": 30, "patience": 90, "risk": 25},
    },
    "The Squeeze": {
        "id": "S9-03", "emoji": "💥", "color": "#ff6b35", "bias": "BOTH",
        "strategy": "BB_Squeeze_ATR", "timeframe": "5m", "sl": 0.008, "tp": 0.032,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "exit_mode": "chandelier",
        "description": "BB squeeze breakout — Chandelier anchors to the post-squeeze spike peak.",
        "personality": {"aggression": 75, "patience": 85, "risk": 55},
    },
    "The ATR Breakout": {
        "id": "S9-08", "emoji": "⚡", "color": "#ec4899", "bias": "BOTH",
        "strategy": "ATR_Breakout", "timeframe": "1h", "sl": 0.012, "tp": 0.036,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "exit_mode": "chandelier",
        "description": "ATR volatility breakout — Chandelier captures the breakout spike top.",
        "personality": {"aggression": 70, "patience": 75, "risk": 65},
    },

    # ── PARABOLIC SAR (2) ─────────────────────────────────────────────────────
    "Momentum": {
        "id": "momentum", "emoji": "🚀", "color": "#FF1493", "bias": "BOTH",
        "strategy": "Momentum", "timeframe": "15m", "sl": 0.030, "tp": 0.030,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "exit_mode": "parabolic",
        "sar_af_start": 0.02, "sar_af_step": 0.02, "sar_af_max": 0.2,
        "description": "Momentum — Parabolic SAR accelerates on long runs, exits fast on flip.",
        "personality": {"aggression": 80, "patience": 50, "risk": 75},
    },
    "The Regime Lord": {
        "id": "S9-02", "emoji": "👑", "color": "#ffd700", "bias": "BOTH",
        "strategy": "Regime_ATR", "timeframe": "1h", "sl": 0.008, "tp": 0.032,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "exit_mode": "parabolic",
        "sar_af_start": 0.02, "sar_af_step": 0.02, "sar_af_max": 0.2,
        "description": "Regime adaptive — Parabolic SAR accelerates through regime-following trends.",
        "personality": {"aggression": 50, "patience": 70, "risk": 40},
    },

    # ── SUPERTREND (5) ────────────────────────────────────────────────────────
    "The Hound": {
        "id": "hound", "emoji": "🐺", "color": "#FF69B4", "bias": "SHORT",
        "strategy": "Donchian_Break", "timeframe": "1h", "sl": 0.012, "tp": 0.060,
        "atr_sl_mult": 2.0, "atr_tp_mult": 6.0, "trailing": True,
        "exit_mode": "supertrend",
        "st_period": 10, "st_mult": 3.0,
        "description": "Donchian breakout — Supertrend band rides the full trend leg.",
        "personality": {"aggression": 65, "patience": 70, "risk": 60},
    },
    "The Comet": {
        "id": "comet", "emoji": "☄️", "color": "#9370DB", "bias": "NEUTRAL",
        "strategy": "ORB", "timeframe": "1h", "sl": 0.020, "tp": 0.040,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "exit_mode": "supertrend",
        "st_period": 10, "st_mult": 3.0,
        "description": "Opening range breakout — Supertrend rides opening momentum trend.",
        "personality": {"aggression": 70, "patience": 60, "risk": 65},
    },
    "The Structure": {
        "id": "S9-04", "emoji": "🏗️", "color": "#a855f7", "bias": "BOTH",
        "strategy": "Market_Structure_ATR", "timeframe": "1h", "sl": 0.012, "tp": 0.036,
        "atr_sl_mult": 2.5, "atr_tp_mult": 5.0, "trailing": True,
        "exit_mode": "supertrend",
        "st_period": 10, "st_mult": 3.0,
        "description": "Break of Structure — Supertrend band follows the whole new trend leg.",
        "personality": {"aggression": 40, "patience": 95, "risk": 60},
    },
    "The EMA Rider": {
        "id": "S9-05", "emoji": "📈", "color": "#10b981", "bias": "BOTH",
        "strategy": "EMA_Pullback_ATR", "timeframe": "1h", "sl": 0.010, "tp": 0.030,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "exit_mode": "supertrend",
        "st_period": 10, "st_mult": 3.0,
        "description": "EMA pullback — Supertrend follows trend until band breaks.",
        "personality": {"aggression": 45, "patience": 80, "risk": 50},
    },
    "The Supertrend": {
        "id": "S9-09", "emoji": "🌊", "color": "#14b8a6", "bias": "BOTH",
        "strategy": "Supertrend_ATR", "timeframe": "1h", "sl": 0.010, "tp": 0.040,
        "atr_sl_mult": 2.0, "atr_tp_mult": 4.0, "trailing": True,
        "supertrend": True, "st_period": 10, "st_mult": 3.0,
        "exit_mode": "supertrend",
        "description": "Supertrend signal + Supertrend band as SL — entry and exit are the same indicator.",
        "personality": {"aggression": 60, "patience": 80, "risk": 55},
    },

    # ── KELTNER EXIT (2) ──────────────────────────────────────────────────────
    "Mean Reversion": {
        "id": "meanrev", "emoji": "🔄", "color": "#FF8C00", "bias": "BOTH",
        "strategy": "Mean_Reversion", "timeframe": "15m", "sl": 0.025, "tp": 0.025,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": False,
        "exit_mode": "keltner_exit",
        "keltner_period": 20, "keltner_mult": 1.5,
        "description": "BB fade — Keltner exit: EMA band, softer and wider, counter-trend safe.",
        "personality": {"aggression": 35, "patience": 75, "risk": 45},
    },
    "MeanRev + Order Flow": {
        "id": "mr_of", "emoji": "🔃", "color": "#DA70D6", "bias": "BOTH",
        "strategy": "MeanRev_OrderFlow", "timeframe": "15m", "sl": 0.015, "tp": 0.030,
        "atr_sl_mult": 1.5, "atr_tp_mult": 3.0, "trailing": False,
        "exit_mode": "keltner_exit",
        "keltner_period": 20, "keltner_mult": 1.5,
        "description": "BB + volume flow — Keltner exit, counter-trend safe.",
        "personality": {"aggression": 40, "patience": 80, "risk": 50},
    },
}

# ── Signal functions ──────────────────────────────────────────────────────────

def _ema(arr, n):
    out = np.zeros(len(arr))
    out[n-1] = np.mean(arr[:n])
    k = 2/(n+1)
    for i in range(n, len(arr)):
        out[i] = arr[i]*k + out[i-1]*(1-k)
    return out

def _rsi(closes, n=14):
    d = np.diff(closes)
    g = np.where(d > 0, d, 0.0); l = np.where(d < 0, -d, 0.0)
    ag = np.convolve(g, np.ones(n)/n, mode='valid')
    al = np.convolve(l, np.ones(n)/n, mode='valid')
    rs = np.where(al == 0, 100.0, ag / (al + 1e-9))
    return np.concatenate([np.full(n, np.nan), 100 - 100/(1+rs)])

def _atr_arr(p):
    h=np.array(p["h"][:p["n"]]); l=np.array(p["l"][:p["n"]]); c=np.array(p["c"][:p["n"]])
    trs=np.maximum(h[1:]-l[1:],np.maximum(np.abs(h[1:]-c[:-1]),np.abs(l[1:]-c[:-1])))
    atr=np.zeros(len(c)); atr[1]=trs[0]
    for i in range(2,len(c)): atr[i]=(atr[i-1]*13+trs[i-1])/14
    return atr

def _bb(closes, n=20, k=2.0):
    mid=np.array([np.mean(closes[i-n:i]) if i>=n else np.nan for i in range(len(closes))])
    std=np.array([np.std(closes[i-n:i])  if i>=n else np.nan for i in range(len(closes))])
    return mid+k*std, mid, mid-k*std

def _macd(closes, fast=12, slow=26, sig=9):
    e1=_ema(closes,fast); e2=_ema(closes,slow); m=e1-e2; s=_ema(m,sig); return m,s

# Liquidity Hunt (from comp9 signals)
def _long_liq_hunt(p, idx):
    c=np.array(p["c"][:p["n"]]); h=np.array(p["h"][:p["n"]]); l=np.array(p["l"][:p["n"]])
    if idx<5: return False
    recent_low=np.min(l[idx-5:idx]); swept=l[idx]<recent_low
    return swept and c[idx]>c[idx-1] and c[idx]>recent_low

def _short_liq_hunt(p, idx):
    c=np.array(p["c"][:p["n"]]); h=np.array(p["h"][:p["n"]])
    if idx<5: return False
    recent_high=np.max(h[idx-5:idx]); swept=h[idx]>recent_high
    return swept and c[idx]<c[idx-1] and c[idx]<recent_high

def _long_liq_mom(p, idx):
    c=np.array(p["c"][:p["n"]]); l=np.array(p["l"][:p["n"]])
    e21=_ema(c,21)
    if idx<5: return False
    swept=l[idx]<np.min(l[idx-5:idx])
    return swept and c[idx]>c[idx-1] and c[idx]>e21[idx]

def _short_liq_mom(p, idx):
    c=np.array(p["c"][:p["n"]]); h=np.array(p["h"][:p["n"]])
    e21=_ema(c,21)
    if idx<5: return False
    swept=h[idx]>np.max(h[idx-5:idx])
    return swept and c[idx]<c[idx-1] and c[idx]<e21[idx]

def _long_vwap_liq(p, idx):
    c=np.array(p["c"][:p["n"]]); l=np.array(p["l"][:p["n"]])
    v=np.array(p.get("v",np.ones(p["n"]))[:p["n"]])
    vwap=np.cumsum(c*v)/np.cumsum(v)
    if idx<5: return False
    swept=l[idx]<np.min(l[idx-5:idx])
    return swept and c[idx]>c[idx-1] and c[idx]>vwap[idx]

def _short_vwap_liq(p, idx):
    c=np.array(p["c"][:p["n"]]); h=np.array(p["h"][:p["n"]])
    v=np.array(p.get("v",np.ones(p["n"]))[:p["n"]])
    vwap=np.cumsum(c*v)/np.cumsum(v)
    if idx<5: return False
    swept=h[idx]>np.max(h[idx-5:idx])
    return swept and c[idx]<c[idx-1] and c[idx]<vwap[idx]

def _long_rsi_oversold(p, idx):
    c=np.array(p["c"][:p["n"]]); rsi=_rsi(c)
    if np.isnan(rsi[idx-1]) or np.isnan(rsi[idx]): return False
    return rsi[idx-1]<30 and rsi[idx]>30

def _short_rsi_oversold(p, idx):
    c=np.array(p["c"][:p["n"]]); rsi=_rsi(c)
    if np.isnan(rsi[idx-1]) or np.isnan(rsi[idx]): return False
    return rsi[idx-1]>70 and rsi[idx]<70

def _long_squeeze(p, idx):
    c=np.array(p["c"][:p["n"]]); ub,mb,lb=_bb(c); atr=_atr_arr(p)
    kc_u=mb+1.5*atr; kc_l=mb-1.5*atr
    if np.isnan(ub[idx-1]): return False
    was_sq=ub[idx-1]<kc_u[idx-1] and lb[idx-1]>kc_l[idx-1]
    return was_sq and ub[idx]>kc_u[idx] and c[idx]>mb[idx]

def _short_squeeze(p, idx):
    c=np.array(p["c"][:p["n"]]); ub,mb,lb=_bb(c); atr=_atr_arr(p)
    kc_u=mb+1.5*atr; kc_l=mb-1.5*atr
    if np.isnan(lb[idx-1]): return False
    was_sq=ub[idx-1]<kc_u[idx-1] and lb[idx-1]>kc_l[idx-1]
    return was_sq and lb[idx]<kc_l[idx] and c[idx]<mb[idx]

def _long_atr_breakout(p, idx):
    c=np.array(p["c"][:p["n"]]); atr=_atr_arr(p)
    if idx<20: return False
    rng=np.max(c[idx-20:idx])-np.min(c[idx-20:idx])
    return c[idx]>c[idx-1] and (c[idx]-c[idx-1])>1.5*atr[idx] and rng>3*atr[idx]

def _short_atr_breakout(p, idx):
    c=np.array(p["c"][:p["n"]]); atr=_atr_arr(p)
    if idx<20: return False
    rng=np.max(c[idx-20:idx])-np.min(c[idx-20:idx])
    return c[idx]<c[idx-1] and (c[idx-1]-c[idx])>1.5*atr[idx] and rng>3*atr[idx]

def _long_momentum(p, idx):
    c=np.array(p["c"][:p["n"]]); e20=_ema(c,20); macd,sig=_macd(c)
    return c[idx]>e20[idx] and macd[idx]>sig[idx] and macd[idx]>macd[idx-1]

def _short_momentum(p, idx):
    c=np.array(p["c"][:p["n"]]); e20=_ema(c,20); macd,sig=_macd(c)
    return c[idx]<e20[idx] and macd[idx]<sig[idx] and macd[idx]<macd[idx-1]

def _long_regime(p, idx):
    c=np.array(p["c"][:p["n"]]); e50=_ema(c,50); e200=_ema(c,200)
    if e200[idx]<=0: return False
    return e50[idx]>e200[idx] and c[idx]>e50[idx] and c[idx]>c[idx-1]

def _short_regime(p, idx):
    c=np.array(p["c"][:p["n"]]); e50=_ema(c,50); e200=_ema(c,200)
    if e200[idx]<=0: return False
    return e50[idx]<e200[idx] and c[idx]<e50[idx] and c[idx]<c[idx-1]

def _long_supertrend(p, idx):
    trend,fu,fl=calc_supertrend(p)
    if idx<1: return False
    return trend[idx-1]==-1 and trend[idx]==1

def _short_supertrend(p, idx):
    trend,fu,fl=calc_supertrend(p)
    if idx<1: return False
    return trend[idx-1]==1 and trend[idx]==-1

def _long_meanrev(p, idx):
    c=np.array(p["c"][:p["n"]]); ub,mb,lb=_bb(c)
    if np.isnan(lb[idx]): return False
    return c[idx-1]<lb[idx-1] and c[idx]>lb[idx]

def _short_meanrev(p, idx):
    c=np.array(p["c"][:p["n"]]); ub,mb,lb=_bb(c)
    if np.isnan(ub[idx]): return False
    return c[idx-1]>ub[idx-1] and c[idx]<ub[idx]

def _long_mr_of(p, idx):
    c=np.array(p["c"][:p["n"]]); v=np.array(p.get("v",np.ones(p["n"]))[:p["n"]])
    ub,mb,lb=_bb(c)
    if np.isnan(lb[idx]): return False
    vol_surge=v[idx]>np.mean(v[max(0,idx-10):idx])*1.2
    return c[idx-1]<lb[idx-1] and c[idx]>lb[idx] and vol_surge

def _short_mr_of(p, idx):
    c=np.array(p["c"][:p["n"]]); v=np.array(p.get("v",np.ones(p["n"]))[:p["n"]])
    ub,mb,lb=_bb(c)
    if np.isnan(ub[idx]): return False
    vol_surge=v[idx]>np.mean(v[max(0,idx-10):idx])*1.2
    return c[idx-1]>ub[idx-1] and c[idx]<ub[idx] and vol_surge

# Supertrend agents (Hound/Comet use STRATS from fast_backtest — handled in engine like comp9)
# Structure / EMA Rider
def _long_structure(p, idx):
    c=np.array(p["c"][:p["n"]]); h=np.array(p["h"][:p["n"]])
    if idx<20: return False
    return c[idx]>np.max(h[idx-20:idx-1]) and c[idx]>c[idx-1]>c[idx-2]

def _short_structure(p, idx):
    c=np.array(p["c"][:p["n"]]); l=np.array(p["l"][:p["n"]])
    if idx<20: return False
    return c[idx]<np.min(l[idx-20:idx-1]) and c[idx]<c[idx-1]<c[idx-2]

def _long_ema_pullback(p, idx):
    c=np.array(p["c"][:p["n"]]); e21=_ema(c,21); e50=_ema(c,50)
    if idx<2: return False
    was_below=c[idx-2]<e21[idx-2] or c[idx-1]<e21[idx-1]
    return e21[idx]>e50[idx] and c[idx]>e21[idx] and was_below

def _short_ema_pullback(p, idx):
    c=np.array(p["c"][:p["n"]]); e21=_ema(c,21); e50=_ema(c,50)
    if idx<2: return False
    was_above=c[idx-2]>e21[idx-2] or c[idx-1]>e21[idx-1]
    return e21[idx]<e50[idx] and c[idx]<e21[idx] and was_above

# ORIGINAL_5 agents (Hound, Comet) use STRATS + base_engine short fns, same as comp9
ORIGINAL_5_IN_11 = {"The Hound", "The Comet"}

LONG_SIGNALS_11 = {
    "Liquidity Hunt":      _long_liq_hunt,
    "Liq + Momentum":      _long_liq_mom,
    "VWAP + Liq Hunt":     _long_vwap_liq,
    "The Surgeon v2":      _long_rsi_oversold,
    "The Squeeze":         _long_squeeze,
    "The ATR Breakout":    _long_atr_breakout,
    "Momentum":            _long_momentum,
    "The Regime Lord":     _long_regime,
    "The Hound":           None,   # uses STRATS in engine
    "The Comet":           None,   # uses STRATS in engine
    "The Structure":       _long_structure,
    "The EMA Rider":       _long_ema_pullback,
    "The Supertrend":      _long_supertrend,
    "Mean Reversion":      _long_meanrev,
    "MeanRev + Order Flow":_long_mr_of,
}

SHORT_SIGNALS_11 = {
    "Liquidity Hunt":      _short_liq_hunt,
    "Liq + Momentum":      _short_liq_mom,
    "VWAP + Liq Hunt":     _short_vwap_liq,
    "The Surgeon v2":      _short_rsi_oversold,
    "The Squeeze":         _short_squeeze,
    "The ATR Breakout":    _short_atr_breakout,
    "Momentum":            _short_momentum,
    "The Regime Lord":     _short_regime,
    "The Hound":           None,   # uses _short_donchian in engine
    "The Comet":           None,   # uses _short_orb in engine
    "The Structure":       _short_structure,
    "The EMA Rider":       _short_ema_pullback,
    "The Supertrend":      _short_supertrend,
    "Mean Reversion":      _short_meanrev,
    "MeanRev + Order Flow":_short_mr_of,
}

from paper9.comp9_agents import COMP9_PAIRS as COMP11_PAIRS
