from __future__ import annotations

from fastapi.testclient import TestClient

from memory_system import MemoryItemCreate, RetrievalLogCreate, create_app


def test_api_event_to_memory_to_context_flow(tmp_path):
    client = TestClient(create_app(tmp_path / "memory.sqlite"))

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    event_response = client.post(
        "/events",
        json={
            "event_type": "user_message",
            "content": "以后技术文档默认用中文，并且区分事实和推断。",
            "source": "conversation",
            "scope": "global",
            "task_id": "task-api",
        },
    )
    assert event_response.status_code == 200
    event = event_response.json()

    loaded_event = client.get(f"/events/{event['id']}")
    assert loaded_event.status_code == 200
    assert loaded_event.json()["content"] == event["content"]

    candidates_response = client.post(f"/candidates/from-event/{event['id']}")
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    assert len(candidates) == 1
    assert candidates[0]["memory_type"] == "user_preference"
    assert candidates[0]["evidence_type"] == "direct_user_statement"

    pending_response = client.get("/candidates", params={"status": "pending"})
    assert pending_response.status_code == 200
    assert [item["id"] for item in pending_response.json()] == [candidates[0]["id"]]

    decision_response = client.post(f"/candidates/{candidates[0]['id']}/evaluate")
    assert decision_response.status_code == 200
    decision = decision_response.json()
    assert decision["decision"] == "write"
    assert decision["structured_reason"]["decision"] == "write"

    commit_response = client.post(
        "/memories/commit",
        json={"candidate_id": candidates[0]["id"], "decision_id": decision["id"]},
    )
    assert commit_response.status_code == 200
    memory = commit_response.json()
    assert memory["memory_type"] == "user_preference"

    search_response = client.post(
        "/memories/search",
        json={"query": "中文", "memory_types": ["user_preference"], "scopes": ["global"]},
    )
    assert search_response.status_code == 200
    results = search_response.json()
    assert [item["id"] for item in results] == [memory["id"]]

    versions_response = client.get(f"/memories/{memory['id']}/versions")
    assert versions_response.status_code == 200
    assert versions_response.json()[0]["change_type"] == "create"

    context_response = client.post(
        "/context/compose",
        json={"task": "写项目说明", "memory_ids": [memory["id"]], "token_budget": 1000},
    )
    assert context_response.status_code == 200
    context = context_response.json()
    assert context["memory_ids"] == [memory["id"]]
    assert "技术文档默认用中文" in context["content"]

    search_logs_response = client.get("/retrieval/logs", params={"source": "search"})
    assert search_logs_response.status_code == 200
    search_logs = search_logs_response.json()
    assert len(search_logs) == 1
    assert search_logs[0]["retrieved_memory_ids"] == [memory["id"]]

    context_logs_response = client.get("/retrieval/logs", params={"source": "context"})
    assert context_logs_response.status_code == 200
    context_log = context_logs_response.json()[0]
    assert context_log["used_memory_ids"] == [memory["id"]]

    feedback_response = client.post(
        f"/retrieval/logs/{context_log['id']}/feedback",
        json={"feedback": "useful", "reason": "Context contained the needed preference."},
    )
    assert feedback_response.status_code == 200
    assert feedback_response.json()["feedback"] == "useful"

    usage_response = client.get(f"/memories/{memory['id']}/usage")
    assert usage_response.status_code == 200
    usage = usage_response.json()
    assert usage["memory_id"] == memory["id"]
    assert usage["used_count"] == 2
    assert usage["useful_feedback_count"] == 1
    assert usage["recommended_action"] == "keep"

    usage_list_response = client.get("/memories/usage", params={"recommended_action": "keep"})
    assert usage_list_response.status_code == 200
    assert memory["id"] in [item["memory_id"] for item in usage_list_response.json()]


def test_api_review_workflow_for_low_evidence_candidate(tmp_path):
    client = TestClient(create_app(tmp_path / "memory.sqlite"))

    event_response = client.post(
        "/events",
        json={
            "event_type": "user_message",
            "content": "我可能喜欢更短一点的回答。",
            "source": "conversation",
            "scope": "global",
            "metadata": {
                "memory_type": "user_preference",
                "confidence": "inferred",
                "claim": "用户可能喜欢更短回复。",
            },
        },
    )
    event = event_response.json()
    candidates = client.post(f"/candidates/from-event/{event['id']}").json()
    candidate_id = candidates[0]["id"]

    decision = client.post(f"/candidates/{candidate_id}/evaluate").json()
    assert decision["decision"] == "ask_user"

    edit_response = client.patch(
        f"/candidates/{candidate_id}",
        json={
            "updates": {
                "claim": "用户明确确认喜欢更短的回答。",
                "evidence_type": "direct_user_statement",
                "time_validity": "persistent",
                "reuse_cases": ["future_responses"],
                "scores": {
                    "long_term": 0.8,
                    "evidence": 1.0,
                    "reuse": 0.7,
                    "risk": 0.1,
                    "specificity": 0.7,
                },
                "confidence": "confirmed",
                "reason": "人工确认后补充证据。",
            }
        },
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["evidence_type"] == "direct_user_statement"

    approved = client.post(
        f"/candidates/{candidate_id}/approve",
        json={"reason": "人工确认该偏好长期有效。"},
    )
    assert approved.status_code == 200
    assert approved.json()["tags"] == ["future_responses"]


def test_api_not_found_and_policy_errors(tmp_path):
    client = TestClient(create_app(tmp_path / "memory.sqlite"))

    assert client.get("/events/evt_missing").status_code == 404
    assert client.post("/candidates/from-event/evt_missing").status_code == 404
    assert client.post("/candidates/cand_missing/approve", json={}).status_code == 404

    event = client.post(
        "/events",
        json={
            "event_type": "user_message",
            "content": "以后默认用中文。",
            "source": "conversation",
            "scope": "global",
        },
    ).json()
    candidate = client.post(f"/candidates/from-event/{event['id']}").json()[0]
    rejected = client.post(
        f"/candidates/{candidate['id']}/reject",
        json={"reason": "测试拒绝。"},
    ).json()
    assert rejected["decision"] == "reject"

    response = client.post(
        "/memories/commit",
        json={"candidate_id": candidate["id"], "decision_id": rejected["id"]},
    )
    assert response.status_code == 409


def test_api_maintenance_review_flow(tmp_path):
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    memory = store.add_memory(
        MemoryItemCreate(
            content="API_MAINTENANCE memory repeatedly rated not useful.",
            memory_type="project_fact",
            scope="repo:C:/workspace/api-maintenance",
            subject="api maintenance",
            confidence="confirmed",
            source_event_ids=["evt_api_maintenance"],
        )
    )
    for index in range(2):
        log = store.record_retrieval_log(
            RetrievalLogCreate(
                query=f"api maintenance {index}",
                source="context",
                retrieved_memory_ids=[memory.id],
                used_memory_ids=[memory.id],
            )
        )
        store.add_retrieval_feedback(log.id, feedback="not_useful")

    created = client.post(
        "/maintenance/reviews/from-usage",
        json={"scope": "repo:C:/workspace/api-maintenance"},
    )
    assert created.status_code == 200
    review = created.json()[0]
    assert review["memory_id"] == memory.id
    assert review["recommended_action"] == "mark_stale"

    listed = client.get("/maintenance/reviews", params={"status": "pending"})
    assert [item["id"] for item in listed.json()] == [review["id"]]

    resolved = client.post(
        f"/maintenance/reviews/{review['id']}/resolve",
        json={"action": "mark_stale", "reason": "API accepts maintenance suggestion."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert store.get_memory(memory.id).status == "stale"


def test_api_memory_lifecycle_endpoints(tmp_path):
    client = TestClient(create_app(tmp_path / "memory.sqlite"))

    event = client.post(
        "/events",
        json={
            "event_type": "user_message",
            "content": "I prefer concise technical answers.",
            "source": "conversation",
            "scope": "global",
        },
    ).json()
    candidate = client.post(f"/candidates/from-event/{event['id']}").json()[0]
    decision = client.post(f"/candidates/{candidate['id']}/evaluate").json()
    memory = client.post(
        "/memories/commit",
        json={"candidate_id": candidate["id"], "decision_id": decision["id"]},
    ).json()

    stale = client.post(
        f"/memories/{memory['id']}/stale",
        json={"reason": "User preference needs re-confirmation."},
    )
    assert stale.status_code == 200
    assert stale.json()["status"] == "stale"

    search = client.post("/memories/search", json={"query": "concise"})
    assert search.status_code == 200
    assert search.json() == []

    archived = client.post(
        f"/memories/{memory['id']}/archive",
        json={"reason": "Preference is no longer useful."},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    versions = client.get(f"/memories/{memory['id']}/versions").json()
    assert [version["change_type"] for version in versions] == ["create", "stale", "archive"]


def test_api_supersede_memory_endpoint(tmp_path):
    client = TestClient(create_app(tmp_path / "memory.sqlite"))

    old_event = client.post(
        "/events",
        json={
            "event_type": "file_observation",
            "content": "passed LIFECYCLE_API_SUPERSEDE start command is npm run dev.",
            "source": "package.json",
            "scope": "repo:C:/workspace/demo",
            "metadata": {"subject": "start command"},
        },
    ).json()
    old_candidate = client.post(f"/candidates/from-event/{old_event['id']}").json()[0]
    old_decision = client.post(f"/candidates/{old_candidate['id']}/evaluate").json()
    old_memory = client.post(
        "/memories/commit",
        json={"candidate_id": old_candidate["id"], "decision_id": old_decision["id"]},
    ).json()

    new_event = client.post(
        "/events",
        json={
            "event_type": "file_observation",
            "content": "passed LIFECYCLE_API_SUPERSEDE start command is pnpm dev.",
            "source": "package.json",
            "scope": "repo:C:/workspace/demo",
            "metadata": {"subject": "start command"},
        },
    ).json()
    new_candidate = client.post(f"/candidates/from-event/{new_event['id']}").json()[0]

    new_memory = client.post(
        f"/memories/{old_memory['id']}/supersede",
        json={
            "candidate_id": new_candidate["id"],
            "reason": "Confirmed package.json changed.",
        },
    )
    assert new_memory.status_code == 200
    assert new_memory.json()["content"].endswith("pnpm dev.")

    old_after = client.get(f"/memories/{old_memory['id']}").json()
    assert old_after["status"] == "superseded"

    search = client.post(
        "/memories/search",
        json={"query": "LIFECYCLE_API_SUPERSEDE", "scopes": ["repo:C:/workspace/demo"]},
    ).json()
    assert [item["id"] for item in search] == [new_memory.json()["id"]]


def test_api_task_recall_endpoint(tmp_path):
    client = TestClient(create_app(tmp_path / "memory.sqlite"))

    pref_event = client.post(
        "/events",
        json={
            "event_type": "user_message",
            "content": "I prefer TASK_API_RECALL documentation in Chinese with concise steps.",
            "source": "conversation",
            "scope": "global",
        },
    ).json()
    pref_candidate = client.post(f"/candidates/from-event/{pref_event['id']}").json()[0]
    pref_decision = client.post(f"/candidates/{pref_candidate['id']}/evaluate").json()
    pref_memory = client.post(
        "/memories/commit",
        json={"candidate_id": pref_candidate["id"], "decision_id": pref_decision["id"]},
    ).json()

    fact_event = client.post(
        "/events",
        json={
            "event_type": "file_observation",
            "content": "passed TASK_API_RECALL start command is pnpm dev.",
            "source": "package.json",
            "scope": "repo:C:/workspace/demo",
            "metadata": {"subject": "start command"},
        },
    ).json()
    fact_candidate = client.post(f"/candidates/from-event/{fact_event['id']}").json()[0]
    fact_decision = client.post(f"/candidates/{fact_candidate['id']}/evaluate").json()
    fact_memory = client.post(
        "/memories/commit",
        json={"candidate_id": fact_candidate["id"], "decision_id": fact_decision["id"]},
    ).json()

    response = client.post(
        "/recall/task",
        json={
            "task": "TASK_API_RECALL 帮我写这个项目的启动说明 README",
            "scope": "repo:C:/workspace/demo",
            "token_budget": 2000,
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["plan"]["intent"] == "documentation"
    memory_ids = [memory["id"] for memory in result["memories"]]
    assert pref_memory["id"] in memory_ids
    assert fact_memory["id"] in memory_ids
    assert pref_memory["id"] in result["context"]["memory_ids"]
    assert fact_memory["id"] in result["context"]["memory_ids"]
