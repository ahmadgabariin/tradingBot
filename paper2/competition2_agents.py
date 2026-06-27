"""
Competition 2 — 17 Agent Definitions
5 original + 12 new strategies from strategy_lab
"""

AGENTS = {
    # ── ORIGINAL 5 ──────────────────────────────────────────────────────────────
    "The Surgeon": {
        "id": "surgeon", "emoji": "🏆", "color": "#FFD700", "bias": "NEUTRAL",
        "strategy": "MACD_BB_Combo", "timeframe": "1h", "sl": 0.008, "tp": 0.080,
        "description": "Cool, calculated, lethal. Runs neutral bias with balanced momentum — no emotional tilt, just clean reads. Low SL, massive TP, waits for the perfect setup.",
        "personality": {"aggression": 40, "momentum": 50, "mean_reversion": 45, "risk_appetite": 85, "discipline": 92},
    },
    "The Maniac": {
        "id": "maniac", "emoji": "🔥", "color": "#FF4500", "bias": "SHORT",
        "strategy": "Keltner_Break", "timeframe": "15m", "sl": 0.025, "tp": 0.006,
        "description": "High-frequency chaos engine. Fires short on every Keltner break. Tiny TP, fast exits, overwhelms with volume. Doesn't wait — attacks.",
        "personality": {"aggression": 95, "momentum": 80, "mean_reversion": 20, "risk_appetite": 70, "discipline": 30},
    },
    "The Hound": {
        "id": "hound", "emoji": "🐺", "color": "#FF69B4", "bias": "SHORT",
        "strategy": "Donchian_Break", "timeframe": "1h", "sl": 0.012, "tp": 0.060,
        "description": "Tracks price to the edge and strikes at breakouts. Tight stop, patient hunter. Waits for the channel break then locks on and doesn't let go.",
        "personality": {"aggression": 65, "momentum": 75, "mean_reversion": 30, "risk_appetite": 60, "discipline": 78},
    },
    "The Oracle": {
        "id": "oracle", "emoji": "🔮", "color": "#00CED1", "bias": "SHORT",
        "strategy": "ADX_Trend", "timeframe": "1h", "sl": 0.035, "tp": 0.020,
        "description": "Sees the trend before it fully forms. ADX-powered conviction trader — only enters when the trend is undeniable. Wide SL, small TP, high frequency wins.",
        "personality": {"aggression": 55, "momentum": 85, "mean_reversion": 15, "risk_appetite": 50, "discipline": 88},
    },
    "The Comet": {
        "id": "comet", "emoji": "☄️", "color": "#9370DB", "bias": "NEUTRAL",
        "strategy": "ORB", "timeframe": "1h", "sl": 0.020, "tp": 0.040,
        "description": "Blazes in at the open, captures the first big move of the session. Balanced risk, neutral bias — goes wherever the opening range breaks.",
        "personality": {"aggression": 70, "momentum": 65, "mean_reversion": 35, "risk_appetite": 65, "discipline": 70},
    },
    # ── NEW 12 ──────────────────────────────────────────────────────────────────
    "VWAP": {
        "id": "vwap", "emoji": "📊", "color": "#00FF88", "bias": "BOTH",
        "strategy": "VWAP", "timeframe": "15m", "sl": 0.035, "tp": 0.020,
        "description": "Trades VWAP crosses with volume confirmation. Institutional-grade entry reference — when price reclaims VWAP with strong volume, it follows through.",
        "personality": {"aggression": 50, "momentum": 60, "mean_reversion": 55, "risk_appetite": 55, "discipline": 75},
    },
    "Mean Reversion": {
        "id": "meanrev", "emoji": "🔄", "color": "#FF8C00", "bias": "BOTH",
        "strategy": "Mean_Reversion", "timeframe": "15m", "sl": 0.025, "tp": 0.025,
        "description": "Fades extremes. Buys when RSI is crushed and price touches lower Bollinger. Sells when euphoria pushes price to upper band. Contrarian by nature.",
        "personality": {"aggression": 35, "momentum": 25, "mean_reversion": 92, "risk_appetite": 45, "discipline": 80},
    },
    "Momentum": {
        "id": "momentum", "emoji": "🚀", "color": "#FF1493", "bias": "BOTH",
        "strategy": "Momentum", "timeframe": "15m", "sl": 0.030, "tp": 0.030,
        "description": "Pure trend rider. EMA stack aligned, MACD accelerating, price making new highs. Best performer in the lab at +$222k. When it moves, it moves hard.",
        "personality": {"aggression": 80, "momentum": 97, "mean_reversion": 10, "risk_appetite": 75, "discipline": 65},
    },
    "Order Flow": {
        "id": "orderflow", "emoji": "🌊", "color": "#1E90FF", "bias": "BOTH",
        "strategy": "Order_Flow", "timeframe": "15m", "sl": 0.025, "tp": 0.025,
        "description": "Reads the tape. Cumulative volume delta reveals who's actually buying vs selling. Follows the smart money flow, not the price candle.",
        "personality": {"aggression": 55, "momentum": 65, "mean_reversion": 40, "risk_appetite": 55, "discipline": 82},
    },
    "Liquidity Hunt": {
        "id": "liqhunt", "emoji": "🎯", "color": "#ADFF2F", "bias": "BOTH",
        "strategy": "Liq_Hunt", "timeframe": "1h", "sl": 0.012, "tp": 0.024,
        "description": "Hunts stop runs. When price sweeps a swing high/low then immediately reverses with volume, the big players just grabbed liquidity. Fade the sweep.",
        "personality": {"aggression": 60, "momentum": 45, "mean_reversion": 70, "risk_appetite": 60, "discipline": 77},
    },
    "VWAP + Momentum": {
        "id": "vwap_mom", "emoji": "⚡", "color": "#FF6347", "bias": "BOTH",
        "strategy": "VWAP_Momentum", "timeframe": "15m", "sl": 0.030, "tp": 0.025,
        "description": "VWAP cross AND trend aligned. Dual confirmation — institutional reference plus momentum fuel. Only fires when both agree.",
        "personality": {"aggression": 65, "momentum": 78, "mean_reversion": 30, "risk_appetite": 65, "discipline": 80},
    },
    "VWAP + Order Flow": {
        "id": "vwap_of", "emoji": "💧", "color": "#40E0D0", "bias": "BOTH",
        "strategy": "VWAP_OrderFlow", "timeframe": "15m", "sl": 0.030, "tp": 0.025,
        "description": "VWAP cross backed by real buying/selling pressure. Volume delta confirms the cross isn't a fake — actual orders flowing in the right direction.",
        "personality": {"aggression": 58, "momentum": 62, "mean_reversion": 42, "risk_appetite": 58, "discipline": 83},
    },
    "MeanRev + Order Flow": {
        "id": "mr_of", "emoji": "🔃", "color": "#DA70D6", "bias": "BOTH",
        "strategy": "MeanRev_OrderFlow", "timeframe": "15m", "sl": 0.015, "tp": 0.030,
        "description": "Fades extremes only when order flow confirms the reversal. Not just oversold — actually seeing real buyers step in. Higher conviction fades.",
        "personality": {"aggression": 40, "momentum": 35, "mean_reversion": 88, "risk_appetite": 50, "discipline": 85},
    },
    "Liq + Momentum": {
        "id": "liq_mom", "emoji": "🏹", "color": "#F0E68C", "bias": "BOTH",
        "strategy": "Liq_Momentum", "timeframe": "15m", "sl": 0.020, "tp": 0.040,
        "description": "Stop hunt followed by trend continuation. Liquidity grabbed, now momentum takes over. The classic institutional play — sweep stops, then run.",
        "personality": {"aggression": 72, "momentum": 70, "mean_reversion": 50, "risk_appetite": 68, "discipline": 72},
    },
    "VWAP + Liq Hunt": {
        "id": "vwap_liq", "emoji": "🔱", "color": "#98FB98", "bias": "BOTH",
        "strategy": "VWAP_Liq", "timeframe": "15m", "sl": 0.015, "tp": 0.020,
        "description": "Liquidity sweep coincides with VWAP reclaim. The rarest and most powerful setup — stops hunted AND institutional level reclaimed simultaneously.",
        "personality": {"aggression": 55, "momentum": 55, "mean_reversion": 60, "risk_appetite": 52, "discipline": 88},
    },
    "VWAP + OF + BB": {
        "id": "vwap_of_bb", "emoji": "🌐", "color": "#DEB887", "bias": "BOTH",
        "strategy": "VWAP_OF_BB", "timeframe": "15m", "sl": 0.030, "tp": 0.030,
        "description": "Triple confirmation system. VWAP cross + order flow + Bollinger position all aligned. Ultra-selective — misses many trades but when it fires, conviction is high.",
        "personality": {"aggression": 45, "momentum": 55, "mean_reversion": 55, "risk_appetite": 50, "discipline": 92},
    },
    "All Combined": {
        "id": "allcombined", "emoji": "💎", "color": "#E6E6FA", "bias": "BOTH",
        "strategy": "All_Combined", "timeframe": "15m", "sl": 0.030, "tp": 0.030,
        "description": "Every filter active. VWAP + order flow + EMA trend + MACD all must agree. Fires rarely but with maximum confidence. The diamond only forms under extreme pressure.",
        "personality": {"aggression": 38, "momentum": 60, "mean_reversion": 45, "risk_appetite": 42, "discipline": 97},
    },
}

PAIRS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
    "ADAUSDT","LINKUSDT","DOTUSDT","AVAXUSDT","POLUSDT",
]
