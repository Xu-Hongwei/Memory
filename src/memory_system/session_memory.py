from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from memory_system.schemas import (
    ContextBlock,
    EventRead,
    MemoryCandidateCreate,
    MemoryItemRead,
    MemoryRouteItem,
    SessionCloseoutDecision,
    SessionMemoryExtractionResult,
    SessionMemoryItemCreate,
    SessionMemoryItemRead,
    SessionMemoryType,
)

TEMPORARY_SESSION_CUES = (
    "\u8fd9\u6b21",
    "\u672c\u8f6e",
    "\u5f53\u524d\u4efb\u52a1",
    "\u5f53\u524d\u4f8b\u5b50",
    "\u4eca\u5929\u5148",
    "\u6682\u65f6",
    "for this task",
    "for now",
    "just for now",
    "this task only",
    "this time only",
    "today only",
    "current example",
)
TEMPORARY_RULE_CUES = (
    "\u4e0d\u8981\u63d0\u4ea4",
    "\u5148\u4e0d\u63d0\u4ea4",
    "\u4e0d\u8981\u5199\u5165",
    "\u4e0d\u8981\u6269\u5927",
    "do not commit",
    "don't commit",
    "do not write",
    "don't write",
    "do not expand",
    "don't expand",
    "skip",
)
WORKING_FACT_CUES = (
    "\u521a\u624d",
    "\u5df2\u7ecf\u8dd1\u5b8c",
    "\u7ed3\u679c\u662f",
    "\u901a\u8fc7",
    "\u5931\u8d25",
    "just ran",
    "result",
    "passed",
    "failed",
)
PENDING_DECISION_CUES = (
    "\u7b49\u6211\u4eec\u786e\u8ba4",
    "\u7b49\u786e\u8ba4",
    "\u5f85\u786e\u8ba4",
    "\u786e\u8ba4\u540e",
    "after we confirm",
    "once we confirm",
    "pending confirmation",
    "wait until confirmed",
)
SESSION_TYPE_BASE_SCORES: dict[SessionMemoryType, float] = {
    "pending_decision": 0.9,
    "temporary_rule": 0.8,
    "task_state": 0.65,
    "working_fact": 0.6,
    "emotional_state": 0.55,
    "scratch_note": 0.35,
}


class SessionMemoryStore:
    """In-process store for task/session-scoped memory.

    Session memory is deliberately separate from long-term MemoryStore. It can
    guide the current task, but it is not committed as durable memory.
    """

    def __init__(self) -> None:
        self._items: dict[str, SessionMemoryItemRead] = {}

    def add_item(self, item: SessionMemoryItemCreate) -> SessionMemoryItemRead:
        now = _utc_now()
        memory_id = _new_session_memory_id()
        created = SessionMemoryItemRead(
            **item.model_dump(),
            id=memory_id,
            status="active",
            created_at=now,
            updated_at=now,
        )
        self._items[memory_id] = created
        return created

    def capture_event(
        self,
        event: EventRead,
        *,
        session_id: str = "default",
    ) -> SessionMemoryExtractionResult:
        extracted = extract_session_items_from_event(event, session_id=session_id)
        stored = [self.add_item(item) for item in extracted.items]
        return extracted.model_copy(update={"items": [_read_to_create(item) for item in stored]})

    def capture_remote_candidates(
        self,
        event: EventRead,
        candidates: list[MemoryCandidateCreate],
        *,
        session_id: str = "default",
    ) -> list[SessionMemoryItemRead]:
        stored: list[SessionMemoryItemRead] = []
        for candidate in candidates:
            item = session_item_from_candidate(event, candidate, session_id=session_id)
            if item is not None:
                stored.append(self.add_item(item))
        return stored

    def capture_route_items(
        self,
        event: EventRead,
        items: list[MemoryRouteItem],
        *,
        session_id: str = "default",
    ) -> list[SessionMemoryItemRead]:
        stored: list[SessionMemoryItemRead] = []
        for route_item in items:
            item = session_item_from_route_item(event, route_item, session_id=session_id)
            if item is not None:
                stored.append(self.add_item(item))
        return stored

    def search(
        self,
        query: str,
        *,
        session_id: str = "default",
        scopes: list[str] | None = None,
        limit: int = 5,
        now: datetime | None = None,
    ) -> list[SessionMemoryItemRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        self.expire(now=now)
        query_tokens = _tokens(query)
        scope_set = set(scopes or [])
        ranked: list[tuple[float, SessionMemoryItemRead]] = []
        for item in self._items.values():
            if item.status != "active" or item.session_id != session_id:
                continue
            if scope_set and item.scope not in scope_set and item.scope != "session":
                continue
            score = _score_session_item(query_tokens, item)
            if score <= 0 and query_tokens:
                continue
            ranked.append((score, item))
        ranked.sort(key=lambda pair: (pair[0], pair[1].updated_at), reverse=True)
        results = [item for _score, item in ranked[:limit]]
        for item in results:
            self._touch(item.id)
        return [self._items[item.id] for item in results]

    def list_items(
        self,
        *,
        session_id: str | None = None,
        include_expired: bool = False,
        now: datetime | None = None,
    ) -> list[SessionMemoryItemRead]:
        self.expire(now=now)
        items = []
        for item in self._items.values():
            if session_id is not None and item.session_id != session_id:
                continue
            if not include_expired and item.status != "active":
                continue
            items.append(item)
        return sorted(items, key=lambda item: item.updated_at, reverse=True)

    def expire(self, *, now: datetime | None = None) -> None:
        current = now or _utc_now()
        for item in list(self._items.values()):
            if item.status != "active" or item.expires_at is None:
                continue
            if item.expires_at <= current:
                self._items[item.id] = item.model_copy(
                    update={"status": "expired", "updated_at": current}
                )

    def clear_session(self, session_id: str) -> int:
        to_delete = [item_id for item_id, item in self._items.items() if item.session_id == session_id]
        for item_id in to_delete:
            del self._items[item_id]
        return len(to_delete)

    def dismiss_items(
        self,
        item_ids: list[str],
        *,
        reason: str = "Session memory dismissed during closeout.",
        action: str = "closeout",
        now: datetime | None = None,
    ) -> list[SessionMemoryItemRead]:
        current = now or _utc_now()
        dismissed: list[SessionMemoryItemRead] = []
        for item_id in dict.fromkeys(item_ids):
            item = self._items.get(item_id)
            if item is None or item.status != "active":
                continue
            updated = item.model_copy(
                update={
                    "status": "dismissed",
                    "updated_at": current,
                    "metadata": {
                        **item.metadata,
                        "closeout_action": action,
                        "closeout_reason": reason,
                    },
                }
            )
            self._items[item_id] = updated
            dismissed.append(updated)
        return dismissed

    def apply_closeout_decisions(
        self,
        decisions: list[SessionCloseoutDecision],
        *,
        now: datetime | None = None,
    ) -> list[SessionMemoryItemRead]:
        dismissed_ids = [
            decision.session_memory_id
            for decision in decisions
            if decision.action in {"discard", "summarize", "promote_candidate"}
        ]
        return self.dismiss_items(
            dismissed_ids,
            reason="Session closeout decision dismissed this item.",
            action="session_closeout",
            now=now,
        )

    def _touch(self, item_id: str) -> None:
        item = self._items[item_id]
        now = _utc_now()
        self._items[item_id] = item.model_copy(update={"last_used_at": now, "updated_at": now})


def extract_session_items_from_event(
    event: EventRead,
    *,
    session_id: str = "default",
) -> SessionMemoryExtractionResult:
    """Conservative local fallback for session memory extraction.

    Normal LLM-backed routing should use RemoteLLMClient.route_memories so the
    same remote call can split events into long-term, session, ignore, reject,
    and ask_user routes. This helper only catches obvious local temporary cues.
    """

    warnings: list[str] = []
    if _contains_sensitive_marker(event.content):
        return SessionMemoryExtractionResult(
            session_id=session_id,
            warnings=["filtered_sensitive_session_event"],
            metadata={"skipped": True},
        )

    item_type = classify_session_memory_type(event)
    if item_type is None:
        return SessionMemoryExtractionResult(session_id=session_id)

    subject = _subject_for_session_item(item_type, event.content)
    item = SessionMemoryItemCreate(
        content=event.content,
        session_id=session_id,
        memory_type=item_type,
        scope=event.scope or "session",
        subject=subject,
        source_event_ids=[event.id],
        reason="Captured as session-scoped memory; it should not enter long-term memory.",
        metadata={"expires_when": _expires_when(item_type), "event_type": event.event_type},
    )
    return SessionMemoryExtractionResult(
        session_id=session_id,
        items=[item],
        warnings=warnings,
        metadata={"source": "local_session_lifecycle"},
    )


def classify_session_memory_type(event: EventRead) -> SessionMemoryType | None:
    content = event.content
    lowered = content.lower()
    if _is_pending_decision(content):
        return "pending_decision"
    if event.event_type in {"tool_result", "test_result"} and _contains_any(
        lowered, WORKING_FACT_CUES
    ):
        return "working_fact"
    if not _contains_any(lowered, TEMPORARY_SESSION_CUES):
        return None
    if _contains_any(lowered, TEMPORARY_RULE_CUES):
        return "temporary_rule"
    return "task_state"


def session_item_from_candidate(
    event: EventRead,
    candidate: MemoryCandidateCreate,
    *,
    session_id: str = "default",
) -> SessionMemoryItemCreate | None:
    if candidate.time_validity != "session":
        return None
    item_type = _session_type_from_candidate(candidate)
    return SessionMemoryItemCreate(
        content=candidate.claim or candidate.content,
        session_id=session_id,
        memory_type=item_type,
        scope=event.scope or candidate.scope or "session",
        subject=candidate.subject,
        source_event_ids=list(dict.fromkeys([*candidate.source_event_ids, event.id])),
        reason=(
            "Remote/LLM candidate was routed to session memory because "
            "time_validity=session."
        ),
        metadata={
            "expires_when": _expires_when(item_type),
            "source_memory_type": candidate.memory_type,
            "remote_scores": candidate.scores.model_dump(),
        },
    )


def session_item_from_route_item(
    event: EventRead,
    item: MemoryRouteItem,
    *,
    session_id: str = "default",
) -> SessionMemoryItemCreate | None:
    if item.route != "session":
        return None
    item_type = item.session_memory_type or _session_type_from_memory_type(item.memory_type)
    subject = item.subject or _subject_for_session_item(item_type, item.content)
    source_event_ids = item.source_event_ids or [event.id]
    return SessionMemoryItemCreate(
        content=item.claim or item.content,
        session_id=session_id,
        memory_type=item_type,
        scope=item.scope or event.scope or "session",
        subject=subject,
        source_event_ids=list(dict.fromkeys([*source_event_ids, event.id])),
        reason=item.reason,
        metadata={
            "expires_when": _expires_when(item_type),
            "source": "memory_route_judge",
            "route_confidence": item.confidence,
            "route_scores": item.scores.model_dump(),
            **item.metadata,
        },
    )


def compose_context_with_session(
    task: str,
    session_items: list[SessionMemoryItemRead],
    memories: list[MemoryItemRead],
    *,
    token_budget: int = 2000,
) -> ContextBlock:
    if token_budget < 1:
        raise ValueError("token_budget must be greater than zero")

    warnings: list[str] = []
    memory_ids: list[str] = []
    session_memory_ids: list[str] = []
    blocks: list[str] = []
    remaining = token_budget

    header = f"Relevant memory for task: {task.strip() or 'unspecified'}"
    blocks.append(header)
    remaining -= len(header)

    for item in session_items:
        if item.status != "active":
            warnings.append(f"Skipped session {item.id}: status={item.status}")
            continue
        block = (
            f"[session][{item.memory_type}][{item.scope}]\n"
            f"Subject: {item.subject}\n"
            f"Content: {item.content}\n"
            f"Expires: {item.metadata.get('expires_when', 'session_end')}"
        )
        if not _append_block(blocks, block, warnings, item.id, remaining):
            break
        remaining -= len(block) + 2
        session_memory_ids.append(item.id)

    for memory in memories:
        if memory.status != "active":
            warnings.append(f"Skipped {memory.id}: status={memory.status}")
            continue
        if memory.confidence != "confirmed":
            warnings.append(f"{memory.id}: confidence={memory.confidence}")
        if memory.last_verified_at is None:
            warnings.append(f"{memory.id}: missing last_verified_at")
        source = ", ".join(memory.source_event_ids)
        block = (
            f"[{memory.confidence}][{memory.memory_type}][{memory.scope}]\n"
            f"Subject: {memory.subject}\n"
            f"Content: {memory.content}\n"
            f"Source: {source}"
        )
        if not _append_block(blocks, block, warnings, memory.id, remaining):
            break
        remaining -= len(block) + 2
        memory_ids.append(memory.id)

    return ContextBlock(
        content="\n\n".join(blocks),
        memory_ids=memory_ids,
        warnings=warnings,
        metadata={
            "task": task,
            "token_budget": str(token_budget),
            "remaining": str(max(0, remaining)),
            "session_memory_ids": ",".join(session_memory_ids),
        },
    )


def _append_block(
    blocks: list[str],
    block: str,
    warnings: list[str],
    item_id: str,
    remaining: int,
) -> bool:
    block_size = len(block) + 2
    if block_size > remaining:
        warnings.append(f"Stopped before {item_id}: token_budget exhausted")
        return False
    blocks.append(block)
    return True


def _session_type_from_candidate(candidate: MemoryCandidateCreate) -> SessionMemoryType:
    return _session_type_from_memory_type(candidate.memory_type)


def _session_type_from_memory_type(memory_type: str | None) -> SessionMemoryType:
    if memory_type == "decision":
        return "pending_decision"
    if memory_type in {"tool_rule", "workflow", "user_preference"}:
        return "temporary_rule"
    if memory_type in {"project_fact", "environment_fact", "troubleshooting"}:
        return "working_fact"
    return "scratch_note"


def _score_session_item(query_tokens: set[str], item: SessionMemoryItemRead) -> float:
    base_score = SESSION_TYPE_BASE_SCORES.get(item.memory_type, 0.25)
    if not query_tokens:
        return base_score
    item_tokens = _tokens(" ".join([item.subject, item.content, item.memory_type]))
    overlap = len(query_tokens & item_tokens)
    if overlap == 0:
        return base_score
    type_bonus = base_score if item.memory_type in {"task_state", "temporary_rule"} else 0.0
    return overlap + type_bonus + base_score


def _subject_for_session_item(item_type: SessionMemoryType, content: str) -> str:
    if item_type == "pending_decision":
        return "pending decision"
    if item_type == "temporary_rule":
        return "temporary task rule"
    if item_type == "working_fact":
        return "working fact"
    if item_type == "emotional_state":
        return "current emotional or comprehension state"
    if item_type == "task_state":
        return "current task state"
    words = _tokens(content)
    if words:
        return " ".join(sorted(words)[:5])
    return "session note"


def _expires_when(item_type: SessionMemoryType) -> str:
    if item_type == "pending_decision":
        return "until_decided_or_session_end"
    if item_type in {"task_state", "temporary_rule", "working_fact", "emotional_state"}:
        return "task_end"
    return "session_end"


def _is_pending_decision(content: str) -> bool:
    lowered = content.lower()
    has_question = "?" in content or "\uff1f" in content
    has_confirmation = _contains_any(lowered, PENDING_DECISION_CUES)
    has_choice = "\u8fd8\u662f" in lowered or " or " in lowered
    return has_confirmation and (has_question or has_choice)


def _contains_sensitive_marker(text: str) -> bool:
    lowered = text.lower()
    exact_markers = (
        "[redacted]",
        "secret",
        "api key",
        "api_key",
        "password",
        "cookie",
        "bearer",
        "authorization",
    )
    if any(marker in lowered for marker in exact_markers):
        return True
    return re.search(r"\b(access|auth|api|private)\s+token\b", lowered) is not None


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[\w\u4e00-\u9fff]+", text) if token}


def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
    return any(cue.lower() in text for cue in cues)


def _read_to_create(item: SessionMemoryItemRead) -> SessionMemoryItemCreate:
    return SessionMemoryItemCreate(
        content=item.content,
        session_id=item.session_id,
        memory_type=item.memory_type,
        scope=item.scope,
        subject=item.subject,
        source_event_ids=item.source_event_ids,
        reason=item.reason,
        expires_at=item.expires_at,
        metadata=item.metadata,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_session_memory_id() -> str:
    return f"smem_{uuid4().hex}"
