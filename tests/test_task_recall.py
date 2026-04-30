from __future__ import annotations

from memory_system import MemoryItemCreate, MemoryStore, RecallPlanner, recall_for_task


def test_recall_planner_detects_documentation_startup_and_scope():
    plan = RecallPlanner().plan(
        "帮我写这个项目的启动说明 README",
        scope="repo:C:/workspace/demo",
    )

    assert plan.intent == "documentation"
    assert plan.scopes == ["repo:C:/workspace/demo", "global"]
    assert "user_preference" in plan.memory_types
    assert "project_fact" in plan.memory_types
    assert "tool_rule" in plan.memory_types
    assert any("start command" in term for term in plan.query_terms)


def test_recall_planner_expands_compound_remote_memory_task():
    plan = RecallPlanner().plan(
        "\u7ee7\u7eed\u521a\u624d\u90a3\u6279\u4e2d\u6587\u8fdc\u7a0b\u53ec\u56de\u6d4b\u8bd5\uff0c\u770b\u4e00\u4e0b DeepSeek judge",
        scope="repo:C:/workspace/demo",
    )

    assert plan.intent == "verification"
    assert "workflow" in plan.memory_types
    assert "decision" in plan.memory_types
    assert "environment_fact" in plan.memory_types
    assert len(plan.query_terms) <= 10
    assert any("recall" in term for term in plan.query_terms)
    assert "DeepSeek" in plan.query_terms
    assert "judge" in plan.query_terms
    assert "Chinese" in plan.query_terms
    assert any("previous" in term for term in plan.query_terms)
    assert "task facet detected: remote" in plan.reasons
    assert "task facet detected: continuation" in plan.reasons


def test_recall_for_task_returns_relevant_memories_and_context():
    memories = MemoryStore(":memory:")
    pref = memories.add_memory(
        MemoryItemCreate(
            content="TASK_RECALL_UNIT documentation style uses Chinese.",
            memory_type="user_preference",
            scope="global",
            subject="doc style",
            confidence="confirmed",
            source_event_ids=["evt_pref"],
            tags=["docs"],
        )
    )
    start = memories.add_memory(
        MemoryItemCreate(
            content="TASK_RECALL_UNIT start command is pnpm dev.",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="start command",
            confidence="confirmed",
            source_event_ids=["evt_start"],
            tags=["startup"],
        )
    )
    other = memories.add_memory(
        MemoryItemCreate(
            content="TASK_RECALL_UNIT other repo start command is yarn dev.",
            memory_type="project_fact",
            scope="repo:C:/workspace/other",
            subject="start command",
            confidence="confirmed",
            source_event_ids=["evt_other"],
        )
    )

    result = recall_for_task(
        "TASK_RECALL_UNIT 帮我写启动说明 README",
        memories,
        scope="repo:C:/workspace/demo",
    )

    ids = [memory.id for memory in result.memories]
    assert start.id in ids
    assert pref.id in ids
    assert other.id not in ids
    assert start.id in result.context.memory_ids
    assert pref.id in result.context.memory_ids
    logs = memories.list_retrieval_logs(source="task_recall")
    assert len(logs) == 1
    assert logs[0].task == "TASK_RECALL_UNIT 帮我写启动说明 README"
    assert logs[0].task_type == "documentation"
    assert set(logs[0].retrieved_memory_ids) == {start.id, pref.id}
    assert set(logs[0].used_memory_ids) == {start.id, pref.id}
    assert logs[0].metadata["limit_per_query"] == 5


def test_recall_for_task_uses_expanded_terms_for_compound_task():
    memories = MemoryStore(":memory:")
    workflow = memories.add_memory(
        MemoryItemCreate(
            content="Remote retrieval workflow uses DeepSeek judge with an embedding cache.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="remote retrieval workflow",
            confidence="confirmed",
            source_event_ids=["evt_remote_workflow"],
            tags=["recall", "judge"],
        )
    )
    decision = memories.add_memory(
        MemoryItemCreate(
            content="Chinese semantic retrieval samples should be evaluated before public cases.",
            memory_type="decision",
            scope="repo:C:/workspace/demo",
            subject="Chinese retrieval priority",
            confidence="confirmed",
            source_event_ids=["evt_remote_decision"],
            tags=["Chinese", "evaluation"],
        )
    )
    other = memories.add_memory(
        MemoryItemCreate(
            content="Remote retrieval workflow for another repo uses a different judge.",
            memory_type="workflow",
            scope="repo:C:/workspace/other",
            subject="other remote workflow",
            confidence="confirmed",
            source_event_ids=["evt_other_remote"],
        )
    )

    result = recall_for_task(
        "\u7ee7\u7eed\u521a\u624d\u90a3\u6279\u4e2d\u6587\u8fdc\u7a0b\u53ec\u56de\u6d4b\u8bd5\uff0c\u770b\u4e00\u4e0b DeepSeek judge",
        memories,
        scope="repo:C:/workspace/demo",
    )

    ids = [memory.id for memory in result.memories]
    assert workflow.id in ids
    assert decision.id in ids
    assert other.id not in ids
    assert workflow.id in result.context.memory_ids
    assert decision.id in result.context.memory_ids
    assert result.plan.intent == "verification"
    assert "DeepSeek" in result.plan.query_terms
    assert "Chinese" in result.plan.query_terms
