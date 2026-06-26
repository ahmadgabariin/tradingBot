"""
Competition 2 — 17 Agent Definitions
5 original + 12 new strategies from strategy_lab
"""

AGENTS = {
    # ── ORIGINAL 5 ──────────────────────────────────────────────────────────────
    "The Surgeon": {
        "id": "surgeon", "emoji": "🏆", "color": "#FFD700", "bias": "NEUTRAL",
        "strategy": "MACD_BB_Combo", "timeframe": "1h", "sl": 0.008, "tp": 0.080,
        "description": "Original — MACD + Bollinger Bands combo",
    },
    "The Maniac": {
        "id": "maniac", "emoji": "🔥", "color": "#FF4500", "bias": "SHORT",
        "strategy": "Keltner_Break", "timeframe": "15m", "sl": 0.025, "tp": 0.006,
        "description": "Original — Keltner Channel breakout",
    },
    "The Hound": {
        "id": "hound", "emoji": "🐺", "color": "#FF69B4", "bias": "SHORT",
        "strategy": "Donchian_Break", "timeframe": "1h", "sl": 0.012, "tp": 0.060,
        "description": "Original — Donchian Channel breakout",
    },
    "The Oracle": {
        "id": "oracle", "emoji": "🔮", "color": "#00CED1", "bias": "SHORT",
        "strategy": "ADX_Trend", "timeframe": "1h", "sl": 0.035, "tp": 0.020,
        "description": "Original — ADX trend following",
    },
    "The Comet": {
        "id": "comet", "emoji": "☄️", "color": "#9370DB", "bias": "NEUTRAL",
        "strategy": "ORB", "timeframe": "1h", "sl": 0.020, "tp": 0.040,
        "description": "Original — Opening range breakout",
    },
    # ── NEW 12 ──────────────────────────────────────────────────────────────────
    "VWAP": {
        "id": "vwap", "emoji": "📊", "color": "#00FF88", "bias": "BOTH",
        "strategy": "VWAP", "timeframe": "15m", "sl": 0.035, "tp": 0.020,
        "description": "VWAP cross + volume + order flow confirmation",
    },
    "Mean Reversion": {
        "id": "meanrev", "emoji": "🔄", "color": "#FF8C00", "bias": "BOTH",
        "strategy": "Mean_Reversion", "timeframe": "15m", "sl": 0.025, "tp": 0.025,
        "description": "Bollinger Band extreme + RSI oversold/overbought",
    },
    "Momentum": {
        "id": "momentum", "emoji": "🚀", "color": "#FF1493", "bias": "BOTH",
        "strategy": "Momentum", "timeframe": "15m", "sl": 0.030, "tp": 0.030,
        "description": "EMA alignment + MACD acceleration — best performer",
    },
    "Order Flow": {
        "id": "orderflow", "emoji": "🌊", "color": "#1E90FF", "bias": "BOTH",
        "strategy": "Order_Flow", "timeframe": "15m", "sl": 0.025, "tp": 0.025,
        "description": "Cumulative volume delta + VWAP position",
    },
    "Liquidity Hunt": {
        "id": "liqhunt", "emoji": "🎯", "color": "#ADFF2F", "bias": "BOTH",
        "strategy": "Liq_Hunt", "timeframe": "1h", "sl": 0.012, "tp": 0.024,
        "description": "Stop-hunt detection — sweeps swing high/low then reverses",
    },
    "VWAP + Momentum": {
        "id": "vwap_mom", "emoji": "⚡", "color": "#FF6347", "bias": "BOTH",
        "strategy": "VWAP_Momentum", "timeframe": "15m", "sl": 0.030, "tp": 0.025,
        "description": "VWAP cross confirmed by EMA trend + MACD",
    },
    "VWAP + Order Flow": {
        "id": "vwap_of", "emoji": "💧", "color": "#40E0D0", "bias": "BOTH",
        "strategy": "VWAP_OrderFlow", "timeframe": "15m", "sl": 0.030, "tp": 0.025,
        "description": "VWAP cross with cumulative buying/selling pressure",
    },
    "MeanRev + Order Flow": {
        "id": "mr_of", "emoji": "🔃", "color": "#DA70D6", "bias": "BOTH",
        "strategy": "MeanRev_OrderFlow", "timeframe": "15m", "sl": 0.015, "tp": 0.030,
        "description": "Extreme price + order flow reversal signal",
    },
    "Liq + Momentum": {
        "id": "liq_mom", "emoji": "🏹", "color": "#F0E68C", "bias": "BOTH",
        "strategy": "Liq_Momentum", "timeframe": "15m", "sl": 0.020, "tp": 0.040,
        "description": "Stop hunt + trend continuation momentum",
    },
    "VWAP + Liq Hunt": {
        "id": "vwap_liq", "emoji": "🔱", "color": "#98FB98", "bias": "BOTH",
        "strategy": "VWAP_Liq", "timeframe": "15m", "sl": 0.015, "tp": 0.020,
        "description": "VWAP cross coinciding with liquidity sweep",
    },
    "VWAP + OF + BB": {
        "id": "vwap_of_bb", "emoji": "🌐", "color": "#DEB887", "bias": "BOTH",
        "strategy": "VWAP_OF_BB", "timeframe": "15m", "sl": 0.030, "tp": 0.030,
        "description": "Triple confirmation — VWAP + order flow + Bollinger position",
    },
    "All Combined": {
        "id": "allcombined", "emoji": "💎", "color": "#E6E6FA", "bias": "BOTH",
        "strategy": "All_Combined", "timeframe": "15m", "sl": 0.030, "tp": 0.030,
        "description": "VWAP + order flow + EMA trend + MACD — ultra selective",
    },
}

PAIRS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
    "ADAUSDT","LINKUSDT","DOTUSDT","AVAXUSDT","POLUSDT",
]
