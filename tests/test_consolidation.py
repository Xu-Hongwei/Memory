from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memory_system import MemoryItemCreate, MemoryPolicyError, MemoryStore, SearchMemoryInput
from memory_system import create_app


def add_memory(
    memories: MemoryStore,
    content: str,
    *,
    memory_type: str = "project_fact",
    scope: str = "repo:C:/workspace/consolidation",
    subject: str = "start command",
    confidence: str = "confirmed",
    tags: list[str] | None = None,
):
    return memories.add_memory(
        MemoryItemCreate(
            content=content,
            memory_type=memory_type,
            scope=scope,
            subject=subject,
            confidence=confidence,
            source_event_ids=[f"evt_{content.split()[0]}"],
            tags=tags or [],
        )
    )


def test_propose_and_commit_consolidation_supersedes_sources():
    memories = MemoryStore(":memory:")
    first = add_memory(
        memories,
        "CONSOLIDATE_PREF documentation defaults to Chinese.",
        memory_type="user_preference",
        scope="global",
        subject="documentation style",
        tags=["docs"],
    )
    second = add_memory(
        memories,
        "CONSOLIDATE_PREF answers should separate facts from inference.",
        memory_type="user_preference",
        scope="global",
        subject="documentation style",
        tags=["style"],
    )

    candidates = memories.propose_consolidations(scope="global", memory_type="user_preference")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_memory_ids == [first.id, second.id]
    assert candidate.tags == ["consolidated", "docs", "style"]
    assert "documentation defaults to Chinese" in candidate.proposed_content
    assert "separate facts from inference" in candidate.proposed_content

    consolidated = memories.commit_consolidation(candidate.id, reason="Manual consolidation.")

    assert consolidated.status == "active"
    assert consolidated.content.startswith("[Consolidated memory]")
    assert memories.get_memory(first.id).status == "superseded"
    assert memories.get_memory(second.id).status == "superseded"
    assert memories.get_consolidation_candidate(candidate.id).status == "committed"
    assert [item.id for item in memories.search_memory(SearchMemoryInput(query="CONSOLIDATE_PREF"))] == [
        consolidated.id
    ]
    assert [version.change_type for version in memories.list_versions(first.id)] == [
        "create",
        "supersede",
    ]
    assert [version.change_type for version in memories.list_versions(consolidated.id)] == ["create"]


def test_consolidation_requires_matching_scope_type_and_subject():
    memories = MemoryStore(":memory:")
    add_memory(memories, "CONSOLIDATE_SCOPE command is npm run dev.", scope="repo:a")
    add_memory(memories, "CONSOLIDATE_SCOPE command is pnpm dev.", scope="repo:b")
    add_memory(
        memories,
        "CONSOLIDATE_TYPE workflow note.",
        memory_type="workflow",
        subject="workflow",
    )
    add_memory(
        memories,
        "CONSOLIDATE_TYPE project fact note.",
        memory_type="project_fact",
        subject="workflow",
    )

    assert memories.propose_consolidations() == []


def test_consolidation_skips_inactive_and_low_confidence_memories():
    memories = MemoryStore(":memory:")
    active = add_memory(memories, "CONSOLIDATE_SKIP active fact.")
    stale = add_memory(memories, "CONSOLIDATE_SKIP stale fact.")
    inferred = add_memory(memories, "CONSOLIDATE_SKIP inferred fact.", confidence="inferred")

    memories.mark_stale(stale.id, "Source needs revalidation.")

    assert memories.propose_consolidations() == []
    assert memories.get_memory(active.id).status == "active"
    assert memories.get_memory(inferred.id).status == "active"


def test_pending_consolidation_is_not_proposed_twice():
    memories = MemoryStore(":memory:")
    add_memory(memories, "CONSOLIDATE_DUP first fact.")
    add_memory(memories, "CONSOLIDATE_DUP second fact.")

    first_batch = memories.propose_consolidations()
    second_batch = memories.propose_consolidations()

    assert len(first_batch) == 1
    assert second_batch == []


def test_reject_consolidation_marks_candidate_rejected():
    memories = MemoryStore(":memory:")
    add_memory(memories, "CONSOLIDATE_REJECT first fact.")
    add_memory(memories, "CONSOLIDATE_REJECT second fact.")
    candidate = memories.propose_consolidations()[0]

    rejected = memories.reject_consolidation(candidate.id, reason="Keep memories separate.")

    assert rejected.status == "rejected"
    with pytest.raises(MemoryPolicyError):
        memories.commit_consolidation(candidate.id)


def test_api_consolidation_flow(tmp_path):
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    first = add_memory(store, "CONSOLIDATE_API first setup fact.")
    second = add_memory(store, "CONSOLIDATE_API second setup fact.")

    proposed = client.post(
        "/consolidation/propose",
        json={"scope": "repo:C:/workspace/consolidation", "memory_type": "project_fact"},
    )
    assert proposed.status_code == 200
    candidate = proposed.json()[0]

    listed = client.get("/consolidation/candidates", params={"status": "pending"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [candidate["id"]]

    committed = client.post(
        f"/consolidation/{candidate['id']}/commit",
        json={"reason": "API consolidation test."},
    )
    assert committed.status_code == 200
    consolidated = committed.json()

    assert client.app.state.runtime.memories.get_memory(first.id).status == "superseded"
    assert client.app.state.runtime.memories.get_memory(second.id).status == "superseded"

    search = client.post(
        "/memories/search",
        json={"query": "CONSOLIDATE_API", "scopes": ["repo:C:/workspace/consolidation"]},
    )
    assert [item["id"] for item in search.json()] == [consolidated["id"]]
