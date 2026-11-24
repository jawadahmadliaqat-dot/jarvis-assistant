"""Persistent memory: SQLite facts, conversation history, reminders.

All memory lives under the configured data dir (default ~/.jarvis).
Nothing is sent anywhere — the LLM only ever receives facts the user
explicitly asked Jarvis to remember, plus recent conversation turns.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


class Memory:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "memory.db"
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS facts(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reminders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                due_ts REAL NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_ts REAL NOT NULL
            );
            """
        )
        self._conn.commit()
        # Migration: track when a reminder was completed (for summaries).
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(reminders)")]
        if "done_ts" not in cols:
            self._conn.execute("ALTER TABLE reminders ADD COLUMN done_ts REAL")
            self._conn.commit()

    # -- facts ----------------------------------------------------------
    def remember_fact(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO facts(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (key.strip().lower(), value.strip(), time.time()),
        )
        self._conn.commit()

    def forget_fact(self, key: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM facts WHERE key=?", (key.strip().lower(),)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_fact(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM facts WHERE key=?", (key.strip().lower(),)
        ).fetchone()
        return row["value"] if row else None

    def all_facts(self) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT key, value FROM facts ORDER BY key"
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    def facts_summary(self) -> str:
        facts = self.all_facts()
        if not facts:
            return ""
        return "\n".join(f"- {k}: {v}" for k, v in facts.items())

    # -- conversation history -------------------------------------------
    def add_message(self, role: str, content: str) -> None:
        self._conn.execute(
            "INSERT INTO conversations(role, content, ts) VALUES(?,?,?)",
            (role, content, time.time()),
        )
        self._conn.commit()

    def recent_history(self, limit: int = 20) -> list[dict[str, str]]:
        rows = self._conn.execute(
            "SELECT role, content FROM conversations "
            "ORDER BY id DESC LIMIT ?",
            (limit * 2,),
        ).fetchall()
        rows = list(reversed(rows))
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def clear_history(self) -> None:
        self._conn.execute("DELETE FROM conversations")
        self._conn.commit()

    # -- reminders -------------------------------------------------------
    def add_reminder(self, text: str, due_ts: float) -> int:
        cur = self._conn.execute(
            "INSERT INTO reminders(text, due_ts, done, created_ts) "
            "VALUES(?,?,0,?)",
            (text, due_ts, time.time()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_reminders(self, include_done: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT id, text, due_ts, done FROM reminders"
        if not include_done:
            sql += " WHERE done=0"
        sql += " ORDER BY due_ts"
        rows = self._conn.execute(sql).fetchall()
        return [dict(r) for r in rows]

    def due_reminders(self, now: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if now is None else now
        rows = self._conn.execute(
            "SELECT id, text, due_ts, done FROM reminders "
            "WHERE done=0 AND due_ts<=? ORDER BY due_ts",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_reminder_done(self, reminder_id: int) -> bool:
        cur = self._conn.execute(
            "UPDATE reminders SET done=1, done_ts=? WHERE id=?",
            (time.time(), reminder_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def reminders_completed_since(self, ts: float) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM reminders "
            "WHERE done=1 AND done_ts IS NOT NULL AND done_ts>=?",
            (ts,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def messages_since(self, ts: float) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM conversations WHERE ts>=?", (ts,)
        ).fetchone()
        return int(row["n"]) if row else 0

    def close(self) -> None:
        self._conn.close()
