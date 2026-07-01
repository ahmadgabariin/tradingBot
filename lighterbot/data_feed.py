"""
Standalone Binance market data feed for LighterBot.
Pulls candles from Binance (signal source) — completely independent from
paper_shared/base_engine.py so this bot never touches the existing project.

Indicator math below is ported 1:1 from fast_backtest.py's precompute() and
paper_shared/base_engine.py's _calc_swing() — comp9/comp10 use these exact
formulas, so LighterBot's Liquidity Hunt / Surgeon v2 signals fire on the
same conditions as the real comp10 agents, not an approximation.
"""
import time
import numpy as np
import requests

BINANCE_BASE = "https://api.binance.com"
CANDLE_LIMIT = 300

# Lighter symbol -> Binance symbol. Matches COMP9_PAIRS (paper9/paper11 agents).
SYMBOL_MAP = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT",
    "XRP": "XRPUSDT", "ADA": "ADAUSDT", "LINK": "LINKUSDT", "DOT": "DOTUSDT",
    "AVAX": "AVAXUSDT", "POL": "POLUSDT",
}

_cache = {}          # (symbol, timeframe) -> {"data": {...}, "ts": float}
_CACHE_TTL = 8        # seconds, avoid hammering Binance every tick


def _fetch_klines(binance_symbol: str, interval: str, limit: int = CANDLE_LIMIT):
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {"symbol": binance_symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


# ── Indicators — ported verbatim from fast_backtest.py ───────────────────────

def _rsi_series(c, period=14):
    n = len(c)
    gains = np.zeros(n); losses = np.zeros(n)
    for i in range(1, n):
        d = c[i] - c[i-1]
        gains[i] = max(d, 0); losses[i] = max(-d, 0)
    out = np.full(n, 50.0)
    for i in range(period, n):
        ag = np.sum(gains[i-period+1:i+1]) / period
        al = np.sum(losses[i-period+1:i+1]) / period
        out[i] = 100 - 100/(1 + ag/al) if al > 0 else 100.0
    return out


def _atr_series(h, l, c, period=14):
    n = len(c)
    trs = np.zeros(n)
    trs[0] = h[0] - l[0]
    for i in range(1, n):
        trs[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    out = np.zeros(n)
    if n > period:
        out[period-1] = np.sum(trs[:period]) / period
        for i in range(period, n):
            out[i] = (out[i-1]*(period-1) + trs[i]) / period
    return out


def _adx_series(h, l, c, period=14):
    n = len(c)
    plus_di = np.zeros(n); minus_di = np.zeros(n); adx_out = np.full(n, 20.0)
    plus_dm_s = np.zeros(n); minus_dm_s = np.zeros(n); tr_s = np.zeros(n)
    for i in range(1, n):
        up = h[i]-h[i-1]; dn = l[i-1]-l[i]
        plus_dm  = max(up, 0) if up > dn else 0
        minus_dm = max(dn, 0) if dn > up else 0
        tr = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        if i < period:
            plus_dm_s[i]  = plus_dm_s[i-1] + plus_dm
            minus_dm_s[i] = minus_dm_s[i-1] + minus_dm
            tr_s[i]       = tr_s[i-1] + tr
        else:
            plus_dm_s[i]  = plus_dm_s[i-1] - plus_dm_s[i-1]/period + plus_dm
            minus_dm_s[i] = minus_dm_s[i-1] - minus_dm_s[i-1]/period + minus_dm
            tr_s[i]       = tr_s[i-1] - tr_s[i-1]/period + tr
        if tr_s[i] > 0:
            plus_di[i]  = 100 * plus_dm_s[i] / tr_s[i]
            minus_di[i] = 100 * minus_dm_s[i] / tr_s[i]
        dsum = plus_di[i] + minus_di[i]
        dx = abs(plus_di[i]-minus_di[i])/dsum*100 if dsum > 0 else 0
        adx_out[i] = (adx_out[i-1]*(period-1) + dx)/period if i >= period else dx
    return adx_out


def _vol_avg_series(v, window=20):
    n = len(v)
    out = np.zeros(n)
    for i in range(window, n):
        out[i] = np.sum(v[i-window:i]) / window
    return out


def _swing_series(h, l, lookback=10):
    n = len(h)
    s_hi = np.zeros(n); s_lo = np.zeros(n)
    for i in range(lookback, n):
        s_hi[i] = np.max(h[i-lookback:i])
        s_lo[i] = np.min(l[i-lookback:i])
    return s_hi, s_lo


def get_candles(symbol: str, timeframe: str):
    """Returns dict with the exact fields comp9/comp10's precompute() produces
    (c, h, l, v, o, rsi, adx, vol_avg, green, s_hi, s_lo, atr, n), so ported
    signal functions run on identical data. Cached briefly to avoid hammering
    Binance every tick."""
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

    if not raw or len(raw) < 50:
        return None

    o = np.array([float(k[1]) for k in raw])
    h = np.array([float(k[2]) for k in raw])
    l = np.array([float(k[3]) for k in raw])
    c = np.array([float(k[4]) for k in raw])
    v = np.array([float(k[5]) for k in raw])
    n = len(c)

    data = {
        "c": c, "h": h, "l": l, "v": v, "o": o, "n": n,
        "rsi": _rsi_series(c),
        "atr": _atr_series(h, l, c),
        "adx": _adx_series(h, l, c),
        "vol_avg": _vol_avg_series(v),
        "green": c > o,
    }
    data["s_hi"], data["s_lo"] = _swing_series(h, l)

    _cache[key] = {"data": data, "ts": now}
    return data


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
