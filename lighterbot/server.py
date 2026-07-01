"""
LighterBot dashboard + control API. Port 8140.
Real-money trading — every mutating endpoint requires X-Action-Password,
same pattern as the paper-trading competitions.
"""
import os, sys
from contextlib import asynccontextmanager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from lighterbot import config as cfgmod
from lighterbot.engine import engine, _load_state
from lighterbot.lighter_client import MARKET_INDEX

_SYMBOL_BY_MARKET_INDEX = {v: k for k, v in MARKET_INDEX.items()}


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # If the process crashes or the server restarts while trading was
    # active, the saved config still says running=True — without this, the
    # engine would silently stay stopped until someone notices and clicks
    # Start again, even though real positions may still be open and need
    # their trailing stops managed.
    cfg = cfgmod.load_config()
    if cfg.get("running"):
        engine.log("Server restarted with running=True in saved config — auto-resuming trading loop.")
        await engine.start()
    yield


app = FastAPI(title="LighterBot", lifespan=lifespan)
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

        # Fetch all active orders once, group by market so SL/TP trigger
        # prices can be attached to each open position below.
        active_orders, _ = await client.get_active_orders()
        orders_by_market = {}
        for o in active_orders:
            orders_by_market.setdefault(getattr(o, "market_index", None), []).append(o)

        for p in raw_positions:
            size = float(getattr(p, "position", 0) or 0)
            if size == 0:
                continue
            symbol = getattr(p, "symbol", "?")
            market_index = MARKET_INDEX.get(symbol)
            market_orders = orders_by_market.get(market_index, [])
            sl_order = next((o for o in market_orders if getattr(o, "type", "") == "stop-loss-limit"), None)
            tp_order = next((o for o in market_orders if getattr(o, "type", "") == "take-profit-limit"), None)

            mapping = st.get("position_agent_map", {}).get(symbol)
            agent_label = mapping["agent"] if mapping else "Manual"

            live_positions.append({
                "symbol": symbol,
                "agent": agent_label,
                "size": size,
                "avg_entry_price": float(getattr(p, "avg_entry_price", 0) or 0),
                "position_value": float(getattr(p, "position_value", 0) or 0),
                "unrealized_pnl": float(getattr(p, "unrealized_pnl", 0) or 0),
                "liquidation_price": getattr(p, "liquidation_price", None),
                "open_order_count": getattr(p, "open_order_count", 0),
                "sl_price": float(getattr(sl_order, "trigger_price", 0) or 0) if sl_order else None,
                "tp_price": float(getattr(tp_order, "trigger_price", 0) or 0) if tp_order else None,
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


def _find_agent(agent_open_log, symbol, opened_at, tolerance_sec=180):
    """Best-effort join: find the agent_open_log entry for this symbol whose
    logged open time is closest to (and within tolerance of) the exchange's
    actual fill timestamp. Falls back to 'Manual' if nothing matches — this
    happens for trades placed before this tracking existed, or from outside
    the bot entirely."""
    candidates = [e for e in agent_open_log if e["symbol"] == symbol]
    if not candidates:
        return "Manual"
    best = min(candidates, key=lambda e: abs(e["opened_at"] - opened_at))
    if abs(best["opened_at"] - opened_at) <= tolerance_sec:
        return best["agent"]
    return "Manual"


@app.get("/trades")
async def trades():
    """Real trade history built by pairing entry fills with their exit fills
    from Lighter's account_inactive_orders — ground truth for prices/timing,
    not reconstructed from local guesses. PNL is computed from the real
    entry/exit prices. Agent attribution comes from the bot's own open-log
    (the exchange has no concept of 'which agent'), matched by nearest
    timestamp. Frontend paginates client-side over this list."""
    try:
        client = await engine.ensure_client()
        orders, err = await client.get_inactive_orders(limit=100)
        if err:
            return JSONResponse({"trades": [], "error": err})

        st = _load_state()
        agent_open_log = st.get("agent_open_log", [])

        filled = [o for o in orders if getattr(o, "status", "") == "filled"]
        by_market = {}
        for o in filled:
            by_market.setdefault(getattr(o, "market_index", None), []).append(o)

        result = []
        for market_index, group in by_market.items():
            group.sort(key=lambda o: getattr(o, "timestamp", 0))
            symbol = _SYMBOL_BY_MARKET_INDEX.get(market_index, f"market_{market_index}")

            pending_entry = None
            for o in group:
                reduce_only = getattr(o, "reduce_only", False)
                if not reduce_only:
                    # A new entry — if one was already pending with no exit yet,
                    # it's superseded (shouldn't normally happen with
                    # max_open_positions=1, but don't silently drop data).
                    pending_entry = o
                    continue

                if pending_entry is None:
                    continue  # exit with no matching entry in this window — skip

                entry = pending_entry
                pending_entry = None

                side = "LONG" if not getattr(entry, "is_ask", False) else "SHORT"
                entry_price = float(getattr(entry, "price", 0) or 0)
                exit_price  = float(getattr(o, "price", 0) or 0)
                qty = float(getattr(entry, "filled_base_amount", 0) or 0)
                pnl = qty * (exit_price - entry_price) if side == "LONG" else qty * (entry_price - exit_price)

                exit_type_raw = getattr(o, "type", "")
                if "take-profit" in exit_type_raw:
                    exit_label = "TP"
                elif "stop-loss" in exit_type_raw:
                    exit_label = "SL"
                else:
                    exit_label = "Manual"

                opened_at = getattr(entry, "timestamp", 0)
                closed_at = getattr(o, "timestamp", 0)
                agent = _find_agent(agent_open_log, symbol, opened_at)

                result.append({
                    "agent": agent,
                    "symbol": symbol,
                    "side": side,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "exit_type": exit_label,
                    "result": "WIN" if pnl >= 0 else "LOSS",
                    "pnl": round(pnl, 4),
                    "opened_at": opened_at,
                    "closed_at": closed_at,
                })

        # Number trades in chronological order (#1 = earliest), then present
        # most-recent-first — trade_number reflects real sequence, not page position.
        result.sort(key=lambda t: t["closed_at"])
        for i, t in enumerate(result):
            t["trade_number"] = i + 1
        result.sort(key=lambda t: t["closed_at"], reverse=True)
        return JSONResponse({"trades": result, "error": None})
    except Exception as e:
        return JSONResponse({"trades": [], "error": str(e)})


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


@app.post("/refresh-leverage")
async def refresh_leverage(request: Request):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    client = await engine.ensure_client()
    ok, result = await client.refresh_max_leverage(force=True)
    return {"ok": ok, "result": str(result)}


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
