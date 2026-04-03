"""
JAMES Conversation Persistence — Save/restore chat history across sessions.

Stores conversation history in SQLite alongside other JAMES data.
Supports multiple named conversations with auto-save.

Usage:
    store = ConversationStore(db_path="james/memory/conversations.db")
    store.save_message("default", "user", "Hello JAMES")
    store.save_message("default", "assistant", "Hey! What would you like me to do?")
    history = store.get_history("default", limit=20)
    conversations = store.list_conversations()
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Optional

logger = logging.getLogger("james.conversations")


class ConversationStore:
    """
    SQLite-backed conversation persistence.

    Each conversation has a name and stores timestamped messages
    with role (user/assistant/system) and optional metadata.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        # Use a consistent path initialization
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        # Initialize persistent connection
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._lock, self._conn as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    message_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    timestamp REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_conv
                ON messages(conversation_name, timestamp)
            """)
            conn.execute("""
                -- ⚡ Bolt: Added index on conversations.updated_at to optimize listing conversations
                -- which uses ORDER BY updated_at DESC LIMIT ?
                CREATE INDEX IF NOT EXISTS idx_conversations_updated
                ON conversations(updated_at DESC)
            """)

    # ── Messages ─────────────────────────────────────────────────

    def save_message(self, conversation: str, role: str, content: str,
                     metadata: Optional[dict] = None) -> int:
        """
        Save a message to a conversation.

        Args:
            conversation: Conversation name (e.g. "default", "web_session").
            role: "user", "assistant", or "system".
            content: Message content.
            metadata: Optional metadata dict.

        Returns:
            Message ID.
        """
        now = time.time()
        meta_json = json.dumps(metadata) if metadata else None

        with self._lock, self._conn as conn:
            # Upsert conversation record
            existing = conn.execute(
                "SELECT id FROM conversations WHERE name = ?",
                (conversation,)
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE conversations SET updated_at = ?, message_count = message_count + 1 WHERE name = ?",
                    (now, conversation)
                )
            else:
                conn.execute(
                    "INSERT INTO conversations (name, created_at, updated_at, message_count) VALUES (?, ?, ?, 1)",
                    (conversation, now, now)
                )

            # Insert message
            cursor = conn.execute(
                "INSERT INTO messages (conversation_name, role, content, metadata, timestamp) VALUES (?, ?, ?, ?, ?)",
                (conversation, role, content, meta_json, now)
            )
            return cursor.lastrowid or 0

    def get_history(self, conversation: str, limit: int = 20,
                    before: Optional[float] = None) -> list[dict]:
        """
        Get recent messages from a conversation.

        Args:
            conversation: Conversation name.
            limit: Maximum messages to return.
            before: Only messages before this timestamp.

        Returns:
            List of message dicts in chronological order.
        """
        with self._lock, self._conn as conn:
            if before:
                rows = conn.execute(
                    "SELECT role, content, metadata, timestamp FROM messages "
                    "WHERE conversation_name = ? AND timestamp < ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (conversation, before, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT role, content, metadata, timestamp FROM messages "
                    "WHERE conversation_name = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (conversation, limit)
                ).fetchall()

        # Reverse to chronological order
        messages = []
        for role, content, meta_json, ts in reversed(rows):
            msg = {"role": role, "content": content, "timestamp": ts}
            if meta_json:
                try:
                    msg["metadata"] = json.loads(meta_json)
                except json.JSONDecodeError:
                    pass
            messages.append(msg)

        return messages

    # ── Conversation Management ──────────────────────────────────

    def list_conversations(self, limit: int = 50) -> list[dict]:
        """List all conversations with metadata."""
        with self._lock, self._conn as conn:
            rows = conn.execute(
                "SELECT name, created_at, updated_at, message_count "
                "FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (limit,)
            ).fetchall()

        return [
            {
                "name": name,
                "created_at": created,
                "updated_at": updated,
                "message_count": count,
            }
            for name, created, updated, count in rows
        ]

    def delete_conversation(self, conversation: str) -> bool:
        """Delete a conversation and all its messages."""
        with self._lock, self._conn as conn:
            conn.execute(
                "DELETE FROM messages WHERE conversation_name = ?",
                (conversation,)
            )
            result = conn.execute(
                "DELETE FROM conversations WHERE name = ?",
                (conversation,)
            )
            return result.rowcount > 0

    def clear_all(self) -> int:
        """Delete all conversations and messages."""
        with self._lock, self._conn as conn:
            conn.execute("DELETE FROM messages")
            result = conn.execute("DELETE FROM conversations")
            return result.rowcount

    def get_conversation_info(self, conversation: str) -> Optional[dict]:
        """Get metadata for a specific conversation."""
        with self._lock, self._conn as conn:
            row = conn.execute(
                "SELECT name, created_at, updated_at, message_count "
                "FROM conversations WHERE name = ?",
                (conversation,)
            ).fetchone()

        if row:
            return {
                "name": row[0],
                "created_at": row[1],
                "updated_at": row[2],
                "message_count": row[3],
            }
        return None

    def close(self):
        """Close the database connection."""
        with self._lock:
            self._conn.close()

    # ── Status ───────────────────────────────────────────────────

    def status(self) -> dict:
        with self._lock, self._conn as conn:
            conv_count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        return {
            "conversations": conv_count,
            "total_messages": msg_count,
            "db_path": self._db_path,
        }
