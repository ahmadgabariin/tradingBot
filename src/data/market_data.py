import ccxt
import pandas as pd
from loguru import logger
from config.settings import settings


class MarketData:
    def __init__(self):
        exchange_config = {
            "apiKey": settings.binance_api_key,
            "secret": settings.binance_secret_key,
            "enableRateLimit": True,
        }
        if settings.use_testnet:
            exchange_config["urls"] = {
                "api": {"public": "https://testnet.binance.vision/api", "private": "https://testnet.binance.vision/api"}
            }

        self.exchange = ccxt.binance(exchange_config)
        logger.info(f"Market data initialized | testnet={settings.use_testnet}")

    def get_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> pd.DataFrame:
        try:
            raw = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV for {symbol}: {e}")
            return pd.DataFrame()

    def get_ticker(self, symbol: str) -> dict:
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"Failed to fetch ticker for {symbol}: {e}")
            return {}

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        try:
            return self.exchange.fetch_order_book(symbol, limit)
        except Exception as e:
            logger.error(f"Failed to fetch order book for {symbol}: {e}")
            return {}

    def get_balance(self) -> dict:
        try:
            balance = self.exchange.fetch_balance()
            return {k: v for k, v in balance["total"].items() if v > 0}
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return {}
