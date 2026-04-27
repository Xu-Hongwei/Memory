from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EventType = Literal[
    "user_message",
    "assistant_message",
    "tool_result",
    "file_observation",
    "test_result",
    "user_confirmation",
]


class EventCreate(BaseModel):
    event_type: EventType
    content: str
    source: str
    scope: str = "global"
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content", "source", "scope")
    @classmethod
    def require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped


class EventRead(EventCreate):
    model_config = ConfigDict(frozen=True)

    id: str
    created_at: datetime
    sanitized: bool = False

