from __future__ import annotations

import json
import math
import time
from pathlib import Path

from memory_system.event_log import EventLog
from memory_system.memory_store import MemoryStore, build_memory_embedding_text
from memory_system.remote import RemoteAdapterError, RemoteEmbeddingClient, RemoteLLMClient
from memory_system.schemas import (
    EventRead,
    MemoryCandidateCreate,
    MemoryItemCreate,
    MemoryItemRead,
    MemoryType,
    RemoteGuardedSearchResult,
    RemoteLLMGuardedSearchResult,
    RemoteEmbeddingBackfillResult,
    RemoteCandidateEvaluationItem,
    RemoteCandidateEvaluationResult,
    RemoteCandidateEvaluationSummary,
    RemoteRecallJudgeResult,
    RemoteRetrievalEvaluationItem,
    RemoteRetrievalEvaluationResult,
    RemoteRetrievalEvaluationSummary,
    RemoteRetrievalCategorySummary,
    RemoteRetrievalGuardDecisionRead,
    RemoteRetrievalJudgeRead,
    SearchMemoryInput,
)


INTENT_SIGNATURES = (
    {
        "label": "release",
        "query_terms": (
            "ship",
            "going live",
            "launch",
            "publishing",
            "publish",
            "rollout",
            "release",
            "deployment",
            "deploy",
            "上线",
            "发布",
        ),
        "memory_terms": (
            "deployment",
            "deploy",
            "release",
            "ruff",
            "pytest",
            "ci",
            "上线",
            "发布",
        ),
        "memory_types": ("workflow",),
    },
    {
        "label": "schema",
        "query_terms": (
            "storage shape",
            "table",
            "schema",
            "data model",
            "persisted field",
            "column",
            "database",
            "migration",
            "数据结构",
            "字段",
            "表",
        ),
        "memory_terms": (
            "schema",
            "migration",
            "database",
            "table",
            "field",
            "column",
            "数据结构",
            "迁移",
        ),
        "memory_types": ("workflow", "project_fact"),
    },
    {
        "label": "encoding",
        "query_terms": (
            "mojibake",
            "garbled",
            "unreadable",
            "multilingual",
            "character corruption",
            "scrambled",
            "powershell",
            "乱码",
            "编码",
        ),
        "memory_terms": (
            "utf-8",
            "65001",
            "code page",
            "console",
            "encoding",
            "garbled",
            "windows",
            "乱码",
            "编码",
        ),
        "memory_types": ("troubleshooting", "environment_fact"),
    },
    {
        "label": "browser",
        "query_terms": (
            "local web",
            "running page",
            "real tab",
            "interaction testing",
            "local frontend",
            "localhost",
            "browser",
            "页面",
            "浏览器",
        ),
        "memory_terms": (
            "browser",
            "localhost",
            "in-app browser",
            "ui validation",
            "frontend",
            "visual",
            "浏览器",
        ),
        "memory_types": ("workflow",),
    },
    {
        "label": "secret",
        "query_terms": (
            "credential",
            "private access",
            "authentication material",
            "bearer",
            "confidential",
            "api key",
            "token",
            "secret",
            "密钥",
            "敏感",
        ),
        "memory_terms": (
            "api key",
            "token",
            "secret",
            "credential",
            "security",
            "sensitive",
            "密钥",
            "敏感",
        ),
        "memory_types": ("tool_rule", "user_preference"),
    },
    {
        "label": "docs",
        "query_terms": (
            "paperwork",
            "written material",
            "project notes",
            "user-visible",
            "explanations aligned",
            "readme",
            "documentation",
            "docs",
            "文档",
            "说明",
        ),
        "memory_terms": (
            "readme",
            "documentation",
            "docs",
            "project notes",
            "explanations",
            "文档",
            "说明",
        ),
        "memory_types": ("workflow", "project_fact"),
    },
    {
        "label": "dependency",
        "query_terms": (
            "package import",
            "module cannot",
            "module not found",
            "missing library",
            "required dependency",
            "python requirement",
            "dependency",
            "依赖",
            "包",
        ),
        "memory_terms": (
            "pip install",
            "python packages",
            "dependency",
            "library",
            "module",
            "package",
            "依赖",
        ),
        "memory_types": ("tool_rule", "environment_fact", "troubleshooting"),
    },
    {
        "label": "server",
        "query_terms": (
            "old version",
            "live endpoint",
            "stale",
            "which process",
            "local url",
            "active port",
            "service",
            "restart",
            "进程",
            "端口",
            "服务",
        ),
        "memory_terms": (
            "active port",
            "process",
            "service",
            "endpoint",
            "restart",
            "runtime",
            "端口",
            "进程",
        ),
        "memory_types": ("troubleshooting", "environment_fact"),
    },
    {
        "label": "assets",
        "query_terms": (
            "blank",
            "images",
            "visually empty",
            "canvas",
            "media area",
            "visual update",
            "assets",
            "渲染",
            "空白",
        ),
        "memory_terms": (
            "assets",
            "render",
            "frontend",
            "visual",
            "canvas",
            "media",
            "images",
            "渲染",
        ),
        "memory_types": ("workflow", "project_fact"),
    },
    {
        "label": "answer_style",
        "query_terms": (
            "phrased",
            "response style",
            "uncertain implementation",
            "language and evidence",
            "confirmed versus guessed",
            "chinese",
            "verified facts",
            "inferences",
            "回答风格",
            "中文",
            "推断",
        ),
        "memory_terms": (
            "chinese",
            "verified facts",
            "inferences",
            "communication",
            "answer style",
            "中文",
            "推断",
        ),
        "memory_types": ("user_preference",),
    },
)

CONCRETE_FACT_QUESTION_TERMS = (
    "是多少",
    "是哪一个",
    "是哪家",
    "哪一个",
    "哪个",
    "哪家",
    "叫什么",
    "是什么",
    "在哪个",
    "哪台",
    "which",
    "what is",
    "what's",
    "where is",
)
CONCRETE_FACT_TARGET_TERMS = (
    "sla",
    "域名",
    "正式访问域名",
    "生产域名",
    "云区域",
    "region",
    "namespace",
    "runner",
    "支付网关",
    "payment gateway",
    "错误监控",
    "monitoring",
    "客服工单",
    "ticket",
    "缓存集群",
    "cache cluster",
    "数据库地址",
    "database host",
    "管理员账号",
    "账号",
    "account",
    "username",
    "密码",
    "password",
    "token",
    "api key",
    "endpoint",
    "url",
)


def evaluate_remote_candidate_quality(
    events: list[EventRead],
    memories: MemoryStore,
    remote_llm: RemoteLLMClient,
    *,
    instructions: str | None = None,
) -> RemoteCandidateEvaluationResult:
    items: list[RemoteCandidateEvaluationItem] = []
    provider = "remote"

    for event in events:
        local_candidates = memories.preview_memory_candidates(event)
        remote_candidates: list[MemoryCandidateCreate] = []
        remote_error: str | None = None
        remote_latency_ms: float | None = None
        warnings: list[str] = []
        started = time.perf_counter()

        try:
            extracted = remote_llm.extract_candidates(event, instructions=instructions)
            provider = extracted.provider
            remote_candidates = extracted.candidates
            warnings = extracted.warnings
        except RemoteAdapterError as exc:
            remote_error = str(exc)
        finally:
            remote_latency_ms = round((time.perf_counter() - started) * 1000, 2)

        local_types = _unique_types(local_candidates)
        remote_types = _unique_types(remote_candidates)
        local_set = set(local_types)
        remote_set = set(remote_types)

        items.append(
            RemoteCandidateEvaluationItem(
                event_id=event.id,
                event_type=event.event_type,
                scope=event.scope,
                source=event.source,
                local_candidates=local_candidates,
                remote_candidates=remote_candidates,
                local_types=local_types,
                remote_types=remote_types,
                overlap_types=sorted(local_set & remote_set),
                local_only_types=sorted(local_set - remote_set),
                remote_only_types=sorted(remote_set - local_set),
                remote_latency_ms=remote_latency_ms,
                remote_error=remote_error,
                warnings=warnings,
            )
        )

    return RemoteCandidateEvaluationResult(
        provider=provider,
        summary=_summarize_items(items),
        items=items,
        warnings=_result_warnings(items),
    )


def load_events_for_remote_evaluation(
    events: EventLog,
    *,
    event_ids: list[str] | None = None,
    source: str | None = None,
    scope: str | None = None,
    task_id: str | None = None,
    limit: int = 20,
) -> list[EventRead]:
    if event_ids:
        loaded: list[EventRead] = []
        missing: list[str] = []
        for event_id in event_ids:
            event = events.get_event(event_id)
            if event is None:
                missing.append(event_id)
            else:
                loaded.append(event)
        if missing:
            raise ValueError(f"events not found: {', '.join(missing)}")
        return loaded
    return events.list_events(source=source, scope=scope, task_id=task_id, limit=limit)


def backfill_remote_memory_embeddings(
    memories: MemoryStore,
    remote_embedding: RemoteEmbeddingClient,
    *,
    model: str | None = None,
    scope: str | None = None,
    memory_type: MemoryType | None = None,
    limit: int = 100,
    batch_size: int = 16,
    dry_run: bool = False,
) -> RemoteEmbeddingBackfillResult:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero")

    target_model = model or remote_embedding.config.embedding_model
    missing = memories.list_memories_missing_embedding(
        model=target_model,
        scope=scope,
        memory_type=memory_type,
        limit=limit,
    )
    if dry_run:
        return RemoteEmbeddingBackfillResult(
            model=target_model,
            requested_count=len(missing),
            skipped_count=len(missing),
            dry_run=True,
            skipped_memory_ids=[memory.id for memory in missing],
        )

    provider = "remote"
    embedded_ids: list[str] = []
    skipped_ids: list[str] = []
    errors: list[str] = []
    dimensions: int | None = None
    batch_count = 0

    for batch in _chunks(missing, batch_size):
        batch_count += 1
        texts = [build_memory_embedding_text(memory) for memory in batch]
        try:
            result = remote_embedding.embed_texts(texts, model=target_model)
        except RemoteAdapterError as exc:
            skipped_ids.extend(memory.id for memory in batch)
            errors.append(f"batch:{','.join(memory.id for memory in batch)}:{exc}")
            continue

        provider = result.provider
        resolved_model = result.model or target_model
        dimensions = result.dimensions or dimensions
        if len(result.vectors) != len(batch):
            skipped_ids.extend(memory.id for memory in batch)
            errors.append(
                "batch:"
                + ",".join(memory.id for memory in batch)
                + f":expected {len(batch)} vectors, got {len(result.vectors)}"
            )
            continue

        for memory, vector, text in zip(batch, result.vectors, texts):
            try:
                embedding = memories.upsert_memory_embedding(
                    memory.id,
                    vector=vector,
                    model=resolved_model,
                    embedded_text=text,
                )
            except (ValueError, LookupError) as exc:
                skipped_ids.append(memory.id)
                errors.append(f"memory:{memory.id}:{exc}")
                continue
            embedded_ids.append(memory.id)
            dimensions = embedding.dimensions

    return RemoteEmbeddingBackfillResult(
        provider=provider,
        model=target_model,
        requested_count=len(missing),
        embedded_count=len(embedded_ids),
        skipped_count=len(skipped_ids),
        error_count=len(errors),
        batch_count=batch_count,
        dimensions=dimensions,
        memory_ids=embedded_ids,
        skipped_memory_ids=skipped_ids,
        errors=errors,
    )


def remote_guarded_hybrid_search(
    memories: MemoryStore,
    remote_embedding: RemoteEmbeddingClient,
    *,
    query: str,
    scopes: list[str] | None = None,
    memory_types: list[MemoryType] | None = None,
    model: str | None = None,
    limit: int = 10,
    guard_top_k: int = 3,
    min_similarity: float = 0.20,
    ambiguity_margin: float = 0.03,
) -> RemoteGuardedSearchResult:
    if not query.strip():
        return RemoteGuardedSearchResult(
            query=query,
            warnings=["empty_query_skipped_remote_embedding"],
        )
    embedded = remote_embedding.embed_texts([query], model=model)
    resolved_model = embedded.model or model or remote_embedding.config.embedding_model
    return _guarded_hybrid_with_query_vector(
        memories,
        query=query,
        query_vector=embedded.vectors[0],
        model=resolved_model,
        scopes=scopes or [],
        memory_types=memory_types or [],
        limit=limit,
        guard_top_k=guard_top_k,
        min_similarity=min_similarity,
        ambiguity_margin=ambiguity_margin,
        provider=embedded.provider,
    )


def remote_llm_guarded_hybrid_search(
    memories: MemoryStore,
    remote_embedding: RemoteEmbeddingClient,
    remote_llm: RemoteLLMClient,
    *,
    query: str,
    scopes: list[str] | None = None,
    memory_types: list[MemoryType] | None = None,
    model: str | None = None,
    limit: int = 10,
    guard_top_k: int = 3,
    min_similarity: float = 0.20,
    ambiguity_margin: float = 0.03,
) -> RemoteLLMGuardedSearchResult:
    if not query.strip():
        local_guard = RemoteGuardedSearchResult(
            query=query,
            warnings=["empty_query_skipped_remote_embedding"],
        )
        judge = _local_recall_judge_result(
            query=query,
            decision="rejected",
            reason="Empty query cannot recall a memory.",
            warnings=["empty_query_skipped_remote_recall_judge"],
        )
        return RemoteLLMGuardedSearchResult(
            query=query,
            local_guard=local_guard,
            judge=judge,
            warnings=[*local_guard.warnings, *judge.warnings],
        )

    embedded = remote_embedding.embed_texts([query], model=model)
    resolved_model = embedded.model or model or remote_embedding.config.embedding_model
    local_guard = _guarded_hybrid_with_query_vector(
        memories,
        query=query,
        query_vector=embedded.vectors[0],
        model=resolved_model,
        scopes=scopes or [],
        memory_types=memory_types or [],
        limit=limit,
        guard_top_k=guard_top_k,
        min_similarity=min_similarity,
        ambiguity_margin=ambiguity_margin,
        provider=embedded.provider,
    )
    candidate_memories = _memories_for_guard_decisions(
        memories,
        local_guard.decisions,
        limit=max(guard_top_k, limit),
    )
    if not candidate_memories:
        judge = _local_recall_judge_result(
            query=query,
            decision="rejected",
            reason="No candidate memories were available for remote recall judging.",
            warnings=["no_recall_candidates"],
        )
    else:
        judge = remote_llm.judge_retrieval(
            query=query,
            memories=candidate_memories,
            local_decisions=local_guard.decisions,
            scopes=scopes or [],
        )
    accepted = _selected_memories_from_judge(candidate_memories, judge, limit=limit)
    warnings = [*local_guard.warnings, *judge.warnings]
    if judge.decision == "accepted" and not accepted:
        warnings.append("llm_guarded_hybrid_no_selected_results")
    return RemoteLLMGuardedSearchResult(
        provider=judge.provider or local_guard.provider,
        model=judge.model or resolved_model,
        query=query,
        memories=accepted,
        local_guard=local_guard,
        judge=judge,
        warnings=warnings,
        metadata={
            **local_guard.metadata,
            "candidate_memory_ids": [memory.id for memory in candidate_memories],
            "embedding_model": resolved_model,
        },
    )


def remote_selective_llm_guarded_hybrid_search(
    memories: MemoryStore,
    remote_embedding: RemoteEmbeddingClient,
    remote_llm: RemoteLLMClient,
    *,
    query: str,
    scopes: list[str] | None = None,
    memory_types: list[MemoryType] | None = None,
    model: str | None = None,
    limit: int = 10,
    guard_top_k: int = 3,
    min_similarity: float = 0.20,
    ambiguity_margin: float = 0.03,
    selective_min_similarity: float = 0.20,
    selective_ambiguity_margin: float = 0.03,
) -> RemoteLLMGuardedSearchResult:
    if not query.strip():
        local_guard = RemoteGuardedSearchResult(
            query=query,
            warnings=["empty_query_skipped_remote_embedding"],
        )
        judge = _local_recall_judge_result(
            query=query,
            decision="rejected",
            reason="Empty query cannot recall a memory.",
            warnings=["empty_query_skipped_remote_recall_judge"],
            metadata={
                "remote_judge_called": False,
                "skip_reason": "empty_query",
            },
        )
        return RemoteLLMGuardedSearchResult(
            query=query,
            local_guard=local_guard,
            judge=judge,
            warnings=[*local_guard.warnings, *judge.warnings],
            metadata={
                "remote_judge_called": False,
                "skip_reason": "empty_query",
            },
        )

    embedded = remote_embedding.embed_texts([query], model=model)
    resolved_model = embedded.model or model or remote_embedding.config.embedding_model
    local_guard = _guarded_hybrid_with_query_vector(
        memories,
        query=query,
        query_vector=embedded.vectors[0],
        model=resolved_model,
        scopes=scopes or [],
        memory_types=memory_types or [],
        limit=limit,
        guard_top_k=guard_top_k,
        min_similarity=min_similarity,
        ambiguity_margin=ambiguity_margin,
        provider=embedded.provider,
    )
    candidate_memories = _memories_for_guard_decisions(
        memories,
        local_guard.decisions,
        limit=max(guard_top_k, limit),
    )
    should_call, call_reason = _should_call_selective_recall_judge(
        local_guard,
        query=query,
        min_similarity=selective_min_similarity,
        ambiguity_margin=selective_ambiguity_margin,
    )

    if should_call and candidate_memories:
        judge = remote_llm.judge_retrieval(
            query=query,
            memories=candidate_memories,
            local_decisions=local_guard.decisions,
            scopes=scopes or [],
        )
        judge = judge.model_copy(
            update={
                "metadata": {
                    **judge.metadata,
                    "remote_judge_called": True,
                    "call_reason": call_reason,
                }
            }
        )
    elif should_call:
        judge = _local_recall_judge_result(
            query=query,
            decision="rejected",
            reason="No candidate memories were available for remote recall judging.",
            warnings=["no_recall_candidates"],
            metadata={
                "remote_judge_called": False,
                "skip_reason": "no_recall_candidates",
                "call_reason": call_reason,
            },
        )
    else:
        judge = _local_recall_judge_result(
            query=query,
            decision="accepted" if local_guard.memories else "rejected",
            reason="Skipped remote recall judge because local guard was confident.",
            selected_memory_ids=[memory.id for memory in local_guard.memories],
            metadata={
                "remote_judge_called": False,
                "skip_reason": call_reason,
            },
        )

    accepted = _selected_memories_from_judge(candidate_memories, judge, limit=limit)
    if judge.provider == "local" and judge.decision == "accepted":
        accepted = local_guard.memories[:limit]
    warnings = [*local_guard.warnings, *judge.warnings]
    if judge.decision == "accepted" and not accepted:
        warnings.append("selective_llm_guarded_hybrid_no_selected_results")
    remote_called = bool(judge.metadata.get("remote_judge_called", judge.provider != "local"))
    return RemoteLLMGuardedSearchResult(
        provider=judge.provider or local_guard.provider,
        model=judge.model or resolved_model,
        query=query,
        memories=accepted,
        local_guard=local_guard,
        judge=judge,
        warnings=warnings,
        metadata={
            **local_guard.metadata,
            "candidate_memory_ids": [memory.id for memory in candidate_memories],
            "embedding_model": resolved_model,
            "remote_judge_called": remote_called,
            "call_reason": call_reason if remote_called else None,
            "skip_reason": None if remote_called else judge.metadata.get("skip_reason", call_reason),
            "selective_min_similarity": selective_min_similarity,
            "selective_ambiguity_margin": selective_ambiguity_margin,
        },
    )


def evaluate_remote_retrieval_fixture(
    fixture_path: str | Path,
    remote_embedding: RemoteEmbeddingClient,
    *,
    remote_llm: RemoteLLMClient | None = None,
    include_llm_judge: bool = False,
    include_selective_llm_judge: bool = False,
    model: str | None = None,
    limit: int | None = None,
    batch_size: int = 16,
    guard_top_k: int = 3,
    guard_min_similarity: float = 0.20,
    guard_ambiguity_margin: float = 0.03,
    selective_min_similarity: float = 0.20,
    selective_ambiguity_margin: float = 0.03,
) -> RemoteRetrievalEvaluationResult:
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero")
    cases = _load_retrieval_cases(fixture_path, limit=limit)
    target_model = model or remote_embedding.config.embedding_model
    items: list[RemoteRetrievalEvaluationItem] = []
    provider = "remote"
    embedded_memory_count = 0
    embedded_query_count = 0

    for case in cases:
        store = MemoryStore(":memory:")
        by_alias = _seed_case_memories(store, case.get("memories", []))
        alias_by_id = {memory.id: alias for alias, memory in by_alias.items()}
        active_memories = [memory for memory in by_alias.values() if memory.status == "active"]
        search_payload = dict(case.get("search", {}))
        query = str(search_payload.get("query", ""))
        query_text = query if query.strip() else str(case.get("name", "empty query"))
        memory_texts = [build_memory_embedding_text(memory) for memory in active_memories]

        if len(active_memories) + 1 <= batch_size:
            embedded = remote_embedding.embed_texts(
                [*memory_texts, query_text],
                model=target_model,
            )
            provider = embedded.provider
            resolved_model = embedded.model or target_model
            if len(embedded.vectors) != len(active_memories) + 1:
                raise RemoteAdapterError(
                    f"expected {len(active_memories) + 1} vectors, got {len(embedded.vectors)}"
                )
            for memory, vector, text in zip(active_memories, embedded.vectors[:-1], memory_texts):
                store.upsert_memory_embedding(
                    memory.id,
                    vector=vector,
                    model=resolved_model,
                    embedded_text=text,
                )
                embedded_memory_count += 1
            target_model = resolved_model
            query_vector = embedded.vectors[-1]
            embedded_query_count += 1
        else:
            for batch in _chunks(active_memories, batch_size):
                embedded = remote_embedding.embed_texts(
                    [build_memory_embedding_text(memory) for memory in batch],
                    model=target_model,
                )
                provider = embedded.provider
                resolved_model = embedded.model or target_model
                for memory, vector in zip(batch, embedded.vectors):
                    store.upsert_memory_embedding(
                        memory.id,
                        vector=vector,
                        model=resolved_model,
                        embedded_text=build_memory_embedding_text(memory),
                    )
                    embedded_memory_count += 1
                target_model = resolved_model

            query_embedding = remote_embedding.embed_texts(
                [query_text],
                model=target_model,
            )
            provider = query_embedding.provider
            resolved_model = query_embedding.model or target_model
            target_model = resolved_model
            query_vector = query_embedding.vectors[0]
            embedded_query_count += 1

        expected_aliases = _expected_aliases(case)
        absent_aliases = list(case.get("expected", {}).get("absent_aliases", []))
        results_by_mode: dict[str, list[str]] = {}
        missing_by_mode: dict[str, list[str]] = {}
        unexpected_by_mode: dict[str, list[str]] = {}
        ambiguous_by_mode: dict[str, list[str]] = {}
        passed_by_mode: dict[str, bool] = {}
        judge_by_mode: dict[str, RemoteRetrievalJudgeRead] = {}

        for mode in ("keyword", "semantic", "hybrid"):
            input_payload = {
                **search_payload,
                "retrieval_mode": mode,
                "query_embedding": query_vector if mode != "keyword" else [],
                "embedding_model": resolved_model if mode != "keyword" else None,
            }
            results = store.search_memory(SearchMemoryInput(**input_payload), log=False)
            aliases = [alias_by_id[memory.id] for memory in results]
            missing = [alias for alias in expected_aliases if alias not in aliases]
            unexpected = [alias for alias in absent_aliases if alias in aliases]
            results_by_mode[mode] = aliases
            missing_by_mode[mode] = missing
            unexpected_by_mode[mode] = unexpected
            ambiguous_by_mode[mode] = []
            passed_by_mode[mode] = not missing and not unexpected

        guarded = _guarded_hybrid_with_query_vector(
            store,
            query=query,
            query_vector=query_vector,
            model=resolved_model,
            scopes=list(search_payload.get("scopes", [])),
            memory_types=list(search_payload.get("memory_types", [])),
            limit=int(search_payload.get("limit", 10)),
            guard_top_k=guard_top_k,
            min_similarity=guard_min_similarity,
            ambiguity_margin=guard_ambiguity_margin,
            provider=provider,
        )
        guarded_aliases = [alias_by_id[memory.id] for memory in guarded.memories]
        guarded_ambiguous = [
            alias_by_id[decision.memory_id]
            for decision in guarded.decisions
            if decision.decision == "ambiguous" and decision.memory_id in alias_by_id
        ]
        guarded_missing = [alias for alias in expected_aliases if alias not in guarded_aliases]
        guarded_unexpected = [alias for alias in absent_aliases if alias in guarded_aliases]
        results_by_mode["guarded_hybrid"] = guarded_aliases
        missing_by_mode["guarded_hybrid"] = guarded_missing
        unexpected_by_mode["guarded_hybrid"] = guarded_unexpected
        ambiguous_by_mode["guarded_hybrid"] = guarded_ambiguous
        passed_by_mode["guarded_hybrid"] = (
            not guarded_missing and not guarded_unexpected and not guarded_ambiguous
        )

        if include_llm_judge:
            if remote_llm is None:
                raise ValueError("remote_llm is required when include_llm_judge is true")
            llm_candidates = _memories_for_guard_decisions(
                store,
                guarded.decisions,
                limit=max(guard_top_k, int(search_payload.get("limit", 10))),
            )
            if llm_candidates:
                judge = remote_llm.judge_retrieval(
                    query=query,
                    memories=llm_candidates,
                    local_decisions=guarded.decisions,
                    scopes=list(search_payload.get("scopes", [])),
                )
            else:
                judge = _local_recall_judge_result(
                    query=query,
                    decision="rejected",
                    reason="No candidate memories were available for remote recall judging.",
                    warnings=["no_recall_candidates"],
                )
            llm_memories = _selected_memories_from_judge(
                llm_candidates,
                judge,
                limit=int(search_payload.get("limit", 10)),
            )
            llm_aliases = [alias_by_id[memory.id] for memory in llm_memories]
            llm_ambiguous = (
                [
                    alias_by_id[memory.id]
                    for memory in llm_candidates
                    if memory.id in alias_by_id
                ]
                if judge.decision == "ambiguous"
                else []
            )
            llm_missing = [alias for alias in expected_aliases if alias not in llm_aliases]
            llm_unexpected = [alias for alias in absent_aliases if alias in llm_aliases]
            results_by_mode["llm_guarded_hybrid"] = llm_aliases
            missing_by_mode["llm_guarded_hybrid"] = llm_missing
            unexpected_by_mode["llm_guarded_hybrid"] = llm_unexpected
            ambiguous_by_mode["llm_guarded_hybrid"] = llm_ambiguous
            passed_by_mode["llm_guarded_hybrid"] = (
                not llm_missing and not llm_unexpected and not llm_ambiguous
            )
            judge_by_mode["llm_guarded_hybrid"] = _retrieval_judge_trace(
                judge,
                candidate_memories=llm_candidates,
                selected_memories=llm_memories,
                alias_by_id=alias_by_id,
            )

        if include_selective_llm_judge:
            if remote_llm is None:
                raise ValueError(
                    "remote_llm is required when include_selective_llm_judge is true"
                )
            selective_candidates = _memories_for_guard_decisions(
                store,
                guarded.decisions,
                limit=max(guard_top_k, int(search_payload.get("limit", 10))),
            )
            should_call, call_reason = _should_call_selective_recall_judge(
                guarded,
                query=query,
                min_similarity=selective_min_similarity,
                ambiguity_margin=selective_ambiguity_margin,
            )
            if should_call and selective_candidates:
                selective_judge = remote_llm.judge_retrieval(
                    query=query,
                    memories=selective_candidates,
                    local_decisions=guarded.decisions,
                    scopes=list(search_payload.get("scopes", [])),
                )
                selective_judge = selective_judge.model_copy(
                    update={
                        "metadata": {
                            **selective_judge.metadata,
                            "remote_judge_called": True,
                            "call_reason": call_reason,
                        }
                    }
                )
            elif should_call:
                selective_judge = _local_recall_judge_result(
                    query=query,
                    decision="rejected",
                    reason="No candidate memories were available for remote recall judging.",
                    warnings=["no_recall_candidates"],
                    metadata={
                        "remote_judge_called": False,
                        "skip_reason": "no_recall_candidates",
                        "call_reason": call_reason,
                    },
                )
            else:
                selective_judge = _local_recall_judge_result(
                    query=query,
                    decision="accepted" if guarded.memories else "rejected",
                    reason="Skipped remote recall judge because local guard was confident.",
                    selected_memory_ids=[memory.id for memory in guarded.memories],
                    metadata={
                        "remote_judge_called": False,
                        "skip_reason": call_reason,
                    },
                )
            selective_memories = _selected_memories_from_judge(
                selective_candidates,
                selective_judge,
                limit=int(search_payload.get("limit", 10)),
            )
            if selective_judge.provider == "local" and selective_judge.decision == "accepted":
                selective_memories = guarded.memories[: int(search_payload.get("limit", 10))]
            selective_aliases = [alias_by_id[memory.id] for memory in selective_memories]
            selective_ambiguous = (
                [
                    alias_by_id[memory.id]
                    for memory in selective_candidates
                    if memory.id in alias_by_id
                ]
                if selective_judge.decision == "ambiguous"
                else []
            )
            selective_missing = [
                alias for alias in expected_aliases if alias not in selective_aliases
            ]
            selective_unexpected = [
                alias for alias in absent_aliases if alias in selective_aliases
            ]
            results_by_mode["selective_llm_guarded_hybrid"] = selective_aliases
            missing_by_mode["selective_llm_guarded_hybrid"] = selective_missing
            unexpected_by_mode["selective_llm_guarded_hybrid"] = selective_unexpected
            ambiguous_by_mode["selective_llm_guarded_hybrid"] = selective_ambiguous
            passed_by_mode["selective_llm_guarded_hybrid"] = (
                not selective_missing and not selective_unexpected and not selective_ambiguous
            )
            judge_by_mode["selective_llm_guarded_hybrid"] = _retrieval_judge_trace(
                selective_judge,
                candidate_memories=selective_candidates,
                selected_memories=selective_memories,
                alias_by_id=alias_by_id,
            )

        items.append(
            RemoteRetrievalEvaluationItem(
                case_name=str(case.get("name", "")),
                category=case.get("category"),
                query=query,
                expected_aliases=expected_aliases,
                results_by_mode=results_by_mode,
                missing_by_mode=missing_by_mode,
                unexpected_by_mode=unexpected_by_mode,
                ambiguous_by_mode=ambiguous_by_mode,
                passed_by_mode=passed_by_mode,
                judge_by_mode=judge_by_mode,
            )
        )

    return RemoteRetrievalEvaluationResult(
        provider=provider,
        model=target_model,
        summary=_summarize_retrieval_items(
            items,
            embedded_memory_count=embedded_memory_count,
            embedded_query_count=embedded_query_count,
        ),
        category_summary=_summarize_retrieval_categories(items),
        items=items,
        warnings=_retrieval_evaluation_warnings(items),
    )


def _summarize_items(
    items: list[RemoteCandidateEvaluationItem],
) -> RemoteCandidateEvaluationSummary:
    success_items = [item for item in items if item.remote_error is None]
    latencies = [
        item.remote_latency_ms
        for item in success_items
        if item.remote_latency_ms is not None
    ]
    return RemoteCandidateEvaluationSummary(
        event_count=len(items),
        remote_success_count=len(success_items),
        remote_error_count=len(items) - len(success_items),
        local_candidate_count=sum(len(item.local_candidates) for item in items),
        remote_candidate_count=sum(len(item.remote_candidates) for item in items),
        both_empty_event_count=sum(
            1
            for item in items
            if not item.local_candidates and not item.remote_candidates and item.remote_error is None
        ),
        overlap_event_count=sum(1 for item in items if item.overlap_types),
        local_only_event_count=sum(
            1 for item in items if item.local_candidates and not item.remote_candidates
        ),
        remote_only_event_count=sum(
            1 for item in items if item.remote_candidates and not item.local_candidates
        ),
        divergent_event_count=sum(
            1
            for item in items
            if item.remote_error is None
            and (
                item.local_only_types
                or item.remote_only_types
                or len(item.local_candidates) != len(item.remote_candidates)
            )
        ),
        average_remote_latency_ms=round(sum(latencies) / len(latencies), 2)
        if latencies
        else None,
    )


def _result_warnings(items: list[RemoteCandidateEvaluationItem]) -> list[str]:
    warnings: list[str] = []
    remote_only = sum(1 for item in items if item.remote_candidates and not item.local_candidates)
    local_only = sum(1 for item in items if item.local_candidates and not item.remote_candidates)
    errors = sum(1 for item in items if item.remote_error is not None)
    if remote_only:
        warnings.append(
            f"remote_only_events={remote_only}; review for possible over-capture or useful recall"
        )
    if local_only:
        warnings.append(f"local_only_events={local_only}; remote may be missing rule-covered cases")
    if errors:
        warnings.append(f"remote_error_events={errors}; inspect remote connectivity or schema issues")
    return warnings


def _unique_types(candidates: list[MemoryCandidateCreate]) -> list[MemoryType]:
    return sorted({candidate.memory_type for candidate in candidates})


def _guarded_hybrid_with_query_vector(
    memories: MemoryStore,
    *,
    query: str,
    query_vector: list[float],
    model: str,
    scopes: list[str],
    memory_types: list[MemoryType],
    limit: int,
    guard_top_k: int,
    min_similarity: float,
    ambiguity_margin: float,
    provider: str = "remote",
) -> RemoteGuardedSearchResult:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    if guard_top_k < 1:
        raise ValueError("guard_top_k must be greater than zero")
    if min_similarity < 0:
        raise ValueError("min_similarity must be zero or greater")
    if ambiguity_margin < 0:
        raise ValueError("ambiguity_margin must be zero or greater")

    candidates = memories.search_memory(
        SearchMemoryInput(
            query=query,
            scopes=scopes,
            memory_types=memory_types,
            limit=max(limit, guard_top_k),
            retrieval_mode="hybrid",
            query_embedding=query_vector,
            embedding_model=model,
        ),
        log=False,
    )
    query_intents = _query_intents(query)
    scored: list[tuple[float, float, MemoryItemRead]] = []
    decisions: list[RemoteRetrievalGuardDecisionRead] = []
    for memory in candidates:
        embedding = memories.get_memory_embedding(memory.id, model=model)
        if embedding is None:
            decisions.append(
                _guard_decision(
                    memory,
                    decision="rejected",
                    reason="missing_embedding",
                    rank=len(decisions) + 1,
                )
            )
            continue
        similarity = _cosine_similarity(query_vector, embedding.vector)
        scored.append((similarity, _memory_intent_score(memory, query_intents), memory))

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return RemoteGuardedSearchResult(
            provider=provider,
            model=model,
            query=query,
            decisions=decisions,
            warnings=["guard_no_scored_candidates"],
            metadata=_guard_metadata(limit, guard_top_k, min_similarity, ambiguity_margin),
        )

    top_similarity = scored[0][0]
    second_similarity = scored[1][0] if len(scored) > 1 else None
    top_margin = (
        round(top_similarity - second_similarity, 6)
        if second_similarity is not None
        else None
    )
    accepted: list[MemoryItemRead] = []
    warnings: list[str] = []
    intent_resolution = _resolve_by_intent(
        scored,
        top_similarity=top_similarity,
        ambiguity_margin=ambiguity_margin,
    )

    if top_similarity < min_similarity:
        warnings.append("guard_top_similarity_below_threshold")
        for rank, (similarity, intent_score, memory) in enumerate(scored, start=1):
            decisions.append(
                _guard_decision(
                    memory,
                    decision="rejected",
                    reason="similarity_below_threshold",
                    rank=rank,
                    similarity=similarity,
                    intent_score=intent_score,
                    score_margin=top_margin if rank == 1 else None,
                )
            )
    elif intent_resolution is not None:
        warnings.append("guard_intent_reranked_top_candidates")
        intent_memory = intent_resolution[1]
        accepted.append(intent_memory)
        for rank, (similarity, intent_score, memory) in enumerate(scored, start=1):
            is_selected = memory.id == intent_memory.id
            decisions.append(
                _guard_decision(
                    memory,
                    decision="accepted" if is_selected else "rejected",
                    reason="intent_match_clear_enough"
                    if is_selected
                    else "lower_intent_match_after_rerank",
                    rank=rank,
                    similarity=similarity,
                    score_margin=top_margin if rank == 1 else None,
                    intent_score=intent_score,
                )
            )
    elif second_similarity is not None and top_similarity - second_similarity < ambiguity_margin:
        warnings.append("guard_ambiguous_top_candidates")
        for rank, (similarity, intent_score, memory) in enumerate(scored, start=1):
            decision = "ambiguous" if rank <= 2 else "rejected"
            reason = "score_margin_below_threshold" if rank <= 2 else "lower_rank_after_ambiguity"
            decisions.append(
                _guard_decision(
                    memory,
                    decision=decision,
                    reason=reason,
                    rank=rank,
                    similarity=similarity,
                    intent_score=intent_score,
                    score_margin=top_margin if rank <= 2 else None,
                )
            )
    else:
        for rank, (similarity, intent_score, memory) in enumerate(scored, start=1):
            if len(accepted) < limit and similarity >= min_similarity:
                accepted.append(memory)
                decisions.append(
                    _guard_decision(
                        memory,
                        decision="accepted",
                        reason="similarity_clear_enough",
                        rank=rank,
                        similarity=similarity,
                        intent_score=intent_score,
                        score_margin=top_margin if rank == 1 else None,
                    )
                )
            else:
                decisions.append(
                    _guard_decision(
                        memory,
                        decision="rejected",
                        reason="outside_limit_or_below_threshold",
                        rank=rank,
                        similarity=similarity,
                        intent_score=intent_score,
                    )
                )

    if not accepted:
        warnings.append("guard_no_accepted_results")
    return RemoteGuardedSearchResult(
        provider=provider,
        model=model,
        query=query,
        memories=accepted,
        decisions=decisions,
        warnings=warnings,
        metadata=_guard_metadata(limit, guard_top_k, min_similarity, ambiguity_margin),
    )


def _memories_for_guard_decisions(
    memories: MemoryStore,
    decisions: list[RemoteRetrievalGuardDecisionRead],
    *,
    limit: int,
) -> list[MemoryItemRead]:
    selected: list[MemoryItemRead] = []
    seen: set[str] = set()
    decision_priority = {"accepted": 0, "ambiguous": 1, "rejected": 2}
    for decision in sorted(
        decisions,
        key=lambda item: (decision_priority.get(item.decision, 3), item.rank),
    ):
        if decision.memory_id in seen:
            continue
        memory = memories.get_memory(decision.memory_id)
        if memory is None:
            continue
        selected.append(memory)
        seen.add(memory.id)
        if len(selected) >= limit:
            break
    return selected


def _selected_memories_from_judge(
    candidates: list[MemoryItemRead],
    judge: RemoteRecallJudgeResult,
    *,
    limit: int,
) -> list[MemoryItemRead]:
    if judge.decision != "accepted":
        return []
    selected_ids = set(judge.selected_memory_ids)
    selected = [memory for memory in candidates if memory.id in selected_ids]
    return selected[:limit]


def _should_call_selective_recall_judge(
    local_guard: RemoteGuardedSearchResult,
    *,
    query: str = "",
    min_similarity: float,
    ambiguity_margin: float,
) -> tuple[bool, str]:
    if not local_guard.decisions:
        return False, "local_no_candidates"
    if any(decision.decision == "ambiguous" for decision in local_guard.decisions):
        return True, "local_ambiguous_candidates"
    if not local_guard.memories:
        return True, "local_no_accepted_results"

    accepted_ids = {memory.id for memory in local_guard.memories}
    accepted_decisions = [
        decision for decision in local_guard.decisions if decision.memory_id in accepted_ids
    ]
    if not accepted_decisions:
        return True, "local_missing_accepted_decision"
    top_accepted = min(accepted_decisions, key=lambda decision: decision.rank)
    if top_accepted.similarity is None:
        return True, "local_missing_similarity"
    if top_accepted.similarity < min_similarity:
        return True, "local_similarity_below_selective_threshold"
    if (
        top_accepted.score_margin is not None
        and top_accepted.score_margin < ambiguity_margin
        and "guard_intent_reranked_top_candidates" not in local_guard.warnings
    ):
        return True, "local_margin_below_selective_threshold"
    if "guard_top_similarity_below_threshold" in local_guard.warnings:
        return True, "local_similarity_below_guard_threshold"
    if "guard_ambiguous_top_candidates" in local_guard.warnings:
        return True, "local_ambiguous_candidates"
    if _is_concrete_fact_risk_query(query or local_guard.query):
        return True, "concrete_fact_risk_query"
    return False, "local_guard_confident"


def _is_concrete_fact_risk_query(query: str) -> bool:
    normalized = query.strip().lower()
    if not normalized:
        return False
    asks_for_specific_value = any(
        term in normalized for term in CONCRETE_FACT_QUESTION_TERMS
    )
    mentions_concrete_target = any(
        term in normalized for term in CONCRETE_FACT_TARGET_TERMS
    )
    return asks_for_specific_value and mentions_concrete_target


def _local_recall_judge_result(
    *,
    query: str,
    decision: str,
    reason: str,
    selected_memory_ids: list[str] | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> RemoteRecallJudgeResult:
    resolved_metadata = {"skipped_remote_call": True}
    if metadata:
        resolved_metadata.update(metadata)
    return RemoteRecallJudgeResult(
        provider="local",
        query=query,
        decision=decision,
        selected_memory_ids=selected_memory_ids or [],
        reason=reason,
        warnings=warnings or [],
        metadata=resolved_metadata,
    )


def _retrieval_judge_trace(
    judge: RemoteRecallJudgeResult,
    *,
    candidate_memories: list[MemoryItemRead],
    selected_memories: list[MemoryItemRead],
    alias_by_id: dict[str, str],
) -> RemoteRetrievalJudgeRead:
    metadata = dict(judge.metadata)
    metadata.setdefault("remote_judge_called", judge.provider != "local")
    return RemoteRetrievalJudgeRead(
        provider=judge.provider,
        model=judge.model,
        decision=judge.decision,
        reason=judge.reason,
        risk=judge.risk,
        selected_aliases=[
            alias_by_id[memory.id] for memory in selected_memories if memory.id in alias_by_id
        ],
        selected_memory_ids=judge.selected_memory_ids,
        candidate_aliases=[
            alias_by_id[memory.id] for memory in candidate_memories if memory.id in alias_by_id
        ],
        candidate_memory_ids=[memory.id for memory in candidate_memories],
        warnings=judge.warnings,
        metadata=metadata,
    )


def _guard_decision(
    memory: MemoryItemRead,
    *,
    decision: str,
    reason: str,
    rank: int,
    similarity: float | None = None,
    score_margin: float | None = None,
    intent_score: float | None = None,
) -> RemoteRetrievalGuardDecisionRead:
    return RemoteRetrievalGuardDecisionRead(
        memory_id=memory.id,
        subject=memory.subject,
        decision=decision,
        reason=reason,
        rank=rank,
        similarity=round(similarity, 6) if similarity is not None else None,
        score_margin=score_margin,
        intent_score=round(intent_score, 3) if intent_score is not None else None,
    )


def _guard_metadata(
    limit: int,
    guard_top_k: int,
    min_similarity: float,
    ambiguity_margin: float,
) -> dict[str, float | int]:
    return {
        "limit": limit,
        "guard_top_k": guard_top_k,
        "min_similarity": min_similarity,
        "ambiguity_margin": ambiguity_margin,
    }


def _query_intents(query: str) -> list[dict[str, object]]:
    lowered = query.lower()
    return [
        signature
        for signature in INTENT_SIGNATURES
        if _contains_any_term(lowered, signature["query_terms"])
    ]


def _memory_intent_score(
    memory: MemoryItemRead,
    query_intents: list[dict[str, object]],
) -> float:
    if not query_intents:
        return 0.0
    memory_text = (
        f"{memory.subject} {memory.content} {' '.join(memory.tags)} {memory.memory_type}"
    ).lower()
    score = 0.0
    for signature in query_intents:
        memory_terms = signature["memory_terms"]
        term_hits = sum(1 for term in memory_terms if str(term).lower() in memory_text)
        if term_hits:
            score += min(3, term_hits)
        if memory.memory_type in signature["memory_types"]:
            score += 0.25
    return score


def _resolve_by_intent(
    scored: list[tuple[float, float, MemoryItemRead]],
    *,
    top_similarity: float,
    ambiguity_margin: float,
) -> tuple[float, MemoryItemRead] | None:
    if not scored:
        return None
    intent_window = max(ambiguity_margin, 0.08)
    close = [item for item in scored if top_similarity - item[0] <= intent_window]
    if len(close) < 2:
        return None
    ranked = sorted(close, key=lambda item: (item[1], item[0]), reverse=True)
    best_similarity, best_intent, best_memory = ranked[0]
    second_intent = ranked[1][1]
    if best_intent >= 1.0 and best_intent - second_intent >= 0.75:
        return best_similarity, best_memory
    return None


def _contains_any_term(text: str, terms: object) -> bool:
    if not isinstance(terms, tuple):
        return False
    return any(str(term).lower() in text for term in terms)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(left_item * right_item for left_item, right_item in zip(left, right)) / (
        left_norm * right_norm
    )


def _chunks(items: list[MemoryItemRead], size: int) -> list[list[MemoryItemRead]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _load_retrieval_cases(
    fixture_path: str | Path,
    *,
    limit: int | None = None,
) -> list[dict]:
    path = Path(fixture_path)
    cases: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        if case.get("mode") == "retrieval":
            cases.append(case)
        if limit is not None and len(cases) >= limit:
            break
    return cases


def _seed_case_memories(
    store: MemoryStore,
    definitions: list[dict],
) -> dict[str, MemoryItemRead]:
    created: dict[str, MemoryItemRead] = {}
    for definition in definitions:
        alias = definition["alias"]
        status = definition.get("status", "active")
        payload = {
            key: value for key, value in definition.items() if key not in {"alias", "status"}
        }
        memory = store.add_memory(MemoryItemCreate(**payload))
        if status == "stale":
            memory = store.mark_stale(memory.id, "Seeded stale memory for retrieval evaluation.")
        elif status == "archived":
            memory = store.archive_memory(
                memory.id,
                "Seeded archived memory for retrieval evaluation.",
            )
        elif status != "active":
            store._update_memory_status(memory.id, status)
            refreshed = store.get_memory(memory.id)
            if refreshed is None:
                raise LookupError(memory.id)
            memory = refreshed
        created[alias] = memory
    return created


def _expected_aliases(case: dict) -> list[str]:
    expected = case.get("expected", {})
    if "exact_aliases" in expected:
        return list(expected["exact_aliases"])
    if "ordered_prefix" in expected:
        return list(expected["ordered_prefix"])
    if "included_aliases" in expected:
        return list(expected["included_aliases"])
    return []


def _summarize_retrieval_items(
    items: list[RemoteRetrievalEvaluationItem],
    *,
    embedded_memory_count: int,
    embedded_query_count: int,
) -> RemoteRetrievalEvaluationSummary:
    modes = _retrieval_modes(items)
    return RemoteRetrievalEvaluationSummary(
        case_count=len(items),
        modes=modes,
        passed_by_mode={
            mode: sum(1 for item in items if item.passed_by_mode.get(mode, False))
            for mode in modes
        },
        failed_by_mode={
            mode: sum(1 for item in items if not item.passed_by_mode.get(mode, False))
            for mode in modes
        },
        false_negative_by_mode={
            mode: sum(len(item.missing_by_mode.get(mode, [])) for item in items)
            for mode in modes
        },
        unexpected_by_mode={
            mode: sum(len(item.unexpected_by_mode.get(mode, [])) for item in items)
            for mode in modes
        },
        ambiguous_by_mode={
            mode: sum(len(item.ambiguous_by_mode.get(mode, [])) for item in items)
            for mode in modes
        },
        top1_hit_by_mode={
            mode: sum(
                1
                for item in items
                if item.expected_aliases
                and item.results_by_mode.get(mode)
                and item.results_by_mode[mode][0] == item.expected_aliases[0]
            )
            for mode in modes
        },
        embedded_memory_count=embedded_memory_count,
        embedded_query_count=embedded_query_count,
        judge_called_by_mode={
            mode: sum(1 for item in items if _judge_was_called(item, mode))
            for mode in modes
        },
        judge_skipped_by_mode={
            mode: sum(1 for item in items if _judge_was_skipped(item, mode))
            for mode in modes
        },
        judge_skip_reason_by_mode={
            mode: _judge_skip_reasons(items, mode)
            for mode in modes
            if _judge_skip_reasons(items, mode)
        },
    )


def _summarize_retrieval_categories(
    items: list[RemoteRetrievalEvaluationItem],
) -> dict[str, RemoteRetrievalCategorySummary]:
    grouped: dict[str, list[RemoteRetrievalEvaluationItem]] = {}
    for item in items:
        grouped.setdefault(item.category or "uncategorized", []).append(item)
    return {
        category: _summarize_retrieval_category(category, category_items)
        for category, category_items in sorted(grouped.items())
    }


def _summarize_retrieval_category(
    category: str,
    items: list[RemoteRetrievalEvaluationItem],
) -> RemoteRetrievalCategorySummary:
    modes = _retrieval_modes(items)
    return RemoteRetrievalCategorySummary(
        category=category,
        case_count=len(items),
        passed_by_mode={
            mode: sum(1 for item in items if item.passed_by_mode.get(mode, False))
            for mode in modes
        },
        failed_by_mode={
            mode: sum(1 for item in items if not item.passed_by_mode.get(mode, False))
            for mode in modes
        },
        false_negative_by_mode={
            mode: sum(len(item.missing_by_mode.get(mode, [])) for item in items)
            for mode in modes
        },
        unexpected_by_mode={
            mode: sum(len(item.unexpected_by_mode.get(mode, [])) for item in items)
            for mode in modes
        },
        ambiguous_by_mode={
            mode: sum(len(item.ambiguous_by_mode.get(mode, [])) for item in items)
            for mode in modes
        },
        top1_hit_by_mode={
            mode: sum(
                1
                for item in items
                if item.expected_aliases
                and item.results_by_mode.get(mode)
                and item.results_by_mode[mode][0] == item.expected_aliases[0]
            )
            for mode in modes
        },
        judge_called_by_mode={
            mode: sum(1 for item in items if _judge_was_called(item, mode))
            for mode in modes
        },
        judge_skipped_by_mode={
            mode: sum(1 for item in items if _judge_was_skipped(item, mode))
            for mode in modes
        },
        judge_skip_reason_by_mode={
            mode: _judge_skip_reasons(items, mode)
            for mode in modes
            if _judge_skip_reasons(items, mode)
        },
    )


def _retrieval_modes(items: list[RemoteRetrievalEvaluationItem]) -> list[str]:
    preferred = [
        "keyword",
        "semantic",
        "hybrid",
        "guarded_hybrid",
        "llm_guarded_hybrid",
        "selective_llm_guarded_hybrid",
    ]
    present = {
        mode
        for item in items
        for mode in (
            set(item.results_by_mode)
            | set(item.missing_by_mode)
            | set(item.unexpected_by_mode)
            | set(item.ambiguous_by_mode)
            | set(item.passed_by_mode)
            | set(item.judge_by_mode)
        )
    }
    modes = [mode for mode in preferred if mode in present]
    modes.extend(sorted(present - set(modes)))
    return modes


def _judge_was_called(item: RemoteRetrievalEvaluationItem, mode: str) -> bool:
    judge = item.judge_by_mode.get(mode)
    if judge is None:
        return False
    return bool(judge.metadata.get("remote_judge_called", judge.provider != "local"))


def _judge_was_skipped(item: RemoteRetrievalEvaluationItem, mode: str) -> bool:
    judge = item.judge_by_mode.get(mode)
    if judge is None:
        return False
    return not _judge_was_called(item, mode)


def _judge_skip_reasons(
    items: list[RemoteRetrievalEvaluationItem],
    mode: str,
) -> dict[str, int]:
    reasons: dict[str, int] = {}
    for item in items:
        judge = item.judge_by_mode.get(mode)
        if judge is None or _judge_was_called(item, mode):
            continue
        reason = str(judge.metadata.get("skip_reason") or "unknown")
        reasons[reason] = reasons.get(reason, 0) + 1
    return dict(sorted(reasons.items()))


def _retrieval_evaluation_warnings(
    items: list[RemoteRetrievalEvaluationItem],
) -> list[str]:
    warnings: list[str] = []
    keyword_fn = sum(len(item.missing_by_mode.get("keyword", [])) for item in items)
    hybrid_fn = sum(len(item.missing_by_mode.get("hybrid", [])) for item in items)
    hybrid_noise = sum(len(item.unexpected_by_mode.get("hybrid", [])) for item in items)
    guarded_noise = sum(
        len(item.unexpected_by_mode.get("guarded_hybrid", [])) for item in items
    )
    guarded_ambiguous = sum(
        len(item.ambiguous_by_mode.get("guarded_hybrid", [])) for item in items
    )
    llm_noise = sum(
        len(item.unexpected_by_mode.get("llm_guarded_hybrid", [])) for item in items
    )
    llm_ambiguous = sum(
        len(item.ambiguous_by_mode.get("llm_guarded_hybrid", [])) for item in items
    )
    selective_noise = sum(
        len(item.unexpected_by_mode.get("selective_llm_guarded_hybrid", [])) for item in items
    )
    selective_ambiguous = sum(
        len(item.ambiguous_by_mode.get("selective_llm_guarded_hybrid", [])) for item in items
    )
    if hybrid_fn < keyword_fn:
        warnings.append(f"hybrid_reduced_false_negatives:{keyword_fn}->{hybrid_fn}")
    if hybrid_noise:
        warnings.append(f"hybrid_unexpected_aliases={hybrid_noise}; review noise cases")
    if guarded_noise < hybrid_noise:
        warnings.append(f"guard_reduced_unexpected_aliases:{hybrid_noise}->{guarded_noise}")
    if guarded_ambiguous:
        warnings.append(f"guarded_hybrid_ambiguous={guarded_ambiguous}; review ambiguous cases")
    if "llm_guarded_hybrid" in _retrieval_modes(items):
        if llm_noise < guarded_noise:
            warnings.append(f"llm_guard_reduced_unexpected_aliases:{guarded_noise}->{llm_noise}")
        if llm_ambiguous < guarded_ambiguous:
            warnings.append(
                f"llm_guard_reduced_ambiguous_aliases:{guarded_ambiguous}->{llm_ambiguous}"
            )
        if llm_ambiguous:
            warnings.append(f"llm_guarded_hybrid_ambiguous={llm_ambiguous}; review ambiguous cases")
    if "selective_llm_guarded_hybrid" in _retrieval_modes(items):
        selective_called = sum(
            1 for item in items if _judge_was_called(item, "selective_llm_guarded_hybrid")
        )
        selective_skipped = sum(
            1 for item in items if _judge_was_skipped(item, "selective_llm_guarded_hybrid")
        )
        warnings.append(
            "selective_llm_judge_calls="
            f"{selective_called}; skipped={selective_skipped}"
        )
        if selective_noise < guarded_noise:
            warnings.append(
                f"selective_llm_guard_reduced_unexpected_aliases:{guarded_noise}->{selective_noise}"
            )
        if selective_ambiguous:
            warnings.append(
                f"selective_llm_guarded_hybrid_ambiguous={selective_ambiguous}; review ambiguous cases"
            )
    return warnings
