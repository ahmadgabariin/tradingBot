"""
Factory that creates a FastAPI app for any competition.
Each comp server just calls create_app() with its config.
"""
import asyncio, time, os, threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from paper_shared.base_engine import CompEngine

TICK_INTERVAL = 10
_HTML_PATH = os.path.join(os.path.dirname(__file__), "competition.html")


def create_app(engine: CompEngine, port: int, comp_name: str, max_open: int) -> FastAPI:
    app = FastAPI(title=comp_name)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    clients: list[WebSocket] = []

    def _background_loop():
        while True:
            if engine.session_running:
                try: engine.run_tick()
                except Exception as e: print(f"[{comp_name} tick error] {e}")
            time.sleep(TICK_INTERVAL)

    threading.Thread(target=_background_loop, daemon=True).start()

    async def _broadcast(data: dict):
        dead = []
        for ws in clients:
            try: await ws.send_json(data)
            except: dead.append(ws)
        for ws in dead:
            if ws in clients: clients.remove(ws)

    def _build_state():
        stats = {n: engine.get_agent_stats(n) for n in engine.AGENTS}
        sorted_agents = sorted(stats.values(), key=lambda x: -x["equity"])
        for i, a in enumerate(sorted_agents): a["rank"] = i+1
        recent = sorted(engine.all_trades, key=lambda t: t.get("close_ts",0), reverse=True)[:100]
        return {
            "type":          "state",
            "running":       engine.session_running,
            "session_start": engine.session_start,
            "agents":        sorted_agents,
            "recent_trades": recent,
            "pair_heatmap":  engine.get_pair_heatmap(),
            "live_prices":   engine.live_prices,
            "tick_ts":       time.time(),
            "leverage":      engine.LEVERAGE,
            "restart_count": engine.restart_count,
            "restart_log":   engine.restart_log,
            "key_moments":   engine.get_key_moments(),
        }

    async def _push_loop():
        while True:
            await asyncio.sleep(TICK_INTERVAL)
            if engine.session_running and clients:
                await _broadcast(_build_state())

    @app.on_event("startup")
    async def startup():
        asyncio.create_task(_push_loop())

    @app.post("/start")
    async def start():
        engine.start_session()
        await _broadcast(_build_state())
        return {"ok": True}

    @app.post("/resume")
    async def resume():
        engine.resume_session()
        await _broadcast(_build_state())
        return {"ok": True}

    @app.post("/stop")
    async def stop():
        engine.stop_session()
        await _broadcast(_build_state())
        return {"ok": True}

    @app.get("/state")
    async def state():
        return JSONResponse(_build_state())

    @app.post("/set-direction")
    async def set_direction(payload: dict):
        agent     = payload.get("agent")
        direction = payload.get("direction")
        if agent and direction:
            engine.set_agent_direction(agent, direction)
            await _broadcast(_build_state())
        return {"ok": True}

    @app.post("/reset-restarts")
    async def reset_restarts():
        engine.restart_count = 0
        engine.restart_log.clear()
        engine._save_state()
        await _broadcast(_build_state())
        return {"ok": True}

    @app.get("/agent/{name}")
    async def agent_detail(name: str):
        if name not in engine.AGENTS:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(engine.get_agent_detail(name))

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        clients.append(ws)
        try:
            await ws.send_json(_build_state())
            while True: await ws.receive_text()
        except WebSocketDisconnect:
            if ws in clients: clients.remove(ws)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        max_open_display = str(max_open) if max_open < 999 else "∞"
        with open(_HTML_PATH, encoding="utf-8") as f:
            html = f.read()
        return (html
            .replace("__PORT__", str(port))
            .replace("__COMP_NAME__", comp_name)
            .replace("__MAX_OPEN__", max_open_display))

    @app.get("/health")
    async def health():
        return {
            "status":       "ok",
            "running":      engine.session_running,
            "agents":       len(engine.AGENTS),
            "open_trades":  sum(len(engine.agent_open[n]) for n in engine.AGENTS),
            "total_closed": len(engine.all_trades),
            "max_open":     engine.MAX_OPEN,
        }

    return app
