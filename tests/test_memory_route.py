from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from memory_system import EventRead, SessionMemoryStore, route_item_to_memory_candidate
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

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).route_memories(events)

    assert result.provider == "fake-route"
    assert [item.route for item in result.items] == ["long_term", "session", "ignore"]
    assert captured[0]["payload"]["schema"] == "memory_system.remote_memory_route.v1"
    assert len(captured[0]["payload"]["events"]) == 3

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
