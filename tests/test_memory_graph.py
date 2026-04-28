from __future__ import annotations

from fastapi.testclient import TestClient

from memory_system import (
    MemoryEntityCreate,
    MemoryItemCreate,
    MemoryRelationCreate,
    MemoryStore,
    create_app,
    graph_recall_for_task,
)


SCOPE = "repo:C:/workspace/graph"
OTHER_SCOPE = "repo:C:/workspace/other-graph"


def add_memory(
    memories: MemoryStore,
    content: str,
    *,
    scope: str = SCOPE,
    memory_type: str = "project_fact",
    subject: str = "graph fact",
):
    return memories.add_memory(
        MemoryItemCreate(
            content=content,
            memory_type=memory_type,
            scope=scope,
            subject=subject,
            confidence="confirmed",
            source_event_ids=[f"evt_{content.split()[0]}"],
            tags=["graph"],
        )
    )


def upsert_entity(
    memories: MemoryStore,
    name: str,
    *,
    scope: str = SCOPE,
    entity_type: str = "concept",
    aliases: list[str] | None = None,
):
    return memories.upsert_entity(
        MemoryEntityCreate(
            name=name,
            entity_type=entity_type,
            scope=scope,
            aliases=aliases or [],
        )
    )


def test_upsert_entity_merges_aliases():
    memories = MemoryStore(":memory:")

    first = upsert_entity(memories, "pnpm", entity_type="tool", aliases=["package manager"])
    second = upsert_entity(memories, "pnpm", entity_type="tool", aliases=["包管理器"])

    assert first.id == second.id
    assert second.aliases == ["package manager", "包管理器"]


def test_graph_recall_follows_relations_to_source_memories():
    memories = MemoryStore(":memory:")
    repo = upsert_entity(memories, SCOPE, entity_type="repo", aliases=["GRAPH_REPO"])
    command = upsert_entity(memories, "pnpm dev", entity_type="command", aliases=["启动命令"])
    memory = add_memory(memories, "GRAPH_REPO start command is pnpm dev.")
    relation = memories.create_relation(
        MemoryRelationCreate(
            from_id=repo.id,
            relation_type="has_start_command",
            to_id=command.id,
            source_memory_ids=[memory.id],
            source_event_ids=memory.source_event_ids,
        )
    )

    result = graph_recall_for_task("GRAPH_REPO 启动失败，帮我排查", memories, scope=SCOPE)

    assert [entity.id for entity in result.seed_entities] == [repo.id]
    assert [item.id for item in result.relations] == [relation.id]
    assert [item.id for item in result.memories] == [memory.id]
    assert result.context.memory_ids == [memory.id]
    logs = memories.list_retrieval_logs(source="graph_recall")
    assert len(logs) == 1
    assert logs[0].task == "GRAPH_REPO 启动失败，帮我排查"
    assert logs[0].retrieved_memory_ids == [memory.id]
    assert logs[0].used_memory_ids == [memory.id]
    assert logs[0].metadata["seed_entity_ids"] == [repo.id]
    assert logs[0].metadata["relation_ids"] == [relation.id]


def test_graph_recall_traverses_multiple_hops():
    memories = MemoryStore(":memory:")
    repo = upsert_entity(memories, SCOPE, entity_type="repo")
    tool = upsert_entity(memories, "Vite", entity_type="tool")
    error = upsert_entity(memories, "host binding error", entity_type="error")
    memory = add_memory(
        memories,
        "GRAPH_MULTI Vite host binding error is fixed by --host 0.0.0.0.",
        memory_type="troubleshooting",
        subject="host binding error",
    )
    memories.create_relation(
        MemoryRelationCreate(from_id=repo.id, relation_type="uses_tool", to_id=tool.id)
    )
    memories.create_relation(
        MemoryRelationCreate(
            from_id=tool.id,
            relation_type="can_trigger",
            to_id=error.id,
            source_memory_ids=[memory.id],
        )
    )

    result = graph_recall_for_task("这个项目启动失败", memories, scope=SCOPE, max_depth=2)

    assert [item.id for item in result.memories] == [memory.id]


def test_graph_recall_skips_inactive_cross_scope_and_low_confidence_edges():
    memories = MemoryStore(":memory:")
    repo = upsert_entity(memories, SCOPE, entity_type="repo", aliases=["GRAPH_SKIP"])
    low_conf_target = upsert_entity(memories, "low confidence target")
    other_repo = upsert_entity(
        memories,
        OTHER_SCOPE,
        scope=OTHER_SCOPE,
        entity_type="repo",
        aliases=["GRAPH_SKIP"],
    )
    other_target = upsert_entity(memories, "other command", scope=OTHER_SCOPE)
    inactive_target = upsert_entity(memories, "old command")

    low_conf_memory = add_memory(memories, "GRAPH_SKIP low confidence relation memory.")
    other_memory = add_memory(memories, "GRAPH_SKIP other scope memory.", scope=OTHER_SCOPE)
    inactive_memory = add_memory(memories, "GRAPH_SKIP inactive memory.")
    memories.mark_stale(inactive_memory.id, "Old graph memory.")

    memories.create_relation(
        MemoryRelationCreate(
            from_id=repo.id,
            relation_type="mentions",
            to_id=low_conf_target.id,
            confidence="inferred",
            source_memory_ids=[low_conf_memory.id],
        )
    )
    memories.create_relation(
        MemoryRelationCreate(
            from_id=other_repo.id,
            relation_type="has_command",
            to_id=other_target.id,
            source_memory_ids=[other_memory.id],
        )
    )
    memories.create_relation(
        MemoryRelationCreate(
            from_id=repo.id,
            relation_type="old_fact",
            to_id=inactive_target.id,
            source_memory_ids=[inactive_memory.id],
        )
    )

    result = graph_recall_for_task("GRAPH_SKIP 启动失败", memories, scope=SCOPE)

    assert result.memories == []


def test_api_graph_flow(tmp_path):
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    memory = add_memory(store, "GRAPH_API package.json dev script is pnpm dev.")

    repo = client.post(
        "/graph/entities",
        json={
            "name": SCOPE,
            "entity_type": "repo",
            "scope": SCOPE,
            "aliases": ["GRAPH_API"],
        },
    ).json()
    command = client.post(
        "/graph/entities",
        json={"name": "pnpm dev", "entity_type": "command", "scope": SCOPE},
    ).json()
    relation = client.post(
        "/graph/relations",
        json={
            "from_id": repo["id"],
            "relation_type": "has_start_command",
            "to_id": command["id"],
            "source_memory_ids": [memory.id],
            "source_event_ids": memory.source_event_ids,
        },
    )
    assert relation.status_code == 200

    listed_entities = client.get("/graph/entities", params={"query": "GRAPH_API"})
    assert [item["id"] for item in listed_entities.json()] == [repo["id"]]

    recalled = client.post(
        "/recall/graph",
        json={"task": "GRAPH_API 启动失败", "scope": SCOPE},
    )
    assert recalled.status_code == 200
    assert [item["id"] for item in recalled.json()["memories"]] == [memory.id]
