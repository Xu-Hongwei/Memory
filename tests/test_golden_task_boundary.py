from __future__ import annotations

import json
from pathlib import Path


FIXTURE = Path("tests/fixtures/golden_cases/task_boundary.jsonl")
ALLOWED_ACTIONS = {
    "same_task",
    "new_task",
    "switch_task",
    "task_done",
    "task_cancelled",
    "unclear",
    "no_change",
}


def _cases() -> list[dict]:
    return [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_task_boundary_fixture_shape_and_uniqueness():
    cases = _cases()
    assert len(cases) == 46
    names = [case["name"] for case in cases]
    assert len(names) == len(set(names))

    categories = {case["category"] for case in cases}
    assert {
        "cn_same_task_substep",
        "en_same_task_substep",
        "cn_switch_task",
        "en_switch_task",
        "task_done",
        "task_cancelled",
        "unclear_ack",
        "accept_proposed_next_task",
    } <= categories

    for case in cases:
        assert case["mode"] == "task_boundary"
        assert case["events"]
        assert case["current_task_state"]["title"]
        expected = case["expected"]
        assert expected["action"] in ALLOWED_ACTIONS
        assert expected["action"] in expected["acceptable_actions"]
        assert set(expected["acceptable_actions"]) <= ALLOWED_ACTIONS
