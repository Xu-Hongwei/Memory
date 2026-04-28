from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_system import MemoryItemCreate, MemoryStore, SearchMemoryInput
from memory_system.schemas import MemoryCandidateCreate


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "lifecycle.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def seed_store(case: dict) -> tuple[MemoryStore, dict[str, str]]:
    memories = MemoryStore(":memory:")
    ids_by_alias: dict[str, str] = {}
    for definition in case["memories"]:
        alias = definition["alias"]
        payload = {key: value for key, value in definition.items() if key != "alias"}
        item = memories.add_memory(MemoryItemCreate(**payload))
        ids_by_alias[alias] = item.id
    for definition in case.get("candidates", []):
        alias = definition["alias"]
        payload = {key: value for key, value in definition.items() if key != "alias"}
        candidate = memories.create_candidate(MemoryCandidateCreate(**payload))
        ids_by_alias[alias] = candidate.id
    return memories, ids_by_alias


def resolve_search_aliases(
    memories: MemoryStore,
    ids_by_alias: dict[str, str],
    query: str,
) -> list[str]:
    alias_by_id = {item_id: alias for alias, item_id in ids_by_alias.items()}
    results = memories.search_memory(SearchMemoryInput(query=query))
    return [alias_by_id[item.id] for item in results]


def test_golden_lifecycle_suite_shape():
    cases = load_cases()
    categories = {case["category"] for case in cases}

    assert len(cases) == 300
    assert len({case["name"] for case in cases}) == len(cases)
    assert categories == {
        "archive_excludes_retrieval",
        "mark_stale_excludes_retrieval",
        "stale_then_archive_versions",
        "supersede_replaces_active",
    }


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["name"])
def test_golden_lifecycle_cases(case):
    memories, ids_by_alias = seed_store(case)
    action = case["action"]

    if action["type"] == "mark_stale":
        memories.mark_stale(ids_by_alias[action["alias"]], action["reason"])
    elif action["type"] == "archive":
        memories.archive_memory(ids_by_alias[action["alias"]], action["reason"])
    elif action["type"] == "supersede":
        new = memories.supersede_memory(
            ids_by_alias[action["old_alias"]],
            ids_by_alias[action["candidate_alias"]],
            action["reason"],
        )
        ids_by_alias[action["candidate_alias"]] = new.id
    elif action["type"] == "stale_then_archive":
        memory_id = ids_by_alias[action["alias"]]
        memories.mark_stale(memory_id, action["stale_reason"])
        memories.archive_memory(memory_id, action["archive_reason"])
    else:
        raise AssertionError(f"unknown action: {action['type']}")

    expected = case["expected"]
    for alias, status in expected["statuses"].items():
        memory = memories.get_memory(ids_by_alias[alias])
        assert memory is not None
        assert memory.status == status

    assert resolve_search_aliases(memories, ids_by_alias, expected["search_query"]) == expected[
        "search_aliases"
    ]

    for alias, change_types in expected["versions"].items():
        memory_id = ids_by_alias[alias]
        assert [version.change_type for version in memories.list_versions(memory_id)] == change_types
