import pandas as pd
import ta
from loguru import logger
from src.strategies.support_resistance import find_sr_levels, score_sr
from src.data.order_book import analyze_order_book
from src.strategies.patterns import detect_patterns


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or len(df) < 50:
        return df
    try:
        df["ema_9"] = ta.trend.EMAIndicator(df["close"], window=9).ema_indicator()
        df["ema_21"] = ta.trend.EMAIndicator(df["close"], window=21).ema_indicator()
        df["ema_50"] = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
        macd = ta.trend.MACD(df["close"])
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_diff"] = macd.macd_diff()
        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_mid"] = bb.bollinger_mavg()
        df["volume_sma"] = df["volume"].rolling(20).mean()
        df["volume_ratio"] = df["volume"] / df["volume_sma"]

        # VWAP (resets each session approximation using rolling 50)
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        df["vwap"] = (typical_price * df["volume"]).rolling(50).sum() / df["volume"].rolling(50).sum()

        # ATR
        df["atr"] = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()

    except Exception as e:
        logger.error(f"Indicator calculation failed: {e}")
    return df


def generate_signal(df: pd.DataFrame, order_book: dict = None) -> dict:
    if df.empty or len(df) < 2:
        return {"signal": "hold", "confidence": 0, "reasons": [], "score": 0}

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    reasons = []
    score = 0

    # --- TREND ---
    if latest["ema_9"] > latest["ema_21"] and prev["ema_9"] <= prev["ema_21"]:
        score += 25
        reasons.append("EMA 9 crossed above EMA 21 (bullish crossover)")
    elif latest["ema_9"] < latest["ema_21"] and prev["ema_9"] >= prev["ema_21"]:
        score -= 25
        reasons.append("EMA 9 crossed below EMA 21 (bearish crossover)")
    elif latest["ema_9"] > latest["ema_21"]:
        score += 8
        reasons.append("EMA 9 above EMA 21 (uptrend)")
    else:
        score -= 8
        reasons.append("EMA 9 below EMA 21 (downtrend)")

    if latest["close"] > latest["ema_50"]:
        score += 10
        reasons.append("Price above EMA 50 (confirmed uptrend)")
    else:
        score -= 10
        reasons.append("Price below EMA 50 (confirmed downtrend)")

    # --- MACD ---
    if latest["macd_diff"] > 0 and prev["macd_diff"] <= 0:
        score += 20
        reasons.append("MACD crossed bullish")
    elif latest["macd_diff"] < 0 and prev["macd_diff"] >= 0:
        score -= 20
        reasons.append("MACD crossed bearish")
    elif latest["macd_diff"] > 0:
        score += 5
        reasons.append("MACD positive momentum")
    else:
        score -= 5
        reasons.append("MACD negative momentum")

    # --- RSI ---
    rsi = latest["rsi"]
    if rsi < 30:
        score += 20
        reasons.append(f"RSI oversold at {rsi:.1f} — strong buy zone")
    elif rsi < 40:
        score += 10
        reasons.append(f"RSI approaching oversold ({rsi:.1f})")
    elif rsi > 70:
        score -= 20
        reasons.append(f"RSI overbought at {rsi:.1f} — avoid buying")
    elif rsi > 60:
        score -= 10
        reasons.append(f"RSI elevated ({rsi:.1f}) — caution")
    else:
        score += 5
        reasons.append(f"RSI neutral at {rsi:.1f}")

    # --- BOLLINGER BANDS ---
    if latest["close"] <= latest["bb_lower"]:
        score += 15
        reasons.append("Price at lower Bollinger Band — potential bounce")
    elif latest["close"] >= latest["bb_upper"]:
        score -= 15
        reasons.append("Price at upper Bollinger Band — potential reversal")
    bb_pos = (latest["close"] - latest["bb_lower"]) / (latest["bb_upper"] - latest["bb_lower"])
    if 0.4 <= bb_pos <= 0.6:
        score += 3
        reasons.append("Price mid-Bollinger — neutral zone")

    # --- VOLUME ---
    vol_ratio = latest["volume_ratio"]
    if vol_ratio > 1.5:
        score = int(score * 1.2)
        reasons.append(f"High volume confirmation ({vol_ratio:.1f}x average)")
    elif vol_ratio < 0.5:
        score = int(score * 0.8)
        reasons.append(f"Low volume — weak move ({vol_ratio:.1f}x average)")

    # --- VWAP ---
    if "vwap" in latest and not pd.isna(latest["vwap"]):
        if latest["close"] > latest["vwap"]:
            score += 10
            reasons.append(f"Price above VWAP ${latest['vwap']:.2f} — institutional bullish")
        else:
            score -= 10
            reasons.append(f"Price below VWAP ${latest['vwap']:.2f} — institutional bearish")

    # --- CANDLESTICK PATTERNS ---
    pat_score, pat_reasons = detect_patterns(df)
    score += pat_score
    reasons.extend(pat_reasons)

    # --- SUPPORT & RESISTANCE ---
    sr = find_sr_levels(df)
    sr_score, sr_reasons = score_sr(sr)
    score += sr_score
    reasons.extend(sr_reasons)

    # --- ORDER BOOK ---
    if order_book:
        ob_score, ob_reasons = analyze_order_book(order_book)
        score += ob_score
        reasons.extend(ob_reasons)

    # --- FINAL SIGNAL ---
    confidence = min(abs(score), 100)
    if score >= 40:
        signal = "buy"
    elif score <= -40:
        signal = "sell"
    else:
        signal = "hold"

    return {
        "signal": signal,
        "confidence": confidence,
        "score": score,
        "reasons": reasons,
        "rsi": round(rsi, 2),
        "macd_diff": round(latest["macd_diff"], 6),
        "price": round(latest["close"], 4),
        "support": sr.get("support", []),
        "resistance": sr.get("resistance", []),
        "nearest_support": sr.get("nearest_support"),
        "nearest_resistance": sr.get("nearest_resistance"),
    }
