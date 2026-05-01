# AI Search Logs DB — by mn-bots
# Stores per-query activity for AI analytics
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from info import DATABASE_URI, DATABASE_NAME

USE_MONGO = bool(DATABASE_URI)

if USE_MONGO:
    import motor.motor_asyncio
    _client = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URI)
    _db     = _client[DATABASE_NAME]
    _col    = _db["ai_search_logs"]
else:
    from database.sql_store import store
    from sqlalchemy import text

    # Auto-create table for SQL backends
    try:
        with store.begin() as _conn:
            _conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ai_search_logs (
                    id         SERIAL PRIMARY KEY,
                    user_id    BIGINT,
                    chat_id    BIGINT,
                    query      TEXT,
                    timestamp  TIMESTAMP DEFAULT NOW(),
                    result_found  BOOLEAN DEFAULT FALSE,
                    clicked       BOOLEAN DEFAULT FALSE,
                    downloaded    BOOLEAN DEFAULT FALSE
                )
            """))
    except Exception as _e:
        logger.warning("ai_search_logs table init: %s", _e)


async def log_search(user_id: int, chat_id: int, query: str, result_found: bool):
    """Insert one search event."""
    doc = {
        "user_id":      user_id,
        "chat_id":      chat_id,
        "query":        query.strip().lower(),
        "timestamp":    datetime.now(timezone.utc),
        "result_found": result_found,
        "clicked":      False,
        "downloaded":   False,
    }
    try:
        if USE_MONGO:
            await _col.insert_one(doc)
        else:
            with store.begin() as conn:
                conn.execute(text("""
                    INSERT INTO ai_search_logs
                        (user_id, chat_id, query, result_found)
                    VALUES (:user_id, :chat_id, :query, :result_found)
                """), {
                    "user_id":      user_id,
                    "chat_id":      chat_id,
                    "query":        doc["query"],
                    "result_found": result_found,
                })
    except Exception as e:
        logger.exception("log_search failed: %s", e)


async def log_click(user_id: int, query: str):
    """Mark the latest search by this user for this query as clicked."""
    try:
        if USE_MONGO:
            await _col.find_one_and_update(
                {"user_id": user_id, "query": query.strip().lower()},
                {"$set": {"clicked": True}},
                sort=[("timestamp", -1)],
            )
        else:
            with store.begin() as conn:
                conn.execute(text("""
                    UPDATE ai_search_logs SET clicked=TRUE
                    WHERE id = (
                        SELECT id FROM ai_search_logs
                        WHERE user_id=:uid AND query=:q
                        ORDER BY id DESC LIMIT 1
                    )
                """), {"uid": user_id, "q": query.strip().lower()})
    except Exception as e:
        logger.exception("log_click failed: %s", e)


async def log_download(user_id: int, query: str):
    """Mark the latest search by this user for this query as downloaded."""
    try:
        if USE_MONGO:
            await _col.find_one_and_update(
                {"user_id": user_id, "query": query.strip().lower()},
                {"$set": {"downloaded": True}},
                sort=[("timestamp", -1)],
            )
        else:
            with store.begin() as conn:
                conn.execute(text("""
                    UPDATE ai_search_logs SET downloaded=TRUE
                    WHERE id = (
                        SELECT id FROM ai_search_logs
                        WHERE user_id=:uid AND query=:q
                        ORDER BY id DESC LIMIT 1
                    )
                """), {"uid": user_id, "q": query.strip().lower()})
    except Exception as e:
        logger.exception("log_download failed: %s", e)


async def get_logs(limit: int = 500) -> list:
    """Return the most recent *limit* log entries as plain dicts."""
    try:
        if USE_MONGO:
            cursor = _col.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
            docs = await cursor.to_list(length=limit)
            for d in docs:
                if isinstance(d.get("timestamp"), datetime):
                    d["timestamp"] = d["timestamp"].isoformat()
            return docs
        else:
            with store.begin() as conn:
                rows = conn.execute(text("""
                    SELECT user_id, chat_id, query, timestamp,
                           result_found, clicked, downloaded
                    FROM ai_search_logs
                    ORDER BY id DESC LIMIT :lim
                """), {"lim": limit}).fetchall()
            return [
                {
                    "user_id":      r[0],
                    "chat_id":      r[1],
                    "query":        r[2],
                    "timestamp":    str(r[3]),
                    "result_found": bool(r[4]),
                    "clicked":      bool(r[5]),
                    "downloaded":   bool(r[6]),
                }
                for r in rows
            ]
    except Exception as e:
        logger.exception("get_logs failed: %s", e)
        return []
