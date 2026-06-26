import pandas as pd


def detect_patterns(df: pd.DataFrame) -> tuple[int, list[str]]:
    if df.empty or len(df) < 5:
        return 0, []

    score = 0
    reasons = []

    c = df.iloc[-1]
    p = df.iloc[-2]
    p2 = df.iloc[-3]

    body = abs(c["close"] - c["open"])
    candle_range = c["high"] - c["low"]
    upper_wick = c["high"] - max(c["close"], c["open"])
    lower_wick = min(c["close"], c["open"]) - c["low"]

    if candle_range == 0:
        return 0, []

    body_pct = body / candle_range
    is_bull_candle = c["close"] > c["open"]
    is_bear_candle = c["close"] < c["open"]

    # Hammer — bullish reversal at bottom
    if (lower_wick > body * 2 and upper_wick < body * 0.5
            and body_pct < 0.4 and p["close"] < p["open"]):
        score += 20
        reasons.append("Hammer candle — bullish reversal signal")

    # Shooting star — bearish reversal at top
    if (upper_wick > body * 2 and lower_wick < body * 0.5
            and body_pct < 0.4 and p["close"] > p["open"]):
        score -= 20
        reasons.append("Shooting star — bearish reversal signal")

    # Bullish engulfing
    if (is_bull_candle and p["close"] < p["open"]
            and c["open"] < p["close"] and c["close"] > p["open"]
            and body > abs(p["close"] - p["open"])):
        score += 25
        reasons.append("Bullish engulfing pattern — strong reversal")

    # Bearish engulfing
    if (is_bear_candle and p["close"] > p["open"]
            and c["open"] > p["close"] and c["close"] < p["open"]
            and body > abs(p["close"] - p["open"])):
        score -= 25
        reasons.append("Bearish engulfing pattern — strong reversal")

    # Doji — indecision
    if body_pct < 0.1:
        score -= 5
        reasons.append("Doji candle — market indecision, caution")

    # Morning star (3-candle bullish reversal)
    if (p2["close"] < p2["open"]                          # bearish candle
            and abs(p["close"] - p["open"]) < abs(p2["close"] - p2["open"]) * 0.3  # small middle
            and is_bull_candle                              # bullish close
            and c["close"] > (p2["open"] + p2["close"]) / 2):
        score += 30
        reasons.append("Morning star pattern — strong 3-candle reversal")

    # Evening star (3-candle bearish reversal)
    if (p2["close"] > p2["open"]
            and abs(p["close"] - p["open"]) < abs(p2["close"] - p2["open"]) * 0.3
            and is_bear_candle
            and c["close"] < (p2["open"] + p2["close"]) / 2):
        score -= 30
        reasons.append("Evening star pattern — strong 3-candle reversal")

    # Strong bullish momentum candle
    if is_bull_candle and body_pct > 0.7 and body > abs(p["close"] - p["open"]) * 1.5:
        score += 15
        reasons.append("Strong bullish momentum candle")

    # Strong bearish momentum candle
    if is_bear_candle and body_pct > 0.7 and body > abs(p["close"] - p["open"]) * 1.5:
        score -= 15
        reasons.append("Strong bearish momentum candle")

    return score, reasons
