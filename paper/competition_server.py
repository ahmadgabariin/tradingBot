"""
openCLAUDE Competition Server
FastAPI + WebSocket real-time trading competition
"""
import asyncio, json, time, threading, os, sys
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paper.competition_engine as engine
from paper.competition_agents import AGENTS

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

clients: list[WebSocket] = []
TICK_INTERVAL = 5  # seconds between engine ticks

# ── Background tick loop ───────────────────────────────────────────────────────
def background_loop():
    while True:
        if engine.session_running:
            try:
                engine.run_tick()
            except Exception as e:
                print(f"[Tick error] {e}")
        time.sleep(TICK_INTERVAL)

thread = threading.Thread(target=background_loop, daemon=True)
thread.start()

# ── Broadcast helper ───────────────────────────────────────────────────────────
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

# ── Push loop ──────────────────────────────────────────────────────────────────
async def push_loop():
    while True:
        await asyncio.sleep(TICK_INTERVAL)
        if engine.session_running and clients:
            data = build_state()
            await broadcast(data)

def build_state():
    stats = {name: engine.get_agent_stats(name) for name in AGENTS}
    sorted_agents = sorted(stats.values(), key=lambda x: -x["equity"])
    for i, a in enumerate(sorted_agents):
        a["rank"] = i + 1

    recent_trades = sorted(engine.all_trades, key=lambda t: t["close_ts"], reverse=True)[:50]

    return {
        "type":         "state",
        "running":      engine.session_running,
        "session_start": engine.session_start,
        "agents":       sorted_agents,
        "recent_trades": recent_trades,
        "pair_heatmap": engine.get_pair_heatmap(),
        "key_moments":  engine.get_key_moments(),
        "live_prices":  engine.live_prices,
        "tick_ts":      time.time(),
        "leverage":     engine.LEVERAGE,
    }

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    asyncio.create_task(push_loop())

@app.post("/start")
async def start():
    engine.start_session_with_ts()
    await broadcast({"type": "session_started"})
    return {"ok": True}

@app.post("/resume")
async def resume():
    engine.resume_session()
    await broadcast({"type": "session_started"})
    return {"ok": True}

@app.post("/stop")
async def stop():
    engine.stop_session()
    await broadcast({"type": "session_stopped"})
    return {"ok": True}

@app.get("/state")
async def state():
    return build_state()

@app.post("/set-direction")
async def set_direction(payload: dict):
    agent = payload.get("agent")
    direction = payload.get("direction")
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
        clients.remove(ws)

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(os.path.dirname(__file__), "competition.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/monitor", response_class=HTMLResponse)
async def monitor():
    html_path = os.path.join(os.path.dirname(__file__), "monitor.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
