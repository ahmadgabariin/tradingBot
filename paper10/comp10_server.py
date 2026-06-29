"""
Competition 10 — same 26 agents as comp9 but MAX_OPEN=unlimited. Port 8131.
Every agent can trade every pair simultaneously — pure max-profit mode.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper_shared.base_server import create_app
from paper9.comp9_engine import Comp9Engine
from paper9.comp9_agents import COMP9_AGENTS, LONG_SIGNALS_9, SHORT_SIGNALS_9, COMP9_PAIRS

PORT      = 8131
MAX_OPEN  = 9999
COMP_NAME = "Competition 10 — 26 Agents ATR Unlimited"
PASSWORD  = "BOT2024"
SAVE_FILE = os.path.join(os.path.dirname(__file__), "comp10_state.json")

engine = Comp9Engine(
    save_file     = SAVE_FILE,
    max_open      = MAX_OPEN,
    comp_name     = COMP_NAME,
    agents        = COMP9_AGENTS,
    long_signals  = LONG_SIGNALS_9,
    short_signals = SHORT_SIGNALS_9,
    pairs_list    = COMP9_PAIRS,
)

app = create_app(engine, PORT, COMP_NAME, MAX_OPEN, comp_password=PASSWORD)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
