from __future__ import annotations

import json
from pathlib import Path

from memory_system import (
    MemoryEntityCreate,
    MemoryItemCreate,
    MemoryRelationCreate,
    MemoryStore,
    RetrievalLogCreate,
)
from memory_system.cli import main


SCOPE = "repo:C:/workspace/cli-review"


def add_memory(memories: MemoryStore, content: str):
    return memories.add_memory(
        MemoryItemCreate(
            content=content,
            memory_type="project_fact",
            scope=SCOPE,
            subject="cli conflict",
            confidence="confirmed",
            source_event_ids=[f"evt_{content.split()[0]}"],
            tags=["cli"],
        )
    )


def add_entity(memories: MemoryStore, name: str, entity_type: str):
    return memories.upsert_entity(
        MemoryEntityCreate(name=name, entity_type=entity_type, scope=SCOPE)
    )


def add_relation(
    memories: MemoryStore,
    from_id: str,
    relation_type: str,
    to_id: str,
    memory_id: str,
):
    memory = memories.get_memory(memory_id)
    return memories.create_relation(
        MemoryRelationCreate(
            from_id=from_id,
            relation_type=relation_type,
            to_id=to_id,
            confidence="confirmed",
            source_memory_ids=[memory_id],
            source_event_ids=memory.source_event_ids if memory else [],
        )
    )


def seed_conflict(db_path: Path):
    memories = MemoryStore(db_path)
    repo = add_entity(memories, SCOPE, "repo")
    npm = add_entity(memories, "npm run dev", "command")
    pnpm = add_entity(memories, "pnpm dev", "command")
    old_memory = add_memory(memories, "CLI_REVIEW old command is npm run dev.")
    new_memory = add_memory(memories, "CLI_REVIEW new command is pnpm dev.")
    add_relation(memories, repo.id, "has_start_command", npm.id, old_memory.id)
    add_relation(memories, repo.id, "has_start_command", pnpm.id, new_memory.id)
    return old_memory, new_memory


def seed_maintenance(db_path: Path):
    memories = MemoryStore(db_path)
    memory = add_memory(memories, "CLI_MAINTENANCE repeatedly rated not useful.")
    for index in range(2):
        log = memories.record_retrieval_log(
            RetrievalLogCreate(
                query=f"cli maintenance {index}",
                source="context",
                retrieved_memory_ids=[memory.id],
                used_memory_ids=[memory.id],
            )
        )
        memories.add_retrieval_feedback(log.id, feedback="not_useful")
    return memory


def test_cli_reviews_generate_list_show_and_resolve_json(tmp_path, capsys):
    db_path = tmp_path / "memory.sqlite"
    old_memory, new_memory = seed_conflict(db_path)

    result = main(
        [
            "--db",
            str(db_path),
            "reviews",
            "generate",
            "--scope",
            SCOPE,
            "--relation-type",
            "has_start_command",
            "--json",
        ]
    )

    assert result == 0
    generated = json.loads(capsys.readouterr().out)
    assert len(generated) == 1
    review_id = generated[0]["id"]
    assert generated[0]["recommended_keep_memory_ids"] == [new_memory.id]

    result = main(["--db", str(db_path), "reviews", "list", "--status", "pending", "--json"])

    assert result == 0
    listed = json.loads(capsys.readouterr().out)
    assert [review["id"] for review in listed] == [review_id]

    result = main(["--db", str(db_path), "reviews", "show", review_id, "--json"])

    assert result == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail["from_entity"]["name"] == SCOPE
    assert {entity["name"] for entity in detail["target_entities"]} == {
        "npm run dev",
        "pnpm dev",
    }
    assert {memory["id"] for memory in detail["memories"]} == {old_memory.id, new_memory.id}

    result = main(
        [
            "--db",
            str(db_path),
            "reviews",
            "resolve",
            review_id,
            "--action",
            "accept_new",
            "--reason",
            "CLI accepts the newer command.",
            "--json",
        ]
    )

    assert result == 0
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["status"] == "resolved"
    assert resolved["resolution_action"] == "accept_new"

    memories = MemoryStore(db_path)
    assert memories.get_memory(old_memory.id).status == "superseded"
    assert memories.get_memory(new_memory.id).status == "active"


def test_cli_reviews_list_text_when_empty(tmp_path, capsys):
    result = main(["--db", str(tmp_path / "memory.sqlite"), "reviews", "list"])

    assert result == 0
    assert capsys.readouterr().out.strip() == "No conflict reviews found."


def test_cli_reviews_show_missing_returns_error(tmp_path, capsys):
    result = main(["--db", str(tmp_path / "memory.sqlite"), "reviews", "show", "conf_missing"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "not found: conf_missing" in captured.err


def test_cli_maintenance_generate_show_and_resolve_json(tmp_path, capsys):
    db_path = tmp_path / "memory.sqlite"
    memory = seed_maintenance(db_path)

    result = main(
        [
            "--db",
            str(db_path),
            "maintenance",
            "generate",
            "--scope",
            SCOPE,
            "--json",
        ]
    )

    assert result == 0
    generated = json.loads(capsys.readouterr().out)
    assert len(generated) == 1
    review_id = generated[0]["id"]
    assert generated[0]["recommended_action"] == "mark_stale"
    assert generated[0]["memory"]["id"] == memory.id

    result = main(["--db", str(db_path), "maintenance", "show", review_id, "--json"])

    assert result == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail["usage"]["not_useful_feedback_count"] == 2

    result = main(
        [
            "--db",
            str(db_path),
            "maintenance",
            "resolve",
            review_id,
            "--action",
            "mark_stale",
            "--json",
        ]
    )

    assert result == 0
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["status"] == "resolved"
    assert MemoryStore(db_path).get_memory(memory.id).status == "stale"
