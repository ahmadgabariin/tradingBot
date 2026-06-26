import sqlite3
import json
from datetime import datetime
from loguru import logger

DB_PATH = "logs/trades.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            action TEXT,
            price REAL,
            amount_usd REAL,
            quantity REAL,
            stop_loss REAL,
            take_profit REAL,
            signal_score INTEGER,
            confidence INTEGER,
            regime TEXT,
            mtf_confluence TEXT,
            fear_greed INTEGER,
            news_sentiment TEXT,
            patterns TEXT,
            ai_recommendation TEXT,
            ai_reasoning TEXT,
            mode TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS closed_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            open_id INTEGER,
            symbol TEXT,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            pnl_pct REAL,
            reason TEXT,
            duration_minutes INTEGER,
            opened_at TEXT,
            closed_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_trade_open(symbol: str, position: dict, signal: dict, regime: dict, mtf: dict, sentiment: dict, ai_result: dict, mode: str) -> int:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO trades (timestamp, symbol, action, price, amount_usd, quantity,
                stop_loss, take_profit, signal_score, confidence, regime, mtf_confluence,
                fear_greed, news_sentiment, patterns, ai_recommendation, ai_reasoning, mode)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.utcnow().isoformat(),
            symbol, "BUY",
            position.get("entry_price", 0),
            position.get("amount_usd", 0),
            position.get("quantity", 0),
            position.get("stop_loss", 0),
            position.get("take_profit", 0),
            signal.get("score", 0),
            signal.get("confidence", 0),
            regime.get("regime", "unknown"),
            mtf.get("confluence", "unknown"),
            sentiment.get("fear_greed", {}).get("value", 0),
            sentiment.get("news", {}).get("label", "neutral"),
            json.dumps(signal.get("reasons", [])[:5]),
            ai_result.get("recommendation", ""),
            ai_result.get("reasoning", ""),
            mode,
        ))
        trade_id = c.lastrowid
        conn.commit()
        conn.close()
        return trade_id
    except Exception as e:
        logger.error(f"Journal log_open failed: {e}")
        return -1


def log_trade_close(open_id: int, symbol: str, entry: float, exit_price: float, pnl: float, pnl_pct: float, reason: str, opened_at: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        opened_dt = datetime.fromisoformat(opened_at) if opened_at else datetime.utcnow()
        closed_dt = datetime.utcnow()
        duration = int((closed_dt - opened_dt).total_seconds() / 60)
        c.execute("""
            INSERT INTO closed_trades (open_id, symbol, entry_price, exit_price, pnl, pnl_pct,
                reason, duration_minutes, opened_at, closed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (open_id, symbol, entry, exit_price, pnl, pnl_pct, reason, duration,
              opened_at, closed_dt.isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Journal log_close failed: {e}")


def get_recent_stats(limit: int = 20) -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT pnl, pnl_pct, reason FROM closed_trades ORDER BY id DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        if not rows:
            return {"recent_win_rate": 50, "recent_pnl": 0, "consecutive_losses": 0}
        wins = sum(1 for r in rows if r[0] > 0)
        total_pnl = sum(r[0] for r in rows)
        consecutive_losses = 0
        for row in rows:
            if row[0] < 0:
                consecutive_losses += 1
            else:
                break
        return {
            "recent_win_rate": round(wins / len(rows) * 100, 1),
            "recent_pnl": round(total_pnl, 2),
            "consecutive_losses": consecutive_losses,
            "sample_size": len(rows),
        }
    except Exception as e:
        logger.error(f"Journal get_stats failed: {e}")
        return {"recent_win_rate": 50, "recent_pnl": 0, "consecutive_losses": 0}


init_db()
