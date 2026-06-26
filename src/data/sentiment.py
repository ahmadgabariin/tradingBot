import requests
import feedparser
from textblob import TextBlob
from loguru import logger
from datetime import datetime, timezone
import time


class SentimentData:
    def __init__(self):
        self._fg_cache = {"value": None, "ts": 0}
        self._news_cache = {"data": [], "ts": 0}
        self.CACHE_TTL = 300  # 5 minutes

    def get_fear_greed(self) -> dict:
        now = time.time()
        if self._fg_cache["value"] and now - self._fg_cache["ts"] < self.CACHE_TTL:
            return self._fg_cache["value"]

        try:
            resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
            data = resp.json()["data"][0]
            result = {
                "value": int(data["value"]),
                "label": data["value_classification"],
                "sentiment": self._fg_to_sentiment(int(data["value"])),
            }
            self._fg_cache = {"value": result, "ts": now}
            return result
        except Exception as e:
            logger.warning(f"Fear & Greed fetch failed: {e}")
            return {"value": 50, "label": "Neutral", "sentiment": "neutral"}

    def _fg_to_sentiment(self, value: int) -> str:
        if value <= 25:
            return "extreme_fear"
        elif value <= 45:
            return "fear"
        elif value <= 55:
            return "neutral"
        elif value <= 75:
            return "greed"
        else:
            return "extreme_greed"

    def get_crypto_news(self, limit: int = 15) -> list[dict]:
        now = time.time()
        if self._news_cache["data"] and now - self._news_cache["ts"] < self.CACHE_TTL:
            return self._news_cache["data"]

        feeds = [
            "https://cointelegraph.com/rss",
            "https://coindesk.com/arc/outboundfeeds/rss/",
            "https://cryptonews.com/news/feed/",
        ]

        articles = []
        for url in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    text = f"{title}. {summary}"
                    blob = TextBlob(text)
                    polarity = blob.sentiment.polarity

                    articles.append({
                        "title": title,
                        "source": feed.feed.get("title", url),
                        "polarity": round(polarity, 3),
                        "sentiment": "positive" if polarity > 0.1 else "negative" if polarity < -0.1 else "neutral",
                        "published": entry.get("published", ""),
                    })
            except Exception as e:
                logger.warning(f"News feed failed ({url}): {e}")

        articles = articles[:limit]
        self._news_cache = {"data": articles, "ts": now}
        return articles

    def get_news_summary(self) -> dict:
        articles = self.get_crypto_news()
        if not articles:
            return {"score": 0, "label": "neutral", "article_count": 0, "positive": 0, "negative": 0, "neutral": 0}

        scores = [a["polarity"] for a in articles]
        avg = sum(scores) / len(scores)
        positive = sum(1 for a in articles if a["sentiment"] == "positive")
        negative = sum(1 for a in articles if a["sentiment"] == "negative")
        neutral = len(articles) - positive - negative

        return {
            "score": round(avg, 3),
            "label": "bullish" if avg > 0.05 else "bearish" if avg < -0.05 else "neutral",
            "article_count": len(articles),
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "headlines": [a["title"] for a in articles[:5]],
        }

    def get_full_context(self) -> dict:
        fg = self.get_fear_greed()
        news = self.get_news_summary()

        combined_score = (fg["value"] / 100) * 0.4 + (news["score"] + 1) / 2 * 0.6

        if combined_score > 0.6:
            overall = "bullish"
        elif combined_score < 0.4:
            overall = "bearish"
        else:
            overall = "neutral"

        return {
            "fear_greed": fg,
            "news": news,
            "overall_sentiment": overall,
            "combined_score": round(combined_score, 3),
        }
