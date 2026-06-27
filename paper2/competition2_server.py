"""
Competition 2 Server — 17 agents on port 8123
"""
import asyncio, json, time, threading, os, sys
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paper2.competition2_engine as engine
from paper2.competition2_agents import AGENTS

app = FastAPI(title="Competition 2")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

clients: list[WebSocket] = []
TICK_INTERVAL = 10

def background_loop():
    while True:
        if engine.session_running:
            try:
                engine.run_tick()
            except Exception as e:
                print(f"[Tick2 error] {e}")
        time.sleep(TICK_INTERVAL)

thread = threading.Thread(target=background_loop, daemon=True)
thread.start()

async def broadcast(data: dict):
    dead = []
    for ws in clients:
        try:
            await ws.send_json(data)
        except:
            dead.append(ws)
    for ws in dead:
        if ws in clients:
            clients.remove(ws)

async def push_loop():
    while True:
        await asyncio.sleep(TICK_INTERVAL)
        if engine.session_running and clients:
            await broadcast(build_state())

def build_state():
    stats = {name: engine.get_agent_stats(name) for name in AGENTS}
    sorted_agents = sorted(stats.values(), key=lambda x: -x["equity"])
    for i, a in enumerate(sorted_agents):
        a["rank"] = i + 1

    recent_trades = sorted(engine.all_trades, key=lambda t: t.get("close_ts", 0), reverse=True)[:100]

    return {
        "type":          "state",
        "running":       engine.session_running,
        "session_start": engine.session_start,
        "agents":        sorted_agents,
        "recent_trades": recent_trades,
        "pair_heatmap":  engine.get_pair_heatmap(),
        "live_prices":   engine.live_prices,
        "tick_ts":       time.time(),
        "leverage":      engine.LEVERAGE,
        "restart_count": engine.restart_count,
        "restart_log":   engine.restart_log,
        "key_moments":   engine.get_key_moments(),
    }

@app.on_event("startup")
async def startup():
    asyncio.create_task(push_loop())

@app.post("/start")
async def start():
    engine.start_session()
    await broadcast(build_state())
    return {"ok": True, "message": "Competition 2 started with 17 agents"}

@app.post("/resume")
async def resume():
    engine.resume_session()
    await broadcast(build_state())
    return {"ok": True, "message": "Competition 2 resumed"}

@app.post("/stop")
async def stop():
    engine.stop_session()
    await broadcast(build_state())
    return {"ok": True}

@app.get("/state")
async def state():
    return JSONResponse(build_state())

@app.post("/set-direction")
async def set_direction(payload: dict):
    agent     = payload.get("agent")
    direction = payload.get("direction")
    if agent and direction:
        engine.set_agent_direction(agent, direction)
        await broadcast(build_state())
    return {"ok": True}

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.append(ws)
    try:
        await ws.send_json(build_state())
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in clients:
            clients.remove(ws)

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "paper_shared", "competition.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    return html.replace("__PORT__", "8123").replace("__COMP_NAME__", "Competition 2").replace("__MAX_OPEN__", "3")

@app.get("/monitor", response_class=HTMLResponse)
async def monitor():
    html_path = os.path.join(os.path.dirname(__file__), "monitor2.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/agent/{name}")
async def agent_detail(name: str):
    if name not in AGENTS:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(engine.get_agent_detail(name))

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "running": engine.session_running,
        "agents": len(AGENTS),
        "open_trades": sum(len(engine.agent_open[n]) for n in AGENTS),
        "total_closed": len(engine.all_trades),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8123, log_level="warning")
