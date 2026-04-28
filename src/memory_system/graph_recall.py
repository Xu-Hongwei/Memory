from __future__ import annotations

from memory_system.context_composer import compose_context
from memory_system.memory_store import MemoryStore
from memory_system.schemas import (
    GraphRecallResult,
    MemoryItemRead,
    MemoryRelationRead,
    RetrievalLogCreate,
)


USABLE_RELATION_CONFIDENCES = {"confirmed", "likely"}


def graph_recall_for_task(
    task: str,
    store: MemoryStore,
    *,
    scope: str | None = None,
    token_budget: int = 2000,
    max_depth: int = 2,
    limit: int = 10,
) -> GraphRecallResult:
    cleaned_task = task.strip()
    if not cleaned_task:
        raise ValueError("task must not be empty")
    if token_budget < 1:
        raise ValueError("token_budget must be greater than zero")
    if max_depth < 1:
        raise ValueError("max_depth must be greater than zero")
    if limit < 1:
        raise ValueError("limit must be greater than zero")

    seed_entities = store.match_entities_for_text(cleaned_task, scope=scope)
    warnings: list[str] = []
    if not seed_entities:
        warnings.append("no seed entities matched task or scope")

    relations = _traverse_relations(store, [entity.id for entity in seed_entities], max_depth)
    memory_ids = _memory_ids_from_relations(relations)
    memories = _load_active_memories(store, memory_ids, scope=scope, limit=limit)
    context = compose_context(cleaned_task, memories, token_budget=token_budget)
    used_memory_ids = set(context.memory_ids)
    store.record_retrieval_log(
        RetrievalLogCreate(
            query=cleaned_task,
            task=cleaned_task,
            task_type="graph_recall",
            scope=scope.strip() if scope and scope.strip() else None,
            source="graph_recall",
            retrieved_memory_ids=[memory.id for memory in memories],
            used_memory_ids=context.memory_ids,
            skipped_memory_ids=[memory.id for memory in memories if memory.id not in used_memory_ids],
            warnings=[*warnings, *context.warnings],
            metadata={
                "seed_entity_ids": [entity.id for entity in seed_entities],
                "relation_ids": [relation.id for relation in relations],
                "max_depth": max_depth,
                "limit": limit,
                "token_budget": token_budget,
            },
        )
    )

    return GraphRecallResult(
        task=cleaned_task,
        scope=scope.strip() if scope and scope.strip() else None,
        seed_entities=seed_entities,
        relations=relations,
        memories=memories,
        context=context,
        warnings=warnings,
    )


def _traverse_relations(
    store: MemoryStore,
    seed_entity_ids: list[str],
    max_depth: int,
) -> list[MemoryRelationRead]:
    frontier = list(dict.fromkeys(seed_entity_ids))
    seen_nodes = set(frontier)
    seen_relation_ids: set[str] = set()
    relations: list[MemoryRelationRead] = []

    for _depth in range(max_depth):
        next_frontier: list[str] = []
        for node_id in frontier:
            for relation in store.list_relations(connected_to_id=node_id, limit=100):
                if relation.id in seen_relation_ids:
                    continue
                seen_relation_ids.add(relation.id)
                if relation.confidence not in USABLE_RELATION_CONFIDENCES:
                    continue
                relations.append(relation)

                for endpoint_id in (relation.from_id, relation.to_id):
                    if endpoint_id.startswith("mem_") or endpoint_id in seen_nodes:
                        continue
                    seen_nodes.add(endpoint_id)
                    next_frontier.append(endpoint_id)
        frontier = next_frontier
        if not frontier:
            break

    return relations


def _memory_ids_from_relations(relations: list[MemoryRelationRead]) -> list[str]:
    memory_ids: list[str] = []
    seen: set[str] = set()
    for relation in relations:
        candidates = [*relation.source_memory_ids]
        if relation.from_id.startswith("mem_"):
            candidates.append(relation.from_id)
        if relation.to_id.startswith("mem_"):
            candidates.append(relation.to_id)
        for memory_id in candidates:
            if memory_id not in seen:
                seen.add(memory_id)
                memory_ids.append(memory_id)
    return memory_ids


def _load_active_memories(
    store: MemoryStore,
    memory_ids: list[str],
    *,
    scope: str | None,
    limit: int,
) -> list[MemoryItemRead]:
    allowed_scopes = {"global"}
    if scope and scope.strip():
        allowed_scopes.add(scope.strip())

    memories: list[MemoryItemRead] = []
    for memory_id in memory_ids:
        memory = store.get_memory(memory_id)
        if memory is None or memory.status != "active":
            continue
        if scope and memory.scope not in allowed_scopes:
            continue
        memories.append(memory)
        if len(memories) >= limit:
            break
    return memories
