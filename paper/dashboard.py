from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio, json, websockets
import paper.engine as engine
from paper.engine import get_stats, get_all_trades, PAIRS, STRATEGY_PARAMS, db_close_trade_manual

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

live_prices = {p: {"price": 0.0, "change": 0.0} for p in PAIRS}
clients: list[WebSocket] = []

STRATEGY_INFO = {
    "KELTNER_BREAK":  {"name": "Keltner Break",   "desc": "Price breaks Keltner Channel upper band",  "wr": 81.7, "tpd": 2.6, "history": "208d", "tf": "15m", "sl": 2.5, "tp": 0.6, "trades": 547,  "ev": "+0.033%"},
    "DONCHIAN_BREAK": {"name": "Donchian Break",   "desc": "Price breaks 20-bar Donchian high",        "wr": 81.3, "tpd": 3.3, "history": "208d", "tf": "15m", "sl": 2.5, "tp": 0.6, "trades": 680,  "ev": "+0.021%"},
    "ORB":            {"name": "Opening Range",    "desc": "Breakout from tight consolidation range",   "wr": 81.8, "tpd": 0.7, "history": "833d", "tf": "1h",  "sl": 2.5, "tp": 0.6, "trades": 594,  "ev": "+0.036%"},
    "SQUEEZE_BREAK":  {"name": "Squeeze Break",   "desc": "Bollinger Band squeeze + breakout",         "wr": 64.7, "tpd": 1.5, "history": "208d", "tf": "15m", "sl": 2.5, "tp": 2.0, "trades": 315,  "ev": "-0.150%"},
    "SCORE":          {"name": "Score Engine",    "desc": "Multi-factor EMA + momentum + RSI score",   "wr": 62.9, "tpd": 0.5, "history": "833d", "tf": "1h",  "sl": 3.0, "tp": 1.5, "trades": 448,  "ev": "+0.147%"},
}


async def binance_stream():
    streams = "/".join(p.lower() + "@ticker" for p in PAIRS)
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"
    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    ticker = data.get("data", {})
                    symbol = ticker.get("s", "")
                    if symbol in live_prices:
                        live_prices[symbol] = {
                            "price": float(ticker.get("c", 0)),
                            "change": round(float(ticker.get("P", 0)), 2),
                        }
                        await broadcast()
        except Exception:
            await asyncio.sleep(3)


async def broadcast():
    payload = json.dumps({
        "prices":            live_prices,
        "stats":             get_stats(),
        "trades":            get_all_trades(150),
        "active_strategies": list(engine.ACTIVE_STRATEGIES),
    })
    dead = []
    for client in clients:
        try:
            await client.send_text(payload)
        except Exception:
            dead.append(client)
    for c in dead:
        clients.remove(c)


@app.on_event("startup")
async def startup():
    asyncio.create_task(binance_stream())


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    await websocket.send_json({
        "prices":            live_prices,
        "stats":             get_stats(),
        "trades":            get_all_trades(150),
        "active_strategies": list(engine.ACTIVE_STRATEGIES),
    })
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in clients:
            clients.remove(websocket)


@app.post("/toggle-strategy/{name}")
async def toggle_strategy(name: str):
    name = name.upper()
    if name not in STRATEGY_PARAMS:
        return JSONResponse({"ok": False, "error": f"Unknown: {name}"}, status_code=400)
    if name in engine.ACTIVE_STRATEGIES:
        if len(engine.ACTIVE_STRATEGIES) == 1:
            return JSONResponse({"ok": False, "error": "Must keep at least one strategy active"}, status_code=400)
        engine.ACTIVE_STRATEGIES.discard(name)
    else:
        engine.ACTIVE_STRATEGIES.add(name)
        engine.get_portfolio(name)  # pre-init portfolio
    await broadcast()
    return {"ok": True, "active": list(engine.ACTIVE_STRATEGIES)}


@app.post("/close-trade/{tid}")
async def close_trade(tid: int):
    result = db_close_trade_manual(tid)
    if not result:
        return JSONResponse({"ok": False, "error": "Trade not found or already closed"}, status_code=400)
    await broadcast()
    return {"ok": True, **result}


@app.get("/strategies")
def strategies():
    return {k: {**v, "active": k in engine.ACTIVE_STRATEGIES} for k, v in STRATEGY_INFO.items()}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return open("paper/dashboard.html", encoding="utf-8").read()
