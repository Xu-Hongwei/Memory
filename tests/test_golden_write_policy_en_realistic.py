from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_system import EventCreate, EventLog, MemoryItemCreate, MemoryStore


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "write_policy_en_realistic.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _has_ascii_letter(text: str) -> bool:
    return any(("a" <= char.lower() <= "z") for char in text)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def test_golden_write_policy_en_realistic_suite_shape():
    cases = load_cases()
    categories = {case["category"] for case in cases}

    assert len(cases) == 800
    assert len({case["name"] for case in cases}) == len(cases)
    assert len({case["event"]["content"] for case in cases}) == len(cases)
    assert all(_has_ascii_letter(case["event"]["content"]) for case in cases)
    assert not any(_has_cjk(case["event"]["content"]) for case in cases)
    assert all(case.get("scenario") for case in cases)
    assert all(case.get("utterance_style") for case in cases)
    assert all(case.get("source_family") for case in cases)
    assert len({case["scenario"] for case in cases}) >= 150
    assert len({case["utterance_style"] for case in cases}) >= 25
    assert len({case["source_family"] for case in cases}) >= 6
    assert categories == {
        "en_ask_conflict",
        "en_merge_duplicate",
        "en_negative_casual_like",
        "en_negative_emotional_or_social",
        "en_negative_question_only",
        "en_negative_sensitive",
        "en_negative_temporary_request",
        "en_positive_environment_fact_explicit",
        "en_positive_preference_direct",
        "en_positive_project_fact_observed",
        "en_positive_tool_rule_explicit",
        "en_positive_troubleshooting_verified",
        "en_positive_workflow_explicit",
        "en_review_preference_uncertain",
        "en_review_preference_underspecified",
    }


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["name"])
def test_golden_write_policy_en_realistic_cases(case):
    db_path = ":memory:"
    events = EventLog(db_path)
    memories = MemoryStore(db_path)

    for memory in case.get("existing_memories", []):
        memories.add_memory(MemoryItemCreate(**memory))

    event = events.record_event(EventCreate(**case["event"]))
    candidates = memories.propose_memory(event)
    expected_candidates = case["expected"]["candidates"]

    assert len(candidates) == len(expected_candidates)
    if not candidates:
        return

    for expected_candidate in expected_candidates:
        matches = [
            candidate
            for candidate in candidates
            if candidate.memory_type == expected_candidate["memory_type"]
        ]
        assert matches, f"missing candidate: {expected_candidate['memory_type']}"
        candidate = matches[0]
        assert candidate.evidence_type == expected_candidate["evidence_type"]

        decision = memories.evaluate_candidate(candidate.id)
        assert decision.decision == expected_candidate["decision"]
        assert decision.structured_reason["decision"] == expected_candidate["decision"]

        if expected_candidate.get("commit"):
            memory = memories.commit_memory(candidate.id, decision.id)
            assert memory.memory_type == expected_candidate["memory_type"]
            if decision.decision == "write":
                assert event.id in memory.source_event_ids
