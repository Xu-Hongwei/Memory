from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from memory_system import (
    MemoryItemCreate,
    MemoryStore,
    RecallPlan,
    SessionMemoryItemCreate,
    SessionMemoryStore,
    create_app,
    orchestrate_recall,
)
from memory_system.schemas import RemoteEmbeddingResult, RemoteRecallJudgeResult


SCOPE = "repo:C:/workspace/orchestrator"


def _add_memory(
    store: MemoryStore,
    content: str,
    *,
    memory_type: str = "workflow",
    subject: str = "Project workflow",
    scope: str = SCOPE,
):
    return store.add_memory(
        MemoryItemCreate(
            content=content,
            memory_type=memory_type,
            scope=scope,
            subject=subject,
            confidence="confirmed",
            source_event_ids=["evt_orchestrator"],
        )
    )


class FakeEmbeddingClient:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.config = SimpleNamespace(embedding_model="fake-embedding")

    def embed_texts(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> RemoteEmbeddingResult:
        return RemoteEmbeddingResult(
            provider="fake-embedding",
            model=model or self.config.embedding_model,
            vectors=[self.vector for _text in texts],
            dimensions=len(self.vector),
        )


class RejectingFakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def judge_retrieval(
        self,
        *,
        query,
        memories,
        local_decisions,
        scopes,
    ) -> RemoteRecallJudgeResult:
        self.calls.append(
            {
                "query": query,
                "memory_ids": [memory.id for memory in memories],
                "local_decision_count": len(local_decisions),
                "scopes": scopes,
            }
        )
        return RemoteRecallJudgeResult(
            provider="fake-llm",
            model="fake-llm",
            query=query,
            decision="rejected",
            selected_memory_ids=[],
            reason="The candidates do not answer the concrete fact question.",
            metadata={"remote_judge_called": True},
        )


class PlanningFakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def plan_recall(self, *, task, scope=None, limit_per_query=5, instructions=None):
        self.calls.append(
            {
                "task": task,
                "scope": scope,
                "limit_per_query": limit_per_query,
                "instructions": instructions,
            }
        )
        return RecallPlan(
            task=task,
            scope=scope,
            intent="verification",
            query_terms=["REMOTE_PLAN_TARGET"],
            memory_types=["workflow"],
            scopes=[scope, "global"] if scope else ["global"],
            limit_per_query=limit_per_query,
            reasons=["remote planner selected target query"],
            facets=["remote"],
            identifiers=["REMOTE_PLAN_TARGET"],
            strategy_hint="keyword",
            include_graph=False,
            include_session=False,
            needs_llm_judge=False,
            confidence=0.9,
            planner_source="remote",
        )


class BrokenPlannerFakeLLM:
    def plan_recall(self, *, task, scope=None, limit_per_query=5, instructions=None):
        del task, scope, limit_per_query, instructions
        raise ValueError("planner unavailable")


def test_orchestrated_recall_uses_local_keyword_and_records_log():
    store = MemoryStore(":memory:")
    memory = _add_memory(store, "The project start command is memoryctl serve.")

    result = orchestrate_recall(
        "How do I start the project?",
        store,
        scope=SCOPE,
        include_graph=False,
    )

    assert result.selected_strategy == "keyword"
    assert [item.id for item in result.memories] == [memory.id]
    assert result.context.memory_ids == [memory.id]

    logs = store.list_retrieval_logs(source="orchestrated_recall")
    assert len(logs) == 1
    assert logs[0].retrieved_memory_ids == [memory.id]
    assert logs[0].used_memory_ids == [memory.id]
    assert logs[0].metadata["selected_strategy"] == "keyword"


def test_orchestrated_recall_uses_remote_planner_first():
    store = MemoryStore(":memory:")
    memory = _add_memory(store, "REMOTE_PLAN_TARGET should be recalled.")
    fake_llm = PlanningFakeLLM()

    result = orchestrate_recall(
        "Use the remote planner",
        store,
        scope=SCOPE,
        include_graph=False,
        remote_llm=fake_llm,
    )

    assert fake_llm.calls
    assert result.plan is not None
    assert result.plan.planner_source == "remote"
    assert result.selected_strategy == "keyword"
    assert [item.id for item in result.memories] == [memory.id]
    assert result.metadata["planner_source"] == "remote"


def test_orchestrated_recall_skips_graph_when_planner_does_not_need_it():
    store = MemoryStore(":memory:")
    memory = _add_memory(store, "REMOTE_PLAN_TARGET should be recalled.")

    result = orchestrate_recall(
        "Use the remote planner",
        store,
        scope=SCOPE,
        include_graph=True,
        remote_llm=PlanningFakeLLM(),
    )

    assert [item.id for item in result.memories] == [memory.id]
    assert result.plan is not None
    assert result.plan.include_graph is False
    assert all(step.name != "graph_recall" for step in result.steps)
    assert result.metadata["effective_include_graph"] is False


def test_orchestrated_recall_falls_back_when_remote_planner_fails():
    store = MemoryStore(":memory:")
    memory = _add_memory(store, "The project start command is memoryctl serve.")

    result = orchestrate_recall(
        "How do I start the project?",
        store,
        scope=SCOPE,
        include_graph=False,
        remote_llm=BrokenPlannerFakeLLM(),
    )

    assert result.plan is not None
    assert result.plan.planner_source == "fallback"
    assert "remote_planner_failed:ValueError" in result.plan.planner_warnings
    assert [item.id for item in result.memories] == [memory.id]


def test_orchestrated_recall_includes_session_memory_in_context():
    store = MemoryStore(":memory:")
    memory = _add_memory(
        store,
        "Prepare the next evaluation with guarded hybrid retrieval.",
        subject="Evaluation workflow",
    )
    session_store = SessionMemoryStore()
    session_item = session_store.add_item(
        SessionMemoryItemCreate(
            content="For this run, only evaluate the Chinese sample set.",
            session_id="s-eval",
            memory_type="temporary_rule",
            scope=SCOPE,
            subject="current evaluation subset",
            source_event_ids=["evt_session_orchestrator"],
        )
    )

    result = orchestrate_recall(
        "Prepare the next evaluation",
        store,
        scope=SCOPE,
        include_graph=False,
        session_store=session_store,
        session_id="s-eval",
        session_limit=3,
    )

    assert result.selected_strategy == "keyword"
    assert [item.id for item in result.memories] == [memory.id]
    assert result.context.memory_ids == [memory.id]
    assert result.metadata["session_memory_ids"] == [session_item.id]
    assert "[session][temporary_rule]" in result.context.content
    assert "only evaluate the Chinese sample set" in result.context.content
    assert result.context.content.index("[session][temporary_rule]") < result.context.content.index(
        "[confirmed][workflow]"
    )
    assert result.steps[-1].name == "session_recall"
    assert result.steps[-1].accepted_memory_ids == [session_item.id]

    logs = store.list_retrieval_logs(source="orchestrated_recall")
    assert logs[0].used_memory_ids == [memory.id]
    assert logs[0].metadata["session_memory_ids"] == session_item.id


def test_orchestrated_recall_soft_caps_session_when_planner_does_not_need_session():
    store = MemoryStore(":memory:")
    memory = _add_memory(store, "REMOTE_PLAN_TARGET should be recalled.")
    session_store = SessionMemoryStore()
    session_store.add_item(
        SessionMemoryItemCreate(
            content="First session note for the current run.",
            session_id="s-soft-cap",
            memory_type="scratch_note",
            scope=SCOPE,
            subject="first session note",
            source_event_ids=["evt_session_soft_cap_1"],
        )
    )
    session_store.add_item(
        SessionMemoryItemCreate(
            content="Second session note for the current run.",
            session_id="s-soft-cap",
            memory_type="scratch_note",
            scope=SCOPE,
            subject="second session note",
            source_event_ids=["evt_session_soft_cap_2"],
        )
    )

    result = orchestrate_recall(
        "Use the remote planner",
        store,
        scope=SCOPE,
        include_graph=False,
        remote_llm=PlanningFakeLLM(),
        session_store=session_store,
        session_id="s-soft-cap",
        session_limit=3,
    )

    assert [item.id for item in result.memories] == [memory.id]
    assert result.plan is not None
    assert result.plan.include_session is False
    assert result.metadata["session_planner_soft_cap"] is True
    assert result.metadata["effective_session_limit"] == 1
    assert len(result.metadata["session_memory_ids"]) == 1
    assert result.steps[-1].name == "session_recall"
    assert len(result.steps[-1].accepted_memory_ids) == 1


def test_orchestrated_recall_skips_low_memory_need_task():
    store = MemoryStore(":memory:")
    _add_memory(store, "The project start command is memoryctl serve.")

    result = orchestrate_recall("ok", store)

    assert result.memory_needed is False
    assert result.selected_strategy == "none"
    assert result.memories == []
    assert result.context.memory_ids == []
    assert "recall_skipped_low_memory_need" in result.warnings

    logs = store.list_retrieval_logs(source="orchestrated_recall")
    assert len(logs) == 1
    assert logs[0].retrieved_memory_ids == []
    assert logs[0].metadata["memory_needed"] is False


def test_orchestrated_recall_lets_llm_reject_concrete_fact_noise():
    store = MemoryStore(":memory:")
    memory = _add_memory(
        store,
        "The project start command is memoryctl serve.",
        memory_type="project_fact",
        subject="Start command",
    )
    store.upsert_memory_embedding(
        memory.id,
        vector=[1.0, 0.0],
        model="fake-embedding",
        embedded_text=memory.content,
    )
    fake_llm = RejectingFakeLLM()

    result = orchestrate_recall(
        "What is the SLA?",
        store,
        scope=SCOPE,
        include_graph=False,
        remote_embedding=FakeEmbeddingClient([1.0, 0.0]),
        remote_llm=fake_llm,
    )

    assert result.selected_strategy == "selective_llm_guarded_hybrid"
    assert fake_llm.calls
    assert result.memories == []
    assert "no_memories_accepted" in result.warnings
    assert result.steps[0].retrieved_memory_ids == [memory.id]
    assert result.steps[0].skipped_memory_ids == [memory.id]

    logs = store.list_retrieval_logs(source="orchestrated_recall")
    assert logs[0].retrieved_memory_ids == [memory.id]
    assert logs[0].used_memory_ids == []
    assert logs[0].skipped_memory_ids == [memory.id]


def test_api_orchestrated_recall_endpoint_uses_local_strategy(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    store = MemoryStore(db_path)
    memory = _add_memory(store, "The project start command is memoryctl serve.")
    client = TestClient(create_app(db_path))

    response = client.post(
        "/recall/orchestrated",
        json={
            "task": "How do I start the project?",
            "scope": SCOPE,
            "include_graph": False,
            "use_remote_planner": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_strategy"] == "keyword"
    assert [item["id"] for item in payload["memories"]] == [memory.id]
    assert payload["context"]["memory_ids"] == [memory.id]


def test_api_orchestrated_recall_endpoint_includes_session_memory(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    store = MemoryStore(db_path)
    memory = _add_memory(
        store,
        "Prepare the next evaluation with guarded hybrid retrieval.",
        subject="Evaluation workflow",
    )
    app = create_app(db_path)
    session_item = app.state.runtime.sessions.add_item(
        SessionMemoryItemCreate(
            content="For this run, only evaluate the Chinese sample set.",
            session_id="s-api",
            memory_type="temporary_rule",
            scope=SCOPE,
            subject="current evaluation subset",
            source_event_ids=["evt_session_api"],
        )
    )
    client = TestClient(app)

    response = client.post(
        "/recall/orchestrated",
        json={
            "task": "Prepare the next evaluation",
            "scope": SCOPE,
            "include_graph": False,
            "session_id": "s-api",
            "session_limit": 3,
            "use_remote_planner": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["memories"]] == [memory.id]
    assert payload["context"]["memory_ids"] == [memory.id]
    assert payload["metadata"]["session_memory_ids"] == [session_item.id]
    assert "[session][temporary_rule]" in payload["context"]["content"]
    assert "only evaluate the Chinese sample set" in payload["context"]["content"]
