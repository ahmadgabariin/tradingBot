from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
from loguru import logger
from config.settings import settings

app = FastAPI(title="BinanceBot Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

bot_instance = None
connected_clients: list[WebSocket] = []


def set_bot(bot):
    global bot_instance
    bot_instance = bot


async def broadcast(data: dict):
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_clients.remove(ws)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            if bot_instance:
                stats = bot_instance.risk.get_stats()
                prices = {}
                for pair in settings.pairs_list:
                    try:
                        ticker = bot_instance.market.get_ticker(pair)
                        prices[pair] = {
                            "price": ticker.get("last", 0),
                            "change": round(ticker.get("percentage", 0), 2),
                        }
                    except Exception:
                        pass

                await websocket.send_json({
                    "type": "update",
                    "stats": stats,
                    "prices": prices,
                    "mode": settings.bot_mode,
                    "budget": settings.bot_budget,
                    "open_trades": bot_instance.risk.open_trades,
                    "trade_history": bot_instance.risk.trade_history[-20:],
                    "sentiment": bot_instance.last_sentiment,
                    "sr_levels": bot_instance.last_sr,
                })
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


@app.get("/api/stats")
def get_stats():
    if not bot_instance:
        return {"error": "Bot not running"}
    return bot_instance.risk.get_stats()


@app.get("/api/trades")
def get_trades():
    if not bot_instance:
        return []
    return bot_instance.risk.trade_history


@app.get("/api/prices")
def get_prices():
    if not bot_instance:
        return {}
    prices = {}
    for pair in settings.pairs_list:
        try:
            ticker = bot_instance.market.get_ticker(pair)
            prices[pair] = {
                "price": ticker.get("last", 0),
                "change": round(ticker.get("percentage", 0), 2),
            }
        except Exception:
            pass
    return prices


@app.post("/api/bot/stop")
def stop_bot():
    if bot_instance:
        bot_instance.stop()
    return {"status": "stopped"}


@app.get("/api/config")
def get_config():
    return {
        "mode": settings.bot_mode,
        "budget": settings.bot_budget,
        "max_trade": settings.max_trade_amount,
        "stop_loss": settings.stop_loss_percent,
        "take_profit": settings.take_profit_percent,
        "pairs": settings.pairs_list,
    }


app.mount("/", StaticFiles(directory="src/dashboard/static", html=True), name="static")
