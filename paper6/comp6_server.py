"""Competition 6 — 17 agents, MAX_OPEN=unlimited, port 8127"""
import os, sys, uvicorn
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paper_shared.base_engine import CompEngine
from paper_shared.base_server import create_app

PORT      = 8127
MAX_OPEN  = 999  # unlimited
COMP_NAME = "Competition 6"
SAVE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

engine = CompEngine(SAVE_FILE, max_open=MAX_OPEN, comp_name=COMP_NAME)
app    = create_app(engine, PORT, COMP_NAME, MAX_OPEN)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
