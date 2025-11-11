"""SQLite-backed conversation history store."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class ConversationMessage:
    """Represents a single stored conversation message."""

    session_id: str
    role: str
    content: str
    metadata: dict | None
    created_at: str


class ConversationStore:
    """Persist chat transcripts keyed by session_id."""

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_session_created
                ON messages(session_id, created_at)
                """
            )

    def record_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Store a single message for a session."""
        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(session_id) VALUES (?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                (session_id,),
            )
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, metadata_json),
            )
            conn.execute(
                "UPDATE sessions SET updated_at=CURRENT_TIMESTAMP WHERE session_id=?",
                (session_id,),
            )

    def get_messages(self, session_id: str, limit: int | None = None) -> list[ConversationMessage]:
        """Fetch ordered messages for a session."""
        query = (
            "SELECT session_id, role, content, metadata, created_at "
            "FROM messages WHERE session_id=? ORDER BY created_at ASC, id ASC"
        )
        params: tuple[object, ...]
        params = (session_id,)
        if limit is not None:
            query = (
                "SELECT session_id, role, content, metadata, created_at FROM ("
                + query
                + ") ORDER BY created_at DESC LIMIT ?"
            )
            query = "SELECT * FROM (" + query + ") ORDER BY created_at ASC"
            params = (session_id, limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        messages: list[ConversationMessage] = []
        for row in rows:
            metadata = json.loads(row["metadata"]) if row["metadata"] else None
            messages.append(
                ConversationMessage(
                    session_id=row["session_id"],
                    role=row["role"],
                    content=row["content"],
                    metadata=metadata,
                    created_at=row["created_at"],
                )
            )
        return messages

    def list_sessions(self, limit: int = 100) -> list[dict]:
        """Summarize stored sessions."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.session_id, s.created_at, s.updated_at, COUNT(m.id) AS message_count
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.session_id
                GROUP BY s.session_id
                ORDER BY s.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_session(self, session_id: str) -> None:
        """Remove a stored conversation."""
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))


def format_history_for_prompt(messages: Iterable[ConversationMessage]) -> str:
    """Render stored history into a readable transcript string."""
    lines: list[str] = []
    for message in messages:
        role = message.role.capitalize()
        lines.append(f"{role}: {message.content}")
    return "\n".join(lines)
