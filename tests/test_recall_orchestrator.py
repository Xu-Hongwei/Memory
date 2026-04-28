from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from memory_system import MemoryItemCreate, MemoryStore, create_app, orchestrate_recall
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
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_strategy"] == "keyword"
    assert [item["id"] for item in payload["memories"]] == [memory.id]
    assert payload["context"]["memory_ids"] == [memory.id]
