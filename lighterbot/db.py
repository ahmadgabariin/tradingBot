"""Persistent trade storage — MongoDB, not a live re-fetch from Lighter.

Each real closed trade gets validated and saved here EXACTLY ONCE, the same
moment engine.sync_realized_pnl() first sees it (that function already has
the "have I counted this trade before?" dedup logic via counted_trade_keys —
this reuses that same trigger point rather than re-deriving it). The Trade
History table and daily PnL are then served from here with real pagination
(only the requested page is ever queried), instead of re-fetching and
re-computing from Lighter's API on every dashboard poll.
"""
import os
from motor.motor_asyncio import AsyncIOMotorClient

_client = None
_db = None


def _get_db():
    global _client, _db
    if _db is None:
        mongo_url = os.environ.get("LIGHTERBOT_MONGO_URL", "mongodb://localhost:27017")
        _client = AsyncIOMotorClient(mongo_url)
        _db = _client["lighterbot"]
    return _db


async def ensure_indexes():
    db = _get_db()
    # trade_key is the same f"{symbol}|{opened_at}|{closed_at}" identity
    # already used by engine.py's counted_trade_keys — unique index makes a
    # duplicate save_trade() call for the same real trade a harmless no-op.
    await db.trades.create_index("trade_key", unique=True)
    await db.trades.create_index([("closed_at", -1)])
    await db.trades.create_index([("agent", 1), ("closed_at", -1)])
    await db.daily_pnl.create_index([("agent", 1), ("date", 1)], unique=True)


async def save_trade(trade: dict, trade_key: str):
    """Idempotent insert — if this trade_key was already saved (e.g. a
    restart re-processing the same recent window), this is a silent no-op
    rather than a duplicate row or a crash."""
    db = _get_db()
    doc = {**trade, "trade_key": trade_key}
    try:
        await db.trades.insert_one(doc)
    except Exception as e:
        if "duplicate key" in str(e).lower() or "E11000" in str(e):
            return  # already saved — expected on reprocessing, not an error
        raise

    date_str = _date_str(trade["closed_at"])
    await db.daily_pnl.update_one(
        {"agent": trade["agent"], "date": date_str},
        {"$inc": {"pnl": trade["pnl"], "trade_count": 1,
                  "wins": 1 if trade["result"] == "WIN" else 0,
                  "losses": 1 if trade["result"] == "LOSS" else 0}},
        upsert=True,
    )


def _date_str(unix_ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d")


async def get_trades_page(page: int = 0, per_page: int = 25, agent: str = None, cutoff: float = 0):
    """Real pagination — only fetches the requested page from MongoDB, not
    the whole history. Returns (trades, total_count)."""
    db = _get_db()
    query = {"closed_at": {"$gt": cutoff}}
    if agent:
        query["agent"] = agent
    total = await db.trades.count_documents(query)
    cursor = (db.trades.find(query, {"_id": 0})
              .sort("closed_at", -1)
              .skip(page * per_page)
              .limit(per_page))
    trades = await cursor.to_list(length=per_page)
    return trades, total


async def get_agent_trades(agent: str, cutoff: float = 0, limit: int = 5000):
    """All of one agent's trades (for equity-curve / win-rate stats), sorted
    oldest-first. A single indexed DB query — fast even as history grows,
    unlike the old approach of re-paging through Lighter's live API."""
    db = _get_db()
    cursor = (db.trades.find({"agent": agent, "closed_at": {"$gt": cutoff}}, {"_id": 0})
              .sort("closed_at", 1)
              .limit(limit))
    return await cursor.to_list(length=limit)


async def get_daily_pnl(agent: str = None, cutoff: float = 0):
    """Precomputed per-day aggregates — no re-summing trades on every call."""
    db = _get_db()
    query = {}
    if agent:
        query["agent"] = agent
    if cutoff:
        cutoff_date = _date_str(cutoff)
        query["date"] = {"$gte": cutoff_date}
    cursor = db.daily_pnl.find(query, {"_id": 0}).sort("date", 1)
    return await cursor.to_list(length=None)


async def reset_agent_daily_pnl(agent: str):
    """Used by /reset-agent-stats — clears this agent's precomputed daily
    PnL aggregates so they start fresh from the reset point, consistent with
    the realized_pnl running total also being zeroed at the same moment."""
    db = _get_db()
    await db.daily_pnl.delete_many({"agent": agent})
