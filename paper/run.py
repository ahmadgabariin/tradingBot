"""
Run paper trader + dashboard together.
Usage: python paper/run.py
"""
import threading
import uvicorn
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper.engine import run_once, init_db, get_stats, PAIRS, STRATEGY_PARAMS
import paper.engine as engine
from paper.dashboard import app
from loguru import logger
import time

logger.add("paper/paper.log", rotation="1 day", level="INFO")


def run_dashboard():
    uvicorn.run(app, host="0.0.0.0", port=9090, log_level="warning")


def run_engine():
    init_db()
    logger.info(f"Paper engine started | pairs={PAIRS} | $1000/pair fake balance")
    cycle = 0
    while True:
        cycle += 1
        logger.info(f"── Cycle {cycle} | active={list(engine.ACTIVE_STRATEGIES)}")
        run_once()
        stats = get_stats()
        for skey, sdata in stats.items():
            logger.info(f"  [{skey}] trades={sdata.get('total',0)} WR={sdata.get('win_rate',0)}% PnL=${sdata.get('total_pnl',0):.2f}")
        # Sleep based on shortest active strategy timeframe
        tfs = [STRATEGY_PARAMS[s]["tf"] for s in engine.ACTIVE_STRATEGIES if s in STRATEGY_PARAMS]
        tf = min(tfs, key=lambda t: {"5m":0,"15m":1,"1h":2,"4h":3}.get(t,99)) if tfs else "1h"
        sleep_secs = 60 if tf == "5m" else 300 if tf == "15m" else 900 if tf == "1h" else 1800
        logger.info(f"  Next check in {sleep_secs//60}m (fastest tf={tf})")
        time.sleep(sleep_secs)


if __name__ == "__main__":
    print("\n" + "="*50)
    print("  BinanceBot Paper Trader")
    print("  Live prices: BTC · ETH · SOL")
    print("  Fake balance: $1000 per pair per strategy")
    print("  Dashboard: http://localhost:9090")
    print("="*50 + "\n")

    t = threading.Thread(target=run_engine, daemon=True)
    t.start()

    run_dashboard()
