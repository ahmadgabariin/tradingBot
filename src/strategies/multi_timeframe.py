import pandas as pd
import ta
from loguru import logger


def analyze_timeframe(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 50:
        return {"trend": "neutral", "score": 0}

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    ema_9 = ta.trend.EMAIndicator(df["close"], window=9).ema_indicator().iloc[-1]
    ema_21 = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator().iloc[-1]
    ema_50 = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator().iloc[-1]
    rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi().iloc[-1]
    macd_obj = ta.trend.MACD(df["close"])
    macd_diff = macd_obj.macd_diff().iloc[-1]

    score = 0
    if ema_9 > ema_21:
        score += 1
    if ema_21 > ema_50:
        score += 1
    if latest["close"] > ema_50:
        score += 1
    if macd_diff > 0:
        score += 1
    if rsi > 50:
        score += 1

    if score >= 4:
        trend = "strong_bull"
    elif score >= 3:
        trend = "bull"
    elif score <= 1:
        trend = "strong_bear"
    elif score <= 2:
        trend = "bear"
    else:
        trend = "neutral"

    return {"trend": trend, "score": score, "rsi": round(rsi, 1), "ema_aligned": ema_9 > ema_21 > ema_50}


def get_mtf_confluence(market_data, symbol: str) -> dict:
    results = {}
    timeframes = {"15m": 200, "1h": 150, "4h": 100}

    for tf, limit in timeframes.items():
        try:
            df = market_data.get_ohlcv(symbol, tf, limit)
            results[tf] = analyze_timeframe(df)
        except Exception as e:
            logger.warning(f"MTF {tf} failed for {symbol}: {e}")
            results[tf] = {"trend": "neutral", "score": 0}

    scores = [r["score"] for r in results.values()]
    avg_score = sum(scores) / len(scores)

    bull_count = sum(1 for r in results.values() if "bull" in r["trend"])
    bear_count = sum(1 for r in results.values() if "bear" in r["trend"])

    if bull_count == 3:
        confluence = "strong_bull"
        conf_score = 30
    elif bull_count == 2:
        confluence = "bull"
        conf_score = 15
    elif bear_count == 3:
        confluence = "strong_bear"
        conf_score = -30
    elif bear_count == 2:
        confluence = "bear"
        conf_score = -15
    else:
        confluence = "mixed"
        conf_score = -10  # conflicting signals = penalize

    return {
        "timeframes": results,
        "confluence": confluence,
        "score_bonus": conf_score,
        "all_aligned": bull_count == 3 or bear_count == 3,
    }
