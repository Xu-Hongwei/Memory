from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_system import MemoryItemCreate, MemoryStore, recall_for_task


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "task_recall.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def seed_memories(memories: MemoryStore, definitions: list[dict]) -> dict[str, str]:
    ids_by_alias: dict[str, str] = {}
    for definition in definitions:
        alias = definition["alias"]
        status = definition.get("status", "active")
        payload = {key: value for key, value in definition.items() if key not in {"alias", "status"}}
        memory = memories.add_memory(MemoryItemCreate(**payload))
        if status == "stale":
            memory = memories.mark_stale(memory.id, "Seeded stale memory for task recall test.")
        elif status == "archived":
            memory = memories.archive_memory(memory.id, "Seeded archived memory for task recall test.")
        ids_by_alias[alias] = memory.id
    return ids_by_alias


def aliases_for_ids(ids_by_alias: dict[str, str], memory_ids: list[str]) -> list[str]:
    alias_by_id = {memory_id: alias for alias, memory_id in ids_by_alias.items()}
    return [alias_by_id[memory_id] for memory_id in memory_ids if memory_id in alias_by_id]


def test_golden_task_recall_suite_shape():
    cases = load_cases()
    categories = {case["category"] for case in cases}

    assert len(cases) == 300
    assert len({case["name"] for case in cases}) == len(cases)
    assert categories == {
        "cross_scope_exclusion_recall",
        "debug_recall",
        "inactive_exclusion_recall",
        "preference_recall",
        "project_structure_recall",
        "startup_docs_recall",
        "verification_recall",
    }
    assert all(case.get("synthetic") is True for case in cases)


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["name"])
def test_golden_task_recall_cases(case):
    memories = MemoryStore(":memory:")
    ids_by_alias = seed_memories(memories, case["memories"])
    result = recall_for_task(case["task"], memories, scope=case["scope"], token_budget=3000)

    result_aliases = aliases_for_ids(ids_by_alias, [memory.id for memory in result.memories])
    context_aliases = aliases_for_ids(ids_by_alias, result.context.memory_ids)
    expected = case["expected"]

    if "intent" in expected:
        assert result.plan.intent == expected["intent"]
    for alias in expected["included_aliases"]:
        assert alias in result_aliases
        assert alias in context_aliases
    for alias in expected["excluded_aliases"]:
        assert alias not in result_aliases
        assert alias not in context_aliases
