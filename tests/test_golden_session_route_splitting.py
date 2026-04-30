from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


FIXTURE = Path(__file__).parent / "fixtures" / "golden_cases" / "session_route_splitting.jsonl"

EXPECTED_CATEGORIES = {
    "single_event_multi_info_cn",
    "single_event_multi_info_en",
    "multi_event_batch_cn",
    "multi_event_batch_en",
}
ROUTES = {"long_term", "session", "ignore", "reject", "ask_user"}
SESSION_TYPES = {
    "task_state",
    "temporary_rule",
    "working_fact",
    "pending_decision",
    "emotional_state",
    "scratch_note",
}


def load_cases() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_golden_session_route_splitting_shape():
    cases = load_cases()

    assert len(cases) == 24
    assert len({case["name"] for case in cases}) == len(cases)
    assert {case["category"] for case in cases} == EXPECTED_CATEGORIES
    assert all(case["mode"] == "session_route_splitting" for case in cases)

    categories = Counter(case["category"] for case in cases)
    assert categories == {
        "single_event_multi_info_cn": 6,
        "single_event_multi_info_en": 6,
        "multi_event_batch_cn": 6,
        "multi_event_batch_en": 6,
    }


def test_golden_session_route_splitting_expected_items_are_valid():
    for case in load_cases():
        aliases = {event["alias"] for event in case["events"]}
        expected_items = case["expected"]["items"]
        assert len(expected_items) >= 2, case["name"]
        assert any(item["route"] == "session" for item in expected_items), case["name"]
        assert any(item["route"] == "long_term" for item in expected_items), case["name"]

        for item in expected_items:
            assert item["route"] in ROUTES, case["name"]
            assert item["source_event_aliases"], case["name"]
            assert set(item["source_event_aliases"]).issubset(aliases), case["name"]
            if item["route"] == "session":
                assert item["session_memory_type"] in SESSION_TYPES, case["name"]
            if item["route"] == "long_term":
                assert item["memory_type"], case["name"]
