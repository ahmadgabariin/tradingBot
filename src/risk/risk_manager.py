from loguru import logger
from config.settings import settings


class RiskManager:
    def __init__(self):
        self.budget = settings.bot_budget
        self.used_budget = 0.0
        self.open_trades = {}
        self.trade_history = []

    @property
    def available_budget(self) -> float:
        return self.budget - self.used_budget

    def can_trade(self, amount: float) -> tuple[bool, str]:
        if settings.bot_mode == "paper":
            return True, "Paper trading mode"

        if amount > settings.max_trade_amount:
            return False, f"Amount ${amount} exceeds max trade size ${settings.max_trade_amount}"

        if amount > self.available_budget:
            return False, f"Insufficient budget. Available: ${self.available_budget:.2f}"

        if len(self.open_trades) >= 3:
            return False, "Max concurrent trades (3) reached"

        return True, "OK"

    def calculate_position(self, price: float) -> dict:
        trade_amount = min(settings.max_trade_amount, self.available_budget)
        quantity = trade_amount / price
        stop_loss = price * (1 - settings.stop_loss_percent / 100)
        take_profit = price * (1 + settings.take_profit_percent / 100)

        return {
            "amount_usd": round(trade_amount, 2),
            "quantity": round(quantity, 6),
            "entry_price": price,
            "stop_loss": round(stop_loss, 4),
            "take_profit": round(take_profit, 4),
            "risk_usd": round(trade_amount * settings.stop_loss_percent / 100, 2),
            "reward_usd": round(trade_amount * settings.take_profit_percent / 100, 2),
        }

    def open_trade(self, symbol: str, position: dict):
        self.open_trades[symbol] = position
        if settings.bot_mode != "paper":
            self.used_budget += position["amount_usd"]
        logger.info(f"Trade opened: {symbol} | ${position['amount_usd']} | SL: {position['stop_loss']} | TP: {position['take_profit']}")

    def close_trade(self, symbol: str, exit_price: float, reason: str):
        if symbol not in self.open_trades:
            return None

        trade = self.open_trades.pop(symbol)
        pnl = (exit_price - trade["entry_price"]) * trade["quantity"]
        pnl_pct = ((exit_price - trade["entry_price"]) / trade["entry_price"]) * 100

        result = {
            "symbol": symbol,
            "entry": trade["entry_price"],
            "exit": exit_price,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "reason": reason,
        }

        self.trade_history.append(result)
        if settings.bot_mode != "paper":
            self.used_budget = max(0, self.used_budget - trade["amount_usd"])

        logger.info(f"Trade closed: {symbol} | PnL: ${pnl:.2f} ({pnl_pct:.2f}%) | {reason}")
        return result

    def get_stats(self) -> dict:
        if not self.trade_history:
            return {"total_trades": 0, "win_rate": 0, "total_pnl": 0}

        wins = [t for t in self.trade_history if t["pnl"] > 0]
        total_pnl = sum(t["pnl"] for t in self.trade_history)

        return {
            "total_trades": len(self.trade_history),
            "wins": len(wins),
            "losses": len(self.trade_history) - len(wins),
            "win_rate": round(len(wins) / len(self.trade_history) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "open_trades": len(self.open_trades),
            "available_budget": round(self.available_budget, 2),
        }
