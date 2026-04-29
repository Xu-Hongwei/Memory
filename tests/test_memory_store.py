from __future__ import annotations

import sqlite3

import pytest

from memory_system import (
    EventCreate,
    EventLog,
    MemoryItemCreate,
    MemoryPolicyError,
    MemoryStore,
    RetrievalLogCreate,
    SearchMemoryInput,
)
from memory_system.schemas import MemoryCandidateCreate


def test_propose_commit_and_search_user_preference(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    events = EventLog(db_path)
    memories = MemoryStore(db_path)

    event = events.record_event(
        EventCreate(
            event_type="user_message",
            content="以后技术文档默认用中文，并且区分事实和推断。",
            source="conversation",
            scope="global",
        )
    )

    candidates = memories.propose_memory(event)

    assert len(candidates) == 1
    assert candidates[0].memory_type == "user_preference"
    assert candidates[0].confidence == "confirmed"
    assert candidates[0].claim == "以后技术文档默认用中文，并且区分事实和推断。"
    assert candidates[0].evidence_type == "direct_user_statement"
    assert candidates[0].time_validity == "persistent"
    assert "future_responses" in candidates[0].reuse_cases
    assert candidates[0].scores.long_term >= 0.8

    decision = memories.evaluate_candidate(candidates[0].id)
    assert decision.decision == "write"
    assert decision.structured_reason["evidence"].startswith("direct_user_statement")
    assert decision.structured_reason["time_validity"] == "persistent"

    memory = memories.commit_memory(candidates[0].id, decision.id)

    assert memory.memory_type == "user_preference"
    assert memory.source_event_ids == [event.id]
    assert "future_responses" in memory.tags
    assert memory.last_verified_at is not None
    assert memories.get_candidate(candidates[0].id).status == "committed"

    results = memories.search_memory(
        SearchMemoryInput(query="中文", memory_types=["user_preference"], scopes=["global"])
    )

    assert [item.id for item in results] == [memory.id]
    assert memories.get_memory(memory.id).last_used_at is not None
    logs = memories.list_retrieval_logs(source="search", memory_id=memory.id)
    assert len(logs) == 1
    assert logs[0].query == "中文"
    assert logs[0].retrieved_memory_ids == [memory.id]
    assert logs[0].used_memory_ids == [memory.id]
    assert logs[0].metadata["memory_types"] == ["user_preference"]

    feedback = memories.add_retrieval_feedback(
        logs[0].id,
        feedback="useful",
        reason="Search result answered the question.",
    )
    assert feedback.feedback == "useful"
    assert feedback.feedback_reason == "Search result answered the question."
    usage = memories.get_memory_usage_stats(memory.id)
    assert usage.used_count == 1
    assert usage.useful_feedback_count == 1
    assert usage.recommended_action == "keep"


def test_preview_uses_structured_metadata_candidates_atomically(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    events = EventLog(db_path)
    memories = MemoryStore(db_path)

    event = events.record_event(
        EventCreate(
            event_type="user_message",
            content=(
                "Going forward, answer architecture questions in Chinese. "
                "For this repo, the release workflow is ruff then pytest."
            ),
            source="conversation",
            scope="repo:C:/workspace/demo",
            metadata={
                "memory_candidates": [
                    {
                        "content": "The user prefers Chinese answers for architecture questions.",
                        "memory_type": "user_preference",
                        "scope": "global",
                        "subject": "architecture answer language",
                        "claim": "Answer architecture questions in Chinese.",
                        "evidence_type": "direct_user_statement",
                        "time_validity": "persistent",
                        "reuse_cases": ["future_responses"],
                        "scores": {
                            "long_term": 0.9,
                            "evidence": 1.0,
                            "reuse": 0.8,
                            "risk": 0.1,
                            "specificity": 0.8,
                        },
                        "confidence": "confirmed",
                        "risk": "low",
                    },
                    {
                        "content": "The repo release workflow is ruff then pytest.",
                        "memory_type": "workflow",
                        "subject": "release workflow",
                        "claim": "Run ruff, then pytest before release.",
                        "evidence_type": "direct_user_statement",
                        "time_validity": "until_changed",
                        "reuse_cases": ["release_validation"],
                        "scores": {
                            "long_term": 0.9,
                            "evidence": 1.0,
                            "reuse": 0.9,
                            "risk": 0.1,
                            "specificity": 0.8,
                        },
                        "confidence": "confirmed",
                        "risk": "low",
                    },
                ]
            },
        )
    )

    candidates = memories.propose_memory(event)

    assert [candidate.memory_type for candidate in candidates] == ["user_preference", "workflow"]
    assert [candidate.claim for candidate in candidates] == [
        "Answer architecture questions in Chinese.",
        "Run ruff, then pytest before release.",
    ]
    assert candidates[0].scope == "global"
    assert candidates[1].scope == "repo:C:/workspace/demo"
    assert [memories.evaluate_candidate(candidate.id).decision for candidate in candidates] == [
        "write",
        "write",
    ]


def test_memory_usage_stats_recommends_review_and_stale(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    reviewed = memories.add_memory(
        MemoryItemCreate(
            content="USAGE_REVIEW often retrieved but never used.",
            memory_type="project_fact",
            scope="repo:C:/workspace/usage",
            subject="usage review",
            confidence="confirmed",
            source_event_ids=["evt_usage_review"],
        )
    )
    stale_candidate = memories.add_memory(
        MemoryItemCreate(
            content="USAGE_STALE repeatedly rated not useful.",
            memory_type="project_fact",
            scope="repo:C:/workspace/usage",
            subject="usage stale",
            confidence="confirmed",
            source_event_ids=["evt_usage_stale"],
        )
    )

    for index in range(3):
        memories.record_retrieval_log(
            RetrievalLogCreate(
                query=f"review {index}",
                source="context",
                retrieved_memory_ids=[reviewed.id],
                skipped_memory_ids=[reviewed.id],
            )
        )

    for index in range(2):
        log = memories.record_retrieval_log(
            RetrievalLogCreate(
                query=f"stale {index}",
                source="context",
                retrieved_memory_ids=[stale_candidate.id],
                used_memory_ids=[stale_candidate.id],
            )
        )
        memories.add_retrieval_feedback(
            log.id,
            feedback="not_useful",
            reason="The memory did not help this task.",
        )

    review_stats = memories.get_memory_usage_stats(reviewed.id)
    assert review_stats.retrieved_count == 3
    assert review_stats.used_count == 0
    assert review_stats.skipped_count == 3
    assert review_stats.recommended_action == "review"

    stale_stats = memories.get_memory_usage_stats(stale_candidate.id)
    assert stale_stats.not_useful_feedback_count == 2
    assert stale_stats.recommended_action == "mark_stale"

    maintenance = memories.list_memory_usage_stats(
        scope="repo:C:/workspace/usage",
        recommended_action="mark_stale",
    )
    assert [item.memory_id for item in maintenance] == [stale_candidate.id]


def test_maintenance_review_queue_resolves_lifecycle_actions(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    stale_candidate = memories.add_memory(
        MemoryItemCreate(
            content="MAINT_REVIEW active memory repeatedly rated not useful.",
            memory_type="project_fact",
            scope="repo:C:/workspace/maintenance",
            subject="maintenance stale",
            confidence="confirmed",
            source_event_ids=["evt_maint_review"],
        )
    )
    review_candidate = memories.add_memory(
        MemoryItemCreate(
            content="MAINT_REVIEW retrieved but never used.",
            memory_type="project_fact",
            scope="repo:C:/workspace/maintenance",
            subject="maintenance review",
            confidence="confirmed",
            source_event_ids=["evt_maint_review_only"],
        )
    )

    for index in range(2):
        log = memories.record_retrieval_log(
            RetrievalLogCreate(
                query=f"not useful {index}",
                source="context",
                retrieved_memory_ids=[stale_candidate.id],
                used_memory_ids=[stale_candidate.id],
            )
        )
        memories.add_retrieval_feedback(log.id, feedback="not_useful")

    for index in range(3):
        memories.record_retrieval_log(
            RetrievalLogCreate(
                query=f"skipped {index}",
                source="context",
                retrieved_memory_ids=[review_candidate.id],
                skipped_memory_ids=[review_candidate.id],
            )
        )

    reviews = memories.create_maintenance_reviews(scope="repo:C:/workspace/maintenance")
    assert {review.recommended_action for review in reviews} == {"mark_stale", "review"}
    assert memories.create_maintenance_reviews(scope="repo:C:/workspace/maintenance") == []

    stale_review = next(review for review in reviews if review.recommended_action == "mark_stale")
    review_only = next(review for review in reviews if review.recommended_action == "review")

    resolved_stale = memories.resolve_maintenance_review(
        stale_review.id,
        action="mark_stale",
        reason="Repeated feedback says this memory is not useful.",
    )
    assert resolved_stale.status == "resolved"
    assert memories.get_memory(stale_candidate.id).status == "stale"
    assert [version.change_type for version in memories.list_versions(stale_candidate.id)] == [
        "create",
        "stale",
    ]

    needs_user = memories.resolve_maintenance_review(review_only.id, action="review")
    assert needs_user.status == "needs_user"
    assert memories.get_memory(review_candidate.id).status == "active"

    archive_review = memories.create_maintenance_reviews(
        scope="repo:C:/workspace/maintenance",
        recommended_action="archive",
    )[0]
    archived = memories.resolve_maintenance_review(archive_review.id, action="archive")
    assert archived.status == "resolved"
    assert memories.get_memory(stale_candidate.id).status == "archived"


def test_one_off_request_does_not_create_candidate(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    events = EventLog(db_path)
    memories = MemoryStore(db_path)

    event = events.record_event(
        EventCreate(
            event_type="user_message",
            content="帮我把这句话改得更正式一点。",
            source="conversation",
        )
    )

    assert memories.propose_memory(event) == []


def test_verified_project_fact_creates_version_and_fts_result(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    events = EventLog(db_path)
    memories = MemoryStore(db_path)

    event = events.record_event(
        EventCreate(
            event_type="file_observation",
            content="已确认 package.json 中 dev 脚本是 vite --host 0.0.0.0。",
            source="package.json",
            scope="repo:C:/workspace/demo",
            metadata={"subject": "dev script"},
        )
    )

    candidate = memories.propose_memory(event)[0]
    decision = memories.evaluate_candidate(candidate.id)
    memory = memories.commit_memory(candidate.id, decision.id)
    versions = memories.list_versions(memory.id)

    assert memory.memory_type == "project_fact"
    assert memory.subject == "dev script"
    assert len(versions) == 1
    assert versions[0].change_type == "create"

    results = memories.search_memory(
        SearchMemoryInput(query="vite", scopes=["repo:C:/workspace/demo"], limit=5)
    )

    assert [item.id for item in results] == [memory.id]


def test_memory_embeddings_support_semantic_search_without_keyword_overlap(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    release = memories.add_memory(
        MemoryItemCreate(
            content="项目发布前要先运行 ruff check 和 pytest。",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )
    language = memories.add_memory(
        MemoryItemCreate(
            content="用户偏好中文技术解释。",
            memory_type="user_preference",
            scope="global",
            subject="answer language",
            confidence="confirmed",
            source_event_ids=["evt_language"],
        )
    )
    memories.upsert_memory_embedding(release.id, vector=[1.0, 0.0], model="fake-embedding")
    memories.upsert_memory_embedding(language.id, vector=[0.0, 1.0], model="fake-embedding")

    results = memories.search_memory(
        SearchMemoryInput(
            query="部署前应该检查什么",
            scopes=["repo:C:/workspace/demo", "global"],
            retrieval_mode="semantic",
            query_embedding=[0.95, 0.05],
            embedding_model="fake-embedding",
            limit=2,
        )
    )

    assert [item.id for item in results] == [release.id, language.id]
    embedding = memories.get_memory_embedding(release.id, model="fake-embedding")
    assert embedding.dimensions == 2
    assert "release checks" in embedding.embedded_text
    logs = memories.list_retrieval_logs(source="search", memory_id=release.id)
    assert logs[0].metadata["retrieval_mode"] == "semantic"
    assert logs[0].metadata["semantic_enabled"] is True
    assert logs[0].metadata["embedding_model"] == "fake-embedding"


def test_hybrid_search_combines_keyword_scope_and_embedding_scores(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    semantic_match = memories.add_memory(
        MemoryItemCreate(
            content="发布前固定运行测试套件。",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="pre release validation",
            confidence="confirmed",
            source_event_ids=["evt_semantic"],
        )
    )
    keyword_match = memories.add_memory(
        MemoryItemCreate(
            content="部署说明文档需要保持简洁。",
            memory_type="user_preference",
            scope="global",
            subject="deployment docs",
            confidence="confirmed",
            source_event_ids=["evt_keyword"],
        )
    )
    memories.upsert_memory_embedding(semantic_match.id, vector=[1.0, 0.0], model="fake-embedding")
    memories.upsert_memory_embedding(keyword_match.id, vector=[0.0, 1.0], model="fake-embedding")

    results = memories.search_memory(
        SearchMemoryInput(
            query="部署前检查",
            scopes=["repo:C:/workspace/demo", "global"],
            retrieval_mode="hybrid",
            query_embedding=[1.0, 0.0],
            embedding_model="fake-embedding",
            limit=2,
        )
    )

    assert results[0].id == semantic_match.id


def test_list_memories_missing_embedding_filters_by_model(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    indexed = memories.add_memory(
        MemoryItemCreate(
            content="INDEXED embedding memory.",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="indexed",
            confidence="confirmed",
            source_event_ids=["evt_indexed"],
        )
    )
    missing = memories.add_memory(
        MemoryItemCreate(
            content="MISSING embedding memory.",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="missing",
            confidence="confirmed",
            source_event_ids=["evt_missing"],
        )
    )
    memories.upsert_memory_embedding(indexed.id, vector=[0.2, 0.8], model="fake-embedding")

    results = memories.list_memories_missing_embedding(
        model="fake-embedding",
        scope="repo:C:/workspace/demo",
    )

    assert [item.id for item in results] == [missing.id]


def test_duplicate_candidate_merges_with_existing_memory(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    events = EventLog(db_path)
    memories = MemoryStore(db_path)

    event = events.record_event(
        EventCreate(
            event_type="file_observation",
            content="已确认 package.json 中 dev 脚本是 vite。",
            source="package.json",
            scope="repo:C:/workspace/demo",
            metadata={"subject": "dev script"},
        )
    )
    first_candidate = memories.propose_memory(event)[0]
    first_decision = memories.evaluate_candidate(first_candidate.id)
    first_memory = memories.commit_memory(first_candidate.id, first_decision.id)

    duplicate_candidate = memories.create_candidate(
        MemoryCandidateCreate(
            content=first_candidate.content,
            memory_type=first_candidate.memory_type,
            scope=first_candidate.scope,
            subject=first_candidate.subject,
            source_event_ids=[event.id],
            reason="重复候选。",
            confidence="confirmed",
            risk="low",
        )
    )

    duplicate_decision = memories.evaluate_candidate(duplicate_candidate.id)
    merged_memory = memories.commit_memory(duplicate_candidate.id, duplicate_decision.id)

    assert duplicate_decision.decision == "merge"
    assert duplicate_decision.matched_memory_ids == [first_memory.id]
    assert merged_memory.id == first_memory.id


def test_conflicting_candidate_requires_user_confirmation(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    memories = MemoryStore(db_path)

    memories.add_memory(
        MemoryItemCreate(
            content="项目启动命令是 npm run dev。",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="启动命令",
            source_event_ids=["evt_existing"],
            confidence="confirmed",
        )
    )

    candidate = memories.create_candidate(
        MemoryCandidateCreate(
            content="项目启动命令是 pnpm dev。",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="启动命令",
            source_event_ids=["evt_new"],
            reason="新观察。",
            confidence="confirmed",
            risk="low",
        )
    )

    decision = memories.evaluate_candidate(candidate.id)

    assert decision.decision == "ask_user"
    assert decision.required_action is not None
    with pytest.raises(MemoryPolicyError):
        memories.commit_memory(candidate.id, decision.id)


def test_canonical_subject_conflict_requires_confirmation(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")

    memories.add_memory(
        MemoryItemCreate(
            content="Previously confirmed startup command: old value says npm run dev.",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="startup command conflict fact",
            source_event_ids=["evt_existing"],
            confidence="confirmed",
        )
    )

    candidate = memories.create_candidate(
        MemoryCandidateCreate(
            content="已确认 startup command: 已确认 the startup command is pnpm dev.",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="startup command",
            source_event_ids=["evt_new"],
            reason="Remote candidate used a shorter subject.",
            evidence_type="file_observation",
            scores={"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
            confidence="confirmed",
            risk="low",
        )
    )

    decision = memories.evaluate_candidate(candidate.id)

    assert decision.decision == "ask_user"
    assert len(decision.matched_memory_ids) == 1


def test_duplicate_candidate_merges_by_canonical_content_even_when_subject_drifts(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    content = (
        "已确认 README.md stores dev command: "
        "已确认 package.json 的 dev command is memoryctl serve."
    )
    existing = memories.add_memory(
        MemoryItemCreate(
            content=content,
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="README.md dev command duplicate",
            source_event_ids=["evt_existing"],
            confidence="confirmed",
        )
    )

    candidate = memories.create_candidate(
        MemoryCandidateCreate(
            content=content,
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="README dev command",
            source_event_ids=["evt_new"],
            reason="Remote candidate used a shorter subject.",
            evidence_type="file_observation",
            scores={"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
            confidence="confirmed",
            risk="low",
        )
    )

    decision = memories.evaluate_candidate(candidate.id)

    assert decision.decision == "merge"
    assert decision.matched_memory_ids == [existing.id]


def test_rejects_high_risk_candidate(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    candidate = memories.create_candidate(
        MemoryCandidateCreate(
            content="token=[REDACTED]",
            memory_type="project_fact",
            scope="global",
            subject="敏感内容",
            source_event_ids=["evt_secret"],
            reason="测试高风险拒绝。",
            confidence="confirmed",
            risk="high",
        )
    )

    decision = memories.evaluate_candidate(candidate.id)

    assert decision.decision == "reject"
    assert memories.get_candidate(candidate.id).status == "rejected"
    with pytest.raises(MemoryPolicyError):
        memories.commit_memory(candidate.id, decision.id)


def test_rejects_raw_sensitive_candidate_even_when_risk_low(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    candidate = memories.create_candidate(
        MemoryCandidateCreate(
            content="Production token=abcdef1234567890 should be reused.",
            memory_type="project_fact",
            scope="global",
            subject="raw token",
            source_event_ids=["evt_secret"],
            reason="Remote extraction returned an unsanitized candidate.",
            claim="token=abcdef1234567890",
            evidence_type="direct_user_statement",
            time_validity="persistent",
            scores={"long_term": 0.9, "evidence": 1.0, "reuse": 0.8},
            confidence="confirmed",
            risk="low",
        )
    )

    decision = memories.evaluate_candidate(candidate.id)

    assert decision.decision == "reject"
    assert memories.get_candidate(candidate.id).status == "rejected"


def test_tool_rule_can_mention_secret_terms_without_secret_value(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    candidate = memories.create_candidate(
        MemoryCandidateCreate(
            content="Do not store API keys or tokens in long-term memory.",
            memory_type="tool_rule",
            scope="global",
            subject="secret handling",
            source_event_ids=["evt_rule"],
            reason="User stated a reusable safety rule.",
            claim="Do not store API keys or tokens in long-term memory.",
            evidence_type="direct_user_statement",
            time_validity="until_changed",
            scores={"long_term": 0.9, "evidence": 1.0, "reuse": 0.9},
            confidence="confirmed",
            risk="low",
        )
    )

    decision = memories.evaluate_candidate(candidate.id)

    assert decision.decision == "write"


def test_candidate_time_validity_controls_policy(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")

    session_candidate = memories.create_candidate(
        MemoryCandidateCreate(
            content="Only remember the current screenshot layout for this session.",
            memory_type="project_fact",
            scope="global",
            subject="temporary screenshot layout",
            source_event_ids=["evt_session"],
            reason="The candidate is explicitly temporary.",
            evidence_type="direct_user_statement",
            time_validity="session",
            scores={"long_term": 0.9, "evidence": 1.0, "reuse": 0.8},
            confidence="confirmed",
            risk="low",
        )
    )
    unknown_candidate = memories.create_candidate(
        MemoryCandidateCreate(
            content="The preferred deployment window may be late evening.",
            memory_type="workflow",
            scope="global",
            subject="deployment window",
            source_event_ids=["evt_unknown"],
            reason="The candidate has evidence but no persistence window.",
            evidence_type="direct_user_statement",
            time_validity="unknown",
            scores={"long_term": 0.9, "evidence": 1.0, "reuse": 0.8},
            confidence="confirmed",
            risk="low",
        )
    )

    session_decision = memories.evaluate_candidate(session_candidate.id)
    unknown_decision = memories.evaluate_candidate(unknown_candidate.id)

    assert session_decision.decision == "reject"
    assert unknown_decision.decision == "ask_user"
    assert unknown_decision.required_action is not None


def test_low_evidence_candidate_requires_review(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    candidate = memories.create_candidate(
        MemoryCandidateCreate(
            content="用户可能喜欢更短的回复。",
            memory_type="user_preference",
            scope="global",
            subject="用户偏好",
            source_event_ids=["evt_inferred"],
            reason="从单次对话推断，证据不足。",
            confidence="inferred",
            risk="low",
        )
    )

    decision = memories.evaluate_candidate(candidate.id)

    assert decision.decision == "ask_user"
    assert "证据" in decision.reason
    assert decision.structured_reason["evidence"].startswith("unknown")


def test_initialize_migrates_old_candidate_tables(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE memory_candidates (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                scope TEXT NOT NULL,
                subject TEXT NOT NULL,
                source_event_ids_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                confidence TEXT NOT NULL,
                risk TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE policy_decisions (
                id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                matched_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                required_action TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

    MemoryStore(db_path)

    with sqlite3.connect(db_path) as conn:
        candidate_columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_candidates)")}
        decision_columns = {row[1] for row in conn.execute("PRAGMA table_info(policy_decisions)")}

    assert {"claim", "evidence_type", "time_validity", "reuse_cases_json", "scores_json"} <= (
        candidate_columns
    )
    assert "structured_reason_json" in decision_columns
