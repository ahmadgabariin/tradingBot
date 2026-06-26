import json
import anthropic
from loguru import logger
from config.settings import settings


class AIAnalyzer:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def analyze_signal(self, symbol: str, signal_data: dict, market_context: dict, sentiment: dict = None) -> dict:
        fg = sentiment.get("fear_greed", {}) if sentiment else {}
        news = sentiment.get("news", {}) if sentiment else {}

        headlines = "\n".join(f"  - {h}" for h in news.get("headlines", [])[:5]) or "  - No recent headlines"

        prompt = f"""You are an expert crypto trading analyst. Analyze this full market picture and give a final trade recommendation.

== SYMBOL ==
{symbol} @ ${signal_data.get('price', 0)}

== TECHNICAL SIGNALS ==
Signal: {signal_data.get('signal', 'hold').upper()} (confidence {signal_data.get('confidence', 0)}/100)
RSI: {signal_data.get('rsi', 0)}
MACD diff: {signal_data.get('macd_diff', 0)}
Reasons:
{chr(10).join(f'  - {r}' for r in signal_data.get('reasons', []))}

== MARKET DATA ==
24h Change: {market_context.get('change_24h', 0):.2f}%
24h Volume: ${market_context.get('volume_24h', 0):,.0f}

== SENTIMENT ==
Fear & Greed Index: {fg.get('value', 50)}/100 — {fg.get('label', 'Neutral')} ({fg.get('sentiment', 'neutral')})
News Sentiment: {news.get('label', 'neutral')} (score {news.get('score', 0)}, {news.get('article_count', 0)} articles)
  Positive: {news.get('positive', 0)} | Negative: {news.get('negative', 0)} | Neutral: {news.get('neutral', 0)}
Top Headlines:
{headlines}

Overall Market Mood: {sentiment.get('overall_sentiment', 'neutral') if sentiment else 'unknown'}

== TASK ==
Combine ALL of the above. If technicals say BUY but sentiment is extreme fear + negative news, downgrade or reject.
If technicals say BUY and sentiment confirms bullish — high confidence.
Be strict. Only recommend BUY if conviction is strong. Default to HOLD when uncertain.

Respond ONLY in this exact JSON format:
{{
  "recommendation": "BUY" | "SELL" | "HOLD",
  "confidence": 0-100,
  "reasoning": "2 sentence max explanation",
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "sentiment_impact": "positive" | "negative" | "neutral",
  "entry_note": "one key thing to watch"
}}"""

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=350,
                messages=[{"role": "user", "content": prompt}]
            )

            text = response.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())

        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return {
                "recommendation": signal_data.get("signal", "hold").upper(),
                "confidence": signal_data.get("confidence", 0),
                "reasoning": "AI analysis unavailable, using technical signals only.",
                "risk_level": "MEDIUM",
                "sentiment_impact": "neutral",
                "entry_note": "Monitor price action carefully.",
            }
