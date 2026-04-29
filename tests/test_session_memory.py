from __future__ import annotations

from datetime import datetime, timedelta, timezone

from memory_system import (
    CandidateScores,
    EventRead,
    MemoryCandidateCreate,
    MemoryItemCreate,
    MemoryStore,
    SessionMemoryItemCreate,
    SessionMemoryStore,
    compose_context_with_session,
    extract_session_items_from_event,
)


def _event(
    content: str,
    *,
    event_id: str = "evt_session",
    event_type: str = "user_message",
    scope: str = "repo:C:/workspace/demo",
) -> EventRead:
    return EventRead(
        id=event_id,
        event_type=event_type,
        content=content,
        source="conversation",
        scope=scope,
        created_at=datetime.now(timezone.utc),
    )


def test_local_session_extraction_captures_temporary_task_state():
    event = _event(
        "For this task, run only pytest tests/test_session_memory.py for now; "
        "the full suite can run later."
    )

    extracted = extract_session_items_from_event(event, session_id="s1")

    assert extracted.session_id == "s1"
    assert extracted.metadata["source"] == "local_session_lifecycle"
    assert len(extracted.items) == 1
    item = extracted.items[0]
    assert item.memory_type == "task_state"
    assert item.source_event_ids == ["evt_session"]
    assert item.metadata["expires_when"] == "task_end"

    store = SessionMemoryStore()
    store.capture_event(event, session_id="s1")
    results = store.search("pytest full suite", session_id="s1")

    assert len(results) == 1
    assert results[0].memory_type == "task_state"
    assert results[0].last_used_at is not None


def test_local_session_extraction_captures_pending_decision():
    event = _event(
        "Should this dataset status be stored as decision or project_fact? "
        "Wait until confirmed."
    )

    extracted = extract_session_items_from_event(event, session_id="s1")

    assert len(extracted.items) == 1
    item = extracted.items[0]
    assert item.memory_type == "pending_decision"
    assert item.subject == "pending decision"
    assert item.metadata["expires_when"] == "until_decided_or_session_end"


def test_local_session_extraction_does_not_treat_advanced_as_temporary():
    event = _event("\u6709\u6ca1\u6709\u5148\u8fdb\u7684\u65b9\u6cd5\uff1f")

    extracted = extract_session_items_from_event(event, session_id="s1")

    assert extracted.items == []


def test_remote_session_candidate_routes_to_session_store():
    event = _event("For this task, do not commit generated reports.", event_id="evt_remote")
    candidate = MemoryCandidateCreate(
        content="For this task, do not commit generated reports.",
        memory_type="workflow",
        scope="repo:C:/workspace/demo",
        subject="temporary commit rule",
        source_event_ids=["evt_remote"],
        reason="The rule is scoped to this task only.",
        evidence_type="direct_user_statement",
        time_validity="session",
        reuse_cases=["current_task"],
        scores=CandidateScores(long_term=0.2, evidence=1.0, reuse=0.2, risk=0.1),
        confidence="confirmed",
    )

    stored = SessionMemoryStore().capture_remote_candidates(event, [candidate], session_id="s1")

    assert len(stored) == 1
    assert stored[0].memory_type == "temporary_rule"
    assert stored[0].content == candidate.content
    assert stored[0].metadata["source_memory_type"] == "workflow"
    assert stored[0].metadata["expires_when"] == "task_end"


def test_persistent_remote_candidate_is_not_session_memory():
    event = _event("Always run ruff before pytest.", event_id="evt_persistent")
    candidate = MemoryCandidateCreate(
        content="Always run ruff before pytest.",
        memory_type="workflow",
        scope="repo:C:/workspace/demo",
        subject="release validation order",
        source_event_ids=["evt_persistent"],
        reason="This is a durable workflow preference.",
        evidence_type="direct_user_statement",
        time_validity="persistent",
        reuse_cases=["future_releases"],
        scores=CandidateScores(long_term=0.9, evidence=1.0, reuse=0.8, risk=0.1),
        confidence="confirmed",
    )

    stored = SessionMemoryStore().capture_remote_candidates(event, [candidate], session_id="s1")

    assert stored == []


def test_session_memory_expiry_hides_inactive_items():
    now = datetime.now(timezone.utc)
    store = SessionMemoryStore()
    store.add_item(
        SessionMemoryItemCreate(
            content="Use the temporary report file only during this run.",
            session_id="s1",
            memory_type="working_fact",
            scope="session",
            subject="temporary report",
            source_event_ids=["evt_report"],
            expires_at=now - timedelta(seconds=1),
        )
    )

    assert store.search("temporary report", session_id="s1", now=now) == []
    items = store.list_items(session_id="s1", include_expired=True, now=now)

    assert len(items) == 1
    assert items[0].status == "expired"


def test_compose_context_with_session_places_session_memory_first(tmp_path):
    session_item = SessionMemoryStore().add_item(
        SessionMemoryItemCreate(
            content="Use the 60-case fixture for this run.",
            session_id="s1",
            memory_type="task_state",
            scope="session",
            subject="current fixture size",
            source_event_ids=["evt_fixture"],
        )
    )
    long_term = MemoryStore(tmp_path / "memory.sqlite").add_memory(
        MemoryItemCreate(
            content="Release validation runs ruff before pytest.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release validation",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )

    block = compose_context_with_session(
        "run retrieval evaluation",
        [session_item],
        [long_term],
        token_budget=1000,
    )

    assert block.content.index("[session]") < block.content.index("[confirmed]")
    assert block.memory_ids == [long_term.id]
    assert block.metadata["session_memory_ids"] == session_item.id
    assert "Use the 60-case fixture" in block.content


def test_sensitive_session_events_are_filtered_but_token_budget_is_allowed():
    secret_event = _event("For this task, use the access token abc123 just for now.")
    budget_event = _event("For this task, report token_budget exhausted warnings for now.")

    secret_result = extract_session_items_from_event(secret_event, session_id="s1")
    budget_result = extract_session_items_from_event(budget_event, session_id="s1")

    assert secret_result.items == []
    assert "filtered_sensitive_session_event" in secret_result.warnings
    assert len(budget_result.items) == 1
