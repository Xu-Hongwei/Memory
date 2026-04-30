from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from memory_system import EventRead, extract_session_items_from_event


SESSION_TYPES = {
    "task_state",
    "temporary_rule",
    "working_fact",
    "pending_decision",
    "emotional_state",
    "scratch_note",
}
ROUTES = {"long_term", "session", "ignore", "reject", "ask_user"}
LONG_TERM_TYPES = {
    "user_preference",
    "project_fact",
    "tool_rule",
    "environment_fact",
    "troubleshooting",
    "decision",
    "workflow",
    "reflection",
}
EXPECTED_CATEGORIES = {
    "cn_ask_user_blocking_decision",
    "cn_ignore_casual_social",
    "cn_ignore_low_info",
    "cn_long_term_preference",
    "cn_long_term_project_rule",
    "cn_reject_sensitive",
    "cn_session_emotional_state",
    "cn_session_pending_decision",
    "cn_session_scratch_note",
    "cn_session_task_state",
    "cn_session_temporary_rule",
    "cn_session_working_fact",
    "en_ask_user_blocking_decision",
    "en_ignore_casual_social",
    "en_ignore_low_info",
    "en_long_term_preference",
    "en_long_term_project_rule",
    "en_reject_sensitive",
    "en_session_emotional_state",
    "en_session_pending_decision",
    "en_session_scratch_note",
    "en_session_task_state",
    "en_session_temporary_rule",
    "en_session_working_fact",
}


def load_cases() -> list[dict[str, Any]]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "session_route.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _event_from_case(case: dict[str, Any]) -> EventRead:
    event = case["event"]
    return EventRead(
        id=f"evt_{case['name']}",
        event_type=event["event_type"],
        content=event["content"],
        source=event["source"],
        scope=event["scope"],
        metadata=event.get("metadata", {}),
        created_at=datetime.now(timezone.utc),
    )


def test_golden_session_route_suite_shape():
    cases = load_cases()
    route_counts = Counter(case["expected"]["route"] for case in cases)
    session_type_counts = Counter(
        case["expected"].get("session_memory_type")
        for case in cases
        if case["expected"]["route"] == "session"
    )

    assert len(cases) == 240
    assert len({case["name"] for case in cases}) == len(cases)
    assert len({case["event"]["content"] for case in cases}) == len(cases)
    assert {case["category"] for case in cases} == EXPECTED_CATEGORIES
    assert all(case["mode"] == "session_route" for case in cases)
    assert all(case.get("scenario") for case in cases)
    assert all(case.get("utterance_style") for case in cases)
    assert all(case.get("source_family") for case in cases)
    assert route_counts == {
        "session": 120,
        "ignore": 40,
        "long_term": 40,
        "reject": 20,
        "ask_user": 20,
    }
    assert session_type_counts == {
        "temporary_rule": 20,
        "task_state": 20,
        "working_fact": 20,
        "pending_decision": 20,
        "emotional_state": 20,
        "scratch_note": 20,
    }


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["name"])
def test_golden_session_route_expected_fields(case):
    expected = case["expected"]
    route = expected["route"]

    assert route in ROUTES
    assert isinstance(expected["should_store_session"], bool)
    assert isinstance(expected["should_create_long_term_candidate"], bool)
    assert expected["should_store_session"] is (route == "session")
    assert expected["should_create_long_term_candidate"] is (route == "long_term")
    assert expected["context_role"] in {"critical", "relevant", "excluded", "review"}

    if route == "session":
        assert expected["session_memory_type"] in SESSION_TYPES
        assert "memory_type" not in expected
        assert expected["context_role"] in {"critical", "relevant"}
    elif route == "long_term":
        assert expected["memory_type"] in LONG_TERM_TYPES
        assert "session_memory_type" not in expected
    else:
        assert "session_memory_type" not in expected
        assert "memory_type" not in expected

    if route == "reject":
        assert expected["remote_preflight_reject"] is True


def test_golden_session_route_local_fallback_subset_matches_current_classifier():
    cases = [
        case
        for case in load_cases()
        if case["expected"].get("local_fallback_supported")
    ]

    assert len(cases) == 80
    for case in cases:
        event = _event_from_case(case)
        extracted = extract_session_items_from_event(event, session_id="golden")
        expected_type = case["expected"]["session_memory_type"]
        assert len(extracted.items) == 1, case["name"]
        assert extracted.items[0].memory_type == expected_type, case["name"]
