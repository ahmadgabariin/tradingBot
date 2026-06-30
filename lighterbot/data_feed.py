"""
Standalone Binance market data feed for LighterBot.
Pulls candles from Binance (signal source) — completely independent from
paper_shared/base_engine.py so this bot never touches the existing project.
"""
import time
import numpy as np
import requests

BINANCE_BASE = "https://api.binance.com"
CANDLE_LIMIT = 300

# Lighter symbol -> Binance symbol
SYMBOL_MAP = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
}

_cache = {}          # (symbol, timeframe) -> {"data": {...}, "ts": float}
_CACHE_TTL = 8        # seconds, avoid hammering Binance every tick


def _fetch_klines(binance_symbol: str, interval: str, limit: int = CANDLE_LIMIT):
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {"symbol": binance_symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def get_candles(symbol: str, timeframe: str):
    """Returns dict with numpy arrays: closes, highs, lows, volumes, atr, n.
    Cached briefly to avoid excessive Binance calls."""
    key = (symbol, timeframe)
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached["ts"] < _CACHE_TTL:
        return cached["data"]

    binance_symbol = SYMBOL_MAP.get(symbol)
    if not binance_symbol:
        return None

    try:
        raw = _fetch_klines(binance_symbol, timeframe)
    except Exception as e:
        print(f"[data_feed] fetch error {symbol} {timeframe}: {e}")
        return cached["data"] if cached else None

    if not raw or len(raw) < 20:
        return None

    closes  = np.array([float(k[4]) for k in raw])
    highs   = np.array([float(k[2]) for k in raw])
    lows    = np.array([float(k[3]) for k in raw])
    volumes = np.array([float(k[5]) for k in raw])
    n = len(closes)

    atr = _calc_atr(highs, lows, closes)

    data = {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes, "atr": atr, "n": n}
    _cache[key] = {"data": data, "ts": now}
    return data


def _calc_atr(highs, lows, closes, period=14):
    if len(closes) < 2:
        return np.zeros(len(closes))
    trs = np.maximum(highs[1:] - lows[1:],
          np.maximum(np.abs(highs[1:] - closes[:-1]),
                     np.abs(lows[1:]  - closes[:-1])))
    atr = np.zeros(len(closes))
    if len(trs) == 0:
        return atr
    atr[1] = trs[0]
    for i in range(2, len(closes)):
        atr[i] = (atr[i-1] * (period-1) + trs[i-1]) / period
    return atr


def get_live_price(symbol: str):
    binance_symbol = SYMBOL_MAP.get(symbol)
    if not binance_symbol:
        return None
    try:
        r = requests.get(f"{BINANCE_BASE}/api/v3/ticker/price",
                          params={"symbol": binance_symbol}, timeout=5)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception as e:
        print(f"[data_feed] price fetch error {symbol}: {e}")
        return None
