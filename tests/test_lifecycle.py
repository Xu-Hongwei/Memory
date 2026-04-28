from __future__ import annotations

import pytest

from memory_system import (
    MemoryItemCreate,
    MemoryPolicyError,
    MemoryStore,
    SearchMemoryInput,
)
from memory_system.schemas import MemoryCandidateCreate


def test_mark_stale_excludes_memory_from_search_and_records_version():
    memories = MemoryStore(":memory:")
    memory = memories.add_memory(
        MemoryItemCreate(
            content="LIFECYCLE_STALE start command is npm run dev.",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="start command",
            confidence="confirmed",
            source_event_ids=["evt_start"],
            tags=["setup"],
        )
    )

    stale = memories.mark_stale(memory.id, "package.json changed; revalidation required.")

    assert stale.status == "stale"
    assert memories.search_memory(SearchMemoryInput(query="LIFECYCLE_STALE")) == []
    versions = memories.list_versions(memory.id)
    assert [version.change_type for version in versions] == ["create", "stale"]
    assert versions[-1].change_reason == "package.json changed; revalidation required."


def test_archive_memory_excludes_memory_and_records_version():
    memories = MemoryStore(":memory:")
    memory = memories.add_memory(
        MemoryItemCreate(
            content="LIFECYCLE_ARCHIVE obsolete setup note.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="obsolete setup",
            confidence="confirmed",
            source_event_ids=["evt_setup"],
        )
    )

    archived = memories.archive_memory(memory.id, "Workflow is no longer used.")

    assert archived.status == "archived"
    assert memories.search_memory(SearchMemoryInput(query="LIFECYCLE_ARCHIVE")) == []
    versions = memories.list_versions(memory.id)
    assert [version.change_type for version in versions] == ["create", "archive"]


def test_supersede_memory_marks_old_memory_and_commits_candidate():
    memories = MemoryStore(":memory:")
    old = memories.add_memory(
        MemoryItemCreate(
            content="LIFECYCLE_SUPERSEDE start command is npm run dev.",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="start command",
            confidence="confirmed",
            source_event_ids=["evt_old"],
        )
    )
    candidate = memories.create_candidate(
        MemoryCandidateCreate(
            content="LIFECYCLE_SUPERSEDE start command is pnpm dev.",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="start command",
            source_event_ids=["evt_new"],
            reason="New verified observation replaces the old command.",
            confidence="confirmed",
            risk="low",
        )
    )

    new = memories.supersede_memory(
        old.id,
        candidate.id,
        "User confirmed the new command replaces the old one.",
    )

    assert memories.get_memory(old.id).status == "superseded"
    assert new.status == "active"
    assert new.content == "LIFECYCLE_SUPERSEDE start command is pnpm dev."
    assert memories.get_candidate(candidate.id).status == "committed"
    assert [item.id for item in memories.search_memory(SearchMemoryInput(query="LIFECYCLE_SUPERSEDE"))] == [
        new.id
    ]
    assert [version.change_type for version in memories.list_versions(old.id)] == [
        "create",
        "supersede",
    ]
    assert [version.change_type for version in memories.list_versions(new.id)] == ["create"]


def test_lifecycle_rejects_invalid_state_transitions():
    memories = MemoryStore(":memory:")
    memory = memories.add_memory(
        MemoryItemCreate(
            content="LIFECYCLE_INVALID archived memory.",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="invalid transition",
            confidence="confirmed",
            source_event_ids=["evt_invalid"],
        )
    )

    memories.archive_memory(memory.id, "No longer needed.")

    with pytest.raises(MemoryPolicyError):
        memories.mark_stale(memory.id, "Cannot stale archived memory.")
    with pytest.raises(MemoryPolicyError):
        memories.archive_memory(memory.id, "Already archived.")
