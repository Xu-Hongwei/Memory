from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from memory_system import EventCreate, EventLog, MemoryItemCreate, MemoryStore


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "write_policy.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_golden_write_policy_suite_shape():
    cases = load_cases()
    categories = {case.get("category") for case in cases}

    assert len(cases) == 2000
    assert len({case["name"] for case in cases}) == len(cases)
    assert categories == {
        "ask_conflict",
        "merge_duplicate",
        "negative_casual_like",
        "negative_emotional_or_social",
        "negative_ordinary_or_unverified",
        "negative_question_only",
        "negative_sensitive",
        "negative_temporary_state",
        "positive_environment_fact_explicit",
        "positive_project_fact",
        "positive_tool_rule",
        "positive_troubleshooting",
        "positive_user_preference",
        "positive_workflow_explicit",
        "review_low_evidence",
    }


def test_golden_write_policy_suite_is_semantically_diverse():
    cases = load_cases()
    event_texts = [case["event"]["content"] for case in cases]
    existing_memory_contents = [
        memory["content"]
        for case in cases
        for memory in case.get("existing_memories", [])
    ]

    assert len(set(event_texts)) == len(event_texts)
    assert len({_normalize_template_text(text) for text in event_texts}) == len(event_texts)
    assert len(set(existing_memory_contents)) == len(existing_memory_contents)
    assert len({_normalize_template_text(text) for text in existing_memory_contents}) == len(
        existing_memory_contents
    )


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["name"])
def test_golden_write_policy_cases(case):
    db_path = ":memory:"
    events = EventLog(db_path)
    memories = MemoryStore(db_path)

    for memory in case.get("existing_memories", []):
        memories.add_memory(MemoryItemCreate(**memory))

    event = events.record_event(EventCreate(**case["event"]))
    candidates = memories.propose_memory(event)
    expected = case["expected"]
    expected_candidates = expected["candidates"]

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


def _normalize_template_text(value: str) -> str:
    noise_pattern = re.compile(
        r"第\s*\d+\s*个"
        r"|样本\s*\d+"
        r"|编号\s*\d+"
        r"|冲突\s*\d+"
        r"|低证据样本\s*\d+"
        r"|临时样本\s*\d+"
        r"|提问样本\s*\d+"
        r"|普通样本\s*\d+"
        r"|情绪闲聊样本\s*\d+"
        r"|场景编号\s*\d+"
        r"|\b\d+\b"
    )
    return re.sub(r"\s+", " ", noise_pattern.sub("<N>", value)).strip()
