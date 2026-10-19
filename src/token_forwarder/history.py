from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class ForwardHistory:
    """Durable record used to avoid forwarding the same event twice."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS forwarded_messages (
                source_chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                contract TEXT NOT NULL,
                destination_chat TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (source_chat_id, source_message_id, contract)
            )
            """
        )
        self._connection.commit()

    def was_sent(self, source_chat_id: int, source_message_id: int, contract: str) -> bool:
        row = self._connection.execute(
            """
            SELECT 1 FROM forwarded_messages
            WHERE source_chat_id = ? AND source_message_id = ? AND contract = ?
            """,
            (source_chat_id, source_message_id, contract),
        ).fetchone()
        return row is not None

    def record_sent(
        self,
        source_chat_id: int,
        source_message_id: int,
        contract: str,
        destination_chat: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO forwarded_messages
                (source_chat_id, source_message_id, contract, destination_chat, sent_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                source_chat_id,
                source_message_id,
                contract,
                destination_chat,
                datetime.now(UTC).isoformat(),
            ),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

