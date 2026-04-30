from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from memory_system import (
    EventRead,
    SessionMemoryItemCreate,
    SessionMemoryStore,
    TaskBoundaryDecision,
    route_item_to_memory_candidate,
)
from memory_system.remote import RemoteAdapterConfig, RemoteLLMClient, OPENAI_COMPATIBILITY


@pytest.fixture
def route_server():
    routes = {}
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            payload = json.loads(body) if body else {}
            captured.append({"path": self.path, "payload": payload})
            handler = routes.get(("POST", self.path))
            if handler is None:
                self.send_response(404)
                self.end_headers()
                return
            status, response = handler(payload)
            raw = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", routes, captured
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _event(event_id: str, content: str) -> EventRead:
    return EventRead(
        id=event_id,
        event_type="user_message",
        content=content,
        source="conversation",
        scope="global",
        created_at=datetime.now(timezone.utc),
    )


def test_remote_memory_route_splits_long_term_session_and_ignore(route_server):
    base_url, routes, captured = route_server
    events = [
        _event("evt_pref", "For future technical answers, default to Chinese."),
        _event("evt_session", "I feel confused by the current memory flow; please slow down."),
        _event("evt_ignore", "ok"),
    ]
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-route",
            "task_boundary": {
                "action": "same_task",
                "confidence": "high",
                "current_task_id": "task_memory_flow",
                "current_task_title": "Memory flow explanation",
                "next_task_title": None,
                "previous_task_status": "active",
                "reason": "The user is continuing the same memory-flow task.",
            },
            "items": [
                {
                    "route": "long_term",
                    "content": "The user wants future technical answers in Chinese.",
                    "memory_type": "user_preference",
                    "subject": "technical answer language",
                    "source_event_ids": ["evt_pref"],
                    "reason": "Stable future response preference.",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["future_responses"],
                    "scores": {"long_term": 0.9, "evidence": 1.0, "reuse": 0.8},
                    "confidence": "confirmed",
                },
                {
                    "route": "session",
                    "content": "The user is currently confused and needs slower explanation.",
                    "session_memory_type": "emotional_state",
                    "subject": "current comprehension state",
                    "source_event_ids": ["evt_session"],
                    "reason": "This changes the current interaction pace.",
                    "time_validity": "session",
                    "confidence": "confirmed",
                },
                {
                    "route": "ignore",
                    "content": "ok",
                    "source_event_ids": ["evt_ignore"],
                    "reason": "Common confirmation with no memory value.",
                },
            ],
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories(
        events,
        current_task_state={
            "task_id": "task_memory_flow",
            "title": "Memory flow explanation",
            "status": "active",
        },
    )

    assert result.provider == "fake-route"
    assert result.task_boundary is not None
    assert result.task_boundary.action == "same_task"
    assert result.task_boundary.current_task_id == "task_memory_flow"
    assert [item.route for item in result.items] == ["long_term", "session", "ignore"]
    assert captured[0]["payload"]["schema"] == "memory_system.remote_memory_route.v1"
    assert len(captured[0]["payload"]["events"]) == 3
    assert captured[0]["payload"]["event_roles"]["recent_events"].startswith("Read-only")
    assert any("events[].id" in rule for rule in captured[0]["payload"]["source_id_policy"])
    assert captured[0]["payload"]["current_task_state"]["task_id"] == "task_memory_flow"
    assert "task_boundary" in captured[0]["payload"]["output"]

    candidate = route_item_to_memory_candidate(result.items[0], events[0])
    assert candidate is not None
    assert candidate.memory_type == "user_preference"
    assert candidate.time_validity == "persistent"

    stored = SessionMemoryStore().capture_route_items(events[1], result.items, session_id="s1")
    assert len(stored) == 1
    assert stored[0].memory_type == "emotional_state"
    assert stored[0].metadata["source"] == "memory_route_judge"


def test_remote_memory_route_rejects_sensitive_events_without_remote_call(route_server):
    base_url, _routes, captured = route_server
    event = _event("evt_secret", "Use api key: abcdefghijklmnop for this task.")

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories([event])

    assert captured == []
    assert result.items[0].route == "reject"
    assert result.items[0].content == "Sensitive event omitted from remote memory routing."
    assert "filtered_sensitive_route_event" in result.warnings
    assert result.metadata["skipped_remote_call"] is True


def test_openai_memory_route_uses_single_chat_completion(route_server):
    base_url, routes, captured = route_server
    event = _event("evt_session", "For this run, keep the explanation short.")
    routes[("POST", "/chat/completions")] = lambda payload: (
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "items": [
                                    {
                                        "route": "session",
                                        "content": "Keep the explanation short for this run.",
                                        "session_memory_type": "temporary_rule",
                                        "source_event_ids": ["evt_session"],
                                        "reason": "Current-run response constraint.",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        },
    )

    result = RemoteLLMClient(
        RemoteAdapterConfig(base_url=base_url, compatibility=OPENAI_COMPATIBILITY)
    ).route_memories([event])

    assert result.items[0].route == "session"
    assert result.items[0].session_memory_type == "temporary_rule"
    assert captured[0]["path"] == "/chat/completions"
    system_message = captured[0]["payload"]["messages"][0]["content"]
    assert "recent_events as read-only context" in system_message
    user_message = captured[0]["payload"]["messages"][1]["content"]
    assert "memory_system.remote_memory_route.v1" in user_message


def test_route_item_with_session_time_validity_is_rerouted_to_session(route_server):
    base_url, routes, _captured = route_server
    event = _event("evt_temp", "For this task, skip the full test suite.")
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "items": [
                {
                    "route": "long_term",
                    "content": "For this task, skip the full test suite.",
                    "reason": "Current task constraint.",
                    "memory_type": "workflow",
                    "time_validity": "session",
                    "source_event_ids": ["evt_temp"],
                }
            ]
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories([event])

    assert result.items[0].route == "session"
    assert result.items[0].session_memory_type == "temporary_rule"
    assert "rerouted_session_validity_item" in result.warnings


def test_route_parser_normalizes_session_type_in_memory_type(route_server):
    base_url, routes, _captured = route_server
    event = _event("evt_temp", "This run only checks Chinese cases.")
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "items": [
                {
                    "route": "session",
                    "content": "This run only checks Chinese cases.",
                    "reason": "Temporary current-run constraint.",
                    "memory_type": "temporary_rule",
                    "source_event_ids": ["evt_temp"],
                }
            ]
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories([event])

    assert result.items[0].route == "session"
    assert result.items[0].memory_type is None
    assert result.items[0].session_memory_type == "temporary_rule"
    assert "normalized_route_memory_type_to_session_memory_type" in result.warnings


def test_route_parser_defaults_null_optional_fields(route_server):
    base_url, routes, _captured = route_server
    event = _event("evt_ignore", "Understood.")
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "items": [
                {
                    "route": "ignore",
                    "content": "Understood.",
                    "reason": "Low-information acknowledgement.",
                    "source_event_ids": ["evt_ignore"],
                    "evidence_type": None,
                    "time_validity": None,
                    "reuse_cases": None,
                    "confidence": None,
                    "risk": None,
                    "scores": None,
                    "metadata": None,
                }
            ]
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories([event])

    assert result.items[0].route == "ignore"
    assert result.items[0].evidence_type == "unknown"
    assert result.items[0].time_validity == "unknown"
    assert result.items[0].reuse_cases == []
    assert result.items[0].confidence == "unknown"
    assert result.items[0].risk == "low"
    assert "defaulted_route_evidence_type" in result.warnings


def test_route_parser_defaults_empty_text_fields_to_event(route_server):
    base_url, routes, _captured = route_server
    event = _event("evt_ignore", "Never mind.")
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "items": [
                {
                    "route": "ignore",
                    "content": "",
                    "reason": "",
                    "subject": "",
                    "source_event_ids": ["evt_ignore"],
                }
            ]
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories([event])

    assert result.items[0].route == "ignore"
    assert result.items[0].content == "Never mind."
    assert result.items[0].subject == "conversation"
    assert result.items[0].reason == "Remote route judge proposed this memory route."


def test_route_parser_normalizes_task_boundary(route_server):
    base_url, routes, _captured = route_server
    event = _event("evt_continue", "可以，继续做任务边界测试。")
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "task_boundary": {
                "action": "continue",
                "confidence": "sure",
                "previous_task_status": "maybe",
                "reason": "",
            },
            "items": [
                {
                    "route": "session",
                    "content": "Continue task boundary testing.",
                    "reason": "Current task state.",
                    "session_memory_type": "task_state",
                    "source_event_ids": ["evt_continue"],
                }
            ],
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories([event])

    assert result.task_boundary is not None
    assert result.task_boundary.action == "unclear"
    assert result.task_boundary.confidence == "unknown"
    assert result.task_boundary.previous_task_status == "unknown"
    assert result.task_boundary.reason == "Remote task boundary judge proposed this decision."
    assert "defaulted_task_boundary_action" in result.warnings


def test_task_boundary_gate_weakens_untitled_low_confidence_switch(route_server):
    base_url, routes, _captured = route_server
    event = _event("evt_test", "Please run the tests now.")
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "task_boundary": {
                "action": "switch_task",
                "confidence": "medium",
                "current_task_id": "task_recent_events",
                "current_task_title": "Improve recent_events readonly policy",
                "next_task_title": None,
                "previous_task_status": "active",
                "reason": "The user asked to run tests.",
            },
            "items": [],
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories(
        [event],
        current_task_state={
            "task_id": "task_recent_events",
            "title": "Improve recent_events readonly policy",
            "status": "active",
        },
    )

    assert result.task_boundary is not None
    assert result.task_boundary.action == "unclear"
    assert result.task_boundary.confidence == "low"
    assert result.task_boundary.next_task_title is None
    assert "weakened_task_boundary_switch_evidence" in result.warnings


def test_task_boundary_gate_keeps_explicit_switch(route_server):
    base_url, routes, _captured = route_server
    event = _event("evt_next", "This part is done; next, work on session memory lifecycle.")
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "task_boundary": {
                "action": "switch_task",
                "confidence": "high",
                "current_task_id": "task_recent_events",
                "current_task_title": "Improve recent_events readonly policy",
                "next_task_title": "session memory lifecycle",
                "previous_task_status": "active",
                "reason": "The user explicitly moved to the next task.",
            },
            "items": [],
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories(
        [event],
        current_task_state={
            "task_id": "task_recent_events",
            "title": "Improve recent_events readonly policy",
            "status": "active",
        },
    )

    assert result.task_boundary is not None
    assert result.task_boundary.action == "switch_task"
    assert result.task_boundary.next_task_title == "session memory lifecycle"
    assert "weakened_task_boundary_switch_evidence" not in result.warnings


def test_session_closeout_parser_promotes_candidate(route_server):
    base_url, routes, captured = route_server
    session_item = SessionMemoryStore().add_item(
        SessionMemoryItemCreate(
            content="The task boundary smoke report passed 46 of 46 cases.",
            session_id="s1",
            memory_type="working_fact",
            scope="repo:C:/workspace/demo",
            subject="task boundary smoke report",
            source_event_ids=["evt_report"],
        )
    )
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-closeout",
            "task_summary": "Task boundary smoke passed.",
            "decisions": [
                {
                    "session_memory_id": session_item.id,
                    "action": "promote_candidate",
                    "reason": "The result is reusable validation evidence.",
                    "candidate": {
                        "content": "Task boundary smoke passed 46 of 46 cases.",
                        "memory_type": "project_fact",
                        "scope": "repo:C:/workspace/demo",
                        "subject": "task boundary smoke report",
                        "source_event_ids": ["evt_report"],
                        "reason": "Promoted from session closeout.",
                        "evidence_type": "test_result",
                        "time_validity": "persistent",
                        "confidence": "confirmed",
                    },
                }
            ],
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).closeout_session_memories(
        session_id="s1",
        session_memories=[session_item],
        task_boundary=TaskBoundaryDecision(
            action="task_done",
            confidence="high",
            previous_task_status="done",
            reason="The task finished.",
        ),
    )

    assert result.provider == "fake-closeout"
    assert result.task_summary == "Task boundary smoke passed."
    assert len(result.decisions) == 1
    decision = result.decisions[0]
    assert decision.action == "promote_candidate"
    assert decision.candidate is not None
    assert decision.candidate.memory_type == "project_fact"
    assert captured[0]["payload"]["schema"] == "memory_system.session_closeout.v1"
    assert captured[0]["payload"]["session_memories"][0]["id"] == session_item.id


def test_memory_route_filters_context_only_non_ignore_items(route_server):
    base_url, routes, captured = route_server
    event = _event("evt_current", "ok")
    recent_event = _event("evt_recent", "For future answers, use Chinese.")
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "items": [
                {
                    "route": "long_term",
                    "content": "The user wants future answers in Chinese.",
                    "memory_type": "user_preference",
                    "reason": "Stable preference from previous context only.",
                    "source_event_ids": ["evt_recent"],
                    "time_validity": "persistent",
                },
                {
                    "route": "session",
                    "content": "Keep the current explanation short.",
                    "session_memory_type": "temporary_rule",
                    "reason": "Temporary rule from previous context only.",
                    "source_event_ids": ["evt_recent"],
                },
            ]
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories(
        [event],
        recent_events=[recent_event],
    )

    assert result.items == []
    assert result.warnings.count("filtered_context_only_route_item") == 2
    assert captured[0]["payload"]["recent_events"][0]["id"] == "evt_recent"


def test_memory_route_filters_ack_only_memory_without_assistant_support(route_server):
    base_url, routes, _captured = route_server
    event = _event("evt_current", "ok")
    recent_event = _event("evt_recent", "For future answers, use Chinese.")
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "items": [
                {
                    "route": "long_term",
                    "content": "The user wants future answers in Chinese.",
                    "memory_type": "user_preference",
                    "reason": "The current event confirms previous context.",
                    "source_event_ids": ["evt_current"],
                    "time_validity": "persistent",
                }
            ]
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories(
        [event],
        recent_events=[recent_event],
    )

    assert result.items == []
    assert "filtered_ack_only_route_item" in result.warnings


def test_memory_route_keeps_ack_confirmation_with_assistant_proposal(route_server):
    base_url, routes, _captured = route_server
    event = _event("evt_current", "可以")
    recent_event = _event(
        "evt_recent",
        "Would you like me to remember that future reports use conclusion, basis, risk, next step?",
    ).model_copy(update={"event_type": "assistant_message"})
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "items": [
                {
                    "route": "long_term",
                    "content": (
                        "The user wants future reports to use conclusion, basis, "
                        "risk, and next step."
                    ),
                    "memory_type": "user_preference",
                    "reason": "The current event confirms an assistant memory proposal.",
                    "source_event_ids": ["evt_current", "evt_recent"],
                    "time_validity": "persistent",
                    "confidence": "confirmed",
                }
            ]
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories(
        [event],
        recent_events=[recent_event],
    )

    assert len(result.items) == 1
    assert result.items[0].route == "long_term"
    assert "filtered_ack_only_route_item" not in result.warnings


def test_memory_route_keeps_current_event_with_recent_supporting_source(route_server):
    base_url, routes, _captured = route_server
    event = _event("evt_current", "Use that format going forward.")
    recent_event = _event(
        "evt_recent",
        "The format is conclusion, reason, risk, and next step.",
    )
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "items": [
                {
                    "route": "long_term",
                    "content": (
                        "The user wants future answers to use conclusion, reason, "
                        "risk, and next step."
                    ),
                    "memory_type": "user_preference",
                    "reason": "The current event makes the prior format durable.",
                    "source_event_ids": ["evt_current", "evt_recent"],
                    "time_validity": "persistent",
                    "confidence": "confirmed",
                }
            ]
        },
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories(
        [event],
        recent_events=[recent_event],
    )

    assert len(result.items) == 1
    assert result.items[0].route == "long_term"
    assert result.items[0].source_event_ids == ["evt_current", "evt_recent"]
    assert "filtered_context_only_route_item" not in result.warnings
