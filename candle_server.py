"""
Shared candle + price cache — one process fetches Binance, all competitions read from here.
Port 8200. Candles refresh every 60s, prices every 3s.
"""
import time, threading, requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="Candle Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PAIRS      = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT","LINKUSDT","DOTUSDT","AVAXUSDT","POLUSDT"]
TIMEFRAMES = ["5m", "15m", "1h"]
REFRESH    = 60
PRICE_REFRESH = 3

_cache    = {}
_cache_ts = {}
_prices   = {}
_lock     = threading.Lock()

def _fetch(pair, tf, n=200):
    url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={tf}&limit={n}"
    r = requests.get(url, timeout=10); r.raise_for_status()
    raw = r.json()
    return {
        "open":  [float(c[1]) for c in raw],
        "high":  [float(c[2]) for c in raw],
        "low":   [float(c[3]) for c in raw],
        "close": [float(c[4]) for c in raw],
        "vol":   [float(c[5]) for c in raw],
        "ts":    [int(c[0])   for c in raw],
        "n":     len(raw),
    }

def _refresh_loop():
    while True:
        for pair in PAIRS:
            for tf in TIMEFRAMES:
                key = f"{pair}:{tf}"
                if time.time() - _cache_ts.get(key, 0) >= REFRESH:
                    try:
                        data = _fetch(pair, tf)
                        with _lock:
                            _cache[key] = data
                            _cache_ts[key] = time.time()
                    except Exception as e:
                        print(f"[candle_server] {key}: {e}")
                    time.sleep(0.15)
        time.sleep(5)

def _price_loop():
    while True:
        try:
            r = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=5)
            r.raise_for_status()
            prices = {item["symbol"]: float(item["price"]) for item in r.json() if item["symbol"] in PAIRS}
            with _lock:
                _prices.update(prices)
        except Exception as e:
            print(f"[candle_server] prices: {e}")
        time.sleep(PRICE_REFRESH)

threading.Thread(target=_refresh_loop, daemon=True).start()
threading.Thread(target=_price_loop,   daemon=True).start()

@app.get("/candles")
def candles(pair: str, tf: str):
    key = f"{pair}:{tf}"
    with _lock:
        cached = _cache.get(key)
    if cached:
        return JSONResponse(cached)
    try:
        data = _fetch(pair, tf)
        with _lock:
            _cache[key] = data
            _cache_ts[key] = time.time()
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/prices")
def prices():
    with _lock:
        return JSONResponse(dict(_prices))

@app.get("/health")
def health():
    return {"cached_keys": len(_cache), "price_pairs": len(_prices), "pairs": PAIRS, "timeframes": TIMEFRAMES}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8200, log_level="warning")
