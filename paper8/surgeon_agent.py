"""
Competition 8 — The Surgeon v2 (solo).
5-year backtest: 5/5 profitable years, EVERY month profitable, 38% WR, MaxDD 19%.
SL=0.5%, TP=1.0%, 15m timeframe. Both directions.
"""

SURGEON_AGENTS = {
    "The Surgeon v2": {
        "id": "S8-01", "emoji": "🧠", "color": "#00d4ff",
        "strategy": "RSI_Oversold_Strict",
        "timeframe": "15m",
        "sl": 0.005, "tp": 0.010,
        "description": "RSI reversal with volume spike + ADX. 38% WR, every month profitable. Best all-round agent.",
        "personality": {"aggression": 30, "patience": 90, "risk": 25},
        "bias": "BOTH",
    },
}

SURGEON_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "LINKUSDT", "DOTUSDT", "AVAXUSDT", "POLUSDT",
]


def _surgeon2_long(p, i):
    if i < 50: return False
    return (p["rsi"][i] < 35
            and p["rsi"][i] > p["rsi"][i - 1]
            and p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.2
            and p["adx"][i] > 15)


def _surgeon2_short(p, i):
    if i < 50: return False
    return (p["rsi"][i] > 65
            and p["rsi"][i] < p["rsi"][i - 1]
            and not p["green"][i]
            and p["v"][i] > p["vol_avg"][i] * 1.2
            and p["adx"][i] > 15)


LONG_SIGNALS = {"The Surgeon v2": _surgeon2_long}
SHORT_SIGNALS = {"The Surgeon v2": _surgeon2_short}
