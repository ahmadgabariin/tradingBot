import time
from datetime import datetime, timezone
from loguru import logger
from config.settings import settings
from src.data.market_data import MarketData
from src.data.sentiment import SentimentData
from src.data.funding_rate import FundingRate
from src.data.journal import log_trade_open, log_trade_close, get_recent_stats
from src.strategies.indicators import add_indicators, generate_signal
from src.strategies.multi_timeframe import get_mtf_confluence
from src.strategies.market_regime import detect_regime, regime_signal_filter
from src.analysis.ai_analysis import AIAnalyzer
from src.risk.risk_manager import RiskManager
from src.risk.advanced_risk import calculate_atr_position, TrailingStop, should_skip_time, adaptive_threshold
from src.notifications.telegram_bot import TelegramNotifier


class BinanceBot:
    def __init__(self):
        self.market = MarketData()
        self.sentiment = SentimentData()
        self.funding = FundingRate()
        self.risk = RiskManager()
        self.trailing = TrailingStop()
        self.ai = AIAnalyzer() if settings.anthropic_api_key else None
        self.telegram = TelegramNotifier() if settings.telegram_bot_token else None
        self.running = False
        self.mode = settings.bot_mode
        self.last_sentiment = {}
        self.last_sr = {}
        self.last_regime = {}
        self.trade_metadata = {}   # symbol -> {opened_at, journal_id, atr}
        logger.info(f"BinanceBot initialized | mode={self.mode} | budget=${settings.bot_budget}")

    def analyze_pair(self, symbol: str, sentiment_ctx: dict, confidence_threshold: int) -> dict | None:
        # --- Fetch data ---
        df = self.market.get_ohlcv(symbol, "15m", 200)
        if df.empty:
            return None

        df = add_indicators(df)
        order_book = self.market.get_order_book(symbol)

        # --- Base technical signal ---
        signal = generate_signal(df, order_book)

        # --- Market regime ---
        regime = detect_regime(df)
        self.last_regime[symbol] = regime
        signal, regime_notes = regime_signal_filter(signal, regime)
        signal["reasons"].extend(regime_notes)
        signal["regime"] = regime["regime"]
        signal["atr"] = regime["atr"]

        # --- Multi-timeframe confluence ---
        mtf = get_mtf_confluence(self.market, symbol)
        signal["score"] += mtf["score_bonus"]
        signal["mtf"] = mtf["confluence"]
        if mtf["all_aligned"]:
            signal["reasons"].append(f"All 3 timeframes aligned — {mtf['confluence']}")
        elif mtf["confluence"] == "mixed":
            signal["reasons"].append("Conflicting timeframes — signal weakened")

        # --- Funding rate ---
        funding = self.funding.get_funding_rate(symbol)
        signal["score"] += funding["signal_impact"]
        if funding["signal_impact"] != 0:
            signal["reasons"].append(funding["note"])

        # --- Sentiment gates ---
        fg_value = sentiment_ctx.get("fear_greed", {}).get("value", 50)
        news_label = sentiment_ctx.get("news", {}).get("label", "neutral")

        if fg_value <= 20 and signal.get("rsi", 50) > 35:
            logger.info(f"{symbol}: Blocked — extreme fear F&G={fg_value}")
            signal["signal"] = "hold"
            return signal

        if fg_value >= 85 and signal["signal"] == "buy":
            signal["score"] -= 20
            signal["reasons"].append(f"Extreme greed (F&G={fg_value}) — risk elevated")

        if news_label == "bearish" and signal["signal"] == "buy":
            signal["score"] -= 15
            signal["reasons"].append("Bearish news sentiment — buy confidence reduced")
        elif news_label == "bullish" and signal["signal"] == "buy":
            signal["score"] += 10
            signal["reasons"].append("Bullish news confirms buy signal")

        # Recalculate confidence after all adjustments
        signal["confidence"] = min(abs(signal["score"]), 100)

        # --- AI final decision ---
        ai_result = {"recommendation": signal["signal"].upper(), "confidence": signal["confidence"],
                     "reasoning": "AI disabled", "risk_level": "MEDIUM"}

        if self.ai and signal["signal"] != "hold" and signal["confidence"] >= confidence_threshold:
            ai_result = self.ai.analyze_signal(symbol, signal, {
                "change_24h": self.market.get_ticker(symbol).get("percentage", 0),
                "volume_24h": self.market.get_ticker(symbol).get("quoteVolume", 0),
            }, sentiment_ctx)

            signal["ai_recommendation"] = ai_result.get("recommendation", "HOLD")
            signal["ai_confidence"] = ai_result.get("confidence", 0)
            signal["ai_reasoning"] = ai_result.get("reasoning", "")
            signal["risk_level"] = ai_result.get("risk_level", "MEDIUM")

            if ai_result["recommendation"].lower() != signal["signal"]:
                logger.info(f"{symbol}: AI overrides to HOLD")
                signal["signal"] = "hold"

        signal["fear_greed"] = fg_value
        signal["news_sentiment"] = news_label
        signal["overall_sentiment"] = sentiment_ctx.get("overall_sentiment", "neutral")
        signal["_regime"] = regime
        signal["_mtf"] = mtf
        signal["_ai_result"] = ai_result
        return signal

    def execute_signal(self, symbol: str, signal: dict, sentiment_ctx: dict, confidence_threshold: int):
        if signal["signal"] not in ("buy", "sell") or signal["confidence"] < confidence_threshold:
            return

        df = self.market.get_ohlcv(symbol, "15m", 50)
        df = add_indicators(df)
        position = calculate_atr_position(df, self.risk.available_budget)
        price = position["entry_price"]

        # Check trailing stop on open trade
        if symbol in self.risk.open_trades:
            atr = self.trade_metadata.get(symbol, {}).get("atr", price * 0.02)
            trail = self.trailing.update(symbol, price, atr)
            if trail["should_exit"]:
                result = self.risk.close_trade(symbol, price, "trailing_stop")
                if result:
                    self._notify_close(symbol, result, trail["peak"])
                    self.trailing.reset(symbol)
                    opened_at = self.trade_metadata.get(symbol, {}).get("opened_at", datetime.utcnow().isoformat())
                    log_trade_close(
                        self.trade_metadata.get(symbol, {}).get("journal_id", -1),
                        symbol, result["entry"], price, result["pnl"], result["pnl_pct"],
                        "trailing_stop", opened_at
                    )
                    self.trade_metadata.pop(symbol, None)
            return

        can_trade, reason = self.risk.can_trade(position["amount_usd"])
        if not can_trade:
            logger.warning(f"{symbol}: Cannot trade — {reason}")
            return

        if signal["signal"] == "buy":
            self._open_position(symbol, signal, position, sentiment_ctx)

    def _open_position(self, symbol: str, signal: dict, position: dict, sentiment_ctx: dict):
        if self.mode == "paper":
            logger.info(f"[PAPER] BUY {symbol} | ${position['amount_usd']} @ {position['entry_price']} | SL={position['stop_loss']} TP={position['tp2']}")
        else:
            try:
                self.market.exchange.create_order(symbol, "market", "buy", position["quantity"])
            except Exception as e:
                logger.error(f"Order failed: {e}")
                return

        self.risk.open_trade(symbol, position)

        opened_at = datetime.utcnow().isoformat()
        journal_id = log_trade_open(
            symbol, position, signal,
            signal.get("_regime", {}),
            signal.get("_mtf", {}),
            sentiment_ctx,
            signal.get("_ai_result", {}),
            self.mode
        )
        self.trade_metadata[symbol] = {
            "opened_at": opened_at,
            "journal_id": journal_id,
            "atr": signal.get("atr", position["entry_price"] * 0.02),
        }

        if self.telegram:
            sup = signal.get("nearest_support")
            res = signal.get("nearest_resistance")
            msg = (
                f"🟢 {'[PAPER] ' if self.mode == 'paper' else ''}BUY — {symbol}\n\n"
                f"💰 Entry: ${position['entry_price']}\n"
                f"📦 Size: ${position['amount_usd']}\n"
                f"🛑 Stop (ATR): ${position['stop_loss']} (-{position['sl_pct']}%)\n"
                f"🎯 TP1: ${position['tp1']} | TP2: ${position['tp2']} | TP3: ${position['tp3']}\n\n"
                f"📊 Score: {signal['score']} | Confidence: {signal['confidence']}%\n"
                f"📈 Regime: {signal.get('regime','?')} | MTF: {signal.get('mtf','?')}\n"
                f"🔵 Support: {'$'+str(sup) if sup else 'N/A'} | 🔴 Resistance: {'$'+str(res) if res else 'N/A'}\n"
                f"😨 F&G: {signal.get('fear_greed','?')}/100 | News: {signal.get('news_sentiment','?')}\n"
                f"🤖 AI: {signal.get('ai_reasoning', 'N/A')}"
            )
            self.telegram.send(msg)

    def _notify_close(self, symbol: str, result: dict, peak: float = None):
        if not self.telegram:
            return
        emoji = "✅" if result["pnl"] > 0 else "🔴"
        msg = (
            f"{emoji} {'[PAPER] ' if self.mode == 'paper' else ''}Closed — {symbol}\n"
            f"Reason: {result['reason'].replace('_', ' ').title()}\n"
            f"PnL: ${result['pnl']} ({result['pnl_pct']}%)"
        )
        if peak:
            msg += f"\nPeak price: ${peak}"
        self.telegram.send(msg)

    def _check_exits(self, symbol: str):
        trade = self.risk.open_trades.get(symbol)
        if not trade:
            return
        try:
            ticker = self.market.get_ticker(symbol)
            price = ticker.get("last", 0)
            if not price:
                return

            atr = self.trade_metadata.get(symbol, {}).get("atr", price * 0.02)
            trail = self.trailing.update(symbol, price, atr)

            reason = None
            if price <= trade["stop_loss"]:
                reason = "stop_loss"
            elif price >= trade.get("take_profit", float("inf")):
                reason = "take_profit"
            elif trail["should_exit"]:
                reason = "trailing_stop"

            if reason:
                result = self.risk.close_trade(symbol, price, reason)
                if result:
                    self._notify_close(symbol, result, trail.get("peak"))
                    self.trailing.reset(symbol)
                    opened_at = self.trade_metadata.get(symbol, {}).get("opened_at", datetime.utcnow().isoformat())
                    log_trade_close(
                        self.trade_metadata.get(symbol, {}).get("journal_id", -1),
                        symbol, result["entry"], price, result["pnl"], result["pnl_pct"],
                        reason, opened_at
                    )
                    self.trade_metadata.pop(symbol, None)
        except Exception as e:
            logger.error(f"Exit check failed for {symbol}: {e}")

    def run_cycle(self):
        # Time filter
        skip, skip_reason = should_skip_time()
        if skip:
            logger.info(f"Skipping cycle: {skip_reason}")
            return

        # Adaptive threshold based on recent performance
        recent = get_recent_stats(20)
        threshold = adaptive_threshold(recent["consecutive_losses"])
        if recent["consecutive_losses"] >= 2:
            logger.warning(f"Adaptive threshold raised to {threshold} after {recent['consecutive_losses']} consecutive losses")

        # Sentiment (cached, cheap)
        sentiment_ctx = self.sentiment.get_full_context()
        self.last_sentiment = sentiment_ctx

        fg = sentiment_ctx["fear_greed"]
        news = sentiment_ctx["news"]
        logger.info(
            f"Cycle | F&G: {fg['value']}/100 ({fg['label']}) | "
            f"News: {news['label']} | Threshold: {threshold} | "
            f"Consecutive losses: {recent['consecutive_losses']}"
        )

        for symbol in settings.pairs_list:
            try:
                # Always check exits first
                self._check_exits(symbol)

                signal = self.analyze_pair(symbol, sentiment_ctx, threshold)
                if signal:
                    self.last_sr[symbol] = {
                        "support": signal.get("support", []),
                        "resistance": signal.get("resistance", []),
                    }
                    logger.info(
                        f"{symbol}: {signal['signal'].upper()} | "
                        f"score={signal['score']} conf={signal['confidence']}% | "
                        f"regime={signal.get('regime','?')} mtf={signal.get('mtf','?')}"
                    )
                    self.execute_signal(symbol, signal, sentiment_ctx, threshold)

                time.sleep(2)
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")

    def start(self):
        self.running = True
        logger.info(f"BinanceBot started | mode={self.mode} | budget=${settings.bot_budget}")
        if self.telegram:
            self.telegram.send(
                f"🤖 BinanceBot started\n"
                f"Mode: {self.mode.upper()}\nBudget: ${settings.bot_budget}\n"
                f"Pairs: {', '.join(settings.pairs_list)}\n"
                f"Engine: MTF + S&R + Patterns + Regime + Funding + AI"
            )

        while self.running:
            self.run_cycle()
            stats = self.risk.get_stats()
            logger.info(f"Stats: {stats}")
            time.sleep(60)

    def stop(self):
        self.running = False
        logger.info("Bot stopped")
