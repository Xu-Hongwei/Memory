from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from memory_system.event_log import EventLog
from memory_system.memory_store import MemoryStore, build_memory_embedding_text
from memory_system.remote import RemoteAdapterError, RemoteEmbeddingClient, RemoteLLMClient
from memory_system.schemas import (
    EventRead,
    MemoryCandidateCreate,
    MemoryItemCreate,
    MemoryItemRead,
    MemoryType,
    RemoteEmbeddingResult,
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


T = TypeVar("T")


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
PRIVATE_FACT_QUESTION_TERMS = (
    "which",
    "what",
    "where",
    "who",
    "when",
    "what was",
    "which exact",
    "do we know",
    "tell me",
    "recall",
    "share",
)
PRIVATE_FACT_TARGET_TERMS = (
    "passport number",
    "passport",
    "government identifier",
    "employee id",
    "license plate",
    "insurance policy",
    "emergency contact",
    "phone number",
    "apartment number",
    "bank branch",
    "doctor",
    "medical",
    "high school",
    "childhood pet",
    "airline seat",
    "hotel room",
    "haircut date",
    "home address",
    "email",
    "private dataset",
    "real api key",
    "api key",
    "database password",
    "password",
    "token",
    "secret",
    "credential",
    "private key",
    "\u62a4\u7167",
    "\u8eab\u4efd\u8bc1",
    "\u8bc1\u4ef6\u53f7",
    "\u5458\u5de5\u53f7",
    "\u8f66\u724c",
    "\u4fdd\u5355",
    "\u7d27\u6025\u8054\u7cfb\u4eba",
    "\u624b\u673a\u53f7",
    "\u7535\u8bdd",
    "\u4f4f\u5740",
    "\u95e8\u724c\u53f7",
    "\u94f6\u884c",
    "\u533b\u751f",
    "\u75c5\u5386",
    "\u90ae\u7bb1",
    "\u5bc6\u7801",
    "\u5bc6\u94a5",
    "\u79c1\u6709\u6570\u636e",
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
    embedding_cache_path: str | Path | None = None,
    case_concurrency: int = 1,
    judge_concurrency: int = 1,
    judge_group_size: int = 1,
    sample_size: int | None = None,
    sample_seed: int | None = None,
) -> RemoteRetrievalEvaluationResult:
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero")
    if case_concurrency < 1:
        raise ValueError("case_concurrency must be greater than zero")
    if judge_concurrency < 1:
        raise ValueError("judge_concurrency must be greater than zero")
    if judge_group_size < 1:
        raise ValueError("judge_group_size must be greater than zero")
    if sample_size is not None and sample_size < 1:
        raise ValueError("sample_size must be greater than zero")
    judge_request_mode = "single" if judge_group_size == 1 else "batch"
    if (include_llm_judge or include_selective_llm_judge) and remote_llm is None:
        raise ValueError("remote_llm is required when an LLM judge mode is enabled")
    cases = _load_retrieval_cases(
        fixture_path,
        limit=limit,
        sample_size=sample_size,
        sample_seed=sample_seed,
    )
    target_model = model or remote_embedding.config.embedding_model
    cache = _EmbeddingCache(Path(embedding_cache_path)) if embedding_cache_path else None
    prefetch_metadata = {"enabled": False}
    if cache is not None and case_concurrency > 1:
        prefetch_metadata = _prefetch_retrieval_embedding_cache(
            cases,
            remote_embedding,
            model=target_model,
            batch_size=batch_size,
            case_concurrency=case_concurrency,
            cache=cache,
        )

    if case_concurrency == 1:
        evaluations = [
            _evaluate_retrieval_case(
                case,
                remote_embedding,
                include_llm_judge=include_llm_judge,
                include_selective_llm_judge=include_selective_llm_judge,
                target_model=target_model,
                batch_size=batch_size,
                guard_top_k=guard_top_k,
                guard_min_similarity=guard_min_similarity,
                guard_ambiguity_margin=guard_ambiguity_margin,
                selective_min_similarity=selective_min_similarity,
                selective_ambiguity_margin=selective_ambiguity_margin,
                cache=cache,
            )
            for case in cases
        ]
    else:
        evaluations_by_index: dict[int, _RetrievalCaseEvaluation] = {}
        with ThreadPoolExecutor(max_workers=case_concurrency) as executor:
            futures = {
                executor.submit(
                    _evaluate_retrieval_case,
                    case,
                    remote_embedding,
                    include_llm_judge=include_llm_judge,
                    include_selective_llm_judge=include_selective_llm_judge,
                    target_model=target_model,
                    batch_size=batch_size,
                    guard_top_k=guard_top_k,
                    guard_min_similarity=guard_min_similarity,
                    guard_ambiguity_margin=guard_ambiguity_margin,
                    selective_min_similarity=selective_min_similarity,
                    selective_ambiguity_margin=selective_ambiguity_margin,
                    cache=cache,
                ): index
                for index, case in enumerate(cases)
            }
            for future in as_completed(futures):
                evaluations_by_index[futures[future]] = future.result()
        evaluations = [evaluations_by_index[index] for index in range(len(cases))]

    judge_metadata = {
        "mode": judge_request_mode,
        "group_size": judge_group_size,
        "concurrency": judge_concurrency,
    }
    if judge_request_mode == "single" and remote_llm is not None:
        judge_metadata.update(
            _run_pending_retrieval_single_judges(
                evaluations,
                remote_llm,
                judge_concurrency=judge_concurrency,
            )
        )
    elif judge_request_mode == "batch" and remote_llm is not None:
        judge_metadata.update(
            _run_pending_retrieval_batch_judges(
                evaluations,
                remote_llm,
                judge_group_size=judge_group_size,
                judge_concurrency=judge_concurrency,
            )
        )

    items = [evaluation.item for evaluation in evaluations]
    evaluation_warnings: list[str] = []
    for evaluation in evaluations:
        evaluation_warnings.extend(evaluation.warnings)
    embedded_memory_count = sum(evaluation.embedded_memory_count for evaluation in evaluations)
    embedded_query_count = sum(evaluation.embedded_query_count for evaluation in evaluations)
    provider = _retrieval_evaluation_provider(evaluations)
    resolved_model = _retrieval_evaluation_model(evaluations, fallback=target_model)

    return RemoteRetrievalEvaluationResult(
        provider=provider,
        model=resolved_model,
        summary=_summarize_retrieval_items(
            items,
            embedded_memory_count=embedded_memory_count,
            embedded_query_count=embedded_query_count,
        ),
        category_summary=_summarize_retrieval_categories(items),
        items=items,
        warnings=[*_retrieval_evaluation_warnings(items), *sorted(set(evaluation_warnings))],
        metadata={
            "embedding_cache": cache.stats() if cache else {"enabled": False},
            "prefetch": prefetch_metadata,
            "case_concurrency": case_concurrency,
            "judge": judge_metadata,
            "selection": {
                "limit": limit,
                "sample_size": sample_size,
                "sample_seed": sample_seed,
                "case_count": len(cases),
                "case_names": [str(case.get("name", "")) for case in cases],
            },
        },
    )


@dataclass
class _RetrievalCaseEvaluation:
    item: RemoteRetrievalEvaluationItem
    provider: str
    model: str
    embedded_memory_count: int = 0
    embedded_query_count: int = 0
    warnings: list[str] = field(default_factory=list)
    pending_judges: list["_PendingRetrievalJudgeTask"] = field(default_factory=list)


@dataclass
class _PendingRetrievalJudgeTask:
    request_id: str
    mode: str
    query: str
    candidate_memories: list[MemoryItemRead]
    local_decisions: list[RemoteRetrievalGuardDecisionRead]
    scopes: list[str]
    expected_aliases: list[str]
    absent_aliases: list[str]
    alias_by_id: dict[str, str]
    limit: int
    call_reason: str | None = None


def _evaluate_retrieval_case(
    case: dict,
    remote_embedding: RemoteEmbeddingClient,
    *,
    include_llm_judge: bool,
    include_selective_llm_judge: bool,
    target_model: str,
    batch_size: int,
    guard_top_k: int,
    guard_min_similarity: float,
    guard_ambiguity_margin: float,
    selective_min_similarity: float,
    selective_ambiguity_margin: float,
    cache: _EmbeddingCache | None,
) -> _RetrievalCaseEvaluation:
    provider = "remote"
    resolved_model = target_model
    embedded_memory_count = 0
    embedded_query_count = 0

    store = MemoryStore(":memory:")
    by_alias = _seed_case_memories(store, case.get("memories", []))
    alias_by_id = {memory.id: alias for alias, memory in by_alias.items()}
    active_memories = [memory for memory in by_alias.values() if memory.status == "active"]
    search_payload = dict(case.get("search", {}))
    query = str(search_payload.get("query", ""))
    query_text = query if query.strip() else str(case.get("name", "empty query"))
    memory_texts = [build_memory_embedding_text(memory) for memory in active_memories]

    try:
        if len(active_memories) + 1 <= batch_size:
            embedded = _embed_texts_resilient(
                remote_embedding,
                [*memory_texts, query_text],
                model=target_model,
                cache=cache,
            )
            provider = embedded.provider
            resolved_model = embedded.model or target_model
            if len(embedded.vectors) != len(active_memories) + 1:
                raise RemoteAdapterError(
                    f"expected {len(active_memories) + 1} vectors, got {len(embedded.vectors)}"
                )
            for memory, vector, text in zip(
                active_memories,
                embedded.vectors[:-1],
                memory_texts,
            ):
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
                batch_texts = [build_memory_embedding_text(memory) for memory in batch]
                embedded = _embed_texts_resilient(
                    remote_embedding,
                    batch_texts,
                    model=target_model,
                    cache=cache,
                )
                provider = embedded.provider
                resolved_model = embedded.model or target_model
                for memory, vector, text in zip(batch, embedded.vectors, batch_texts):
                    store.upsert_memory_embedding(
                        memory.id,
                        vector=vector,
                        model=resolved_model,
                        embedded_text=text,
                    )
                    embedded_memory_count += 1
                target_model = resolved_model

            query_embedding = _embed_texts_resilient(
                remote_embedding,
                [query_text],
                model=target_model,
                cache=cache,
            )
            provider = query_embedding.provider
            resolved_model = query_embedding.model or target_model
            target_model = resolved_model
            query_vector = query_embedding.vectors[0]
            embedded_query_count += 1
    except RemoteAdapterError as exc:
        return _RetrievalCaseEvaluation(
            item=_remote_retrieval_error_item(
                case,
                query=query,
                message=str(exc),
                include_llm_judge=include_llm_judge,
                include_selective_llm_judge=include_selective_llm_judge,
            ),
            provider=provider,
            model=resolved_model,
            warnings=["remote_embedding_error"],
        )

    expected_aliases = _expected_aliases(case)
    absent_aliases = list(case.get("expected", {}).get("absent_aliases", []))
    results_by_mode: dict[str, list[str]] = {}
    missing_by_mode: dict[str, list[str]] = {}
    unexpected_by_mode: dict[str, list[str]] = {}
    ambiguous_by_mode: dict[str, list[str]] = {}
    passed_by_mode: dict[str, bool] = {}
    judge_by_mode: dict[str, RemoteRetrievalJudgeRead] = {}
    pending_judges: list[_PendingRetrievalJudgeTask] = []

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
        llm_candidates = _memories_for_guard_decisions(
            store,
            guarded.decisions,
            limit=max(guard_top_k, int(search_payload.get("limit", 10))),
        )
        if llm_candidates:
            pending_judges.append(
                _PendingRetrievalJudgeTask(
                    request_id=f"{case.get('name', '')}:llm_guarded_hybrid",
                    mode="llm_guarded_hybrid",
                    query=query,
                    candidate_memories=llm_candidates,
                    local_decisions=guarded.decisions,
                    scopes=list(search_payload.get("scopes", [])),
                    expected_aliases=expected_aliases,
                    absent_aliases=absent_aliases,
                    alias_by_id=alias_by_id,
                    limit=int(search_payload.get("limit", 10)),
                )
            )
            judge = _local_recall_judge_result(
                query=query,
                decision="ambiguous",
                reason="Remote recall judge deferred for later execution.",
                metadata={
                    "remote_judge_called": False,
                    "skip_reason": "judge_deferred",
                },
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
            [alias_by_id[memory.id] for memory in llm_candidates if memory.id in alias_by_id]
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
            pending_judges.append(
                _PendingRetrievalJudgeTask(
                    request_id=f"{case.get('name', '')}:selective_llm_guarded_hybrid",
                    mode="selective_llm_guarded_hybrid",
                    query=query,
                    candidate_memories=selective_candidates,
                    local_decisions=guarded.decisions,
                    scopes=list(search_payload.get("scopes", [])),
                    expected_aliases=expected_aliases,
                    absent_aliases=absent_aliases,
                    alias_by_id=alias_by_id,
                    limit=int(search_payload.get("limit", 10)),
                    call_reason=call_reason,
                )
            )
            selective_judge = _local_recall_judge_result(
                query=query,
                decision="ambiguous",
                reason="Remote recall judge deferred for later execution.",
                metadata={
                    "remote_judge_called": False,
                    "skip_reason": "judge_deferred",
                    "call_reason": call_reason,
                },
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
        selective_missing = [alias for alias in expected_aliases if alias not in selective_aliases]
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

    return _RetrievalCaseEvaluation(
        item=RemoteRetrievalEvaluationItem(
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
        ),
        provider=provider,
        model=resolved_model,
        embedded_memory_count=embedded_memory_count,
        embedded_query_count=embedded_query_count,
        pending_judges=pending_judges,
    )


@dataclass
class _JudgeBatchExecution:
    results: list[
        tuple[_RetrievalCaseEvaluation, _PendingRetrievalJudgeTask, RemoteRecallJudgeResult]
    ] = field(default_factory=list)
    single_calls: int = 0
    batch_calls: int = 0
    fallback_single_calls: int = 0
    errors: int = 0


def _run_pending_retrieval_single_judges(
    evaluations: list[_RetrievalCaseEvaluation],
    remote_llm: RemoteLLMClient,
    *,
    judge_concurrency: int,
) -> dict[str, object]:
    pending = [
        (evaluation, task)
        for evaluation in evaluations
        for task in evaluation.pending_judges
    ]
    if not pending:
        return {
            "pending_tasks": 0,
            "single_calls": 0,
            "batch_count": 0,
            "batch_calls": 0,
            "fallback_single_calls": 0,
            "errors": 0,
        }

    if judge_concurrency == 1:
        executions = [
            _execute_retrieval_judge_single(remote_llm, pair)
            for pair in pending
        ]
    else:
        executions_by_index: dict[int, _JudgeBatchExecution] = {}
        with ThreadPoolExecutor(max_workers=judge_concurrency) as executor:
            futures = {
                executor.submit(_execute_retrieval_judge_single, remote_llm, pair): index
                for index, pair in enumerate(pending)
            }
            for future in as_completed(futures):
                executions_by_index[futures[future]] = future.result()
        executions = [executions_by_index[index] for index in range(len(pending))]

    for execution in executions:
        for evaluation, task, judge in execution.results:
            evaluation.item = _retrieval_item_with_judge_result(
                evaluation.item,
                task,
                _decorate_single_judge(judge, task),
            )
    return {
        "pending_tasks": len(pending),
        "single_calls": sum(execution.single_calls for execution in executions),
        "batch_count": 0,
        "batch_calls": 0,
        "fallback_single_calls": 0,
        "errors": sum(execution.errors for execution in executions),
    }


def _execute_retrieval_judge_single(
    remote_llm: RemoteLLMClient,
    pair: tuple[_RetrievalCaseEvaluation, _PendingRetrievalJudgeTask],
) -> _JudgeBatchExecution:
    evaluation, task = pair
    judge = _safe_remote_recall_judge(
        remote_llm,
        query=task.query,
        memories=task.candidate_memories,
        local_decisions=task.local_decisions,
        scopes=task.scopes,
    )
    skipped_remote = bool(judge.metadata.get("skipped_remote_call"))
    return _JudgeBatchExecution(
        results=[(evaluation, task, judge)],
        single_calls=0 if skipped_remote else 1,
        errors=1 if "remote_recall_judge_error" in judge.warnings else 0,
    )


def _run_pending_retrieval_batch_judges(
    evaluations: list[_RetrievalCaseEvaluation],
    remote_llm: RemoteLLMClient,
    *,
    judge_group_size: int,
    judge_concurrency: int,
) -> dict[str, object]:
    pending = [
        (evaluation, task)
        for evaluation in evaluations
        for task in evaluation.pending_judges
    ]
    if not pending:
        return {
            "pending_tasks": 0,
            "single_calls": 0,
            "batch_count": 0,
            "batch_calls": 0,
            "fallback_single_calls": 0,
            "errors": 0,
        }

    batches = _chunks(pending, judge_group_size)
    if judge_concurrency == 1:
        executions = [
            _execute_retrieval_judge_batch(remote_llm, batch)
            for batch in batches
        ]
    else:
        executions_by_index: dict[int, _JudgeBatchExecution] = {}
        with ThreadPoolExecutor(max_workers=judge_concurrency) as executor:
            futures = {
                executor.submit(_execute_retrieval_judge_batch, remote_llm, batch): index
                for index, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                executions_by_index[futures[future]] = future.result()
        executions = [executions_by_index[index] for index in range(len(batches))]

    for execution in executions:
        for evaluation, task, judge in execution.results:
            evaluation.item = _retrieval_item_with_judge_result(
                evaluation.item,
                task,
                _decorate_batch_judge(judge, task),
            )
    return {
        "pending_tasks": len(pending),
        "single_calls": 0,
        "batch_count": len(batches),
        "batch_calls": sum(execution.batch_calls for execution in executions),
        "fallback_single_calls": sum(
            execution.fallback_single_calls for execution in executions
        ),
        "errors": sum(execution.errors for execution in executions),
    }


def _execute_retrieval_judge_batch(
    remote_llm: RemoteLLMClient,
    pairs: list[tuple[_RetrievalCaseEvaluation, _PendingRetrievalJudgeTask]],
) -> _JudgeBatchExecution:
    if not pairs:
        return _JudgeBatchExecution()
    requests = [
        {
            "request_id": task.request_id,
            "query": task.query,
            "memories": task.candidate_memories,
            "local_decisions": task.local_decisions,
            "scopes": task.scopes,
        }
        for _evaluation, task in pairs
    ]
    try:
        results_by_id = remote_llm.judge_retrieval_batch(requests)
        return _JudgeBatchExecution(
            results=[
                (evaluation, task, results_by_id[task.request_id])
                for evaluation, task in pairs
                if task.request_id in results_by_id
            ],
            batch_calls=1,
        )
    except RemoteAdapterError:
        if len(pairs) == 1:
            evaluation, task = pairs[0]
            judge = _safe_remote_recall_judge(
                remote_llm,
                query=task.query,
                memories=task.candidate_memories,
                local_decisions=task.local_decisions,
                scopes=task.scopes,
            )
            judge = judge.model_copy(
                update={
                    "metadata": {
                        **judge.metadata,
                        "batch_fallback_single": True,
                    }
                }
            )
            return _JudgeBatchExecution(
                results=[(evaluation, task, judge)],
                fallback_single_calls=1,
                errors=1,
            )
        middle = len(pairs) // 2
        left = _execute_retrieval_judge_batch(remote_llm, pairs[:middle])
        right = _execute_retrieval_judge_batch(remote_llm, pairs[middle:])
        return _JudgeBatchExecution(
            results=[*left.results, *right.results],
            batch_calls=left.batch_calls + right.batch_calls,
            fallback_single_calls=left.fallback_single_calls + right.fallback_single_calls,
            errors=left.errors + right.errors + 1,
    )


def _decorate_single_judge(
    judge: RemoteRecallJudgeResult,
    task: _PendingRetrievalJudgeTask,
) -> RemoteRecallJudgeResult:
    skipped_remote = bool(judge.metadata.get("skipped_remote_call"))
    metadata = {
        **judge.metadata,
        "request_mode": "single",
        "remote_judge_called": not skipped_remote,
    }
    if task.call_reason:
        metadata["call_reason"] = task.call_reason
    if skipped_remote and "skip_reason" not in metadata:
        metadata["skip_reason"] = "remote_single_skipped"
    return judge.model_copy(update={"metadata": metadata})


def _decorate_batch_judge(
    judge: RemoteRecallJudgeResult,
    task: _PendingRetrievalJudgeTask,
) -> RemoteRecallJudgeResult:
    skipped_remote = bool(judge.metadata.get("skipped_remote_call"))
    metadata = {
        **judge.metadata,
        "request_mode": "batch",
        "remote_judge_called": not skipped_remote,
    }
    if task.call_reason:
        metadata["call_reason"] = task.call_reason
    if skipped_remote and "skip_reason" not in metadata:
        metadata["skip_reason"] = "remote_batch_skipped"
    return judge.model_copy(update={"metadata": metadata})


def _retrieval_item_with_judge_result(
    item: RemoteRetrievalEvaluationItem,
    task: _PendingRetrievalJudgeTask,
    judge: RemoteRecallJudgeResult,
) -> RemoteRetrievalEvaluationItem:
    selected = _selected_memories_from_judge(
        task.candidate_memories,
        judge,
        limit=task.limit,
    )
    aliases = [task.alias_by_id[memory.id] for memory in selected if memory.id in task.alias_by_id]
    ambiguous = (
        [
            task.alias_by_id[memory.id]
            for memory in task.candidate_memories
            if memory.id in task.alias_by_id
        ]
        if judge.decision == "ambiguous"
        else []
    )
    missing = [alias for alias in task.expected_aliases if alias not in aliases]
    unexpected = [alias for alias in task.absent_aliases if alias in aliases]
    results_by_mode = {**item.results_by_mode, task.mode: aliases}
    missing_by_mode = {**item.missing_by_mode, task.mode: missing}
    unexpected_by_mode = {**item.unexpected_by_mode, task.mode: unexpected}
    ambiguous_by_mode = {**item.ambiguous_by_mode, task.mode: ambiguous}
    passed_by_mode = {
        **item.passed_by_mode,
        task.mode: not missing and not unexpected and not ambiguous,
    }
    judge_by_mode = {
        **item.judge_by_mode,
        task.mode: _retrieval_judge_trace(
            judge,
            candidate_memories=task.candidate_memories,
            selected_memories=selected,
            alias_by_id=task.alias_by_id,
        ),
    }
    return item.model_copy(
        update={
            "results_by_mode": results_by_mode,
            "missing_by_mode": missing_by_mode,
            "unexpected_by_mode": unexpected_by_mode,
            "ambiguous_by_mode": ambiguous_by_mode,
            "passed_by_mode": passed_by_mode,
            "judge_by_mode": judge_by_mode,
        }
    )


def _prefetch_retrieval_embedding_cache(
    cases: list[dict],
    remote_embedding: RemoteEmbeddingClient,
    *,
    model: str,
    batch_size: int,
    case_concurrency: int,
    cache: _EmbeddingCache,
) -> dict[str, object]:
    texts = list(dict.fromkeys(_retrieval_fixture_embedding_texts(cases)))
    batches = _chunks(texts, batch_size)
    errors: list[str] = []

    def embed_batch(batch: list[str]) -> None:
        _embed_texts_resilient(
            remote_embedding,
            batch,
            model=model,
            cache=cache,
        )

    if case_concurrency == 1:
        for batch in batches:
            try:
                embed_batch(batch)
            except RemoteAdapterError as exc:
                errors.append(str(exc))
    else:
        with ThreadPoolExecutor(max_workers=case_concurrency) as executor:
            futures = [executor.submit(embed_batch, batch) for batch in batches]
            for future in as_completed(futures):
                try:
                    future.result()
                except RemoteAdapterError as exc:
                    errors.append(str(exc))

    return {
        "enabled": True,
        "case_concurrency": case_concurrency,
        "text_count": len(texts),
        "batch_count": len(batches),
        "errors": len(errors),
        "error_samples": errors[:3],
    }


def _retrieval_fixture_embedding_texts(cases: list[dict]) -> list[str]:
    texts: list[str] = []
    for case in cases:
        store = MemoryStore(":memory:")
        by_alias = _seed_case_memories(store, case.get("memories", []))
        active_memories = [memory for memory in by_alias.values() if memory.status == "active"]
        texts.extend(build_memory_embedding_text(memory) for memory in active_memories)
        search_payload = dict(case.get("search", {}))
        query = str(search_payload.get("query", ""))
        texts.append(query if query.strip() else str(case.get("name", "empty query")))
    return texts


def _retrieval_evaluation_provider(evaluations: list[_RetrievalCaseEvaluation]) -> str:
    for evaluation in evaluations:
        if evaluation.provider != "cache":
            return evaluation.provider
    if evaluations:
        return evaluations[-1].provider
    return "remote"


def _retrieval_evaluation_model(
    evaluations: list[_RetrievalCaseEvaluation],
    *,
    fallback: str,
) -> str:
    for evaluation in reversed(evaluations):
        if evaluation.model:
            return evaluation.model
    return fallback


@dataclass
class _EmbeddingCache:
    path: Path
    entries: dict[str, dict[str, object]] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
    writes: int = 0
    load_errors: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                self.load_errors += 1
                continue
            key = payload.get("key")
            vector = payload.get("vector")
            if isinstance(key, str) and isinstance(vector, list):
                self.entries[key] = payload

    def get(self, *, model: str, text: str) -> list[float] | None:
        with self._lock:
            payload = self.entries.get(_embedding_cache_key(model=model, text=text))
            if payload is None:
                self.misses += 1
                return None
            vector = payload.get("vector")
            if not isinstance(vector, list):
                self.misses += 1
                return None
            self.hits += 1
            return [float(item) for item in vector]

    def put(
        self,
        *,
        model: str,
        text: str,
        vector: list[float],
        provider: str,
    ) -> None:
        key = _embedding_cache_key(model=model, text=text)
        payload = {
            "key": key,
            "model": model,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "provider": provider,
            "dimensions": len(vector),
            "vector": vector,
        }
        with self._lock:
            self.entries[key] = payload
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.writes += 1

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "enabled": True,
                "path": str(self.path),
                "entries": len(self.entries),
                "hits": self.hits,
                "misses": self.misses,
                "writes": self.writes,
                "load_errors": self.load_errors,
            }


def _embedding_cache_key(*, model: str, text: str) -> str:
    payload = json.dumps(
        {"model": model, "text": text},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _embed_texts_resilient(
    remote_embedding: RemoteEmbeddingClient,
    texts: list[str],
    *,
    model: str,
    cache: _EmbeddingCache | None,
) -> RemoteEmbeddingResult:
    vectors: list[list[float] | None] = [None] * len(texts)
    missing_indexes: list[int] = []
    missing_texts: list[str] = []
    if cache:
        for index, text in enumerate(texts):
            cached = cache.get(model=model, text=text)
            if cached is None:
                missing_indexes.append(index)
                missing_texts.append(text)
            else:
                vectors[index] = cached
    else:
        missing_indexes = list(range(len(texts)))
        missing_texts = list(texts)

    provider = "cache" if not missing_texts else "remote"
    resolved_model = model
    if missing_texts:
        embedded = _embed_uncached_with_split(remote_embedding, missing_texts, model=model)
        if len(embedded.vectors) != len(missing_texts):
            raise RemoteAdapterError(
                f"expected {len(missing_texts)} vectors, got {len(embedded.vectors)}"
            )
        provider = embedded.provider
        resolved_model = embedded.model or model
        for index, text, vector in zip(missing_indexes, missing_texts, embedded.vectors):
            vectors[index] = vector
            if cache:
                cache.put(model=model, text=text, vector=vector, provider=provider)
                if resolved_model != model:
                    cache.put(model=resolved_model, text=text, vector=vector, provider=provider)

    resolved_vectors = [vector for vector in vectors if vector is not None]
    if len(resolved_vectors) != len(texts):
        raise RemoteAdapterError("remote embedding cache returned incomplete vectors")
    dimensions = len(resolved_vectors[0]) if resolved_vectors else 0
    return RemoteEmbeddingResult(
        provider=provider,
        model=resolved_model,
        vectors=resolved_vectors,
        dimensions=dimensions,
        metadata={"cache": cache.stats() if cache else {"enabled": False}},
    )


def _embed_uncached_with_split(
    remote_embedding: RemoteEmbeddingClient,
    texts: list[str],
    *,
    model: str,
) -> RemoteEmbeddingResult:
    try:
        embedded = remote_embedding.embed_texts(texts, model=model)
        if len(embedded.vectors) != len(texts):
            raise RemoteAdapterError(
                f"expected {len(texts)} vectors, got {len(embedded.vectors)}"
            )
        return embedded
    except RemoteAdapterError:
        if len(texts) == 1:
            raise
        middle = len(texts) // 2
        left = _embed_uncached_with_split(remote_embedding, texts[:middle], model=model)
        right = _embed_uncached_with_split(remote_embedding, texts[middle:], model=model)
        resolved_model = right.model or left.model or model
        vectors = [*left.vectors, *right.vectors]
        return RemoteEmbeddingResult(
            provider=right.provider or left.provider,
            model=resolved_model,
            vectors=vectors,
            dimensions=len(vectors[0]) if vectors else 0,
            metadata={"split_retry": True},
        )


def _remote_retrieval_error_item(
    case: dict[str, object],
    *,
    query: str,
    message: str,
    include_llm_judge: bool,
    include_selective_llm_judge: bool,
) -> RemoteRetrievalEvaluationItem:
    modes = ["keyword", "semantic", "hybrid", "guarded_hybrid"]
    if include_llm_judge:
        modes.append("llm_guarded_hybrid")
    if include_selective_llm_judge:
        modes.append("selective_llm_guarded_hybrid")
    expected_aliases = _expected_aliases(case)
    return RemoteRetrievalEvaluationItem(
        case_name=str(case.get("name", "")),
        category=case.get("category") if isinstance(case.get("category"), str) else None,
        query=query,
        expected_aliases=expected_aliases,
        results_by_mode={mode: [] for mode in modes},
        missing_by_mode={mode: list(expected_aliases) for mode in modes},
        unexpected_by_mode={mode: [] for mode in modes},
        ambiguous_by_mode={mode: ["remote_error"] for mode in modes},
        passed_by_mode={mode: False for mode in modes},
        warnings=["remote_embedding_error"],
        metadata={"remote_error": message},
    )


def _safe_remote_recall_judge(
    remote_llm: RemoteLLMClient,
    *,
    query: str,
    memories: list[MemoryItemRead],
    local_decisions: list[RemoteRetrievalGuardDecisionRead],
    scopes: list[str],
) -> RemoteRecallJudgeResult:
    try:
        return remote_llm.judge_retrieval(
            query=query,
            memories=memories,
            local_decisions=local_decisions,
            scopes=scopes,
        )
    except RemoteAdapterError as exc:
        return _local_recall_judge_result(
            query=query,
            decision="ambiguous",
            reason=f"Remote recall judge failed: {exc}",
            warnings=["remote_recall_judge_error"],
            metadata={"remote_error": str(exc)},
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
    if _is_private_fact_query(query or local_guard.query):
        return True, "private_fact_query"
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


def _is_private_fact_query(query: str) -> bool:
    normalized = query.strip().lower()
    if not normalized:
        return False
    asks_for_specific_value = any(
        term in normalized for term in PRIVATE_FACT_QUESTION_TERMS
    ) or normalized.endswith("?")
    mentions_private_target = any(
        term in normalized for term in PRIVATE_FACT_TARGET_TERMS
    )
    return asks_for_specific_value and mentions_private_target


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


def _chunks(items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _load_retrieval_cases(
    fixture_path: str | Path,
    *,
    limit: int | None = None,
    sample_size: int | None = None,
    sample_seed: int | None = None,
) -> list[dict]:
    if sample_size is not None and sample_size < 1:
        raise ValueError("sample_size must be greater than zero")
    path = Path(fixture_path)
    cases: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        if case.get("mode") == "retrieval":
            cases.append(case)
        if sample_size is None and limit is not None and len(cases) >= limit:
            break
    if sample_size is not None:
        sample_count = min(sample_size, len(cases))
        cases = random.Random(sample_seed).sample(cases, sample_count)
    if limit is not None:
        cases = cases[:limit]
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
