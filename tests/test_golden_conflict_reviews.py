from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_system import MemoryEntityCreate, MemoryItemCreate, MemoryRelationCreate, MemoryStore


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "conflict_reviews.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def seed_memories(memories: MemoryStore, definitions: list[dict]) -> dict[str, str]:
    ids_by_alias: dict[str, str] = {}
    for definition in definitions:
        alias = definition["alias"]
        status = definition.get("status", "active")
        payload = {key: value for key, value in definition.items() if key not in {"alias", "status"}}
        memory = memories.add_memory(MemoryItemCreate(**payload))
        if status == "stale":
            memory = memories.mark_stale(memory.id, "Seeded stale memory for review test.")
        elif status == "archived":
            memory = memories.archive_memory(memory.id, "Seeded archived memory for review test.")
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


def test_golden_conflict_review_suite_shape():
    cases = load_cases()
    categories = {case["category"] for case in cases}

    assert len(cases) == 300
    assert len({case["name"] for case in cases}) == len(cases)
    assert categories == {
        "accept_new_resolution",
        "archive_all_resolution",
        "ask_user_resolution",
        "duplicate_pending_review",
        "inactive_or_low_confidence_no_review",
        "keep_existing_resolution",
        "same_target_no_review",
    }
    assert all(case.get("synthetic") is True for case in cases)


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["name"])
def test_golden_conflict_review_cases(case):
    memories = MemoryStore(":memory:")
    memory_ids = seed_memories(memories, case["memories"])
    entity_ids = seed_entities(memories, case["entities"])
    seed_relations(memories, case["relations"], entity_ids, memory_ids)

    action = case["action"]
    expected = case["expected"]
    reviews = memories.create_conflict_reviews(
        scope=action["scope"],
        relation_type=action["relation_type"],
    )
    assert len(reviews) == expected["review_count"]

    if action["type"] == "create_twice":
        second_reviews = memories.create_conflict_reviews(
            scope=action["scope"],
            relation_type=action["relation_type"],
        )
        assert len(second_reviews) == expected["second_review_count"]
        return

    if expected["review_count"] == 0:
        return

    review = reviews[0]
    if "recommended_keep_aliases" in expected:
        assert review.recommended_keep_memory_ids == [
            memory_ids[alias] for alias in expected["recommended_keep_aliases"]
        ]

    if action["resolve_action"] is not None:
        resolved = memories.resolve_conflict_review(
            review.id,
            action=action["resolve_action"],
            reason="Golden conflict review resolution.",
        )
        assert resolved.status == expected["review_status"]

    for alias, status in expected.get("statuses", {}).items():
        memory = memories.get_memory(memory_ids[alias])
        assert memory is not None
        assert memory.status == status

    if "conflicts_after" in expected:
        assert len(
            memories.detect_graph_conflicts(
                scope=action["scope"],
                relation_type=action["relation_type"],
            )
        ) == expected["conflicts_after"]
