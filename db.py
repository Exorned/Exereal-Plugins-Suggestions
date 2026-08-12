"""
Работа с базой данных (SQLite) для хранения идей плагинов exteraGram.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "ideas.db"


def init_db() -> None:
    """Создаёт таблицу, если её ещё нет."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def add_idea(user_id: int, username: str | None, full_name: str, text: str) -> int:
    """Сохраняет новую идею и возвращает её id."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO ideas (user_id, username, full_name, text, status, created_at)
            VALUES (?, ?, ?, ?, 'new', ?)
            """,
            (user_id, username, full_name, text, datetime.utcnow().isoformat()),
        )
        conn.commit()
        return cur.lastrowid


def get_user_ideas(user_id: int, limit: int = 20) -> list[sqlite3.Row]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM ideas WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return cur.fetchall()


def get_idea(idea_id: int) -> sqlite3.Row | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,))
        return cur.fetchone()


def set_status(idea_id: int, status: str) -> bool:
    """status: new / approved / rejected"""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE ideas SET status = ? WHERE id = ?", (status, idea_id)
        )
        conn.commit()
        return cur.rowcount > 0


def get_ideas_by_status(status: str, limit: int = 30) -> list[sqlite3.Row]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM ideas WHERE status = ? ORDER BY id ASC LIMIT ?",
            (status, limit),
        )
        return cur.fetchall()


def get_stats() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            SELECT status, COUNT(*) FROM ideas GROUP BY status
            """
        )
        rows = dict(cur.fetchall())
        total = sum(rows.values())
        return {
            "total": total,
            "new": rows.get("new", 0),
            "approved": rows.get("approved", 0),
            "rejected": rows.get("rejected", 0),
        }
