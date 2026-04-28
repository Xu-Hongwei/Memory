from __future__ import annotations

from fastapi.testclient import TestClient

from memory_system import (
    MemoryEntityCreate,
    MemoryItemCreate,
    MemoryRelationCreate,
    MemoryStore,
    create_app,
)


SCOPE = "repo:C:/workspace/graph-conflict"
OTHER_SCOPE = "repo:C:/workspace/other-graph-conflict"


def add_memory(
    memories: MemoryStore,
    content: str,
    *,
    scope: str = SCOPE,
):
    return memories.add_memory(
        MemoryItemCreate(
            content=content,
            memory_type="project_fact",
            scope=scope,
            subject="graph conflict",
            confidence="confirmed",
            source_event_ids=[f"evt_{content.split()[0]}"],
            tags=["graph-conflict"],
        )
    )


def entity(
    memories: MemoryStore,
    name: str,
    *,
    entity_type: str = "concept",
    scope: str = SCOPE,
):
    return memories.upsert_entity(
        MemoryEntityCreate(name=name, entity_type=entity_type, scope=scope)
    )


def add_relation(
    memories: MemoryStore,
    from_id: str,
    relation_type: str,
    to_id: str,
    memory_id: str,
    *,
    confidence: str = "confirmed",
):
    memory = memories.get_memory(memory_id)
    return memories.create_relation(
        MemoryRelationCreate(
            from_id=from_id,
            relation_type=relation_type,
            to_id=to_id,
            confidence=confidence,
            source_memory_ids=[memory_id],
            source_event_ids=memory.source_event_ids if memory else [],
        )
    )


def test_detects_same_entity_relation_pointing_to_multiple_targets():
    memories = MemoryStore(":memory:")
    repo = entity(memories, SCOPE, entity_type="repo")
    npm = entity(memories, "npm run dev", entity_type="command")
    pnpm = entity(memories, "pnpm dev", entity_type="command")
    npm_memory = add_memory(memories, "GRAPH_CONFLICT start command is npm run dev.")
    pnpm_memory = add_memory(memories, "GRAPH_CONFLICT start command is pnpm dev.")
    npm_relation = add_relation(memories, repo.id, "has_start_command", npm.id, npm_memory.id)
    pnpm_relation = add_relation(memories, repo.id, "has_start_command", pnpm.id, pnpm_memory.id)

    conflicts = memories.detect_graph_conflicts(scope=SCOPE)

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.conflict_key == f"{repo.id}:has_start_command"
    assert [entity.name for entity in conflict.target_entities] == ["npm run dev", "pnpm dev"]
    assert [relation.id for relation in conflict.relations] == [npm_relation.id, pnpm_relation.id]
    assert [memory.id for memory in conflict.memories] == [npm_memory.id, pnpm_memory.id]


def test_duplicate_relation_to_same_target_is_not_conflict():
    memories = MemoryStore(":memory:")
    repo = entity(memories, SCOPE, entity_type="repo")
    command = entity(memories, "pnpm dev", entity_type="command")
    first = add_memory(memories, "GRAPH_NO_CONFLICT start command is pnpm dev.")
    second = add_memory(memories, "GRAPH_NO_CONFLICT README also says pnpm dev.")
    add_relation(memories, repo.id, "has_start_command", command.id, first.id)
    add_relation(memories, repo.id, "has_start_command", command.id, second.id)

    assert memories.detect_graph_conflicts(scope=SCOPE) == []


def test_graph_conflict_detection_skips_inactive_low_confidence_and_cross_scope():
    memories = MemoryStore(":memory:")
    repo = entity(memories, SCOPE, entity_type="repo")
    npm = entity(memories, "npm run dev", entity_type="command")
    pnpm = entity(memories, "pnpm dev", entity_type="command")
    yarn = entity(memories, "yarn dev", entity_type="command")
    active = add_memory(memories, "GRAPH_SKIP active command is pnpm dev.")
    stale = add_memory(memories, "GRAPH_SKIP stale command is npm run dev.")
    low_conf = add_memory(memories, "GRAPH_SKIP guessed command is yarn dev.")
    memories.mark_stale(stale.id, "Old command.")

    add_relation(memories, repo.id, "has_start_command", pnpm.id, active.id)
    add_relation(memories, repo.id, "has_start_command", npm.id, stale.id)
    add_relation(
        memories,
        repo.id,
        "has_start_command",
        yarn.id,
        low_conf.id,
        confidence="inferred",
    )

    other_repo = entity(memories, OTHER_SCOPE, entity_type="repo", scope=OTHER_SCOPE)
    other_npm = entity(memories, "npm run dev", entity_type="command", scope=OTHER_SCOPE)
    other_pnpm = entity(memories, "pnpm dev", entity_type="command", scope=OTHER_SCOPE)
    other_first = add_memory(memories, "GRAPH_SKIP other command is npm.", scope=OTHER_SCOPE)
    other_second = add_memory(memories, "GRAPH_SKIP other command is pnpm.", scope=OTHER_SCOPE)
    add_relation(memories, other_repo.id, "has_start_command", other_npm.id, other_first.id)
    add_relation(memories, other_repo.id, "has_start_command", other_pnpm.id, other_second.id)

    assert memories.detect_graph_conflicts(scope=SCOPE) == []
    assert len(memories.detect_graph_conflicts(scope=OTHER_SCOPE)) == 1


def test_api_detect_graph_conflicts(tmp_path):
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    repo = entity(store, SCOPE, entity_type="repo")
    npm = entity(store, "npm run dev", entity_type="command")
    pnpm = entity(store, "pnpm dev", entity_type="command")
    npm_memory = add_memory(store, "GRAPH_API_CONFLICT command is npm run dev.")
    pnpm_memory = add_memory(store, "GRAPH_API_CONFLICT command is pnpm dev.")
    add_relation(store, repo.id, "has_start_command", npm.id, npm_memory.id)
    add_relation(store, repo.id, "has_start_command", pnpm.id, pnpm_memory.id)

    response = client.get(
        "/graph/conflicts",
        params={"scope": SCOPE, "relation_type": "has_start_command"},
    )

    assert response.status_code == 200
    conflicts = response.json()
    assert len(conflicts) == 1
    assert conflicts[0]["from_entity"]["id"] == repo.id
    assert {entity["name"] for entity in conflicts[0]["target_entities"]} == {
        "npm run dev",
        "pnpm dev",
    }


def test_create_and_resolve_conflict_review_accept_new():
    memories = MemoryStore(":memory:")
    repo = entity(memories, SCOPE, entity_type="repo")
    npm = entity(memories, "npm run dev", entity_type="command")
    pnpm = entity(memories, "pnpm dev", entity_type="command")
    old_memory = add_memory(memories, "GRAPH_REVIEW old command is npm run dev.")
    new_memory = add_memory(memories, "GRAPH_REVIEW new command is pnpm dev.")
    add_relation(memories, repo.id, "has_start_command", npm.id, old_memory.id)
    add_relation(memories, repo.id, "has_start_command", pnpm.id, new_memory.id)

    reviews = memories.create_conflict_reviews(scope=SCOPE, relation_type="has_start_command")

    assert len(reviews) == 1
    review = reviews[0]
    assert review.recommended_action == "accept_new"
    assert review.recommended_keep_memory_ids == [new_memory.id]
    assert memories.create_conflict_reviews(scope=SCOPE, relation_type="has_start_command") == []

    resolved = memories.resolve_conflict_review(
        review.id,
        action="accept_new",
        reason="package.json confirms pnpm dev.",
    )

    assert resolved.status == "resolved"
    assert resolved.resolution_action == "accept_new"
    assert memories.get_memory(old_memory.id).status == "superseded"
    assert memories.get_memory(new_memory.id).status == "active"
    assert memories.detect_graph_conflicts(scope=SCOPE, relation_type="has_start_command") == []
    assert [version.change_type for version in memories.list_versions(old_memory.id)] == [
        "create",
        "supersede",
    ]


def test_resolve_conflict_review_keep_existing_and_archive_all():
    memories = MemoryStore(":memory:")
    repo = entity(memories, SCOPE, entity_type="repo")
    npm = entity(memories, "npm run dev", entity_type="command")
    pnpm = entity(memories, "pnpm dev", entity_type="command")
    old_memory = add_memory(memories, "GRAPH_KEEP old command is npm run dev.")
    new_memory = add_memory(memories, "GRAPH_KEEP new command is pnpm dev.")
    add_relation(memories, repo.id, "has_start_command", npm.id, old_memory.id)
    add_relation(memories, repo.id, "has_start_command", pnpm.id, new_memory.id)
    review = memories.create_conflict_reviews(scope=SCOPE, relation_type="has_start_command")[0]

    memories.resolve_conflict_review(review.id, action="keep_existing", reason="README remains source.")

    assert memories.get_memory(old_memory.id).status == "active"
    assert memories.get_memory(new_memory.id).status == "superseded"

    repo_2 = entity(memories, "repo-archive", entity_type="repo")
    sqlite = entity(memories, "SQLite", entity_type="tool")
    redis = entity(memories, "Redis", entity_type="tool")
    first = add_memory(memories, "GRAPH_ARCHIVE SQLite claim is obsolete.")
    second = add_memory(memories, "GRAPH_ARCHIVE Redis claim is obsolete.")
    add_relation(memories, repo_2.id, "uses_database", sqlite.id, first.id)
    add_relation(memories, repo_2.id, "uses_database", redis.id, second.id)
    archive_review = memories.create_conflict_reviews(
        scope=SCOPE,
        relation_type="uses_database",
    )[0]

    memories.resolve_conflict_review(archive_review.id, action="archive_all", reason="Both are obsolete.")

    assert memories.get_memory(first.id).status == "archived"
    assert memories.get_memory(second.id).status == "archived"


def test_conflict_review_non_mutating_actions_block_duplicate_reviews():
    memories = MemoryStore(":memory:")
    repo = entity(memories, SCOPE, entity_type="repo")
    npm = entity(memories, "npm run dev", entity_type="command")
    pnpm = entity(memories, "pnpm dev", entity_type="command")
    old_memory = add_memory(memories, "GRAPH_ASK_USER old command is npm run dev.")
    new_memory = add_memory(memories, "GRAPH_ASK_USER new command is pnpm dev.")
    add_relation(memories, repo.id, "has_start_command", npm.id, old_memory.id)
    add_relation(memories, repo.id, "has_start_command", pnpm.id, new_memory.id)
    review = memories.create_conflict_reviews(scope=SCOPE, relation_type="has_start_command")[0]

    resolved = memories.resolve_conflict_review(review.id, action="ask_user")

    assert resolved.status == "needs_user"
    assert memories.get_memory(old_memory.id).status == "active"
    assert memories.get_memory(new_memory.id).status == "active"
    assert memories.create_conflict_reviews(scope=SCOPE, relation_type="has_start_command") == []

    repo_2 = entity(memories, "repo-both-scoped", entity_type="repo")
    sqlite = entity(memories, "SQLite", entity_type="tool")
    redis = entity(memories, "Redis", entity_type="tool")
    first = add_memory(memories, "GRAPH_KEEP_BOTH SQLite applies in local scope.")
    second = add_memory(memories, "GRAPH_KEEP_BOTH Redis applies in remote scope.")
    add_relation(memories, repo_2.id, "uses_database", sqlite.id, first.id)
    add_relation(memories, repo_2.id, "uses_database", redis.id, second.id)
    keep_both_review = memories.create_conflict_reviews(
        scope=SCOPE,
        relation_type="uses_database",
    )[0]

    resolved_keep_both = memories.resolve_conflict_review(
        keep_both_review.id,
        action="keep_both_scoped",
        reason="Both facts are valid after scoping review.",
    )

    assert resolved_keep_both.status == "resolved"
    assert memories.get_memory(first.id).status == "active"
    assert memories.get_memory(second.id).status == "active"
    assert memories.create_conflict_reviews(scope=SCOPE, relation_type="uses_database") == []


def test_api_conflict_review_flow(tmp_path):
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    repo = entity(store, SCOPE, entity_type="repo")
    npm = entity(store, "npm run dev", entity_type="command")
    pnpm = entity(store, "pnpm dev", entity_type="command")
    old_memory = add_memory(store, "GRAPH_API_REVIEW old command is npm run dev.")
    new_memory = add_memory(store, "GRAPH_API_REVIEW new command is pnpm dev.")
    add_relation(store, repo.id, "has_start_command", npm.id, old_memory.id)
    add_relation(store, repo.id, "has_start_command", pnpm.id, new_memory.id)

    created = client.post(
        "/graph/conflict-reviews/from-conflicts",
        json={"scope": SCOPE, "relation_type": "has_start_command"},
    )
    assert created.status_code == 200
    review = created.json()[0]

    listed = client.get("/graph/conflict-reviews", params={"status": "pending"})
    assert [item["id"] for item in listed.json()] == [review["id"]]

    resolved = client.post(
        f"/graph/conflict-reviews/{review['id']}/resolve",
        json={"action": "accept_new", "reason": "API review accepts newer command."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert store.get_memory(old_memory.id).status == "superseded"
    assert store.get_memory(new_memory.id).status == "active"
