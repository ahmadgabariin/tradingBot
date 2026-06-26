import requests
from loguru import logger
from config.settings import settings


class TelegramNotifier:
    def __init__(self):
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send(self, message: str) -> bool:
        try:
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False
