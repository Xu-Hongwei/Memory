from __future__ import annotations

from collections.abc import Iterable

from memory_system.context_composer import compose_context
from memory_system.graph_recall import graph_recall_for_task
from memory_system.memory_store import MemoryStore
from memory_system.remote import RemoteAdapterError, RemoteEmbeddingClient, RemoteLLMClient
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
    SessionMemoryItemRead,
)
from memory_system.session_memory import SessionMemoryStore, compose_context_with_session
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
    session_store: SessionMemoryStore | None = None,
    session_id: str = "default",
    session_limit: int = 5,
    session_scopes: list[str] | None = None,
) -> OrchestratedRecallResult:
    cleaned_task = task.strip()
    if not cleaned_task:
        raise ValueError("task must not be empty")
    if token_budget < 1:
        raise ValueError("token_budget must be greater than zero")
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    if session_limit < 0:
        raise ValueError("session_limit must not be negative")

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

    plan = _plan_recall(
        cleaned_task,
        scope=scope,
        limit_per_query=max(1, limit),
        planner=planner,
        remote_llm=remote_llm,
    )
    if memory_types:
        plan = plan.model_copy(update={"memory_types": _unique(memory_types)})

    selected_strategy = _select_strategy(
        strategy,
        strategy_hint=plan.strategy_hint,
        needs_llm_judge=plan.needs_llm_judge,
        remote_embedding=remote_embedding,
        remote_llm=remote_llm,
    )
    effective_include_graph = include_graph and plan.include_graph
    effective_session_limit = session_limit
    session_planner_soft_cap = False
    if session_store is not None and session_limit > 0 and not plan.include_session:
        effective_session_limit = min(session_limit, 1)
        session_planner_soft_cap = True
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

    if effective_include_graph:
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
    session_items: list[SessionMemoryItemRead] = []
    if session_store is not None and effective_session_limit > 0:
        session_scope_filter = session_scopes if session_scopes is not None else plan.scopes
        session_items, session_step = _session_recall(
            session_store,
            cleaned_task,
            session_id=session_id,
            scopes=session_scope_filter,
            limit=effective_session_limit,
        )
        steps.append(session_step)
    context = (
        compose_context_with_session(
            cleaned_task,
            session_items,
            final_memories,
            token_budget=token_budget,
        )
        if session_items
        else compose_context(cleaned_task, final_memories, token_budget=token_budget)
    )
    context_ids = set(context.memory_ids)
    session_context_ids = _split_csv(context.metadata.get("session_memory_ids", ""))
    retrieved_ids = _unique(
        memory_id
        for step in steps
        if step.name != "session_recall"
        for memory_id in step.retrieved_memory_ids
    )
    accepted_ids = [memory.id for memory in final_memories]
    skipped_ids = _unique(
        [
            *[
                memory_id
                for step in steps
                if step.name != "session_recall"
                for memory_id in step.skipped_memory_ids
            ],
            *[memory.id for memory in final_memories if memory.id not in context_ids],
        ]
    )
    warnings = _unique(
        [
            *[warning for step in steps for warning in step.warnings],
            *context.warnings,
        ]
    )
    if not final_memories and not session_items:
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
                "planner_source": plan.planner_source,
                "planner_facets": plan.facets,
                "planner_identifiers": plan.identifiers,
                "planner_constraints": plan.constraints,
                "planner_strategy_hint": plan.strategy_hint,
                "planner_include_graph": plan.include_graph,
                "planner_include_session": plan.include_session,
                "planner_needs_llm_judge": plan.needs_llm_judge,
                "planner_confidence": plan.confidence,
                "planner_warnings": plan.planner_warnings,
                "include_graph": include_graph,
                "effective_include_graph": effective_include_graph,
                "token_budget": token_budget,
                "limit": limit,
                "session_id": session_id,
                "session_limit": session_limit,
                "effective_session_limit": effective_session_limit,
                "session_planner_soft_cap": session_planner_soft_cap,
                "session_scopes": session_scopes or [],
                "session_memory_ids": ",".join(session_context_ids),
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
            "session_memory_ids": session_context_ids,
            "planner_source": plan.planner_source,
            "planner_strategy_hint": plan.strategy_hint,
            "planner_confidence": plan.confidence,
            "planner_warnings": plan.planner_warnings,
            "effective_include_graph": effective_include_graph,
            "effective_session_limit": effective_session_limit,
            "session_planner_soft_cap": session_planner_soft_cap,
            "token_budget": token_budget,
            "limit": limit,
        },
    )


def _memory_needed(task: str) -> bool:
    return task.strip().lower() not in LOW_MEMORY_NEED_MESSAGES


def _clean_scope(scope: str | None) -> str | None:
    return scope.strip() if scope and scope.strip() else None


def _plan_recall(
    task: str,
    *,
    scope: str | None,
    limit_per_query: int,
    planner: RecallPlanner | None,
    remote_llm: RemoteLLMClient | None,
) -> RecallPlan:
    fallback_planner = planner or RecallPlanner()
    if remote_llm is not None:
        try:
            return remote_llm.plan_recall(
                task=task,
                scope=scope,
                limit_per_query=limit_per_query,
            )
        except (AttributeError, RemoteAdapterError, ValueError) as exc:
            local_plan = fallback_planner.plan(
                task,
                scope=scope,
                limit_per_query=limit_per_query,
            )
            return local_plan.model_copy(
                update={
                    "planner_source": "fallback",
                    "strategy_hint": "auto",
                    "planner_warnings": [
                        *local_plan.planner_warnings,
                        f"remote_planner_failed:{type(exc).__name__}",
                    ],
                }
            )
    return fallback_planner.plan(task, scope=scope, limit_per_query=limit_per_query)


def _select_strategy(
    strategy: RecallStrategy,
    *,
    strategy_hint: RecallStrategy,
    needs_llm_judge: bool,
    remote_embedding: RemoteEmbeddingClient | None,
    remote_llm: RemoteLLMClient | None,
) -> str:
    if strategy != "auto":
        if strategy in {"guarded_hybrid", "selective_llm_guarded_hybrid"} and remote_embedding is None:
            raise ValueError(f"{strategy} requires remote_embedding")
        if strategy == "selective_llm_guarded_hybrid" and remote_llm is None:
            raise ValueError("selective_llm_guarded_hybrid requires remote_llm")
        return strategy
    if strategy_hint == "selective_llm_guarded_hybrid" or needs_llm_judge:
        if remote_embedding is not None and remote_llm is not None:
            return "selective_llm_guarded_hybrid"
        if remote_embedding is not None:
            return "guarded_hybrid"
        return "keyword"
    if strategy_hint == "guarded_hybrid":
        return "guarded_hybrid" if remote_embedding is not None else "keyword"
    if strategy_hint == "keyword":
        return "keyword"
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


def _session_recall(
    session_store: SessionMemoryStore,
    task: str,
    *,
    session_id: str,
    scopes: list[str],
    limit: int,
) -> tuple[list[SessionMemoryItemRead], OrchestratedRecallStep]:
    session_items = session_store.search(
        task,
        session_id=session_id,
        scopes=scopes,
        limit=limit,
    )
    session_ids = [item.id for item in session_items]
    return session_items, OrchestratedRecallStep(
        name="session_recall",
        strategy="session",
        retrieved_memory_ids=session_ids,
        accepted_memory_ids=session_ids,
        metadata={
            "session_id": session_id,
            "scopes": scopes,
            "limit": limit,
            "count": len(session_items),
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


def _split_csv(value: str) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]
