"""
Shared candle cache — one process fetches Binance, all competitions read from here.
Port 8200. Refreshes each pair/timeframe every 60s (~20 fetches/min total).
"""
import time, threading, requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="Candle Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PAIRS      = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT","LINKUSDT","DOTUSDT","AVAXUSDT","POLUSDT"]
TIMEFRAMES = ["15m", "1h"]
REFRESH    = 60

_cache    = {}
_cache_ts = {}
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

threading.Thread(target=_refresh_loop, daemon=True).start()

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

@app.get("/health")
def health():
    return {"cached_keys": len(_cache), "pairs": PAIRS, "timeframes": TIMEFRAMES}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8200, log_level="warning")
