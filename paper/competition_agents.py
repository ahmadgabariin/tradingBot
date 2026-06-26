"""
Agent personality definitions for the openCLAUDE-style competition
"""

AGENTS = {
    "The Surgeon": {
        "id": "surgeon",
        "emoji": "🏆",
        "color": "#FFD700",
        "bias": "NEUTRAL",
        "description": "Cool, calculated, lethal. Runs neutral bias with balanced momentum — no emotional tilt, just clean reads. Low SL, massive TP, waits for the perfect setup.",
        "strategy": "MACD_BB_Combo",
        "timeframe": "1h",
        "sl": 0.008,
        "tp": 0.080,
        "personality": {"aggression": 40, "momentum": 50, "mean_reversion": 45, "risk_appetite": 85, "discipline": 92},
    },
    "The Maniac": {
        "id": "maniac",
        "emoji": "🔥",
        "color": "#FF4500",
        "bias": "SHORT",
        "description": "Maximum aggression cranked to 1.6x. Swings big on every tick. High risk, high chaos, high reward — or spectacular blowup.",
        "strategy": "Keltner_Break",
        "timeframe": "15m",
        "sl": 0.025,
        "tp": 0.006,
        "personality": {"aggression": 100, "momentum": 58, "mean_reversion": 42, "risk_appetite": 100, "discipline": 10},
    },
    "The Hound": {
        "id": "hound",
        "emoji": "🐺",
        "color": "#FF69B4",
        "bias": "SHORT",
        "description": "Relentless. Chases every trend and sniffs out every breakout. 68% momentum — solid and dependable.",
        "strategy": "Donchian_Break",
        "timeframe": "1h",
        "sl": 0.012,
        "tp": 0.060,
        "personality": {"aggression": 62, "momentum": 68, "mean_reversion": 32, "risk_appetite": 81, "discipline": 44},
    },
    "The Oracle": {
        "id": "oracle",
        "emoji": "🔮",
        "color": "#00CED1",
        "bias": "SHORT",
        "description": "Most momentum-driven at 77%. Bets everything on reading the trend. Lands moonshots but dies by conviction.",
        "strategy": "ADX_Trend",
        "timeframe": "1h",
        "sl": 0.035,
        "tp": 0.020,
        "personality": {"aggression": 33, "momentum": 77, "mean_reversion": 23, "risk_appetite": 48, "discipline": 70},
    },
    "The Comet": {
        "id": "comet",
        "emoji": "☄️",
        "color": "#9370DB",
        "bias": "NEUTRAL",
        "description": "Burns brightest, then fades. Hits the session's highest peak before slowly giving it back. 50/50 momentum-reversion.",
        "strategy": "ORB",
        "timeframe": "1h",
        "sl": 0.020,
        "tp": 0.040,
        "personality": {"aggression": 41, "momentum": 49, "mean_reversion": 51, "risk_appetite": 84, "discipline": 63},
    },
}

PAIRS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
    "ADAUSDT","LINKUSDT","DOTUSDT","AVAXUSDT","POLUSDT",
]
