"""
Competition 7 — 5 Smart Agents on port 8128.
Strategies: RSI Oversold, Regime-Adaptive, BB Squeeze, Market Structure, EMA Pullback.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper_shared.base_engine import CompEngine
from paper_shared.base_server import create_app
from paper7.smart_agents import SMART_AGENTS, LONG_SIGNALS, SHORT_SIGNALS, SMART_PAIRS

PORT      = 8128
MAX_OPEN  = 3
COMP_NAME = "Competition 7 — Smart Agents"
SAVE_FILE = os.path.join(os.path.dirname(__file__), "comp7_state.json")

engine = CompEngine(
    save_file    = SAVE_FILE,
    max_open     = MAX_OPEN,
    comp_name    = COMP_NAME,
    agents       = SMART_AGENTS,
    long_signals = LONG_SIGNALS,
    short_signals= SHORT_SIGNALS,
    pairs_list   = SMART_PAIRS,
)

app = create_app(engine, PORT, COMP_NAME, MAX_OPEN, comp_password="BOT2024")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
