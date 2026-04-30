from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_system.schemas import MemoryRouteItem, RemoteMemoryRouteResult
from tools.evaluate_session_route import evaluate_session_routes, select_cases


class FakeRouteClient:
    def route_memories(self, events, *, recent_events=None, instructions=None):  # noqa: ANN001
        del recent_events, instructions
        event = events[0]
        if "do not commit" in event.content:
            return RemoteMemoryRouteResult(
                provider="fake-route",
                items=[
                    MemoryRouteItem(
                        route="session",
                        content=event.content,
                        reason="Current task constraint.",
                        session_memory_type="temporary_rule",
                        source_event_ids=[event.id],
                    )
                ],
            )
        if event.content == "Ok.":
            return RemoteMemoryRouteResult(
                provider="fake-route",
                items=[
                    MemoryRouteItem(
                        route="ignore",
                        content=event.content,
                        reason="Low information acknowledgement.",
                        source_event_ids=[event.id],
                    )
                ],
            )
        if event.content == "Never mind.":
            return RemoteMemoryRouteResult(provider="fake-route", items=[])
        return RemoteMemoryRouteResult(
            provider="fake-route",
            items=[
                MemoryRouteItem(
                    route="session",
                    content=event.content,
                    reason="Intentionally mismatched for test coverage.",
                    session_memory_type="task_state",
                    source_event_ids=[event.id],
                )
            ],
        )


def _case(
    name: str,
    content: str,
    expected: dict[str, Any],
    *,
    category: str,
) -> tuple[Path, dict[str, Any]]:
    return (
        Path("fixture.jsonl"),
        {
            "name": name,
            "category": category,
            "event": {
                "event_type": "user_message",
                "content": content,
                "source": "conversation",
                "scope": "global",
                "metadata": {},
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            "expected": expected,
        },
    )


def test_evaluate_session_routes_summarizes_route_and_strict_accuracy():
    cases = [
        _case(
            "session_ok",
            "For this task, do not commit anything.",
            {
                "route": "session",
                "session_memory_type": "temporary_rule",
                "context_role": "critical",
            },
            category="session",
        ),
        _case(
            "ignore_ok",
            "Ok.",
            {"route": "ignore", "context_role": "excluded"},
            category="ignore",
        ),
        _case(
            "ignore_empty_ok",
            "Never mind.",
            {"route": "ignore", "context_role": "excluded"},
            category="ignore",
        ),
        _case(
            "long_term_miss",
            "Going forward, answer in Chinese.",
            {
                "route": "long_term",
                "memory_type": "user_preference",
                "context_role": "excluded",
            },
            category="long_term",
        ),
    ]

    result = evaluate_session_routes(
        cases,
        remote_llm=FakeRouteClient(),  # type: ignore[arg-type]
        failure_limit=10,
    )

    assert result.summary.cases == 4
    assert result.summary.route_passed == 3
    assert result.summary.strict_passed == 3
    assert result.summary.route_mismatch == 1
    assert result.summary.serious_failures == 1
    assert result.category_summary["session"].strict_passed == 1
    assert result.failures[0].name == "long_term_miss"
    assert result.failures[0].serious_failure == "long_term_missed:session"


def test_select_cases_samples_deterministically():
    cases = [
        _case(str(index), f"case {index}", {"route": "ignore"}, category="sample")
        for index in range(10)
    ]

    first = select_cases(cases, sample_size=4, sample_seed=17)
    second = select_cases(cases, sample_size=4, sample_seed=17)

    assert [case["name"] for _path, case in first] == [
        case["name"] for _path, case in second
    ]
    assert len(first) == 4
