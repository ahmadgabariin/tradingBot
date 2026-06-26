from pydantic_settings import BaseSettings
from typing import List
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Binance
    binance_api_key: str = ""
    binance_secret_key: str = ""
    use_testnet: bool = True

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Claude AI
    anthropic_api_key: str = ""

    # Bot
    bot_mode: str = "paper"         # paper | limited | full
    bot_budget: float = 100.0
    max_trade_percent: float = 10.0
    stop_loss_percent: float = 2.0
    take_profit_percent: float = 4.0
    trading_pairs: str = "BTC/USDT,ETH/USDT,BNB/USDT"

    # Dashboard
    dashboard_port: int = 8000
    dashboard_host: str = "0.0.0.0"

    @property
    def pairs_list(self) -> List[str]:
        return [p.strip() for p in self.trading_pairs.split(",")]

    @property
    def max_trade_amount(self) -> float:
        return self.bot_budget * (self.max_trade_percent / 100)

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
