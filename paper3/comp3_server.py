"""Competition 3 — 17 agents, MAX_OPEN=1, port 8124"""
import os, sys, uvicorn
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paper_shared.base_engine import CompEngine
from paper_shared.base_server import create_app

PORT      = 8124
MAX_OPEN  = 1
COMP_NAME = "Competition 3"
SAVE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

engine = CompEngine(SAVE_FILE, max_open=MAX_OPEN, comp_name=COMP_NAME)
app    = create_app(engine, PORT, COMP_NAME, MAX_OPEN)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
