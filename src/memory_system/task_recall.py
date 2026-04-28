from __future__ import annotations

from collections.abc import Iterable

from memory_system.context_composer import compose_context
from memory_system.memory_store import MemoryStore
from memory_system.schemas import (
    MemoryItemRead,
    MemoryType,
    RecallPlan,
    RetrievalLogCreate,
    SearchMemoryInput,
    TaskRecallResult,
)


DOC_CUES = ("文档", "说明", "README", "readme", "docs", "documentation")
START_CUES = ("启动", "运行", "start", "dev", "serve")
DEBUG_CUES = ("报错", "失败", "错误", "排错", "debug", "error", "fail", "failure")
TEST_CUES = ("测试", "验证", "pytest", "ruff", "test", "check", "verify")
STRUCTURE_CUES = ("结构", "架构", "目录", "模块", "structure", "architecture", "module")
PREFERENCE_CUES = ("偏好", "风格", "默认", "preference", "style", "tone")

DEFAULT_TYPES: list[MemoryType] = ["user_preference", "project_fact", "workflow"]


def _contains_any(text: str, cues: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(cue.lower() in lowered for cue in cues)


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

        memory_types: list[MemoryType] = list(DEFAULT_TYPES)
        query_terms = [cleaned_task]
        reasons: list[str] = []
        intent = "general"

        if _contains_any(cleaned_task, DOC_CUES):
            intent = "documentation"
            memory_types.extend(["tool_rule", "workflow"])
            query_terms.extend(["文档", "说明", "README", "docs", "documentation"])
            reasons.append("task looks like documentation work")

        if _contains_any(cleaned_task, START_CUES):
            if intent == "general":
                intent = "startup"
            memory_types.extend(["tool_rule", "environment_fact"])
            query_terms.extend(["启动", "启动命令", "start command", "dev"])
            reasons.append("task mentions startup or running commands")

        if _contains_any(cleaned_task, DEBUG_CUES):
            intent = "troubleshooting"
            memory_types.extend(["troubleshooting", "project_fact", "environment_fact", "tool_rule"])
            query_terms.extend(["报错", "失败", "错误", "排错", "error", "debug", "troubleshooting"])
            reasons.append("task looks like debugging or troubleshooting")

        if _contains_any(cleaned_task, TEST_CUES):
            if intent in {"general", "startup"}:
                intent = "verification"
            memory_types.extend(["tool_rule", "troubleshooting", "workflow", "project_fact"])
            query_terms.extend(["测试", "验证", "pytest", "ruff", "test", "verify"])
            reasons.append("task mentions testing or verification")

        if _contains_any(cleaned_task, STRUCTURE_CUES):
            intent = "project_structure" if intent == "general" else intent
            memory_types.extend(["project_fact", "workflow", "tool_rule"])
            query_terms.extend(["项目结构", "目录", "架构", "structure", "architecture", "module"])
            reasons.append("task asks about project structure")

        if _contains_any(cleaned_task, PREFERENCE_CUES):
            intent = "preference" if intent == "general" else intent
            memory_types.insert(0, "user_preference")
            query_terms.extend(["偏好", "风格", "默认", "preference", "style", "tone"])
            reasons.append("task asks for user preference or style")

        scopes = ["global"]
        if scope and scope.strip() and scope.strip() != "global":
            scopes.insert(0, scope.strip())

        return RecallPlan(
            task=cleaned_task,
            scope=scope.strip() if scope and scope.strip() else None,
            intent=intent,
            query_terms=_unique(query_terms),
            memory_types=list(dict.fromkeys(memory_types)),
            scopes=scopes,
            limit_per_query=limit_per_query,
            reasons=reasons or ["default recall plan"],
        )


def recall_for_task(
    task: str,
    store: MemoryStore,
    *,
    scope: str | None = None,
    token_budget: int = 2000,
    planner: RecallPlanner | None = None,
    limit_per_query: int = 5,
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
    context = compose_context(plan.task, memories, token_budget=token_budget)
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
