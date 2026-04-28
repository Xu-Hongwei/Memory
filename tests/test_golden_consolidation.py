from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_system import MemoryItemCreate, MemoryStore, SearchMemoryInput


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "consolidation.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def seed_memories(memories: MemoryStore, definitions: list[dict]) -> dict[str, str]:
    ids_by_alias: dict[str, str] = {}
    for definition in definitions:
        alias = definition["alias"]
        status = definition.get("status", "active")
        payload = {key: value for key, value in definition.items() if key not in {"alias", "status"}}
        memory = memories.add_memory(MemoryItemCreate(**payload))
        if status == "stale":
            memory = memories.mark_stale(memory.id, "Seeded stale memory for consolidation test.")
        elif status == "archived":
            memory = memories.archive_memory(memory.id, "Seeded archived memory for consolidation test.")
        ids_by_alias[alias] = memory.id
    return ids_by_alias


def aliases_for_search(
    memories: MemoryStore,
    ids_by_alias: dict[str, str],
    query: str,
) -> list[str]:
    alias_by_id = {memory_id: alias for alias, memory_id in ids_by_alias.items()}
    results = memories.search_memory(SearchMemoryInput(query=query))
    return [alias_by_id[item.id] for item in results if item.id in alias_by_id]


def test_golden_consolidation_suite_shape():
    cases = load_cases()
    categories = {case["category"] for case in cases}

    assert len(cases) == 300
    assert len({case["name"] for case in cases}) == len(cases)
    assert categories == {
        "merge_project_fact",
        "merge_user_preference",
        "skip_cross_scope",
        "skip_different_type",
        "skip_inactive",
        "skip_low_confidence",
    }
    assert all(case.get("synthetic") is True for case in cases)


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["name"])
def test_golden_consolidation_cases(case):
    memories = MemoryStore(":memory:")
    ids_by_alias = seed_memories(memories, case["memories"])
    action = case["action"]
    expected = case["expected"]

    candidates = memories.propose_consolidations(
        scope=action.get("scope"),
        memory_type=action.get("memory_type"),
    )

    assert len(candidates) == expected["candidate_count"]
    if action["type"] == "propose_and_commit":
        candidate = candidates[0]
        assert {
            alias
            for alias, memory_id in ids_by_alias.items()
            if memory_id in candidate.source_memory_ids
        } == set(expected["source_aliases"])
        consolidated = memories.commit_consolidation(candidate.id, reason="Golden consolidation.")
        ids_by_alias["consolidated"] = consolidated.id
        assert memories.get_consolidation_candidate(candidate.id).status == "committed"

    for alias, status in expected.get("statuses", {}).items():
        memory = memories.get_memory(ids_by_alias[alias])
        assert memory is not None
        assert memory.status == status

    if "search_query" in expected:
        assert aliases_for_search(memories, ids_by_alias, expected["search_query"]) == expected[
            "search_aliases"
        ]

    for alias, change_types in expected.get("versions", {}).items():
        assert [version.change_type for version in memories.list_versions(ids_by_alias[alias])] == (
            change_types
        )
