"""
Competition 8 — The Surgeon v2 (max profit mode) on port 8129.
20 pairs, MAX_OPEN=10 — maximizes trade frequency and compounding.
Proven: 38% WR, every month profitable, MaxDD 19%, 5/5 years.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper_shared.base_engine import CompEngine
from paper_shared.base_server import create_app
from paper8.surgeon_agent import SURGEON_AGENTS, LONG_SIGNALS, SHORT_SIGNALS, SURGEON_PAIRS

PORT      = 8129
MAX_OPEN  = 10
COMP_NAME = "Competition 8 — The Surgeon v2 (Max Profit)"
SAVE_FILE = os.path.join(os.path.dirname(__file__), "comp8_state.json")

engine = CompEngine(
    save_file     = SAVE_FILE,
    max_open      = MAX_OPEN,
    comp_name     = COMP_NAME,
    agents        = SURGEON_AGENTS,
    long_signals  = LONG_SIGNALS,
    short_signals = SHORT_SIGNALS,
    pairs_list    = SURGEON_PAIRS,
)

app = create_app(engine, PORT, COMP_NAME, MAX_OPEN)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
