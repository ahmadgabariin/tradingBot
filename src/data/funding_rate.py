import requests
from loguru import logger
import time


class FundingRate:
    def __init__(self):
        self._cache = {}
        self.CACHE_TTL = 300

    def get_funding_rate(self, symbol: str) -> dict:
        now = time.time()
        cache_key = symbol.replace("/", "")

        if cache_key in self._cache and now - self._cache[cache_key]["ts"] < self.CACHE_TTL:
            return self._cache[cache_key]["data"]

        try:
            clean = symbol.replace("/", "")
            url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={clean}"
            resp = requests.get(url, timeout=8)
            data = resp.json()

            rate = float(data.get("lastFundingRate", 0)) * 100  # convert to %
            mark_price = float(data.get("markPrice", 0))
            index_price = float(data.get("indexPrice", 0))

            if rate > 0.1:
                sentiment = "overheated_longs"
                signal_impact = -20
                note = f"High funding rate {rate:.4f}% — longs paying too much, reversal risk"
            elif rate > 0.05:
                sentiment = "bullish_bias"
                signal_impact = -5
                note = f"Elevated funding {rate:.4f}% — slight long bias"
            elif rate < -0.05:
                sentiment = "overheated_shorts"
                signal_impact = +15
                note = f"Negative funding {rate:.4f}% — shorts squeezed, potential pump"
            else:
                sentiment = "neutral"
                signal_impact = 0
                note = f"Neutral funding rate {rate:.4f}%"

            result = {
                "rate": round(rate, 4),
                "sentiment": sentiment,
                "signal_impact": signal_impact,
                "note": note,
                "mark_price": mark_price,
            }
            self._cache[cache_key] = {"data": result, "ts": now}
            return result

        except Exception as e:
            logger.warning(f"Funding rate fetch failed for {symbol}: {e}")
            return {"rate": 0, "sentiment": "neutral", "signal_impact": 0, "note": "Funding data unavailable"}
