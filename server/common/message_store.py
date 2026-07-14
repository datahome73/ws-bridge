"""只读 SQLite 查询接口（web-ui 用）。仅暴露查询方法，无写操作。
假设 DB 已由 WS 进程创建并初始化（init_db 在 ws-server 端）。
"""
import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger("ws-bridge.common.ms")

_local = threading.local()
DEFAULT_DB_NAME = "messages.db"


def _get_conn(db_path: str) -> sqlite3.Connection:
    """Thread-local connection, read-only URI mode."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return _local.conn


def _ensure_db(data_dir: Path) -> str | None:
    db_path = str(data_dir / DEFAULT_DB_NAME)
    if not Path(db_path).exists():
        logger.warning("Message store DB not found at %s — read-only queries will return empty", db_path)
        return None
    return db_path


def get_messages_since(ts: float, data_dir: Path, limit: int = 500, channel: str | None = None) -> list[dict]:
    """Retrieve messages with ts > given timestamp, optionally filtered by channel."""
    db_path = _ensure_db(data_dir)
    if not db_path:
        return []
    conn = _get_conn(db_path)
    if channel:
        rows = conn.execute(
            "SELECT msg_id, msg_type, from_agent, from_name, content, ts, channel "
            "FROM messages WHERE ts > ? AND channel = ? ORDER BY ts ASC LIMIT ?",
            (ts, channel, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT msg_id, msg_type, from_agent, from_name, content, ts, channel "
            "FROM messages WHERE ts > ? ORDER BY ts ASC LIMIT ?",
            (ts, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_messages_by_channel(channel: str, data_dir: Path, limit: int = 100) -> list[dict]:
    """Retrieve latest messages from a specific channel, newest first."""
    db_path = _ensure_db(data_dir)
    if not db_path:
        return []
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT msg_id, msg_type, from_agent, from_name, content, ts, channel "
        "FROM messages WHERE channel = ? ORDER BY ts DESC LIMIT ?",
        (channel, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def search_messages(
    query: str,
    data_dir: Path,
    limit: int = 50,
    channel: str | None = None,
    sender: str | None = None,
) -> list[dict]:
    """Search messages by content or sender name (LIKE query)."""
    db_path = _ensure_db(data_dir)
    if not db_path:
        return []
    conn = _get_conn(db_path)
    try:
        conditions = ["(content LIKE ? OR from_name LIKE ?)"]
        params = [f"%{query}%", f"%{query}%"]
        if channel:
            conditions.append("channel = ?")
            params.append(channel)
        if sender:
            conditions.append("from_name LIKE ?")
            params.append(f"%{sender}%")
        where = " AND ".join(conditions)
        cur = conn.execute(
            f"SELECT msg_id, from_name, content, ts, channel "
            f"FROM messages WHERE {where} ORDER BY ts DESC LIMIT ?",
            params + [limit],
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def get_messages_by_channel_pattern(
    pattern: str, data_dir: Path, limit: int = 50, since: float | None = None
) -> list[dict]:
    """Retrieve messages from channels matching a SQL LIKE pattern."""
    db_path = _ensure_db(data_dir)
    if not db_path:
        return []
    conn = _get_conn(db_path)
    try:
        query = (
            "SELECT msg_id, msg_type, from_agent, from_name, content, ts, channel "
            "FROM messages WHERE channel LIKE ?"
        )
        params: list = [pattern]
        if since is not None:
            query += " AND ts > ?"
            params.append(since)
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_messages_by_time_range(
    start_ts: float, end_ts: float, data_dir: Path
) -> list[dict]:
    """Retrieve all messages within a time range, ordered by timestamp ascending."""
    db_path = _ensure_db(data_dir)
    if not db_path:
        return []
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT msg_id, msg_type, from_agent, from_name, content, ts, channel "
            "FROM messages WHERE ts >= ? AND ts <= ? ORDER BY ts ASC",
            (start_ts, end_ts),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
