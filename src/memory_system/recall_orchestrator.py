from __future__ import annotations

from collections.abc import Iterable

from memory_system.context_composer import compose_context
from memory_system.graph_recall import graph_recall_for_task
from memory_system.memory_store import MemoryStore
from memory_system.remote import RemoteEmbeddingClient, RemoteLLMClient
from memory_system.remote_evaluation import (
    remote_guarded_hybrid_search,
    remote_selective_llm_guarded_hybrid_search,
)
from memory_system.schemas import (
    MemoryItemRead,
    MemoryType,
    OrchestratedRecallResult,
    OrchestratedRecallStep,
    RecallPlan,
    RecallStrategy,
    RetrievalLogCreate,
    SearchMemoryInput,
)
from memory_system.task_recall import RecallPlanner


LOW_MEMORY_NEED_MESSAGES = {
    "ok",
    "okay",
    "yes",
    "thanks",
    "thank you",
    "thx",
    "\u53ef\u4ee5",
    "\u597d",
    "\u597d\u7684",
    "\u55ef",
    "\u8c22\u8c22",
}


def orchestrate_recall(
    task: str,
    store: MemoryStore,
    *,
    scope: str | None = None,
    strategy: RecallStrategy = "auto",
    token_budget: int = 2000,
    limit: int = 10,
    memory_types: list[MemoryType] | None = None,
    include_graph: bool = True,
    remote_embedding: RemoteEmbeddingClient | None = None,
    remote_llm: RemoteLLMClient | None = None,
    model: str | None = None,
    planner: RecallPlanner | None = None,
    guard_top_k: int = 3,
    guard_min_similarity: float = 0.20,
    guard_ambiguity_margin: float = 0.03,
    selective_min_similarity: float = 0.20,
    selective_ambiguity_margin: float = 0.03,
) -> OrchestratedRecallResult:
    cleaned_task = task.strip()
    if not cleaned_task:
        raise ValueError("task must not be empty")
    if token_budget < 1:
        raise ValueError("token_budget must be greater than zero")
    if limit < 1:
        raise ValueError("limit must be greater than zero")

    if not _memory_needed(cleaned_task):
        context = compose_context(cleaned_task, [], token_budget=token_budget)
        warning = "recall_skipped_low_memory_need"
        store.record_retrieval_log(
            RetrievalLogCreate(
                query=cleaned_task,
                task=cleaned_task,
                task_type="orchestrated_recall",
                scope=_clean_scope(scope),
                source="orchestrated_recall",
                warnings=[warning, *context.warnings],
                metadata={
                    "strategy": strategy,
                    "selected_strategy": "none",
                    "memory_needed": False,
                    "token_budget": token_budget,
                },
            )
        )
        return OrchestratedRecallResult(
            task=cleaned_task,
            scope=_clean_scope(scope),
            strategy=strategy,
            selected_strategy="none",
            memory_needed=False,
            context=context,
            warnings=[warning, *context.warnings],
            metadata={"token_budget": token_budget},
        )

    active_planner = planner or RecallPlanner()
    plan = active_planner.plan(cleaned_task, scope=scope, limit_per_query=max(1, limit))
    if memory_types:
        plan = plan.model_copy(update={"memory_types": _unique(memory_types)})

    selected_strategy = _select_strategy(
        strategy,
        remote_embedding=remote_embedding,
        remote_llm=remote_llm,
    )
    steps: list[OrchestratedRecallStep] = []
    candidate_memories: list[MemoryItemRead] = []

    if selected_strategy == "keyword":
        candidate_memories, step = _keyword_recall(
            store,
            plan,
            limit=limit,
        )
        steps.append(step)
    elif selected_strategy == "guarded_hybrid":
        candidate_memories, step = _guarded_hybrid_recall(
            store,
            plan,
            remote_embedding=remote_embedding,
            model=model,
            limit=limit,
            guard_top_k=guard_top_k,
            guard_min_similarity=guard_min_similarity,
            guard_ambiguity_margin=guard_ambiguity_margin,
        )
        steps.append(step)
    elif selected_strategy == "selective_llm_guarded_hybrid":
        candidate_memories, step = _selective_llm_guarded_hybrid_recall(
            store,
            plan,
            remote_embedding=remote_embedding,
            remote_llm=remote_llm,
            model=model,
            limit=limit,
            guard_top_k=guard_top_k,
            guard_min_similarity=guard_min_similarity,
            guard_ambiguity_margin=guard_ambiguity_margin,
            selective_min_similarity=selective_min_similarity,
            selective_ambiguity_margin=selective_ambiguity_margin,
        )
        steps.append(step)
    else:
        raise ValueError(f"unsupported recall strategy: {selected_strategy}")

    if include_graph:
        graph_memories, graph_step = _graph_recall(
            store,
            cleaned_task,
            scope=scope,
            token_budget=token_budget,
            limit=limit,
        )
        steps.append(graph_step)
        candidate_memories = _merge_memories(candidate_memories, graph_memories)

    final_memories = candidate_memories[:limit]
    context = compose_context(cleaned_task, final_memories, token_budget=token_budget)
    context_ids = set(context.memory_ids)
    retrieved_ids = _unique(
        memory_id for step in steps for memory_id in step.retrieved_memory_ids
    )
    accepted_ids = [memory.id for memory in final_memories]
    skipped_ids = _unique(
        [
            *[memory_id for step in steps for memory_id in step.skipped_memory_ids],
            *[memory.id for memory in final_memories if memory.id not in context_ids],
        ]
    )
    warnings = _unique(
        [
            *[warning for step in steps for warning in step.warnings],
            *context.warnings,
        ]
    )
    if not final_memories:
        warnings.append("no_memories_accepted")

    store.record_retrieval_log(
        RetrievalLogCreate(
            query=cleaned_task,
            task=cleaned_task,
            task_type=plan.intent,
            scope=plan.scope,
            source="orchestrated_recall",
            retrieved_memory_ids=retrieved_ids or accepted_ids,
            used_memory_ids=context.memory_ids,
            skipped_memory_ids=skipped_ids,
            warnings=warnings,
            metadata={
                "strategy": strategy,
                "selected_strategy": selected_strategy,
                "memory_needed": True,
                "query_terms": plan.query_terms,
                "memory_types": plan.memory_types,
                "scopes": plan.scopes,
                "include_graph": include_graph,
                "token_budget": token_budget,
                "limit": limit,
                "steps": [step.model_dump() for step in steps],
            },
        )
    )
    return OrchestratedRecallResult(
        task=cleaned_task,
        scope=plan.scope,
        strategy=strategy,
        selected_strategy=selected_strategy,
        memory_needed=True,
        plan=plan,
        memories=final_memories,
        context=context,
        steps=steps,
        warnings=warnings,
        metadata={
            "retrieved_memory_ids": retrieved_ids,
            "accepted_memory_ids": accepted_ids,
            "used_memory_ids": context.memory_ids,
            "skipped_memory_ids": skipped_ids,
            "token_budget": token_budget,
            "limit": limit,
        },
    )


def _memory_needed(task: str) -> bool:
    return task.strip().lower() not in LOW_MEMORY_NEED_MESSAGES


def _clean_scope(scope: str | None) -> str | None:
    return scope.strip() if scope and scope.strip() else None


def _select_strategy(
    strategy: RecallStrategy,
    *,
    remote_embedding: RemoteEmbeddingClient | None,
    remote_llm: RemoteLLMClient | None,
) -> str:
    if strategy != "auto":
        if strategy in {"guarded_hybrid", "selective_llm_guarded_hybrid"} and remote_embedding is None:
            raise ValueError(f"{strategy} requires remote_embedding")
        if strategy == "selective_llm_guarded_hybrid" and remote_llm is None:
            raise ValueError("selective_llm_guarded_hybrid requires remote_llm")
        return strategy
    if remote_embedding is not None and remote_llm is not None:
        return "selective_llm_guarded_hybrid"
    if remote_embedding is not None:
        return "guarded_hybrid"
    return "keyword"


def _keyword_recall(
    store: MemoryStore,
    plan: RecallPlan,
    *,
    limit: int,
) -> tuple[list[MemoryItemRead], OrchestratedRecallStep]:
    found: dict[str, MemoryItemRead] = {}
    first_seen: dict[str, int] = {}
    for query in plan.query_terms:
        results = store.search_memory(
            SearchMemoryInput(
                query=query,
                memory_types=plan.memory_types,
                scopes=plan.scopes,
                limit=plan.limit_per_query,
                retrieval_mode="keyword",
            ),
            log=False,
        )
        for memory in results:
            if memory.id not in found:
                first_seen[memory.id] = len(first_seen)
            found[memory.id] = memory
    memories = sorted(
        found.values(),
        key=lambda memory: _rank_memory(memory, plan, first_seen[memory.id]),
        reverse=True,
    )[:limit]
    return memories, OrchestratedRecallStep(
        name="keyword_recall",
        strategy="keyword",
        retrieved_memory_ids=[memory.id for memory in memories],
        accepted_memory_ids=[memory.id for memory in memories],
        metadata={
            "query_terms": plan.query_terms,
            "memory_types": plan.memory_types,
            "scopes": plan.scopes,
        },
    )


def _guarded_hybrid_recall(
    store: MemoryStore,
    plan: RecallPlan,
    *,
    remote_embedding: RemoteEmbeddingClient | None,
    model: str | None,
    limit: int,
    guard_top_k: int,
    guard_min_similarity: float,
    guard_ambiguity_margin: float,
) -> tuple[list[MemoryItemRead], OrchestratedRecallStep]:
    if remote_embedding is None:
        raise ValueError("guarded_hybrid requires remote_embedding")
    result = remote_guarded_hybrid_search(
        store,
        remote_embedding,
        query=plan.task,
        scopes=plan.scopes,
        memory_types=plan.memory_types,
        model=model,
        limit=limit,
        guard_top_k=guard_top_k,
        min_similarity=guard_min_similarity,
        ambiguity_margin=guard_ambiguity_margin,
    )
    retrieved_ids = [decision.memory_id for decision in result.decisions]
    accepted_ids = [memory.id for memory in result.memories]
    return result.memories, OrchestratedRecallStep(
        name="guarded_hybrid_recall",
        strategy="guarded_hybrid",
        retrieved_memory_ids=retrieved_ids,
        accepted_memory_ids=accepted_ids,
        skipped_memory_ids=[memory_id for memory_id in retrieved_ids if memory_id not in accepted_ids],
        warnings=result.warnings,
        metadata={
            **result.metadata,
            "provider": result.provider,
            "model": result.model,
            "decisions": [decision.model_dump() for decision in result.decisions],
        },
    )


def _selective_llm_guarded_hybrid_recall(
    store: MemoryStore,
    plan: RecallPlan,
    *,
    remote_embedding: RemoteEmbeddingClient | None,
    remote_llm: RemoteLLMClient | None,
    model: str | None,
    limit: int,
    guard_top_k: int,
    guard_min_similarity: float,
    guard_ambiguity_margin: float,
    selective_min_similarity: float,
    selective_ambiguity_margin: float,
) -> tuple[list[MemoryItemRead], OrchestratedRecallStep]:
    if remote_embedding is None or remote_llm is None:
        raise ValueError("selective_llm_guarded_hybrid requires remote_embedding and remote_llm")
    result = remote_selective_llm_guarded_hybrid_search(
        store,
        remote_embedding,
        remote_llm,
        query=plan.task,
        scopes=plan.scopes,
        memory_types=plan.memory_types,
        model=model,
        limit=limit,
        guard_top_k=guard_top_k,
        min_similarity=guard_min_similarity,
        ambiguity_margin=guard_ambiguity_margin,
        selective_min_similarity=selective_min_similarity,
        selective_ambiguity_margin=selective_ambiguity_margin,
    )
    retrieved_ids = [decision.memory_id for decision in result.local_guard.decisions]
    accepted_ids = [memory.id for memory in result.memories]
    return result.memories, OrchestratedRecallStep(
        name="selective_llm_guarded_hybrid_recall",
        strategy="selective_llm_guarded_hybrid",
        retrieved_memory_ids=retrieved_ids,
        accepted_memory_ids=accepted_ids,
        skipped_memory_ids=[memory_id for memory_id in retrieved_ids if memory_id not in accepted_ids],
        warnings=result.warnings,
        metadata={
            **result.metadata,
            "provider": result.provider,
            "model": result.model,
            "local_decisions": [
                decision.model_dump() for decision in result.local_guard.decisions
            ],
            "judge": result.judge.model_dump(),
        },
    )


def _graph_recall(
    store: MemoryStore,
    task: str,
    *,
    scope: str | None,
    token_budget: int,
    limit: int,
) -> tuple[list[MemoryItemRead], OrchestratedRecallStep]:
    result = graph_recall_for_task(
        task,
        store,
        scope=scope,
        token_budget=token_budget,
        limit=limit,
    )
    return result.memories, OrchestratedRecallStep(
        name="graph_recall",
        strategy="graph",
        retrieved_memory_ids=[memory.id for memory in result.memories],
        accepted_memory_ids=[memory.id for memory in result.memories],
        warnings=[*result.warnings, *result.context.warnings],
        metadata={
            "seed_entity_ids": [entity.id for entity in result.seed_entities],
            "relation_ids": [relation.id for relation in result.relations],
        },
    )


def _rank_memory(memory: MemoryItemRead, plan: RecallPlan, first_seen: int) -> tuple[int, int, int, int]:
    scope_score = 0
    if memory.scope in plan.scopes:
        scope_score = 100 - (plan.scopes.index(memory.scope) * 10)
    type_score = 0
    if memory.memory_type in plan.memory_types:
        type_score = 50 - plan.memory_types.index(memory.memory_type)
    confidence_score = {"confirmed": 5, "likely": 3, "inferred": 1, "unknown": 0}.get(
        memory.confidence,
        0,
    )
    return scope_score, type_score, confidence_score, -first_seen


def _merge_memories(
    primary: list[MemoryItemRead],
    secondary: list[MemoryItemRead],
) -> list[MemoryItemRead]:
    merged: list[MemoryItemRead] = []
    seen: set[str] = set()
    for memory in [*primary, *secondary]:
        if memory.id in seen:
            continue
        seen.add(memory.id)
        merged.append(memory)
    return merged


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
