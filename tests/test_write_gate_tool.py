from __future__ import annotations

import time
from pathlib import Path

import tools.evaluate_write_gate as write_gate
from tools.evaluate_write_gate import (
    CandidateOutcome,
    CaseEvaluation,
    ModeOutcome,
    classify_failure,
    select_cases,
)


def test_select_cases_random_sample_is_seeded_and_not_prefix() -> None:
    cases = [
        (
            Path(f"fixture_{index}.jsonl"),
            {"name": f"case_{index:03d}", "category": "sample"},
        )
        for index in range(12)
    ]

    first = select_cases(cases, sample_size=5, sample_seed=17)
    second = select_cases(cases, sample_size=5, sample_seed=17)

    first_names = [case["name"] for _, case in first]
    second_names = [case["name"] for _, case in second]

    assert first_names == second_names
    assert len(first_names) == 5
    assert first_names != [case["name"] for _, case in cases[:5]]


def test_select_cases_randomizes_per_category_when_seeded() -> None:
    cases = [
        (
            Path("fixture.jsonl"),
            {"name": f"{category}_{index}", "category": category},
        )
        for category in ("a", "b")
        for index in range(6)
    ]

    selected = select_cases(cases, sample_per_category=2, sample_seed=23)

    names_by_category = {
        category: [case["name"] for _, case in selected if case["category"] == category]
        for category in ("a", "b")
    }

    assert {category: len(names) for category, names in names_by_category.items()} == {
        "a": 2,
        "b": 2,
    }
    assert names_by_category["a"] != ["a_0", "a_1"]


def test_evaluate_case_batch_concurrent_preserves_input_order(monkeypatch) -> None:
    cases = [
        (
            Path("fixture.jsonl"),
            {
                "name": f"case_{index}",
                "category": "sample",
                "event": {"content": f"content {index}"},
            },
        )
        for index in range(6)
    ]

    def fake_evaluate_case(item, **_kwargs):
        path, case = item
        index = int(case["name"].split("_")[1])
        time.sleep((6 - index) * 0.001)
        return CaseEvaluation(
            fixture=path,
            case=case,
            category=case["category"],
            content=case["event"]["content"],
            expected=[],
            local=ModeOutcome(actual=[], warnings=[], latency_ms=0.0, failure_type=None),
        )

    monkeypatch.setattr(write_gate, "evaluate_case", fake_evaluate_case)

    results = write_gate.evaluate_case_batch(
        cases,
        include_remote=True,
        remote_llm=None,
        instructions=None,
        case_concurrency=3,
    )

    assert [result.case["name"] for result in results] == [case["name"] for _, case in cases]


def test_classify_failure_can_allow_remote_omitted_rejects() -> None:
    expected = [
        CandidateOutcome(
            memory_type="user_preference",
            evidence_type="direct_user_statement",
            decision="reject",
        )
    ]

    assert classify_failure(expected, []) == "fn"
    assert classify_failure(expected, [], allow_omitted_rejects=True) is None
