from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_system.schemas import MemoryRouteItem, RemoteMemoryRouteResult
from tools.evaluate_session_route_splitting import (
    evaluate_session_route_splitting,
    select_cases,
)


class FakeSplitClient:
    def route_memories(self, events, *, recent_events=None, instructions=None):  # noqa: ANN001
        del recent_events, instructions
        if len(events) > 1:
            return RemoteMemoryRouteResult(
                provider="fake-split",
                items=[
                    MemoryRouteItem(
                        route="long_term",
                        content=events[0].content,
                        reason="Stable preference.",
                        memory_type="user_preference",
                        source_event_ids=[events[0].id],
                    ),
                    MemoryRouteItem(
                        route="session",
                        content=events[1].content,
                        reason="Temporary rule.",
                        session_memory_type="temporary_rule",
                        source_event_ids=[events[1].id],
                    ),
                    *(
                        [
                            MemoryRouteItem(
                                route="ignore",
                                content=events[2].content,
                                reason="Low information acknowledgement.",
                                source_event_ids=[events[2].id],
                            )
                        ]
                        if len(events) > 2
                        else []
                    ),
                ],
            )
        return RemoteMemoryRouteResult(
            provider="fake-split",
            items=[
                MemoryRouteItem(
                    route="long_term",
                    content="Future answers should be concise.",
                    reason="Stable preference.",
                    memory_type="user_preference",
                    source_event_ids=[events[0].id],
                ),
                MemoryRouteItem(
                    route="session",
                    content="Do not commit for this task.",
                    reason="Temporary rule.",
                    session_memory_type="temporary_rule",
                    source_event_ids=[events[0].id],
                ),
            ],
        )


def _case(
    name: str,
    events: list[dict[str, Any]],
    expected_items: list[dict[str, Any]],
    *,
    category: str,
) -> tuple[Path, dict[str, Any]]:
    return (
        Path("split.jsonl"),
        {
            "name": name,
            "category": category,
            "mode": "session_route_splitting",
            "events": events,
            "expected": {"items": expected_items},
        },
    )


def _event(alias: str, content: str) -> dict[str, str]:
    return {
        "alias": alias,
        "event_type": "user_message",
        "content": content,
        "source": "conversation",
        "scope": "global",
    }


def test_evaluate_session_route_splitting_scores_multi_item_and_multi_event_cases():
    cases = [
        _case(
            "single_split",
            [_event("mixed", "Going forward be concise; for this task do not commit.")],
            [
                {
                    "label": "preference",
                    "route": "long_term",
                    "memory_type": "user_preference",
                    "source_event_aliases": ["mixed"],
                },
                {
                    "label": "temporary_rule",
                    "route": "session",
                    "session_memory_type": "temporary_rule",
                    "source_event_aliases": ["mixed"],
                    "context_role": "critical",
                },
            ],
            category="single",
        ),
        _case(
            "batch_split",
            [
                _event("pref", "Going forward be concise."),
                _event("rule", "For this task do not commit."),
                _event("ack", "Ok."),
            ],
            [
                {
                    "label": "preference",
                    "route": "long_term",
                    "memory_type": "user_preference",
                    "source_event_aliases": ["pref"],
                },
                {
                    "label": "temporary_rule",
                    "route": "session",
                    "session_memory_type": "temporary_rule",
                    "source_event_aliases": ["rule"],
                    "context_role": "critical",
                },
            ],
            category="batch",
        ),
    ]

    result = evaluate_session_route_splitting(
        cases,
        remote_llm=FakeSplitClient(),  # type: ignore[arg-type]
        failure_limit=10,
    )

    assert result.summary.cases == 2
    assert result.summary.expected_items == 4
    assert result.summary.route_passed_cases == 2
    assert result.summary.strict_passed_cases == 2
    assert result.summary.route_item_accuracy == 1.0
    assert result.summary.strict_item_accuracy == 1.0
    assert result.failures == []


def test_evaluate_session_route_splitting_reports_source_mismatch():
    case = _case(
        "source_mismatch",
        [_event("pref", "Going forward be concise."), _event("rule", "Do not commit.")],
        [
            {
                "label": "temporary_rule",
                "route": "session",
                "session_memory_type": "temporary_rule",
                "source_event_aliases": ["pref"],
            }
        ],
        category="batch",
    )

    result = evaluate_session_route_splitting(
        [case],
        remote_llm=FakeSplitClient(),  # type: ignore[arg-type]
        failure_limit=10,
    )

    assert result.summary.route_passed_items == 1
    assert result.summary.strict_passed_items == 0
    assert result.summary.source_mismatch == 1
    assert result.failures[0].item_failures[0].strict_failure == "source_mismatch"


def test_select_cases_samples_splitting_cases_deterministically():
    cases = [
        _case(
            str(index),
            [_event("event", f"case {index}")],
            [{"label": "ignore", "route": "ignore", "source_event_aliases": ["event"]}],
            category="sample",
        )
        for index in range(10)
    ]

    first = select_cases(cases, sample_size=3, sample_seed=29)
    second = select_cases(cases, sample_size=3, sample_seed=29)

    assert [case["name"] for _path, case in first] == [case["name"] for _path, case in second]
