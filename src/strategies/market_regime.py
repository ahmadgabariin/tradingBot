import pandas as pd
import numpy as np
import ta
from loguru import logger


def detect_regime(df: pd.DataFrame) -> dict:
    """
    Detects whether market is trending or ranging.
    Trending = follow the trend, use EMA signals.
    Ranging = mean reversion, use RSI/BB extremes only.
    """
    if df.empty or len(df) < 50:
        return {"regime": "unknown", "atr": 0, "adx": 0}

    # ADX — measures trend strength (>25 = trending, <20 = ranging)
    try:
        adx_indicator = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
        adx = adx_indicator.adx().iloc[-1]
        di_plus = adx_indicator.adx_pos().iloc[-1]
        di_minus = adx_indicator.adx_neg().iloc[-1]
    except Exception:
        adx = 20
        di_plus = di_minus = 0

    # ATR — measures volatility
    try:
        atr = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range().iloc[-1]
        atr_pct = atr / df["close"].iloc[-1] * 100
    except Exception:
        atr = 0
        atr_pct = 0

    # Price range efficiency — how directional is the move?
    recent = df.tail(20)
    total_move = abs(recent["close"].iloc[-1] - recent["close"].iloc[0])
    total_path = recent["close"].diff().abs().sum()
    efficiency = total_move / total_path if total_path > 0 else 0

    if adx > 25 and efficiency > 0.3:
        regime = "trending"
        direction = "up" if di_plus > di_minus else "down"
    elif adx < 20 or efficiency < 0.15:
        regime = "ranging"
        direction = "neutral"
    else:
        regime = "transitioning"
        direction = "up" if di_plus > di_minus else "down"

    return {
        "regime": regime,
        "direction": direction,
        "adx": round(adx, 1),
        "atr": round(atr, 4),
        "atr_pct": round(atr_pct, 3),
        "efficiency": round(efficiency, 3),
        "di_plus": round(di_plus, 1),
        "di_minus": round(di_minus, 1),
    }


def regime_signal_filter(signal: dict, regime: dict) -> tuple[dict, list[str]]:
    notes = []
    adj_signal = signal.copy()

    if regime["regime"] == "ranging":
        # In ranging market — only take RSI extremes, not trend signals
        if signal.get("rsi", 50) > 40 and signal["signal"] == "buy":
            adj_signal["signal"] = "hold"
            adj_signal["confidence"] = max(0, signal["confidence"] - 30)
            notes.append("Ranging market — EMA signals suppressed, need RSI < 40 to buy")
        elif signal.get("rsi", 50) < 35:
            notes.append("Ranging market — RSI oversold bounce play valid")
        else:
            notes.append(f"Ranging market (ADX={regime['adx']}) — reduced confidence")
            adj_signal["confidence"] = max(0, signal["confidence"] - 20)

    elif regime["regime"] == "trending":
        if regime["direction"] == "up" and signal["signal"] == "buy":
            adj_signal["confidence"] = min(100, signal["confidence"] + 10)
            notes.append(f"Trending up (ADX={regime['adx']}) — buy signal confirmed by trend")
        elif regime["direction"] == "down" and signal["signal"] == "buy":
            adj_signal["signal"] = "hold"
            notes.append(f"Trending DOWN (ADX={regime['adx']}) — buying against trend, blocked")

    return adj_signal, notes
