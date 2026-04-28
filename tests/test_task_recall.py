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
    assert "start command" in plan.query_terms


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
