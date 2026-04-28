from __future__ import annotations

from memory_system import (
    CandidateScores,
    MemoryItemCreate,
    MemoryStore,
    compose_context,
)
from memory_system.schemas import MemoryCandidateCreate


def test_pending_review_can_list_approve_reject_and_edit(tmp_path):
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

    assert [item.id for item in memories.list_candidates(status="pending")] == [candidate.id]
    decision = memories.evaluate_candidate(candidate.id)
    assert decision.decision == "ask_user"

    edited = memories.edit_candidate(
        candidate.id,
        claim="用户明确确认偏好更短的回复。",
        evidence_type="direct_user_statement",
        time_validity="persistent",
        reuse_cases=["future_responses"],
        scores=CandidateScores(long_term=0.8, evidence=1.0, reuse=0.7, risk=0.1, specificity=0.7),
        confidence="confirmed",
        reason="人工确认后补充证据。",
    )
    assert edited.evidence_type == "direct_user_statement"

    memory = memories.approve_candidate(edited.id)
    assert memory.memory_type == "user_preference"
    assert memories.get_candidate(candidate.id).status == "committed"

    rejected = memories.create_candidate(
        MemoryCandidateCreate(
            content="临时状态：今天先不处理。",
            memory_type="workflow",
            scope="global",
            subject="临时状态",
            source_event_ids=["evt_temp"],
            reason="人工判断没有长期价值。",
            confidence="unknown",
            risk="low",
        )
    )
    reject_decision = memories.reject_candidate(rejected.id)

    assert reject_decision.decision == "reject"
    assert reject_decision.structured_reason["manual_review"] == "rejected"
    assert memories.get_candidate(rejected.id).status == "rejected"


def test_context_composer_skips_inactive_memories_and_warns_on_low_confidence(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    confirmed = memories.add_memory(
        MemoryItemCreate(
            content="技术文档默认使用中文。",
            memory_type="user_preference",
            scope="global",
            subject="文档语言",
            confidence="confirmed",
            source_event_ids=["evt_pref"],
            tags=["future_responses"],
        )
    )
    likely = memories.add_memory(
        MemoryItemCreate(
            content="项目可能需要 pnpm dev 启动。",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="启动命令",
            confidence="likely",
            source_event_ids=["evt_start"],
        )
    )
    archived = confirmed.model_copy(update={"id": "mem_archived", "status": "archived"})

    block = compose_context("写项目说明", [confirmed, likely, archived], token_budget=1000)

    assert confirmed.id in block.memory_ids
    assert likely.id in block.memory_ids
    assert "mem_archived" not in block.memory_ids
    assert "技术文档默认使用中文。" in block.content
    assert any("status=archived" in warning for warning in block.warnings)
    assert any(f"{likely.id}: confidence=likely" == warning for warning in block.warnings)
    assert any(f"{likely.id}: missing last_verified_at" == warning for warning in block.warnings)


def test_context_composer_respects_budget(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")
    memory = memories.add_memory(
        MemoryItemCreate(
            content="这是一条很长的记忆。" * 50,
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="长记忆",
            confidence="confirmed",
            source_event_ids=["evt_long"],
        )
    )

    block = compose_context("短预算", [memory], token_budget=30)

    assert block.memory_ids == []
    assert any("token_budget exhausted" in warning for warning in block.warnings)


def test_approve_candidate_raises_for_missing_candidate(tmp_path):
    memories = MemoryStore(tmp_path / "memory.sqlite")

    try:
        memories.approve_candidate("cand_missing")
    except Exception as exc:
        assert isinstance(exc, LookupError)
    else:
        raise AssertionError("expected missing candidate to raise")
