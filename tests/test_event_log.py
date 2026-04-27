from __future__ import annotations

import pytest
from pydantic import ValidationError

from memory_system import EventCreate, EventLog, SensitiveContentError


def test_record_and_get_event(tmp_path):
    log = EventLog(tmp_path / "memory.sqlite")

    event = log.record_event(
        EventCreate(
            event_type="user_message",
            content="以后技术文档默认用中文。",
            source="conversation",
            scope="global",
            task_id="task-1",
            metadata={"turn": 1},
        )
    )

    assert event.id.startswith("evt_")
    assert event.sanitized is False
    assert log.count_events() == 1

    loaded = log.get_event(event.id)

    assert loaded == event
    assert loaded is not None
    assert loaded.metadata == {"turn": 1}


def test_in_memory_database_reuses_connection():
    log = EventLog(":memory:")

    event = log.record_event(
        EventCreate(
            event_type="user_message",
            content="当前任务只验证事件日志。",
            source="conversation",
        )
    )

    assert log.count_events() == 1
    assert log.get_event(event.id) == event


def test_list_events_filters_by_source_scope_and_task(tmp_path):
    log = EventLog(tmp_path / "memory.sqlite")
    log.record_event(
        EventCreate(
            event_type="tool_result",
            content="package.json 中 dev 脚本是 vite。",
            source="package.json",
            scope="repo:C:/demo/a",
            task_id="task-a",
        )
    )
    log.record_event(
        EventCreate(
            event_type="tool_result",
            content="package.json 中 dev 脚本是 pnpm dev。",
            source="package.json",
            scope="repo:C:/demo/b",
            task_id="task-b",
        )
    )

    results = log.list_events(source="package.json", scope="repo:C:/demo/a", task_id="task-a")

    assert len(results) == 1
    assert results[0].content == "package.json 中 dev 脚本是 vite。"


def test_sensitive_content_is_redacted_in_content_and_metadata(tmp_path):
    log = EventLog(tmp_path / "memory.sqlite")

    event = log.record_event(
        EventCreate(
            event_type="tool_result",
            content="token=abc123456789 and Authorization: Bearer abcdef1234567890",
            source="shell",
            metadata={
                "api_key": "sk-should-not-survive",
                "nested": {"note": "password=supersecretvalue"},
            },
        )
    )

    assert event.sanitized is True
    assert "abc123456789" not in event.content
    assert "abcdef1234567890" not in event.content
    assert event.metadata["api_key"] == "[REDACTED]"
    assert event.metadata["nested"]["note"] == "password=[REDACTED]"


def test_sensitive_content_can_be_rejected(tmp_path):
    log = EventLog(tmp_path / "memory.sqlite", redaction_mode="reject")

    with pytest.raises(SensitiveContentError):
        log.record_event(
            EventCreate(
                event_type="user_message",
                content="api_key=abc123456789",
                source="conversation",
            )
        )

    assert log.count_events() == 0


def test_event_create_rejects_empty_required_text():
    with pytest.raises(ValidationError):
        EventCreate(event_type="user_message", content="  ", source="conversation")
