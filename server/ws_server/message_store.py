"""SQLite-based message persistence for ws-im server.

Stores all broadcast messages for offline catchup.
Auto-cleanup old messages (7-day TTL, capped at 100K rows).
"""
import logging
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger("ws-im")

# Defaults
DEFAULT_DB_NAME = "messages.db"
MAX_AGE_DAYS = 7
MAX_COUNT = 100_000

_local = threading.local()


def _get_conn(db_path: str) -> sqlite3.Connection:
    """Get thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(db_path)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
    return _local.conn


def init_db(data_dir: Path) -> None:
    """Create tables and indexes if they don't exist."""
    db_path = str(data_dir / DEFAULT_DB_NAME)
    conn = _get_conn(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id      TEXT UNIQUE,
            msg_type    TEXT NOT NULL DEFAULT 'broadcast',
            from_agent  TEXT NOT NULL,
            from_name   TEXT,
            content     TEXT NOT NULL,
            ts          REAL NOT NULL,
            channel     TEXT NOT NULL DEFAULT 'lobby',
            created_at  DATETIME DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_msg_id ON messages(msg_id)")
    # Migrate: add channel column if missing (R4 workspace system)
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN channel TEXT NOT NULL DEFAULT 'lobby'")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel)")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    logger.info("Message store initialised at %s", db_path)


def save_message(
    msg_id: str,
    msg_type: str,
    from_agent: str,
    from_name: str,
    content: str,
    ts: float,
    data_dir: Path,
    channel: str = "lobby",
) -> None:
    """Insert a single message into the store.

    R41 B: Uses INSERT OR IGNORE on msg_id for dedup.
    """
    db_path = str(data_dir / DEFAULT_DB_NAME)
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO messages (msg_id, msg_type, from_agent, from_name, content, ts, channel) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (msg_id, msg_type, from_agent, from_name or "", content, ts, channel),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Failed to save message: %s", exc)


def get_messages_since(ts: float, data_dir: Path, limit: int = 500, channel: str | None = None) -> list[dict]:
    """Retrieve messages with ts > given timestamp, optionally filtered by channel.
    
    When channel is None, returns messages from all channels (offline catchup for lobby).
    When channel is set, returns only messages from that channel.
    """
    db_path = str(data_dir / DEFAULT_DB_NAME)
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
    db_path = str(data_dir / DEFAULT_DB_NAME)
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT msg_id, msg_type, from_agent, from_name, content, ts, channel "
        "FROM messages WHERE channel = ? ORDER BY ts DESC LIMIT ?",
        (channel, limit),
    ).fetchall()
    return [dict(r) for r in rows]



def clear_messages_by_channel(channel: str, data_dir: Path):
    """Delete all messages for a given channel (used on workspace cleanup)."""
    db_path = str(data_dir / DEFAULT_DB_NAME)
    if not Path(db_path).exists():
        return
    conn = _get_conn(db_path)
    conn.execute("DELETE FROM messages WHERE channel = ?", (channel,))
    conn.commit()


def is_duplicate(channel: str, content: str, window_sec: float, data_dir: Path) -> bool:
    """R129 B-6: 检查同 channel 最近 window_sec 秒内是否有相同 content 的消息。"""
    db_path = str(data_dir / DEFAULT_DB_NAME)
    if not Path(db_path).exists():
        return False
    cutoff = time.time() - window_sec
    conn = _get_conn(db_path)
    try:
        cur = conn.execute(
            "SELECT 1 FROM messages WHERE channel = ? AND content = ? AND ts > ? LIMIT 1",
            (channel, content, cutoff),
        )
        return cur.fetchone() is not None
    except Exception:
        return False


def clean_old_messages(
    data_dir: Path,
    max_age_days: int = MAX_AGE_DAYS,
    max_count: int = MAX_COUNT,
) -> int:
    """Delete expired messages and cap total rows. Returns total removed."""
    db_path = str(data_dir / DEFAULT_DB_NAME)
    conn = _get_conn(db_path)
    cutoff = time.time() - max_age_days * 86400
    removed = conn.execute("DELETE FROM messages WHERE ts < ?", (cutoff,)).rowcount
    # Also cap total count (delete oldest beyond max_count)
    conn.execute(
        "DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY ts DESC LIMIT ?)",
        (max_count,),
    )
    conn.commit()
    if removed:
        logger.info("Cleaned %d old messages", removed)
    return removed
