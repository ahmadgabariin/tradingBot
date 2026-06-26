import ta
import pandas as pd
from loguru import logger
from config.settings import settings


def calculate_atr_position(df: pd.DataFrame, budget: float) -> dict:
    """
    Uses ATR to set dynamic stop loss — adapts to actual market volatility.
    Wide market = wider stop, tight market = tighter stop.
    """
    price = df["close"].iloc[-1]

    try:
        atr = ta.volatility.AverageTrueRange(
            df["high"], df["low"], df["close"], window=14
        ).average_true_range().iloc[-1]
        atr_pct = atr / price * 100
    except Exception:
        atr = price * 0.02
        atr_pct = 2.0

    # Stop = 1.5× ATR below entry (not too tight, not too loose)
    stop_distance = atr * 1.5
    stop_loss = price - stop_distance
    sl_pct = stop_distance / price * 100

    # Take profit = 2.5× ATR (better than fixed 4%)
    tp1 = price + atr * 1.5   # 50% close here
    tp2 = price + atr * 2.5   # 30% close here
    tp3 = price + atr * 4.0   # 20% let ride

    # Position size based on fixed dollar risk
    max_risk_usd = budget * (settings.max_trade_percent / 100) * 0.02  # 2% of trade
    trade_amount = min(budget * settings.max_trade_percent / 100, max_risk_usd / (sl_pct / 100))
    trade_amount = min(trade_amount, budget * settings.max_trade_percent / 100)

    quantity = trade_amount / price

    return {
        "entry_price": round(price, 4),
        "amount_usd": round(trade_amount, 2),
        "quantity": round(quantity, 6),
        "stop_loss": round(stop_loss, 4),
        "take_profit": round(tp2, 4),   # main TP
        "tp1": round(tp1, 4),
        "tp2": round(tp2, 4),
        "tp3": round(tp3, 4),
        "atr": round(atr, 4),
        "atr_pct": round(atr_pct, 3),
        "sl_pct": round(sl_pct, 3),
        "risk_usd": round(trade_amount * sl_pct / 100, 2),
        "reward_usd": round(trade_amount * (atr * 2.5 / price * 100) / 100, 2),
    }


class TrailingStop:
    def __init__(self):
        self.peaks = {}  # symbol -> highest price seen

    def update(self, symbol: str, current_price: float, atr: float) -> dict:
        if symbol not in self.peaks:
            self.peaks[symbol] = current_price

        if current_price > self.peaks[symbol]:
            self.peaks[symbol] = current_price

        peak = self.peaks[symbol]
        trail_distance = atr * 1.5
        trailing_sl = peak - trail_distance
        gain_pct = (current_price - (peak - trail_distance)) / peak * 100

        return {
            "peak": round(peak, 4),
            "trailing_sl": round(trailing_sl, 4),
            "should_exit": current_price <= trailing_sl,
            "gain_locked_pct": round((peak - trailing_sl) / peak * 100, 2),
        }

    def reset(self, symbol: str):
        self.peaks.pop(symbol, None)


def should_skip_time() -> tuple[bool, str]:
    """
    Avoid low-liquidity hours (UTC). Best hours: 8-12 and 14-22 UTC.
    """
    from datetime import datetime, timezone
    hour = datetime.now(timezone.utc).hour

    # Avoid 00:00–07:00 UTC (low volume, erratic moves)
    if 0 <= hour < 7:
        return True, f"Low liquidity hours (UTC {hour}:xx) — skipping"

    return False, ""


def adaptive_threshold(consecutive_losses: int, base_threshold: int = 50) -> int:
    """
    After consecutive losses, raise the confidence bar to protect capital.
    """
    if consecutive_losses >= 4:
        return min(base_threshold + 25, 80)
    elif consecutive_losses >= 2:
        return min(base_threshold + 10, 70)
    return base_threshold
