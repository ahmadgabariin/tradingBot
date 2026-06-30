"""
Competition 11 — 26 agents with upgraded exit techniques. Port 8132.
Chandelier / Parabolic SAR / Supertrend / Keltner Exit per agent.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper_shared.base_server import create_app
from paper11.comp11_engine import Comp11Engine
from paper11.comp11_agents import COMP11_AGENTS, LONG_SIGNALS_11, SHORT_SIGNALS_11, COMP11_PAIRS

PORT      = 8132
MAX_OPEN  = 3
COMP_NAME = "Competition 11 — 15 Agents Upgraded Exits (Chandelier / SAR / Supertrend / Keltner)"
PASSWORD  = "BOT2024"
SAVE_FILE = os.path.join(os.path.dirname(__file__), "comp11_state.json")

engine = Comp11Engine(
    save_file     = SAVE_FILE,
    max_open      = MAX_OPEN,
    comp_name     = COMP_NAME,
    agents        = COMP11_AGENTS,
    long_signals  = LONG_SIGNALS_11,
    short_signals = SHORT_SIGNALS_11,
    pairs_list    = COMP11_PAIRS,
)

app = create_app(engine, PORT, COMP_NAME, MAX_OPEN, comp_password=PASSWORD)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
