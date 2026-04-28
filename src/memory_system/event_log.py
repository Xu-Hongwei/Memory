from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from memory_system.schemas import EventCreate, EventRead


class SensitiveContentError(ValueError):
    """Raised when redaction_mode='reject' and sensitive content is detected."""


RedactionMode = Literal["redact", "reject"]

SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|passwd|cookie)", re.I)
SENSITIVE_VALUE_PATTERNS = [
    re.compile(
        r"(?P<key>api[_-]?key|token|secret|password|passwd|cookie)"
        r"(?P<sep>\s*[:=]\s*)"
        r"(?P<quote>['\"]?)"
        r"(?P<value>[^\s,'\"]{8,})"
        r"(?P=quote)",
        re.I,
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_metadata(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)


def _deserialize_metadata(raw: str) -> dict[str, Any]:
    data = json.loads(raw) if raw else {}
    if isinstance(data, dict):
        return data
    return {"value": data}


def _redact_string(value: str) -> tuple[str, bool]:
    sanitized = False

    def replace_key_value(match: re.Match[str]) -> str:
        nonlocal sanitized
        sanitized = True
        return f"{match.group('key')}{match.group('sep')}{match.group('quote')}[REDACTED]{match.group('quote')}"

    redacted = SENSITIVE_VALUE_PATTERNS[0].sub(replace_key_value, value)
    redacted, bearer_count = SENSITIVE_VALUE_PATTERNS[1].subn("Bearer [REDACTED]", redacted)
    redacted, email_count = SENSITIVE_VALUE_PATTERNS[2].subn("[REDACTED_EMAIL]", redacted)
    redacted, phone_count = SENSITIVE_VALUE_PATTERNS[3].subn("[REDACTED_PHONE]", redacted)
    redacted, id_count = SENSITIVE_VALUE_PATTERNS[4].subn("[REDACTED_ID]", redacted)
    sanitized = sanitized or bearer_count > 0 or email_count > 0 or phone_count > 0 or id_count > 0
    return redacted, sanitized


def _sanitize_metadata(value: Any, *, parent_key: str | None = None) -> tuple[Any, bool]:
    if isinstance(value, dict):
        sanitized = False
        result: dict[str, Any] = {}
        for key, item in value.items():
            child, child_sanitized = _sanitize_metadata(item, parent_key=str(key))
            result[str(key)] = child
            sanitized = sanitized or child_sanitized
        return result, sanitized

    if isinstance(value, list):
        sanitized = False
        result = []
        for item in value:
            child, child_sanitized = _sanitize_metadata(item, parent_key=parent_key)
            result.append(child)
            sanitized = sanitized or child_sanitized
        return result, sanitized

    if isinstance(value, str):
        if parent_key and SENSITIVE_KEY_RE.search(parent_key):
            return "[REDACTED]", True
        return _redact_string(value)

    return value, False


def sanitize_event(event: EventCreate) -> tuple[EventCreate, bool]:
    content, content_sanitized = _redact_string(event.content)
    metadata, metadata_sanitized = _sanitize_metadata(event.metadata)
    sanitized = content_sanitized or metadata_sanitized
    return event.model_copy(update={"content": content, "metadata": metadata}), sanitized


class EventLog:
    def __init__(self, db_path: str | Path, *, redaction_mode: RedactionMode = "redact") -> None:
        self._db_name = str(db_path)
        self.db_path = Path(db_path)
        self.redaction_mode = redaction_mode
        self._memory_conn: sqlite3.Connection | None = None
        if redaction_mode not in {"redact", "reject"}:
            raise ValueError("redaction_mode must be 'redact' or 'reject'")
        if self._db_name == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.row_factory = sqlite3.Row
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sanitized INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    task_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_source ON events(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_scope ON events(scope)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at)")

    def record_event(self, event: EventCreate) -> EventRead:
        event, sanitized = sanitize_event(event)
        if sanitized and self.redaction_mode == "reject":
            raise SensitiveContentError("sensitive content detected")

        event_id = f"evt_{uuid4().hex}"
        created_at = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    id,
                    event_type,
                    content,
                    sanitized,
                    source,
                    scope,
                    task_id,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event.event_type,
                    event.content,
                    1 if sanitized else 0,
                    event.source,
                    event.scope,
                    event.task_id,
                    _serialize_metadata(event.metadata),
                    created_at.isoformat(),
                ),
            )
        return EventRead(
            id=event_id,
            created_at=created_at,
            sanitized=sanitized,
            **event.model_dump(),
        )

    def get_event(self, event_id: str) -> EventRead | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._row_to_event(row) if row else None

    def list_events(
        self,
        *,
        source: str | None = None,
        scope: str | None = None,
        task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EventRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        filters: list[str] = []
        params: list[Any] = []
        if source is not None:
            filters.append("source = ?")
            params.append(source)
        if scope is not None:
            filters.append("scope = ?")
            params.append(scope)
        if task_id is not None:
            filters.append("task_id = ?")
            params.append(task_id)

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM events
                {where}
                ORDER BY created_at ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def count_events(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM events").fetchone()
        return int(row["count"])

    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> EventRead:
        return EventRead(
            id=row["id"],
            event_type=row["event_type"],
            content=row["content"],
            sanitized=bool(row["sanitized"]),
            source=row["source"],
            scope=row["scope"],
            task_id=row["task_id"],
            metadata=_deserialize_metadata(row["metadata_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
