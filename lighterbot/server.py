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
from lighterbot.lighter_client import signed_position_size
# MARKET_INDEX/PRICE_DECIMALS come from client.MARKET_INDEX/client.PRICE_DECIMALS
# below (platform-aware), not a flat import — see engine.py's ensure_client().
from lighterbot import db

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
    try:
        await db.ensure_indexes()
    except Exception as e:
        engine.log(f"MongoDB index setup failed (trade history persistence may be degraded): {e}")

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
        await engine.maybe_init_agent_balances()
        await engine.sync_realized_pnl()
        cfg = cfgmod.load_config()  # reload — may have just been auto-initialized above
        raw_positions, pos_err = await client.get_open_positions()

        # Fetch all active orders once, group by market so SL/TP trigger
        # prices can be attached to each open position below.
        active_orders, _ = await client.get_active_orders()
        orders_by_market = {}
        for o in active_orders:
            orders_by_market.setdefault(getattr(o, "market_index", None), []).append(o)

        for p in raw_positions:
            size = signed_position_size(p)
            if size == 0:
                continue
            symbol = getattr(p, "symbol", "?")
            market_index = client.MARKET_INDEX.get(symbol)
            market_orders = orders_by_market.get(market_index, [])
            sl_order = next((o for o in market_orders if getattr(o, "type", "") == "stop-loss-limit"), None)
            tp_order = next((o for o in market_orders if getattr(o, "type", "") == "take-profit-limit"), None)

            mapping = st.get("position_agent_map", {}).get(symbol)
            agent_label = mapping["agent"] if mapping else "Manual"
            price_dec = client.PRICE_DECIMALS.get(symbol, 4)

            # Best-effort open time: latest agent_open_log entry for this
            # symbol (opens are logged, closes aren't, so the newest entry
            # for a symbol that's still open is the one that opened it).
            open_log_matches = [e for e in st.get("agent_open_log", []) if e["symbol"] == symbol]
            opened_at = max((e["opened_at"] for e in open_log_matches), default=None)

            # Prefer the REAL leverage Binance reports for this specific
            # open position over the current config value — the config can
            # change after a position opens (e.g. bumping leverage for
            # future trades), but Binance refuses to change leverage on a
            # symbol with an open position, so the live position keeps
            # running at whatever leverage it actually opened with. Showing
            # the new config value here would misrepresent the real trade.
            real_leverage = getattr(p, "leverage", None)
            leverage = real_leverage if real_leverage else cfg.get("leverage", {}).get(symbol, cfg.get("default_leverage"))

            live_positions.append({
                "symbol": symbol,
                "agent": agent_label,
                "size": size,
                "avg_entry_price": round(float(getattr(p, "avg_entry_price", 0) or 0), price_dec),
                "position_value": round(float(getattr(p, "position_value", 0) or 0), 2),
                "unrealized_pnl": round(float(getattr(p, "unrealized_pnl", 0) or 0), 4),
                "liquidation_price": getattr(p, "liquidation_price", None),
                "open_order_count": getattr(p, "open_order_count", 0),
                "sl_price": round(float(getattr(sl_order, "trigger_price", 0) or 0), price_dec) if sl_order else None,
                "tp_price": round(float(getattr(tp_order, "trigger_price", 0) or 0), price_dec) if tp_order else None,
                "opened_at": opened_at,
                "leverage": leverage,
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
        "started_at": engine.started_at,    # engine process start time, for uptime display
        # Authoritative, never-windowed per-agent realized PnL (see
        # engine.sync_realized_pnl) — the dashboard uses THIS for equity/
        # return%, not a live recompute from the capped /trades list, so
        # those numbers stay exact no matter how much trade history piles up.
        "agent_realized_pnl": engine.state.get("agent_realized_pnl", {}),
    })


@app.get("/trades")
async def trades(page: int = 0, per_page: int = 25, agent: str = None):
    """Real, validated trade history — served from MongoDB (see db.py), NOT
    re-fetched from Lighter's API on every call. Each trade is written to the
    DB exactly once, the moment engine.sync_realized_pnl() first confirms it
    closed. Real pagination: only the requested page is ever queried, not
    the whole history sorted/sliced in memory."""
    try:
        cfg = cfgmod.load_config()
        cutoff = cfg.get("trade_history_cutoff", 0)
        per_page = max(1, min(per_page, 200))
        page = max(0, page)

        result, total = await db.get_trades_page(page=page, per_page=per_page, agent=agent, cutoff=cutoff)

        # trade_number reflects true chronological sequence (#1 = earliest
        # visible) even though this page shows most-recent-first.
        for i, t in enumerate(result):
            t["trade_number"] = total - (page * per_page + i)

        return JSONResponse({"trades": result, "total": total, "page": page, "per_page": per_page, "error": None})
    except Exception as e:
        return JSONResponse({"trades": [], "total": 0, "page": page, "per_page": per_page, "error": str(e)})


@app.get("/daily-pnl")
async def daily_pnl(agent: str = None):
    """Precomputed per-day PnL aggregates (see db.py) — not recalculated by
    summing every trade on each request."""
    try:
        cfg = cfgmod.load_config()
        cutoff = cfg.get("trade_history_cutoff", 0)
        data = await db.get_daily_pnl(agent=agent, cutoff=cutoff)
        return JSONResponse({"daily_pnl": data, "error": None})
    except Exception as e:
        return JSONResponse({"daily_pnl": [], "error": str(e)})


@app.get("/agent-trades/{agent_name}")
async def agent_trades(agent_name: str):
    """All of one agent's trades, for computing its stats/equity-curve on the
    dashboard — a single indexed MongoDB query instead of the old approach of
    re-paging through Lighter's live API on every poll."""
    try:
        cfg = cfgmod.load_config()
        global_cutoff = cfg.get("trade_history_cutoff", 0)
        agent_cutoff = cfg.get("agents", {}).get(agent_name, {}).get("stats_reset_at", 0)
        cutoff = max(global_cutoff, agent_cutoff)
        result = await db.get_agent_trades(agent_name, cutoff=cutoff)
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
            if name not in cfg["agents"]:
                continue
            # "sizing"/"trailing" are nested dicts — a shallow .update() would
            # replace the whole sub-dict and silently drop any sibling keys
            # the caller didn't include (e.g. sending only {"sar_af_max": 0.1}
            # would wipe sar_af_start/sar_af_step). Merge those one level
            # deeper; everything else (enabled, direction, start_balance) is
            # a flat scalar and still gets a plain overwrite.
            for k, v in acfg.items():
                if k in ("sizing", "trailing") and isinstance(v, dict) and isinstance(cfg["agents"][name].get(k), dict):
                    cfg["agents"][name][k].update(v)
                else:
                    cfg["agents"][name][k] = v
    if "sizing" in payload:
        cfg["sizing"].update(payload["sizing"])
    leverage_sync = None
    if "leverage" in payload:
        client = await engine.ensure_client()
        await client.refresh_max_leverage()
        clamped = {}
        for symbol, requested in payload["leverage"].items():
            max_lev = client.get_max_leverage(symbol)
            clamped[symbol] = min(int(requested), max_lev)
        cfg["leverage"].update(clamped)

        # Leverage on the exchange only ever changes at the moment the bot
        # opens a fresh trade — saving a new value here otherwise just sits
        # unapplied until the next signal fires on that symbol, which is
        # confusing (a user changing BNB to 20x sees it still at whatever it
        # was last set to, with no obvious reason why). Push it immediately
        # to every symbol that's currently FLAT (no position, no resting
        # orders) so the change takes effect right away instead of silently
        # waiting; symbols with an open position/order are left alone since
        # the exchange always rejects a leverage change there regardless —
        # those pick up the new value automatically on their next fresh open.
        positions, pos_err = await client.get_open_positions()
        held_symbols = set()
        if not pos_err:
            held_symbols = {getattr(p, "symbol", None) for p in positions if signed_position_size(p) != 0}
        leverage_sync = {}
        for symbol, new_lev in clamped.items():
            if symbol in held_symbols:
                leverage_sync[symbol] = {"synced": False, "reason": "position open — will apply on next fresh trade"}
                continue
            ok, result = await client.set_leverage(symbol, new_lev)
            leverage_sync[symbol] = {"synced": ok, "reason": None if ok else str(result)}
            if not ok:
                engine.log_critical_error("leverage_sync_failed", symbol=symbol, requested=new_lev, error=str(result))

    if "default_leverage" in payload:
        cfg["default_leverage"] = payload["default_leverage"]
    if "min_notional_usd" in payload:
        cfg["min_notional_usd"] = payload["min_notional_usd"]

    if "platform" in payload:
        requested = payload["platform"]
        if requested not in ("lighter", "binance"):
            return JSONResponse({"error": f"unknown platform '{requested}'"}, status_code=400)
        # Switching which exchange executes real orders while the bot is
        # live is exactly the kind of state change that should never happen
        # silently mid-tick — require a stop first, same principle as not
        # letting leverage change under an open position.
        if requested != cfg.get("platform", "lighter") and cfg.get("running"):
            return JSONResponse({"error": "stop the bot before switching platforms"}, status_code=400)
        if requested == "binance" and not (os.environ.get("BINANCE_API_KEY") and os.environ.get("BINANCE_API_SECRET")):
            return JSONResponse({"error": "BINANCE_API_KEY/BINANCE_API_SECRET not set in .env — add them first"}, status_code=400)
        cfg["platform"] = requested
        engine.client = None  # force ensure_client() to rebuild against the new platform next tick

    cfgmod.save_config(cfg)
    return {"ok": True, "config": cfg, "leverage_sync": leverage_sync}


@app.get("/platform-status")
async def platform_status():
    """Lets the dashboard show whether Binance credentials are actually
    present WITHOUT ever exposing the key/secret values themselves — only a
    boolean, same boundary as how Lighter's own credentials are never
    surfaced through any endpoint."""
    return {
        "lighter_configured": bool(os.environ.get("LIGHTER_API_PRIVATE_KEY")),
        "binance_configured": bool(os.environ.get("BINANCE_API_KEY") and os.environ.get("BINANCE_API_SECRET")),
    }


@app.post("/manual-trade")
async def manual_trade(request: Request, payload: dict):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    symbol       = payload.get("symbol", "BTC")
    side         = payload.get("side", "LONG")
    override_usd = payload.get("override_usd")        # margin $ override, e.g. 0.5
    leverage     = payload.get("leverage")             # optional leverage override
    sl_pct       = payload.get("sl_pct", 1.5)
    tp_pct       = payload.get("tp_pct", 3.0)
    sl_price     = payload.get("sl_price")             # exact price, overrides sl_pct if present
    tp_price     = payload.get("tp_price")             # exact price, overrides tp_pct if present

    ok, result = await engine.manual_trade(symbol, side, override_usd, leverage, sl_pct, tp_pct,
                                            sl_price_override=sl_price, tp_price_override=tp_price)
    return {"ok": ok, "result": str(result)}


@app.post("/clear-log")
async def clear_log(request: Request):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    engine.clear_log()
    return {"ok": True}


@app.post("/clear-errors")
async def clear_errors(request: Request):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    engine.clear_critical_errors()
    return {"ok": True}


@app.post("/reset-agent-stats")
async def reset_agent_stats(request: Request, payload: dict):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    agent = payload.get("agent")
    cfg = cfgmod.load_config()
    if not agent or agent not in cfg["agents"]:
        return JSONResponse({"error": "unknown agent"}, status_code=400)

    import time
    # Marks the boundary so the dashboard's displayed win rate/avg win-loss/
    # charts/trade table for this agent also start fresh from now, in sync
    # with the realized-PnL reset below — real trades on Lighter are
    # untouched, this only resets what's displayed/tracked for this agent.
    cfg["agents"][agent]["stats_reset_at"] = time.time()
    cfgmod.save_config(cfg)
    engine.reset_agent_stats(agent)
    try:
        await db.reset_agent_daily_pnl(agent)
    except Exception as e:
        engine.log(f"Could not clear MongoDB daily_pnl for {agent} on reset: {e}")
    return {"ok": True}


@app.post("/clear-trade-history")
async def clear_trade_history(request: Request):
    if not _auth(request): return JSONResponse({"error": "forbidden"}, status_code=403)
    import time
    cfg = cfgmod.load_config()
    cfg["trade_history_cutoff"] = time.time()
    cfgmod.save_config(cfg)
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


@app.get("/errors")
async def critical_errors():
    """Permanent (last 500, not the rotating 300-line trade_log) record of
    anything that could have left real money at risk — failed entries,
    failed leverage sets, failed SL/TP attachments, failed trailing modifies.
    Built after the POL-left-unprotected incident on 2026-07-05, where the
    actual root cause had already scrolled off the regular trade_log by the
    time anyone went looking for it."""
    st = _load_state()
    errors = list(reversed(st.get("critical_errors", [])))  # most recent first
    return JSONResponse({"errors": errors})


@app.get("/health")
async def health():
    return {"status": "ok", "running": engine.running}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8140, log_level="warning")
