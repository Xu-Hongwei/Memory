from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_system.schemas import (
    MemoryCandidateCreate,
    SessionCloseoutDecision,
    SessionCloseoutResult,
)
from tools.evaluate_session_closeout import evaluate_session_closeouts, select_cases


class FakeCloseoutClient:
    def closeout_session_memories(  # noqa: PLR0913
        self,
        *,
        session_id,
        session_memories,
        task_boundary=None,
        current_task_state=None,
        recent_events=None,
        instructions=None,
    ):
        del current_task_state, recent_events, instructions
        decisions = []
        for item in session_memories:
            if "stable fact" in item.content:
                decisions.append(
                    SessionCloseoutDecision(
                        session_memory_id=item.id,
                        action="promote_candidate",
                        reason="Stable verified fact.",
                        candidate=MemoryCandidateCreate(
                            content=item.content,
                            memory_type="project_fact",
                            scope=item.scope,
                            subject=item.subject,
                            source_event_ids=item.source_event_ids,
                            reason="Promoted by fake closeout client.",
                            evidence_type="test_result",
                            time_validity="persistent",
                            confidence="confirmed",
                        ),
                    )
                )
            elif "temporary rule" in item.content:
                decisions.append(
                    SessionCloseoutDecision(
                        session_memory_id=item.id,
                        action="discard",
                        reason="Temporary rule ended.",
                    )
                )
            elif "recap" in item.content:
                decisions.append(
                    SessionCloseoutDecision(
                        session_memory_id=item.id,
                        action="summarize",
                        reason="Only needed for task summary.",
                        summary=item.content,
                    )
                )
            elif "filtered secret" in item.content:
                continue
            else:
                decisions.append(
                    SessionCloseoutDecision(
                        session_memory_id=item.id,
                        action="keep",
                        reason="Still needed.",
                    )
                )
        return SessionCloseoutResult(
            provider="fake-closeout",
            session_id=session_id,
            task_boundary=task_boundary,
            decisions=decisions,
            warnings=[],
        )


def _case(
    name: str,
    memories: list[dict[str, Any]],
    expected: dict[str, Any],
    *,
    category: str = "fake",
) -> tuple[Path, dict[str, Any]]:
    return (
        Path("fixture.jsonl"),
        {
            "name": name,
            "mode": "session_closeout",
            "category": category,
            "session_id": f"s_{name}",
            "task_boundary": {
                "action": "task_done",
                "confidence": "high",
                "current_task_id": "task_fake",
                "current_task_title": "Fake closeout",
                "previous_task_status": "done",
                "reason": "Fake boundary.",
            },
            "current_task_state": {"task_id": "task_fake", "status": "done"},
            "recent_events": [
                {
                    "event_type": "user_message",
                    "content": "The fake task is complete.",
                    "source": "conversation",
                    "scope": "repo:C:/workspace/session-closeout",
                    "metadata": {},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "session_memories": memories,
            "expected": {"items": expected},
        },
    )


def _memory(alias: str, content: str, memory_type: str) -> dict[str, Any]:
    return {
        "alias": alias,
        "content": content,
        "memory_type": memory_type,
        "scope": "repo:C:/workspace/session-closeout",
        "subject": alias,
        "source_event_ids": [f"evt_{alias}"],
        "reason": "Fake memory.",
        "metadata": {"expires_when": "task_end"},
    }


def test_evaluate_session_closeout_summarizes_item_accuracy():
    cases = [
        _case(
            "closeout_ok",
            [
                _memory("fact", "stable fact: closeout reports are saved.", "working_fact"),
                _memory("rule", "temporary rule: do not commit this run.", "temporary_rule"),
                _memory("recap", "recap: tests passed and docs changed.", "task_state"),
                _memory("pending", "pending choice: keep report or delete it.", "pending_decision"),
            ],
            {
                "fact": {
                    "action": "promote_candidate",
                    "acceptable_actions": ["promote_candidate"],
                    "candidate_memory_types": ["project_fact"],
                },
                "rule": {"action": "discard", "acceptable_actions": ["discard"]},
                "recap": {"action": "summarize", "acceptable_actions": ["summarize"]},
                "pending": {"action": "keep", "acceptable_actions": ["keep"]},
            },
        ),
        _case(
            "closeout_missing_ok",
            [_memory("secret", "filtered secret [REDACTED] token", "temporary_rule")],
            {
                "secret": {
                    "action": "missing",
                    "acceptable_actions": ["missing", "discard", "keep"],
                    "forbid_promote": True,
                }
            },
        ),
    ]

    result = evaluate_session_closeouts(
        cases,
        remote_llm=FakeCloseoutClient(),  # type: ignore[arg-type]
        failure_limit=10,
    )

    assert result.summary.cases == 2
    assert result.summary.items == 5
    assert result.summary.case_passed == 2
    assert result.summary.action_passed == 5
    assert result.summary.strict_passed == 5
    assert result.summary.missing_decisions == 1
    assert result.failures == []


def test_select_cases_samples_closeout_cases_deterministically():
    cases = [
        _case(
            str(index),
            [_memory("rule", f"temporary rule {index}", "temporary_rule")],
            {"rule": {"action": "discard", "acceptable_actions": ["discard"]}},
        )
        for index in range(10)
    ]

    first = select_cases(cases, sample_size=4, sample_seed=23)
    second = select_cases(cases, sample_size=4, sample_seed=23)

    assert [case["name"] for _path, case in first] == [
        case["name"] for _path, case in second
    ]
    assert len(first) == 4
