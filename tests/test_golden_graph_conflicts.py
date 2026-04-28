from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_system import MemoryEntityCreate, MemoryItemCreate, MemoryRelationCreate, MemoryStore


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "graph_conflicts.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def seed_memories(memories: MemoryStore, definitions: list[dict]) -> dict[str, str]:
    ids_by_alias: dict[str, str] = {}
    for definition in definitions:
        alias = definition["alias"]
        status = definition.get("status", "active")
        payload = {key: value for key, value in definition.items() if key not in {"alias", "status"}}
        memory = memories.add_memory(MemoryItemCreate(**payload))
        if status == "stale":
            memory = memories.mark_stale(memory.id, "Seeded stale memory for graph conflict test.")
        elif status == "archived":
            memory = memories.archive_memory(memory.id, "Seeded archived memory for graph conflict test.")
        ids_by_alias[alias] = memory.id
    return ids_by_alias


def seed_entities(memories: MemoryStore, definitions: list[dict]) -> dict[str, str]:
    ids_by_alias: dict[str, str] = {}
    for definition in definitions:
        alias = definition["alias"]
        payload = {key: value for key, value in definition.items() if key != "alias"}
        entity = memories.upsert_entity(MemoryEntityCreate(**payload))
        ids_by_alias[alias] = entity.id
    return ids_by_alias


def seed_relations(
    memories: MemoryStore,
    definitions: list[dict],
    entity_ids: dict[str, str],
    memory_ids: dict[str, str],
) -> None:
    for definition in definitions:
        source_memory_ids = [
            memory_ids[alias] for alias in definition.get("source_memory_aliases", [])
        ]
        source_event_ids = [
            event_id
            for alias in definition.get("source_memory_aliases", [])
            for event_id in memories.get_memory(memory_ids[alias]).source_event_ids
        ]
        memories.create_relation(
            MemoryRelationCreate(
                from_id=entity_ids[definition["from_alias"]],
                relation_type=definition["relation_type"],
                to_id=entity_ids[definition["to_alias"]],
                confidence=definition.get("confidence", "confirmed"),
                source_memory_ids=source_memory_ids,
                source_event_ids=source_event_ids,
            )
        )


def test_golden_graph_conflict_suite_shape():
    cases = load_cases()
    categories = {case["category"] for case in cases}

    assert len(cases) == 300
    assert len({case["name"] for case in cases}) == len(cases)
    assert categories == {
        "cross_scope_exclusion",
        "database_conflict",
        "inactive_source_exclusion",
        "language_conflict",
        "low_confidence_relation_exclusion",
        "same_target_no_conflict",
        "start_command_conflict",
    }
    assert all(case.get("synthetic") is True for case in cases)


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["name"])
def test_golden_graph_conflict_cases(case):
    memories = MemoryStore(":memory:")
    memory_ids = seed_memories(memories, case["memories"])
    entity_ids = seed_entities(memories, case["entities"])
    seed_relations(memories, case["relations"], entity_ids, memory_ids)

    action = case["action"]
    conflicts = memories.detect_graph_conflicts(
        scope=action["scope"],
        relation_type=action["relation_type"],
    )

    expected = case["expected"]
    assert len(conflicts) == expected["conflict_count"]
    if expected["conflict_count"] == 0:
        return

    conflict = conflicts[0]
    expected_conflict = expected["conflicts"][0]
    assert conflict.from_entity.id == entity_ids[expected_conflict["from_alias"]]
    assert conflict.relation_type == expected_conflict["relation_type"]
    assert [entity.id for entity in conflict.target_entities] == [
        entity_ids[alias] for alias in expected_conflict["target_aliases"]
    ]
    assert [memory.id for memory in conflict.memories] == [
        memory_ids[alias] for alias in expected_conflict["memory_aliases"]
    ]
