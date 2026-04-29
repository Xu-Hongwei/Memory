from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_system import EventCreate, EventLog, MemoryItemCreate, MemoryStore


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "write_policy_time_validity.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_golden_write_policy_time_validity_suite_shape():
    cases = load_cases()
    categories = {case["category"] for case in cases}

    assert len(cases) == 16
    assert len({case["name"] for case in cases}) == len(cases)
    assert categories == {
        "time_validity_persistent_write",
        "time_validity_until_changed_write",
        "time_validity_session_reject",
        "time_validity_unknown_review",
    }


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["name"])
def test_golden_write_policy_time_validity_cases(case):
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
        assert decision.structured_reason["time_validity"] == candidate.time_validity

        if expected_candidate.get("commit"):
            memory = memories.commit_memory(candidate.id, decision.id)
            assert memory.memory_type == expected_candidate["memory_type"]
            if decision.decision == "write":
                assert event.id in memory.source_event_ids
