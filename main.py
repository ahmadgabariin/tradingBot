import sys
import threading
import uvicorn
from loguru import logger
from src.bot.trader import BinanceBot
from src.dashboard.api import app, set_bot
from config.settings import settings

logger.add("logs/bot.log", rotation="1 day", retention="7 days", level="INFO")


def run_dashboard():
    uvicorn.run(app, host=settings.dashboard_host, port=settings.dashboard_port, log_level="warning")


def main():
    logger.info("Starting BinanceBot...")
    bot = BinanceBot()
    set_bot(bot)

    dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
    dashboard_thread.start()
    logger.info(f"Dashboard running at http://localhost:{settings.dashboard_port}")

    try:
        bot.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        bot.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
