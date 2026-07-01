"""
LighterBot dashboard + control API. Port 8140.
Real-money trading — every mutating endpoint requires X-Action-Password,
same pattern as the paper-trading competitions.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from lighterbot import config as cfgmod
from lighterbot.engine import engine, _load_state


def _load_dotenv():
    """Minimal .env loader — avoids adding python-dotenv as a hard dependency."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()
PASSWORD = os.environ.get("LIGHTERBOT_PASSWORD", "BOT2024")

app = FastAPI(title="LighterBot")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _auth(request: Request):
    if not PASSWORD:
        return True
    return request.headers.get("X-Action-Password", "") == PASSWORD


@app.get("/", response_class=HTMLResponse)
async def index():
    path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


@app.get("/state")
async def state():
    cfg = cfgmod.load_config()
    st = _load_state()
    balance, bal_err = (None, None)
    live_positions, pos_err = ([], None)
    max_leverage = {}
    try:
        client = await engine.ensure_client()
        await client.refresh_max_leverage()
        max_leverage = dict(client.max_leverage_cache)
        balance, bal_err = await client.get_balance_usd()
        raw_positions, pos_err = await client.get_open_positions()
        for p in raw_positions:
            size = float(getattr(p, "position", 0) or 0)
            if size == 0:
                continue
            live_positions.append({
                "symbol": getattr(p, "symbol", "?"),
                "size": size,
                "avg_entry_price": float(getattr(p, "avg_entry_price", 0) or 0),
                "position_value": float(getattr(p, "position_value", 0) or 0),
                "unrealized_pnl": float(getattr(p, "unrealized_pnl", 0) or 0),
                "liquidation_price": getattr(p, "liquidation_price", None),
                "open_order_count": getattr(p, "open_order_count", 0),
            })
    except Exception as e:
        bal_err = bal_err or str(e)

    return JSONResponse({
        "config": cfg,
        "open_positions": live_positions,   # live from Lighter — shows manual + auto trades alike
        "trade_log": st["trade_log"][-100:],
        "running": engine.running,
        "balance_usd": balance,
        "balance_error": bal_err,
        "positions_error": pos_err,
        "last_error": engine.last_error,
        "max_leverage": max_leverage,       # live from Lighter, refreshed every 5 min
    })


@app.post("/start")
async def start(request: Request):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    await engine.start()
    return {"ok": True}


@app.post("/stop")
async def stop(request: Request):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    await engine.stop()
    return {"ok": True}


@app.post("/selftest")
async def selftest(request: Request):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    ok, res = await engine.selftest()
    return {"ok": ok, "result": str(res)}


@app.post("/config")
async def update_config(request: Request, payload: dict):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    cfg = cfgmod.load_config()

    if "agents" in payload:
        for name, acfg in payload["agents"].items():
            if name in cfg["agents"]:
                cfg["agents"][name].update(acfg)
    if "sizing" in payload:
        cfg["sizing"].update(payload["sizing"])
    if "leverage" in payload:
        client = await engine.ensure_client()
        await client.refresh_max_leverage()
        clamped = {}
        for symbol, requested in payload["leverage"].items():
            max_lev = client.get_max_leverage(symbol)
            clamped[symbol] = min(int(requested), max_lev)
        cfg["leverage"].update(clamped)
    if "default_leverage" in payload:
        cfg["default_leverage"] = payload["default_leverage"]
    if "max_open_positions" in payload:
        cfg["max_open_positions"] = payload["max_open_positions"]
    if "min_notional_usd" in payload:
        cfg["min_notional_usd"] = payload["min_notional_usd"]

    cfgmod.save_config(cfg)
    return {"ok": True, "config": cfg}


@app.post("/manual-trade")
async def manual_trade(request: Request, payload: dict):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    symbol       = payload.get("symbol", "BTC")
    side         = payload.get("side", "LONG")
    override_usd = payload.get("override_usd")        # margin $ override, e.g. 0.5
    leverage     = payload.get("leverage")             # optional leverage override
    sl_pct       = payload.get("sl_pct", 1.5)
    tp_pct       = payload.get("tp_pct", 3.0)

    ok, result = await engine.manual_trade(symbol, side, override_usd, leverage, sl_pct, tp_pct)
    return {"ok": ok, "result": str(result)}


@app.post("/clear-log")
async def clear_log(request: Request):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    engine.clear_log()
    return {"ok": True}


@app.post("/close-position")
async def close_position(request: Request, payload: dict):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    symbol = payload.get("symbol")
    if not symbol:
        return JSONResponse({"error": "symbol required"}, status_code=400)
    ok, result = await engine.close_position(symbol)
    return {"ok": ok, "result": str(result)}


@app.post("/close-all")
async def close_all(request: Request):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    results, err = await engine.close_all_positions()
    if err:
        return {"ok": False, "result": err}
    all_ok = all(r["ok"] for r in results.values()) if results else True
    return {"ok": all_ok, "result": results}


@app.post("/emergency-stop")
async def emergency_stop(request: Request):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    await engine.stop()
    results, err = await engine.close_all_positions()
    if err:
        return {"ok": False, "result": err}
    all_ok = all(r["ok"] for r in results.values()) if results else True
    return {"ok": all_ok, "result": results}


@app.get("/health")
async def health():
    return {"status": "ok", "running": engine.running}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8140, log_level="warning")
