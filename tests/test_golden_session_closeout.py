from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from memory_system import SessionMemoryItemCreate, TaskBoundaryDecision


EXPECTED_CATEGORIES = {
    "cn_cancel_discard",
    "cn_done_discard_temporary",
    "cn_done_promote_project_fact",
    "cn_done_promote_workflow",
    "cn_done_summarize_state",
    "cn_keep_pending_decision",
    "cn_sensitive_filtered",
    "cn_switch_task_mixed",
    "en_cancel_discard",
    "en_done_discard_temporary",
    "en_done_promote_project_fact",
    "en_done_promote_workflow",
    "en_done_summarize_state",
    "en_keep_pending_decision",
    "en_sensitive_filtered",
    "en_switch_task_mixed",
}
SESSION_TYPES = {
    "task_state",
    "temporary_rule",
    "working_fact",
    "pending_decision",
    "emotional_state",
    "scratch_note",
}
EXPECTED_ACTIONS = {"keep", "discard", "summarize", "promote_candidate", "missing"}
REMOTE_ACTIONS = {"keep", "discard", "summarize", "promote_candidate", "missing"}
MEMORY_TYPES = {
    "user_preference",
    "project_fact",
    "tool_rule",
    "environment_fact",
    "troubleshooting",
    "decision",
    "workflow",
    "reflection",
}


def load_cases() -> list[dict[str, Any]]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "session_closeout.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_golden_session_closeout_suite_shape():
    cases = load_cases()
    category_counts = Counter(case["category"] for case in cases)
    session_memory_contents = [
        item["content"]
        for case in cases
        for item in case["session_memories"]
    ]

    assert len(cases) == 160
    assert len({case["name"] for case in cases}) == len(cases)
    assert len(set(session_memory_contents)) == len(session_memory_contents)
    assert {case["category"] for case in cases} == EXPECTED_CATEGORIES
    assert all(case["mode"] == "session_closeout" for case in cases)
    assert all(case.get("scenario") for case in cases)
    assert all(case.get("utterance_style") for case in cases)
    assert all(case.get("source_family") for case in cases)
    assert set(category_counts.values()) == {10}


def test_golden_session_closeout_items_are_valid():
    for case in load_cases():
        TaskBoundaryDecision.model_validate(case["task_boundary"])
        aliases = [item["alias"] for item in case["session_memories"]]
        assert len(aliases) == len(set(aliases)), case["name"]
        assert len(aliases) >= 2, case["name"]
        assert set(case["expected"]["items"]) == set(aliases), case["name"]

        for item in case["session_memories"]:
            assert item["memory_type"] in SESSION_TYPES
            payload = {key: value for key, value in item.items() if key != "alias"}
            payload["session_id"] = case["session_id"]
            SessionMemoryItemCreate.model_validate(payload)

        for alias, expected in case["expected"]["items"].items():
            assert alias in aliases, case["name"]
            assert expected["action"] in EXPECTED_ACTIONS
            assert set(expected["acceptable_actions"]).issubset(REMOTE_ACTIONS)
            if expected["action"] == "promote_candidate":
                assert set(expected["candidate_memory_types"]).issubset(MEMORY_TYPES)
            if expected.get("forbid_promote"):
                assert "promote_candidate" not in expected["acceptable_actions"]


def test_golden_session_closeout_sensitive_cases_use_placeholders_only():
    cases = [case for case in load_cases() if case["category"].endswith("sensitive_filtered")]
    assert len(cases) == 20

    for case in cases:
        secret = next(item for item in case["session_memories"] if item["alias"] == "secret")
        expected = case["expected"]["items"]["secret"]
        assert "[REDACTED]" in secret["content"]
        assert expected["forbid_promote"] is True
        assert "missing" in expected["acceptable_actions"]
