from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_system import (
    MemoryCandidateCreate,
    MemoryEntityCreate,
    MemoryItemCreate,
    MemoryRelationCreate,
    MemoryStore,
    graph_recall_for_task,
)


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "graph_recall.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def seed_memories(memories: MemoryStore, definitions: list[dict]) -> dict[str, str]:
    ids_by_alias: dict[str, str] = {}
    for definition in definitions:
        alias = definition["alias"]
        status = definition.get("status", "active")
        payload = {key: value for key, value in definition.items() if key not in {"alias", "status"}}
        memory = memories.add_memory(MemoryItemCreate(**payload))
        if status == "stale":
            memory = memories.mark_stale(memory.id, "Seeded stale memory for graph recall test.")
        elif status == "archived":
            memory = memories.archive_memory(memory.id, "Seeded archived memory for graph recall test.")
        elif status == "superseded":
            candidate = memories.create_candidate(
                MemoryCandidateCreate(
                    content=f"replacement for {memory.content}",
                    memory_type=memory.memory_type,
                    scope=memory.scope,
                    subject=memory.subject,
                    source_event_ids=[f"evt_replacement_{alias}"],
                    reason="Seeded replacement for graph recall test.",
                    confidence="confirmed",
                    risk="low",
                )
            )
            memories.supersede_memory(memory.id, candidate.id, "Seeded superseded memory.")
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


def aliases_for_memories(ids_by_alias: dict[str, str], memory_ids: list[str]) -> list[str]:
    alias_by_id = {memory_id: alias for alias, memory_id in ids_by_alias.items()}
    return [alias_by_id[memory_id] for memory_id in memory_ids if memory_id in alias_by_id]


def test_golden_graph_recall_suite_shape():
    cases = load_cases()
    categories = {case["category"] for case in cases}

    assert len(cases) == 300
    assert len({case["name"] for case in cases}) == len(cases)
    assert categories == {
        "cross_scope_exclusion",
        "error_solution_recall",
        "file_entity_recall",
        "low_confidence_relation_exclusion",
        "old_memory_exclusion",
        "repo_entity_recall",
        "tool_entity_recall",
    }
    assert all(case.get("synthetic") is True for case in cases)


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["name"])
def test_golden_graph_recall_cases(case):
    memories = MemoryStore(":memory:")
    memory_ids = seed_memories(memories, case["memories"])
    entity_ids = seed_entities(memories, case["entities"])
    seed_relations(memories, case["relations"], entity_ids, memory_ids)

    result = graph_recall_for_task(
        case["task"],
        memories,
        scope=case["scope"],
        max_depth=case["max_depth"],
        token_budget=3000,
    )
    result_aliases = aliases_for_memories(memory_ids, [memory.id for memory in result.memories])
    context_aliases = aliases_for_memories(memory_ids, result.context.memory_ids)
    expected = case["expected"]

    for alias in expected["included_aliases"]:
        assert alias in result_aliases
        assert alias in context_aliases
    for alias in expected["excluded_aliases"]:
        assert alias not in result_aliases
        assert alias not in context_aliases
