from __future__ import annotations

import json

from memory_system import RemoteMemoryRouteResult, TaskBoundaryDecision
from tools.evaluate_task_boundary import evaluate_task_boundaries


class _FakeBoundaryClient:
    def route_memories(  # noqa: ANN001
        self,
        events,
        *,
        recent_events=None,
        current_task_state=None,
        instructions=None,
    ):
        del recent_events, current_task_state, instructions
        name = events[0].id.removesuffix("_event_0")
        if name == "case_same":
            action = "same_task"
            next_title = None
        else:
            action = "same_task"
            next_title = None
        return RemoteMemoryRouteResult(
            provider="fake",
            items=[],
            task_boundary=TaskBoundaryDecision(
                action=action,
                confidence="high",
                next_task_title=next_title,
                previous_task_status="active",
                reason="Fake boundary decision.",
            ),
            warnings=[],
        )


def test_evaluate_task_boundaries_scores_action_and_strict_failures(tmp_path):
    fixture = tmp_path / "task_boundary.jsonl"
    cases = [
        {
            "mode": "task_boundary",
            "name": "case_same",
            "category": "same",
            "current_task_state": {"task_id": "t1", "title": "Current task", "status": "active"},
            "recent_events": [],
            "events": [{"event_type": "user_message", "content": "Run tests.", "source": "conversation", "scope": "global"}],
            "expected": {"action": "same_task", "acceptable_actions": ["same_task", "no_change"], "next_task_title": None},
        },
        {
            "mode": "task_boundary",
            "name": "case_switch",
            "category": "switch",
            "current_task_state": {"task_id": "t2", "title": "Current task", "status": "active"},
            "recent_events": [],
            "events": [{"event_type": "user_message", "content": "Next, work on lifecycle.", "source": "conversation", "scope": "global"}],
            "expected": {"action": "switch_task", "acceptable_actions": ["switch_task"], "next_task_title": "lifecycle"},
        },
    ]
    fixture.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )

    result = evaluate_task_boundaries([fixture], remote_llm=_FakeBoundaryClient())

    assert result.summary.cases == 2
    assert result.summary.action_passed == 1
    assert result.summary.strict_passed == 1
    assert result.summary.action_mismatch == 1
    assert len(result.failures) == 1
    assert result.failures[0].name == "case_switch"
