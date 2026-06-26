import pandas as pd
import numpy as np
from loguru import logger


def find_sr_levels(df: pd.DataFrame, lookback: int = 100, tolerance: float = 0.002) -> dict:
    if df.empty or len(df) < lookback:
        return {"support": [], "resistance": [], "nearest_support": None, "nearest_resistance": None}

    data = df.tail(lookback)
    highs = data["high"].values
    lows = data["low"].values
    current = data["close"].iloc[-1]

    swing_highs = []
    swing_lows = []

    for i in range(2, len(data) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swing_lows.append(lows[i])

    # Add round number levels near current price
    magnitude = 10 ** (len(str(int(current))) - 2)
    for multiplier in range(-5, 6):
        level = round(current / magnitude) * magnitude + multiplier * magnitude
        if level > current * 0.95 and level < current * 1.05:
            if current < level:
                swing_highs.append(level)
            else:
                swing_lows.append(level)

    # Add 24h high/low
    high_24h = data["high"].max()
    low_24h = data["low"].min()
    swing_highs.append(high_24h)
    swing_lows.append(low_24h)

    # Cluster nearby levels
    resistance = _cluster_levels(swing_highs, tolerance)
    support = _cluster_levels(swing_lows, tolerance)

    resistance = sorted([r for r in resistance if r > current])
    support = sorted([s for s in support if s < current], reverse=True)

    return {
        "support": support[:3],
        "resistance": resistance[:3],
        "nearest_support": support[0] if support else None,
        "nearest_resistance": resistance[0] if resistance else None,
        "current": current,
    }


def _cluster_levels(levels: list, tolerance: float) -> list:
    if not levels:
        return []
    levels = sorted(levels)
    clusters = []
    group = [levels[0]]

    for level in levels[1:]:
        if (level - group[-1]) / group[-1] <= tolerance:
            group.append(level)
        else:
            clusters.append(np.mean(group))
            group = [level]
    clusters.append(np.mean(group))
    return clusters


def score_sr(sr: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    current = sr.get("current")
    nearest_sup = sr.get("nearest_support")
    nearest_res = sr.get("nearest_resistance")

    if not current:
        return 0, []

    if nearest_sup:
        dist_pct = (current - nearest_sup) / current * 100
        if dist_pct <= 0.5:
            score += 20
            reasons.append(f"Price at support ${nearest_sup:.2f} ({dist_pct:.2f}% away)")
        elif dist_pct <= 1.5:
            score += 10
            reasons.append(f"Price near support ${nearest_sup:.2f} ({dist_pct:.2f}% away)")

    if nearest_res:
        dist_pct = (nearest_res - current) / current * 100
        if dist_pct <= 0.5:
            score -= 30
            reasons.append(f"Price at resistance ${nearest_res:.2f} — bad entry ({dist_pct:.2f}% away)")
        elif dist_pct <= 1.5:
            score -= 10
            reasons.append(f"Price near resistance ${nearest_res:.2f} ({dist_pct:.2f}% away)")
        elif dist_pct <= 0.3:
            score += 25
            reasons.append(f"Breaking above resistance ${nearest_res:.2f} — strong signal")

    return score, reasons
