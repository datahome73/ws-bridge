"""SQLite-based Task persistence for ws-im server.

Stores Task instances (from R38 Task State Machine) with full lifecycle support.
Separate from message_store.py — tasks are metadata, not messages.
"""
import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import shared.protocol as p

logger = logging.getLogger("ws-im")

DEFAULT_DB_NAME = "tasks.db"

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
    """Create tasks table if not exists."""
    db_path = str(data_dir / DEFAULT_DB_NAME)
    conn = _get_conn(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id              TEXT PRIMARY KEY,
            context_id      TEXT NOT NULL,
            name            TEXT NOT NULL,
            state           TEXT NOT NULL DEFAULT 'pending',
            assigned_role   TEXT,
            output_refs     TEXT NOT NULL DEFAULT '[]',
            reject_count    INTEGER NOT NULL DEFAULT 0,
            created_by      TEXT,
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_context ON tasks(context_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state)")
    conn.commit()
    logger.info("Task store initialised at %s", db_path)


def create_task(
    context_id: str,
    name: str,
    assigned_role: str | None = None,
    created_by: str | None = None,
    data_dir: Path | None = None,
) -> dict:
    """Create a new task in SUBMITTED state. Returns full task dict."""
    task_id = str(uuid.uuid4())
    now = time.time()
    db_path = str(data_dir / DEFAULT_DB_NAME) if data_dir else ""
    conn = _get_conn(db_path)
    conn.execute(
        "INSERT INTO tasks (id, context_id, name, state, assigned_role, output_refs, reject_count, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, context_id, name, p.TaskState.SUBMITTED.value, assigned_role or "",
         "[]", 0, created_by or "", now, now),
    )
    conn.commit()
    return _row_to_dict(conn, task_id)


def get_task(task_id: str, data_dir: Path | None = None) -> dict | None:
    """Get a single task by ID."""
    db_path = str(data_dir / DEFAULT_DB_NAME) if data_dir else ""
    conn = _get_conn(db_path)
    return _row_to_dict(conn, task_id)


def update_state(
    task_id: str,
    new_state: str,
    data_dir: Path | None = None,
) -> dict | None:
    """Update task state and updated_at. Returns updated task or None."""
    db_path = str(data_dir / DEFAULT_DB_NAME) if data_dir else ""
    conn = _get_conn(db_path)
    now = time.time()
    conn.execute(
        "UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?",
        (new_state, now, task_id),
    )
    conn.commit()
    if conn.total_changes == 0:
        return None
    return _row_to_dict(conn, task_id)


def increment_reject_count(
    task_id: str,
    data_dir: Path | None = None,
) -> dict | None:
    """Increment reject_count by 1. Returns updated task or None."""
    db_path = str(data_dir / DEFAULT_DB_NAME) if data_dir else ""
    conn = _get_conn(db_path)
    now = time.time()
    conn.execute(
        "UPDATE tasks SET reject_count = reject_count + 1, updated_at = ? WHERE id = ?",
        (now, task_id),
    )
    conn.commit()
    return _row_to_dict(conn, task_id)


def add_output_ref(
    task_id: str,
    ref: str,
    data_dir: Path | None = None,
) -> dict | None:
    """Append an output reference to a task. Returns updated task or None."""
    db_path = str(data_dir / DEFAULT_DB_NAME) if data_dir else ""
    conn = _get_conn(db_path)
    row = conn.execute("SELECT output_refs FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        return None
    refs = json.loads(row["output_refs"])
    if ref not in refs:
        refs.append(ref)
    now = time.time()
    conn.execute(
        "UPDATE tasks SET output_refs = ?, updated_at = ? WHERE id = ?",
        (json.dumps(refs), now, task_id),
    )
    conn.commit()
    return _row_to_dict(conn, task_id)


def list_tasks_by_context(
    context_id: str,
    data_dir: Path | None = None,
) -> list[dict]:
    """List all tasks for a given context/round, ordered by created_at."""
    db_path = str(data_dir / DEFAULT_DB_NAME) if data_dir else ""
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT * FROM tasks WHERE context_id = ? ORDER BY created_at ASC",
        (context_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_all_tasks(
    data_dir: Path | None = None,
    limit: int = 50,
) -> list[dict]:
    """List recent tasks across all contexts."""
    db_path = str(data_dir / DEFAULT_DB_NAME) if data_dir else ""
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def _row_to_dict(conn: sqlite3.Connection, task_id: str) -> dict | None:
    """Fetch a single row and convert to dict with parsed output_refs."""
    row = conn.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["output_refs"] = json.loads(d.get("output_refs", "[]"))
    except (json.JSONDecodeError, TypeError):
        d["output_refs"] = []
    return d
