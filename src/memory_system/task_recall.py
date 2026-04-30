from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from memory_system.context_composer import compose_context
from memory_system.memory_store import MemoryStore
from memory_system.session_memory import SessionMemoryStore, compose_context_with_session
from memory_system.schemas import (
    MemoryItemRead,
    MemoryType,
    RecallPlan,
    RecallStrategy,
    RetrievalLogCreate,
    SearchMemoryInput,
    TaskRecallResult,
)


DOC_CUES = (
    "\u6587\u6863",
    "\u8bf4\u660e",
    "\u9879\u76ee\u8bf4\u660e",
    "\u4f7f\u7528\u8bf4\u660e",
    "README",
    "readme",
    "docs",
    "documentation",
    "markdown",
)
START_CUES = (
    "\u542f\u52a8",
    "\u8fd0\u884c",
    "\u672c\u5730\u8dd1",
    "\u670d\u52a1",
    "start",
    "dev",
    "serve",
    "run",
    "launch",
)
DEBUG_CUES = (
    "\u62a5\u9519",
    "\u5931\u8d25",
    "\u9519\u8bef",
    "\u6392\u9519",
    "\u4fee\u590d",
    "\u95ee\u9898",
    "debug",
    "error",
    "fail",
    "failure",
    "fix",
    "bug",
    "traceback",
    "exception",
)
TEST_CUES = (
    "\u6d4b\u8bd5",
    "\u9a8c\u8bc1",
    "\u8dd1\u4e00\u4e0b",
    "\u8dd1\u4e00\u6279",
    "\u56de\u5f52",
    "\u8bc4\u4f30",
    "pytest",
    "ruff",
    "test",
    "check",
    "verify",
    "eval",
    "benchmark",
)
STRUCTURE_CUES = (
    "\u7ed3\u6784",
    "\u67b6\u6784",
    "\u76ee\u5f55",
    "\u6a21\u5757",
    "\u94fe\u8def",
    "structure",
    "architecture",
    "module",
    "pipeline",
)
PREFERENCE_CUES = (
    "\u504f\u597d",
    "\u98ce\u683c",
    "\u9ed8\u8ba4",
    "\u4e60\u60ef",
    "\u559c\u6b22",
    "preference",
    "style",
    "tone",
)
MEMORY_CUES = (
    "\u8bb0\u5fc6",
    "\u53ec\u56de",
    "\u4e0a\u4e0b\u6587",
    "\u957f\u671f",
    "\u77ed\u671f",
    "\u5206\u6d41",
    "\u95e8\u7981",
    "memory",
    "recall",
    "context",
    "session",
    "route",
)
REMOTE_CUES = (
    "\u8fdc\u7a0b",
    "\u6a21\u578b",
    "llm",
    "embedding",
    "judge",
    "deepseek",
    "qwen",
)
ENVIRONMENT_CUES = (
    "\u73af\u5883",
    "\u73af\u5883\u53d8\u91cf",
    "\u914d\u7f6e",
    "\u5b89\u88c5",
    "env",
    "environment",
    "config",
    "install",
)
DECISION_CUES = (
    "\u4e0b\u4e00\u6b65",
    "\u63a5\u4e0b\u6765",
    "\u65b9\u6848",
    "\u8ba1\u5212",
    "\u9009\u62e9",
    "\u51b3\u5b9a",
    "next",
    "plan",
    "decision",
    "choose",
)
CONTINUATION_CUES = (
    "\u521a\u624d",
    "\u4e0a\u6b21",
    "\u7ee7\u7eed",
    "\u8fd9\u4e00\u6b65",
    "\u90a3\u4e2a",
    "\u524d\u9762",
    "previous",
    "earlier",
    "continue",
    "last time",
)
LANGUAGE_CUES = (
    "\u4e2d\u6587",
    "\u82f1\u6587",
    "Chinese",
    "English",
)

DEFAULT_TYPES: list[MemoryType] = ["user_preference", "project_fact", "workflow"]
IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_./:-]{2,}")
QUERY_TERM_LIMIT = 10
QUERY_STOPWORDS = {
    "and",
    "are",
    "but",
    "can",
    "for",
    "from",
    "how",
    "the",
    "this",
    "that",
    "with",
    "you",
    "help",
}


@dataclass(frozen=True)
class _TaskFrame:
    task: str
    intent: str
    facets: tuple[str, ...]
    identifiers: tuple[str, ...]
    language_constraints: tuple[str, ...]
    scope: str | None


def _matched_cues(text: str, cues: Iterable[str]) -> list[str]:
    lowered = text.lower()
    return [cue for cue in cues if cue.lower() in lowered]


def _identifier_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in IDENTIFIER_RE.finditer(text):
        term = match.group(0).strip(".,;:!?()[]{}")
        if len(term) < 3 or term.lower() in QUERY_STOPWORDS:
            continue
        terms.append(term)
    return _unique(terms)


def _build_task_frame(task: str, scope: str | None) -> _TaskFrame:
    facet_matches = {
        "documentation": _matched_cues(task, DOC_CUES),
        "startup": _matched_cues(task, START_CUES),
        "troubleshooting": _matched_cues(task, DEBUG_CUES),
        "verification": _matched_cues(task, TEST_CUES),
        "project_structure": _matched_cues(task, STRUCTURE_CUES),
        "preference": _matched_cues(task, PREFERENCE_CUES),
        "memory_system": _matched_cues(task, MEMORY_CUES),
        "remote": _matched_cues(task, REMOTE_CUES),
        "environment": _matched_cues(task, ENVIRONMENT_CUES),
        "planning": _matched_cues(task, DECISION_CUES),
        "continuation": _matched_cues(task, CONTINUATION_CUES),
        "language": _matched_cues(task, LANGUAGE_CUES),
    }
    facets = tuple(facet for facet, matches in facet_matches.items() if matches)
    languages = tuple(
        "Chinese" if match in {"\u4e2d\u6587", "Chinese"} else "English"
        for match in facet_matches["language"]
    )
    return _TaskFrame(
        task=task,
        intent=_choose_intent(facets),
        facets=facets,
        identifiers=tuple(_identifier_terms(task)),
        language_constraints=tuple(_unique(languages)),
        scope=scope.strip() if scope and scope.strip() else None,
    )


def _choose_intent(facets: tuple[str, ...]) -> str:
    priority = (
        "troubleshooting",
        "documentation",
        "verification",
        "project_structure",
        "environment",
        "preference",
        "planning",
        "memory_system",
        "startup",
    )
    for intent in priority:
        if intent in facets:
            return intent
    return "general"


def _memory_types_for_frame(frame: _TaskFrame) -> list[MemoryType]:
    memory_types: list[MemoryType] = list(DEFAULT_TYPES)
    facet_types: dict[str, list[MemoryType]] = {
        "documentation": ["tool_rule", "workflow"],
        "startup": ["tool_rule", "environment_fact"],
        "troubleshooting": ["troubleshooting", "project_fact", "environment_fact", "tool_rule"],
        "verification": ["tool_rule", "troubleshooting", "workflow", "project_fact"],
        "project_structure": ["project_fact", "workflow", "tool_rule"],
        "preference": ["user_preference"],
        "memory_system": ["project_fact", "workflow", "tool_rule", "decision"],
        "remote": ["environment_fact", "tool_rule", "workflow", "project_fact"],
        "environment": ["environment_fact", "tool_rule", "troubleshooting"],
        "planning": ["decision", "workflow", "project_fact", "user_preference"],
        "continuation": ["decision", "workflow", "project_fact", "troubleshooting"],
        "language": ["user_preference", "project_fact", "workflow"],
    }
    for facet in frame.facets:
        memory_types.extend(facet_types.get(facet, []))
    return list(dict.fromkeys(memory_types))


def _query_terms_for_frame(frame: _TaskFrame) -> list[str]:
    terms = [frame.task]
    terms.extend(frame.identifiers[:4])

    facet_queries = {
        "documentation": "README docs documentation",
        "startup": "start command dev serve",
        "troubleshooting": "error debug troubleshooting fix",
        "verification": "pytest ruff test verify benchmark",
        "project_structure": "project structure architecture module pipeline",
        "preference": "preference style tone",
        "memory_system": "memory recall context session route_memories",
        "remote": "remote llm embedding judge",
        "environment": "environment env config install",
        "planning": "next step plan decision workflow",
        "continuation": "previous continue last result decision workflow",
    }
    for facet in frame.facets:
        query = facet_queries.get(facet)
        if query:
            terms.append(query)
    terms.extend(frame.language_constraints)
    return _unique(terms)[:QUERY_TERM_LIMIT]


def _strategy_hint_for_frame(frame: _TaskFrame) -> RecallStrategy:
    if {"remote", "verification", "troubleshooting"} & set(frame.facets):
        return "guarded_hybrid"
    if {"memory_system", "preference"} & set(frame.facets):
        return "guarded_hybrid"
    return "keyword"


def _include_graph_for_frame(frame: _TaskFrame) -> bool:
    return bool({"project_structure", "memory_system"} & set(frame.facets))


def _include_session_for_frame(frame: _TaskFrame) -> bool:
    return bool({"continuation", "planning", "verification", "troubleshooting"} & set(frame.facets))


def _needs_llm_judge_for_frame(frame: _TaskFrame) -> bool:
    return bool({"remote", "memory_system"} & set(frame.facets))


def _reasons_for_frame(frame: _TaskFrame) -> list[str]:
    if not frame.facets:
        return ["default recall plan"]
    return [f"task facet detected: {facet}" for facet in frame.facets]


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        stripped = value.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            result.append(stripped)
    return result


class RecallPlanner:
    def plan(
        self,
        task: str,
        *,
        scope: str | None = None,
        limit_per_query: int = 5,
    ) -> RecallPlan:
        cleaned_task = task.strip()
        if not cleaned_task:
            raise ValueError("task must not be empty")
        if limit_per_query < 1:
            raise ValueError("limit_per_query must be greater than zero")

        frame = _build_task_frame(cleaned_task, scope)

        scopes = ["global"]
        if frame.scope and frame.scope != "global":
            scopes.insert(0, frame.scope)

        return RecallPlan(
            task=cleaned_task,
            scope=frame.scope,
            intent=frame.intent,
            query_terms=_query_terms_for_frame(frame),
            memory_types=_memory_types_for_frame(frame),
            scopes=scopes,
            limit_per_query=limit_per_query,
            reasons=_reasons_for_frame(frame),
            facets=list(frame.facets),
            identifiers=list(frame.identifiers),
            constraints={
                "language": list(frame.language_constraints),
            },
            strategy_hint=_strategy_hint_for_frame(frame),
            include_graph=_include_graph_for_frame(frame),
            include_session=_include_session_for_frame(frame),
            needs_llm_judge=_needs_llm_judge_for_frame(frame),
            confidence=0.65 if frame.facets else 0.35,
            planner_source="local",
        )


def recall_for_task(
    task: str,
    store: MemoryStore,
    *,
    scope: str | None = None,
    token_budget: int = 2000,
    planner: RecallPlanner | None = None,
    limit_per_query: int = 5,
    session_store: SessionMemoryStore | None = None,
    session_id: str = "default",
    session_limit: int = 5,
) -> TaskRecallResult:
    active_planner = planner or RecallPlanner()
    plan = active_planner.plan(task, scope=scope, limit_per_query=limit_per_query)
    found: dict[str, MemoryItemRead] = {}
    first_seen: dict[str, int] = {}

    for query in plan.query_terms:
        results = store.search_memory(
            SearchMemoryInput(
                query=query,
                memory_types=plan.memory_types,
                scopes=plan.scopes,
                limit=plan.limit_per_query,
            ),
            log=False,
        )
        for memory in results:
            if memory.id not in found:
                first_seen[memory.id] = len(first_seen)
            found[memory.id] = memory

    memories = sorted(
        found.values(),
        key=lambda memory: _recall_rank(memory, plan, first_seen[memory.id]),
        reverse=True,
    )
    session_items = []
    if session_store is not None and session_limit > 0:
        session_items = session_store.search(
            plan.task,
            session_id=session_id,
            scopes=plan.scopes,
            limit=session_limit,
        )
    context = (
        compose_context_with_session(
            plan.task,
            session_items,
            memories,
            token_budget=token_budget,
        )
        if session_items
        else compose_context(plan.task, memories, token_budget=token_budget)
    )
    used_memory_ids = set(context.memory_ids)
    store.record_retrieval_log(
        RetrievalLogCreate(
            query=plan.task,
            task=plan.task,
            task_type=plan.intent,
            scope=plan.scope,
            source="task_recall",
            retrieved_memory_ids=[memory.id for memory in memories],
            used_memory_ids=context.memory_ids,
            skipped_memory_ids=[memory.id for memory in memories if memory.id not in used_memory_ids],
            warnings=context.warnings,
            metadata={
                "query_terms": plan.query_terms,
                "memory_types": plan.memory_types,
                "scopes": plan.scopes,
                "limit_per_query": plan.limit_per_query,
                "token_budget": token_budget,
                "session_id": session_id,
                "session_limit": session_limit,
                "session_memory_ids": context.metadata.get("session_memory_ids", ""),
            },
        )
    )
    return TaskRecallResult(plan=plan, memories=memories, context=context)


def _recall_rank(memory: MemoryItemRead, plan: RecallPlan, first_seen: int) -> tuple[int, int, int, int]:
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
