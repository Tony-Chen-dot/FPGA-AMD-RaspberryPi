from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    """Stores AI conversations beside the inspection database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ai_conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS ai_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(conversation_id) REFERENCES ai_conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_ai_messages_conversation
                ON ai_messages(conversation_id, id);
                """
            )

    def create(self, title: str = "新对话") -> dict[str, Any]:
        conversation_id = uuid4().hex
        now = utcnow_iso()
        clean_title = (title or "新对话").strip()[:80] or "新对话"
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO ai_conversations (id, title, created_at, updated_at, message_count)
                VALUES (?, ?, ?, ?, 0)
                """,
                (conversation_id, clean_title, now, now),
            )
        return self.get(conversation_id) or {
            "id": conversation_id,
            "title": clean_title,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
        }

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT id, title, created_at, updated_at, message_count FROM ai_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                """
                SELECT id, title, created_at, updated_at, message_count
                FROM ai_conversations
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def append(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if role not in {"user", "assistant", "system"}:
            raise ValueError(f"不支持的消息角色: {role}")
        clean_content = (content or "").strip()
        if not clean_content:
            raise ValueError("消息内容不能为空")
        now = utcnow_iso()
        with closing(self._connect()) as conn, conn:
            conversation = conn.execute(
                "SELECT title, message_count FROM ai_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise KeyError(f"对话不存在: {conversation_id}")
            conn.execute(
                """
                INSERT INTO ai_messages (conversation_id, role, content, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, role, clean_content, now, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            message_count = int(conversation["message_count"] or 0) + 1
            title = conversation["title"]
            if role == "user" and title == "新对话":
                title = clean_content.replace("\n", " ")[:40] or title
            conn.execute(
                """
                UPDATE ai_conversations
                SET title = ?, updated_at = ?, message_count = ?
                WHERE id = ?
                """,
                (title, now, message_count, conversation_id),
            )
            message_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        return {
            "id": message_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": clean_content,
            "created_at": now,
            "metadata": metadata or {},
        }

    def messages(self, conversation_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT id, conversation_id, role, content, created_at, metadata_json
            FROM ai_messages
            WHERE conversation_id = ?
            ORDER BY id ASC
        """
        params: tuple[Any, ...] = (conversation_id,)
        if limit is not None:
            query = """
                SELECT id, conversation_id, role, content, created_at, metadata_json
                FROM (
                    SELECT id, conversation_id, role, content, created_at, metadata_json
                    FROM ai_messages
                    WHERE conversation_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
            """
            params = (conversation_id, max(1, min(limit, 200)))
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(query, params).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            messages.append(
                {
                    "id": int(row["id"]),
                    "conversation_id": row["conversation_id"],
                    "role": row["role"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                    "metadata": metadata,
                }
            )
        return messages

    def delete(self, conversation_id: str) -> bool:
        with closing(self._connect()) as conn, conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute("DELETE FROM ai_conversations WHERE id = ?", (conversation_id,))
        return cursor.rowcount > 0
