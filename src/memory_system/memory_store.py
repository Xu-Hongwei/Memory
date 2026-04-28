from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from memory_system.schemas import (
    CandidateStatus,
    CandidateScores,
    ConflictReviewAction,
    ConflictReviewItemCreate,
    ConflictReviewItemRead,
    ConflictReviewStatus,
    ConsolidationCandidateCreate,
    ConsolidationCandidateRead,
    ConsolidationStatus,
    Confidence,
    EventRead,
    GraphConflictRead,
    MaintenanceReviewItemCreate,
    MaintenanceReviewItemRead,
    MaintenanceReviewStatus,
    MemoryMaintenanceAction,
    MemoryEmbeddingRead,
    MemoryEntityCreate,
    MemoryEntityRead,
    MemoryCandidateCreate,
    MemoryCandidateRead,
    MemoryItemCreate,
    MemoryItemRead,
    MemoryRelationCreate,
    MemoryRelationRead,
    MemoryStatus,
    MemoryType,
    MemoryVersionRead,
    PolicyAction,
    PolicyDecisionRead,
    RetrievalFeedback,
    RetrievalLogCreate,
    RetrievalLogRead,
    RetrievalSource,
    MemoryUsageStatsRead,
    SearchMemoryInput,
    VersionChangeType,
)


class MemoryPolicyError(ValueError):
    """Raised when a memory operation violates the write policy."""


class MemoryNotFoundError(LookupError):
    """Raised when a candidate, decision, or memory item cannot be found."""


STRONG_PREFERENCE_CUES = (
    "以后",
    "默认",
    "记住",
    "偏好",
    "请始终",
    "总是",
    "prefer",
    "preference",
    "remember",
    "default",
    "always",
)
WEAK_PREFERENCE_CUES = ("喜欢", "like")
PREFERENCE_OBJECT_CUES = (
    "回答",
    "回复",
    "文档",
    "代码",
    "格式",
    "风格",
    "语言",
    "注释",
    "排版",
    "说明",
    "tone",
    "answer",
    "answers",
    "response",
    "responses",
    "docs",
    "documentation",
    "code",
    "format",
    "style",
    "language",
)
VERIFIED_CUES = ("已确认", "确认", "已验证", "验证通过", "passed", "通过")
TROUBLESHOOTING_CUES = ("问题", "经验", "解决方式")
TEMPORARY_CUES = (
    "这次",
    "当前任务",
    "本轮",
    "今天先",
    "先用",
    "暂时",
    "temporary",
    "temporarily",
)
TEMPORARY_PHRASES = (
    "临时用",
    "临时把",
    "临时先",
    "临时记住",
    "临时输出",
    "临时文件",
)
TEMPORARY_TOPIC_EXCEPTIONS = ("临时状态", "临时信息", "temporary state", "session state")
SENSITIVE_MARKERS = ("[REDACTED]",)
CONSOLIDATION_CONFIDENCES: tuple[Confidence, ...] = ("confirmed", "likely")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(raw: str) -> Any:
    return json.loads(raw) if raw else None


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(cue.lower() in lowered for cue in cues)


def _normalize_vector_payload(vector: list[float]) -> list[float]:
    if not vector:
        raise ValueError("vector must not be empty")
    normalized: list[float] = []
    for item in vector:
        value = float(item)
        if not math.isfinite(value):
            raise ValueError("vector must contain finite numbers")
        normalized.append(value)
    return normalized


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimensions")
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(left_item * right_item for left_item, right_item in zip(left, right)) / (
        left_norm * right_norm
    )


def build_memory_embedding_text(memory: MemoryItemRead) -> str:
    tags = " ".join(memory.tags)
    return "\n".join(
        item
        for item in (
            f"subject: {memory.subject}",
            f"type: {memory.memory_type}",
            f"scope: {memory.scope}",
            f"content: {memory.content}",
            f"tags: {tags}" if tags else "",
        )
        if item
    )


def _is_temporary(text: str) -> bool:
    lowered = text.lower()
    if _contains_any(lowered, TEMPORARY_TOPIC_EXCEPTIONS):
        return False
    return _contains_any(lowered, TEMPORARY_CUES) or _contains_any(lowered, TEMPORARY_PHRASES)


def _is_preference_candidate(text: str) -> bool:
    if _is_temporary(text):
        return False
    if _contains_any(text, STRONG_PREFERENCE_CUES):
        return True
    return _contains_any(text, WEAK_PREFERENCE_CUES) and _contains_any(
        text, PREFERENCE_OBJECT_CUES
    )


def _default_subject(event: EventRead, memory_type: MemoryType) -> str:
    if isinstance(event.metadata.get("subject"), str) and event.metadata["subject"].strip():
        return event.metadata["subject"].strip()
    if memory_type == "user_preference":
        return "用户偏好"
    if memory_type == "troubleshooting":
        return "排错经验"
    return event.source


def _candidate_scores(
    *,
    long_term: float,
    evidence: float,
    reuse: float,
    risk: float,
    specificity: float,
) -> CandidateScores:
    return CandidateScores(
        long_term=long_term,
        evidence=evidence,
        reuse=reuse,
        risk=risk,
        specificity=specificity,
    )


def _candidate_claim(event: EventRead) -> str:
    claim = event.metadata.get("claim")
    if isinstance(claim, str) and claim.strip():
        return claim.strip()
    return event.content.strip()


def _make_fts_query(query: str) -> str:
    terms = re.findall(r"[\w:/.\-]+", query, flags=re.UNICODE)
    return " OR ".join(f'"{term}"' for term in terms[:8])


def _like_pattern(query: str) -> str:
    escaped = query.replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def _unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _max_datetime(
    current: datetime | None,
    candidate: datetime | None,
) -> datetime | None:
    if candidate is None:
        return current
    if current is None or candidate > current:
        return candidate
    return current


class MemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_name = str(db_path)
        self.db_path = Path(db_path)
        self._memory_conn: sqlite3.Connection | None = None
        if self._db_name == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:")
            self._memory_conn.row_factory = sqlite3.Row
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_candidates (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    source_event_ids_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    claim TEXT NOT NULL DEFAULT '',
                    evidence_type TEXT NOT NULL DEFAULT 'unknown',
                    time_validity TEXT NOT NULL DEFAULT 'unknown',
                    reuse_cases_json TEXT NOT NULL DEFAULT '[]',
                    scores_json TEXT NOT NULL DEFAULT '{}',
                    confidence TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_decisions (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    structured_reason_json TEXT NOT NULL DEFAULT '{}',
                    matched_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    required_action TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES memory_candidates(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    source_event_ids_json TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    last_verified_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_versions (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    change_reason TEXT NOT NULL,
                    source_event_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES memory_items(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    memory_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    embedded_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(memory_id, model),
                    FOREIGN KEY(memory_id) REFERENCES memory_items(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_entities (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_relations (
                    id TEXT PRIMARY KEY,
                    from_memory_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    to_memory_id TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    source_event_ids_json TEXT NOT NULL,
                    source_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consolidation_candidates (
                    id TEXT PRIMARY KEY,
                    source_memory_ids_json TEXT NOT NULL,
                    proposed_content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conflict_review_items (
                    id TEXT PRIMARY KEY,
                    conflict_key TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    from_entity_id TEXT NOT NULL,
                    target_entity_ids_json TEXT NOT NULL DEFAULT '[]',
                    relation_ids_json TEXT NOT NULL DEFAULT '[]',
                    memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    recommended_action TEXT NOT NULL,
                    recommended_keep_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    reason TEXT NOT NULL,
                    required_action TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    resolution_action TEXT,
                    resolution_reason TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retrieval_logs (
                    id TEXT PRIMARY KEY,
                    query TEXT NOT NULL DEFAULT '',
                    task TEXT,
                    task_type TEXT,
                    scope TEXT,
                    source TEXT NOT NULL,
                    retrieved_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    used_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    skipped_memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    feedback TEXT,
                    feedback_reason TEXT,
                    created_at TEXT NOT NULL,
                    feedback_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maintenance_review_items (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    usage_score REAL NOT NULL DEFAULT 0,
                    retrieved_count INTEGER NOT NULL DEFAULT 0,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    useful_feedback_count INTEGER NOT NULL DEFAULT 0,
                    not_useful_feedback_count INTEGER NOT NULL DEFAULT 0,
                    reasons_json TEXT NOT NULL DEFAULT '[]',
                    required_action TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    resolution_action TEXT,
                    resolution_reason TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY(memory_id) REFERENCES memory_items(id)
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts USING fts5(
                    memory_id UNINDEXED,
                    subject,
                    content,
                    tags
                )
                """
            )
            self._ensure_column(conn, "memory_candidates", "claim", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn, "memory_candidates", "evidence_type", "TEXT NOT NULL DEFAULT 'unknown'"
            )
            self._ensure_column(
                conn, "memory_candidates", "time_validity", "TEXT NOT NULL DEFAULT 'unknown'"
            )
            self._ensure_column(
                conn, "memory_candidates", "reuse_cases_json", "TEXT NOT NULL DEFAULT '[]'"
            )
            self._ensure_column(
                conn, "memory_candidates", "scores_json", "TEXT NOT NULL DEFAULT '{}'"
            )
            self._ensure_column(
                conn, "policy_decisions", "structured_reason_json", "TEXT NOT NULL DEFAULT '{}'"
            )
            self._ensure_column(
                conn, "memory_relations", "source_memory_ids_json", "TEXT NOT NULL DEFAULT '[]'"
            )
            self._ensure_column(
                conn, "memory_relations", "metadata_json", "TEXT NOT NULL DEFAULT '{}'"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidates_status ON memory_candidates(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidates_scope ON memory_candidates(scope)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory_items(scope)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_items(memory_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_items(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_subject ON memory_items(subject)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_embeddings_model "
                "ON memory_embeddings(model)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_name ON memory_entities(name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_scope ON memory_entities(scope)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entity_type ON memory_entities(entity_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_relation_from ON memory_relations(from_memory_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_relation_to ON memory_relations(to_memory_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_relation_type ON memory_relations(relation_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_consolidation_status "
                "ON consolidation_candidates(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_consolidation_scope "
                "ON consolidation_candidates(scope)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_consolidation_type "
                "ON consolidation_candidates(memory_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conflict_review_status "
                "ON conflict_review_items(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conflict_review_scope "
                "ON conflict_review_items(scope)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conflict_review_key "
                "ON conflict_review_items(conflict_key)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_retrieval_logs_source "
                "ON retrieval_logs(source)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_retrieval_logs_scope "
                "ON retrieval_logs(scope)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_retrieval_logs_created "
                "ON retrieval_logs(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_maintenance_review_status "
                "ON maintenance_review_items(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_maintenance_review_memory "
                "ON maintenance_review_items(memory_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_maintenance_review_action "
                "ON maintenance_review_items(recommended_action)"
            )

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def preview_memory_candidates(self, event: EventRead) -> list[MemoryCandidateCreate]:
        if event.sanitized or _contains_any(event.content, SENSITIVE_MARKERS):
            return []

        candidates: list[MemoryCandidateCreate] = []
        content = event.content.strip()

        explicit_type = event.metadata.get("memory_type")
        if explicit_type:
            candidates.append(
                MemoryCandidateCreate(
                    content=content,
                    memory_type=explicit_type,
                    scope=event.scope,
                    subject=_default_subject(event, explicit_type),
                    source_event_ids=[event.id],
                    reason="事件 metadata 显式声明了候选记忆类型。",
                    claim=_candidate_claim(event),
                    evidence_type=event.metadata.get("evidence_type", "unknown"),
                    time_validity=event.metadata.get("time_validity", "unknown"),
                    reuse_cases=event.metadata.get("reuse_cases", []),
                    scores=CandidateScores(**event.metadata.get("scores", {})),
                    confidence=event.metadata.get("confidence", "likely"),
                    risk=event.metadata.get("risk", "low"),
                )
            )
        elif all(cue in content for cue in TROUBLESHOOTING_CUES) and _contains_any(
            content, VERIFIED_CUES
        ):
            candidates.append(
                MemoryCandidateCreate(
                    content=content,
                    memory_type="troubleshooting",
                    scope=event.scope,
                    subject=_default_subject(event, "troubleshooting"),
                    source_event_ids=[event.id],
                    reason="事件包含已验证排错经验结构。",
                    claim=_candidate_claim(event),
                    evidence_type=event.event_type,
                    time_validity="until_changed",
                    reuse_cases=["debugging", "incident_response"],
                    scores=_candidate_scores(
                        long_term=0.9,
                        evidence=0.9,
                        reuse=0.9,
                        risk=0.2,
                        specificity=0.8,
                    ),
                    confidence="confirmed",
                    risk="low",
                )
            )
        elif (
            event.event_type == "user_message"
            and _is_preference_candidate(content)
        ):
            candidates.append(
                MemoryCandidateCreate(
                    content=content,
                    memory_type="user_preference",
                    scope=event.scope,
                    subject=_default_subject(event, "user_preference"),
                    source_event_ids=[event.id],
                    reason="用户消息包含长期偏好线索。",
                    claim=_candidate_claim(event),
                    evidence_type="direct_user_statement",
                    time_validity="persistent",
                    reuse_cases=["style_guidance", "future_responses"],
                    scores=_candidate_scores(
                        long_term=0.9,
                        evidence=1.0,
                        reuse=0.8,
                        risk=0.1,
                        specificity=0.7,
                    ),
                    confidence="confirmed",
                    risk="low",
                )
            )
        elif event.event_type in {"file_observation", "tool_result"} and _contains_any(
            content, VERIFIED_CUES
        ):
            candidates.append(
                MemoryCandidateCreate(
                    content=content,
                    memory_type="project_fact",
                    scope=event.scope,
                    subject=_default_subject(event, "project_fact"),
                    source_event_ids=[event.id],
                    reason="工具或文件观察包含已验证事实线索。",
                    claim=_candidate_claim(event),
                    evidence_type=event.event_type,
                    time_validity="until_changed",
                    reuse_cases=["project_lookup", "setup", "debugging"],
                    scores=_candidate_scores(
                        long_term=0.8,
                        evidence=0.9,
                        reuse=0.8,
                        risk=0.2,
                        specificity=0.8,
                    ),
                    confidence="confirmed",
                    risk="low",
                )
            )

        return candidates

    def propose_memory(self, event: EventRead) -> list[MemoryCandidateRead]:
        return [
            self.create_candidate(candidate)
            for candidate in self.preview_memory_candidates(event)
        ]

    def create_candidate(self, candidate: MemoryCandidateCreate) -> MemoryCandidateRead:
        candidate_id = _new_id("cand")
        created_at = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_candidates (
                    id,
                    content,
                    memory_type,
                    scope,
                    subject,
                    source_event_ids_json,
                    reason,
                    claim,
                    evidence_type,
                    time_validity,
                    reuse_cases_json,
                    scores_json,
                    confidence,
                    risk,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    candidate_id,
                    candidate.content,
                    candidate.memory_type,
                    candidate.scope,
                    candidate.subject,
                    _json_dumps(candidate.source_event_ids),
                    candidate.reason,
                    candidate.claim or candidate.content,
                    candidate.evidence_type,
                    candidate.time_validity,
                    _json_dumps(candidate.reuse_cases),
                    _json_dumps(candidate.scores.model_dump()),
                    candidate.confidence,
                    candidate.risk,
                    created_at.isoformat(),
                ),
            )
        return MemoryCandidateRead(
            id=candidate_id,
            status="pending",
            created_at=created_at,
            **candidate.model_dump(),
        )

    def get_candidate(self, candidate_id: str) -> MemoryCandidateRead | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
        return self._row_to_candidate(row) if row else None

    def list_candidates(
        self,
        *,
        status: CandidateStatus | None = None,
        scope: str | None = None,
        memory_type: MemoryType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryCandidateRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        filters: list[str] = []
        params: list[Any] = []
        if status is not None:
            filters.append("status = ?")
            params.append(status)
        if scope is not None:
            filters.append("scope = ?")
            params.append(scope)
        if memory_type is not None:
            filters.append("memory_type = ?")
            params.append(memory_type)

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_candidates
                {where}
                ORDER BY created_at ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_candidate(row) for row in rows]

    def edit_candidate(self, candidate_id: str, **updates: Any) -> MemoryCandidateRead:
        candidate = self._require_candidate(candidate_id)
        allowed_fields = {
            "content",
            "memory_type",
            "scope",
            "subject",
            "source_event_ids",
            "reason",
            "claim",
            "evidence_type",
            "time_validity",
            "reuse_cases",
            "scores",
            "confidence",
            "risk",
        }
        unknown_fields = set(updates) - allowed_fields
        if unknown_fields:
            unknown = ", ".join(sorted(unknown_fields))
            raise ValueError(f"unsupported candidate update fields: {unknown}")

        data = candidate.model_dump(exclude={"id", "status", "created_at"})
        data.update(updates)
        edited = MemoryCandidateCreate(**data)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_candidates
                SET content = ?,
                    memory_type = ?,
                    scope = ?,
                    subject = ?,
                    source_event_ids_json = ?,
                    reason = ?,
                    claim = ?,
                    evidence_type = ?,
                    time_validity = ?,
                    reuse_cases_json = ?,
                    scores_json = ?,
                    confidence = ?,
                    risk = ?,
                    status = 'pending'
                WHERE id = ?
                """,
                (
                    edited.content,
                    edited.memory_type,
                    edited.scope,
                    edited.subject,
                    _json_dumps(edited.source_event_ids),
                    edited.reason,
                    edited.claim or edited.content,
                    edited.evidence_type,
                    edited.time_validity,
                    _json_dumps(edited.reuse_cases),
                    _json_dumps(edited.scores.model_dump()),
                    edited.confidence,
                    edited.risk,
                    candidate_id,
                ),
            )
        return self._require_candidate(candidate_id)

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        reason: str = "Manually approved candidate for long-term memory.",
    ) -> MemoryItemRead:
        candidate = self._require_candidate(candidate_id)
        decision = self._create_policy_decision(
            candidate_id=candidate.id,
            decision="write",
            reason=reason,
            structured_reason={
                **self._build_structured_reason(candidate, "write", reason),
                "manual_review": "approved",
            },
            matched_memory_ids=[],
            required_action=None,
        )
        return self.commit_memory(candidate.id, decision.id)

    def reject_candidate(
        self,
        candidate_id: str,
        *,
        reason: str = "Manually rejected candidate.",
    ) -> PolicyDecisionRead:
        candidate = self._require_candidate(candidate_id)
        return self._create_policy_decision(
            candidate_id=candidate.id,
            decision="reject",
            reason=reason,
            structured_reason={
                **self._build_structured_reason(candidate, "reject", reason),
                "manual_review": "rejected",
            },
            matched_memory_ids=[],
            required_action=None,
        )

    def evaluate_candidate(self, candidate_id: str) -> PolicyDecisionRead:
        candidate = self._require_candidate(candidate_id)
        matched_duplicates = self._find_duplicate_memories(candidate)
        matched_conflicts = self._find_conflicting_memories(candidate)

        decision: PolicyAction
        reason: str
        required_action: str | None = None
        matched_memory_ids: list[str] = []

        if candidate.risk == "high" or _contains_any(candidate.content, SENSITIVE_MARKERS):
            decision = "reject"
            reason = "候选记忆风险较高或包含脱敏标记，不允许写入长期记忆。"
        elif matched_duplicates:
            decision = "merge"
            reason = "候选记忆与已有长期记忆重复，复用已有记忆。"
            matched_memory_ids = [item.id for item in matched_duplicates]
        elif matched_conflicts:
            decision = "ask_user"
            reason = "候选记忆与同 scope/type/subject 的已有记忆可能冲突。"
            matched_memory_ids = [item.id for item in matched_conflicts]
            required_action = "请确认应替换旧记忆、合并，还是保留为新的适用范围。"
        elif candidate.evidence_type == "unknown" or candidate.scores.evidence < 0.5:
            decision = "ask_user"
            reason = "候选记忆缺少明确证据类型或证据分不足。"
            required_action = "请确认这条候选是否有可靠来源。"
        elif candidate.scores.long_term < 0.5 or candidate.scores.reuse < 0.4:
            decision = "reject"
            reason = "候选记忆长期价值或复用价值不足。"
        elif candidate.memory_type in {
            "user_preference",
            "project_fact",
            "tool_rule",
            "environment_fact",
            "troubleshooting",
            "workflow",
            "decision",
        } and candidate.confidence in {"confirmed", "likely"}:
            decision = "write"
            reason = "候选记忆长期有用、低风险，并且具备足够置信度。"
        elif candidate.confidence in {"inferred", "unknown"}:
            decision = "ask_user"
            reason = "候选记忆置信度不足，需要人工确认后再写入。"
            required_action = "请确认这条信息是否长期有效。"
        else:
            decision = "reject"
            reason = "候选记忆不满足自动写入条件。"

        return self._create_policy_decision(
            candidate_id=candidate.id,
            decision=decision,
            reason=reason,
            structured_reason=self._build_structured_reason(candidate, decision, reason),
            matched_memory_ids=matched_memory_ids,
            required_action=required_action,
        )

    def get_policy_decision(self, decision_id: str) -> PolicyDecisionRead | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM policy_decisions WHERE id = ?", (decision_id,)
            ).fetchone()
        return self._row_to_policy_decision(row) if row else None

    def commit_memory(self, candidate_id: str, decision_id: str) -> MemoryItemRead:
        candidate = self._require_candidate(candidate_id)
        decision = self._require_policy_decision(decision_id)
        if decision.candidate_id != candidate.id:
            raise MemoryPolicyError("decision does not belong to candidate")

        if decision.decision == "merge":
            if not decision.matched_memory_ids:
                raise MemoryPolicyError("merge decision has no matched memory")
            memory = self._require_memory(decision.matched_memory_ids[0])
            self._mark_candidate(candidate.id, "committed")
            return memory

        if decision.decision == "update":
            if not decision.matched_memory_ids:
                raise MemoryPolicyError("update decision has no matched memory")
            for memory_id in decision.matched_memory_ids:
                self._change_memory_status(
                    memory_id,
                    "superseded",
                    change_type="supersede",
                    reason=decision.reason,
                    source_event_ids=candidate.source_event_ids,
                )
            return self._insert_memory_from_candidate(
                candidate,
                change_reason=decision.reason,
                candidate_status="committed",
            )

        if decision.decision != "write":
            raise MemoryPolicyError(f"cannot commit decision '{decision.decision}'")

        return self._insert_memory_from_candidate(
            candidate,
            change_reason=decision.reason,
            candidate_status="committed",
        )

    def add_memory(self, memory: MemoryItemCreate) -> MemoryItemRead:
        candidate = MemoryCandidateRead(
            id=_new_id("manual"),
            content=memory.content,
            memory_type=memory.memory_type,
            scope=memory.scope,
            subject=memory.subject,
            source_event_ids=memory.source_event_ids,
            reason="手动写入长期记忆。",
            confidence=memory.confidence,
            risk="low",
            status="pending",
            created_at=_utc_now(),
        )
        return self._insert_memory(
            content=memory.content,
            memory_type=memory.memory_type,
            scope=memory.scope,
            subject=memory.subject,
            confidence=memory.confidence,
            source_event_ids=memory.source_event_ids,
            tags=memory.tags,
            change_reason="手动写入长期记忆。",
            candidate_status=None,
            candidate_id=candidate.id,
        )

    def get_memory(self, memory_id: str) -> MemoryItemRead | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
        return self._row_to_memory(row) if row else None

    def upsert_memory_embedding(
        self,
        memory_id: str,
        *,
        vector: list[float],
        model: str,
        embedded_text: str | None = None,
    ) -> MemoryEmbeddingRead:
        memory = self._require_memory(memory_id)
        normalized_vector = _normalize_vector_payload(vector)
        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("model must not be empty")
        text = (
            embedded_text.strip()
            if embedded_text and embedded_text.strip()
            else build_memory_embedding_text(memory)
        )
        now = _utc_now()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT created_at FROM memory_embeddings
                WHERE memory_id = ? AND model = ?
                """,
                (memory.id, normalized_model),
            ).fetchone()
            created_at = existing["created_at"] if existing else now.isoformat()
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_embeddings (
                    memory_id,
                    model,
                    vector_json,
                    dimensions,
                    embedded_text,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.id,
                    normalized_model,
                    _json_dumps(normalized_vector),
                    len(normalized_vector),
                    text,
                    created_at,
                    now.isoformat(),
                ),
            )
        embedding = self.get_memory_embedding(memory.id, model=normalized_model)
        if embedding is None:
            raise MemoryNotFoundError(memory.id)
        return embedding

    def get_memory_embedding(
        self,
        memory_id: str,
        *,
        model: str | None = None,
    ) -> MemoryEmbeddingRead | None:
        params: list[Any] = [memory_id]
        where = "memory_id = ?"
        if model is not None:
            where += " AND model = ?"
            params.append(model)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM memory_embeddings
                WHERE {where}
                ORDER BY updated_at DESC, model ASC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._row_to_embedding(row) if row else None

    def list_memory_embeddings(
        self,
        *,
        memory_id: str | None = None,
        model: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryEmbeddingRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")
        filters: list[str] = []
        params: list[Any] = []
        if memory_id is not None:
            filters.append("memory_id = ?")
            params.append(memory_id)
        if model is not None:
            filters.append("model = ?")
            params.append(model)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_embeddings
                {where}
                ORDER BY updated_at DESC, memory_id ASC, model ASC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_embedding(row) for row in rows]

    def list_memories_missing_embedding(
        self,
        *,
        model: str,
        scope: str | None = None,
        memory_type: MemoryType | None = None,
        limit: int = 100,
    ) -> list[MemoryItemRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("model must not be empty")
        filters = ["memory_items.status = 'active'", "memory_embeddings.memory_id IS NULL"]
        params: list[Any] = [normalized_model]
        if scope is not None:
            filters.append("memory_items.scope = ?")
            params.append(scope)
        if memory_type is not None:
            filters.append("memory_items.memory_type = ?")
            params.append(memory_type)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT memory_items.* FROM memory_items
                LEFT JOIN memory_embeddings
                  ON memory_embeddings.memory_id = memory_items.id
                 AND memory_embeddings.model = ?
                WHERE {' AND '.join(filters)}
                ORDER BY memory_items.updated_at DESC, memory_items.id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def list_versions(self, memory_id: str) -> list[MemoryVersionRead]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_versions
                WHERE memory_id = ?
                ORDER BY version ASC
                """,
                (memory_id,),
            ).fetchall()
        return [self._row_to_version(row) for row in rows]

    def upsert_entity(self, entity: MemoryEntityCreate) -> MemoryEntityRead:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM memory_entities
                WHERE scope = ? AND entity_type = ? AND name = ?
                """,
                (entity.scope, entity.entity_type, entity.name),
            ).fetchone()
            if row is None:
                entity_id = _new_id("ent")
                conn.execute(
                    """
                    INSERT INTO memory_entities (
                        id,
                        name,
                        entity_type,
                        scope,
                        aliases_json,
                        metadata_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity_id,
                        entity.name,
                        entity.entity_type,
                        entity.scope,
                        _json_dumps(_unique_ordered(entity.aliases)),
                        _json_dumps(entity.metadata),
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
            else:
                entity_id = row["id"]
                existing_aliases = _json_loads(row["aliases_json"]) or []
                existing_metadata = _json_loads(row["metadata_json"]) or {}
                merged_metadata = {**existing_metadata, **entity.metadata}
                conn.execute(
                    """
                    UPDATE memory_entities
                    SET aliases_json = ?,
                        metadata_json = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _json_dumps(_unique_ordered([*existing_aliases, *entity.aliases])),
                        _json_dumps(merged_metadata),
                        now.isoformat(),
                        entity_id,
                    ),
                )
        loaded = self.get_entity(entity_id)
        if loaded is None:
            raise MemoryNotFoundError(entity_id)
        return loaded

    def get_entity(self, entity_id: str) -> MemoryEntityRead | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_entities WHERE id = ?", (entity_id,)).fetchone()
        return self._row_to_entity(row) if row else None

    def list_entities(
        self,
        *,
        query: str | None = None,
        scope: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryEntityRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        filters: list[str] = []
        params: list[Any] = []
        if query:
            like = _like_pattern(query.strip())
            filters.append("(name LIKE ? ESCAPE '\\' OR aliases_json LIKE ? ESCAPE '\\')")
            params.extend([like, like])
        if scope is not None:
            filters.append("scope = ?")
            params.append(scope)
        if entity_type is not None:
            filters.append("entity_type = ?")
            params.append(entity_type)

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_entities
                {where}
                ORDER BY updated_at DESC, rowid ASC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_entity(row) for row in rows]

    def match_entities_for_text(
        self,
        text: str,
        *,
        scope: str | None = None,
        limit: int = 20,
    ) -> list[MemoryEntityRead]:
        cleaned_text = text.strip().lower()
        if not cleaned_text and not scope:
            return []

        scopes = ["global"]
        if scope and scope.strip() and scope.strip() != "global":
            scopes.insert(0, scope.strip())
        placeholders = ", ".join("?" for _ in scopes)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_entities
                WHERE scope IN ({placeholders})
                ORDER BY scope DESC, updated_at DESC, rowid ASC
                """,
                scopes,
            ).fetchall()

        matched: list[MemoryEntityRead] = []
        scope_markers = {item.lower() for item in scopes}
        for entity in [self._row_to_entity(row) for row in rows]:
            labels = [entity.name, *entity.aliases]
            lowered_labels = [label.lower() for label in labels if label.strip()]
            if any(label in cleaned_text for label in lowered_labels) or any(
                label in scope_markers for label in lowered_labels
            ):
                matched.append(entity)
            if len(matched) >= limit:
                break
        return matched

    def create_relation(self, relation: MemoryRelationCreate) -> MemoryRelationRead:
        relation_id = _new_id("rel")
        created_at = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_relations (
                    id,
                    from_memory_id,
                    relation_type,
                    to_memory_id,
                    confidence,
                    source_event_ids_json,
                    source_memory_ids_json,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relation_id,
                    relation.from_id,
                    relation.relation_type,
                    relation.to_id,
                    relation.confidence,
                    _json_dumps(relation.source_event_ids),
                    _json_dumps(relation.source_memory_ids),
                    _json_dumps(relation.metadata),
                    created_at.isoformat(),
                ),
            )
        return MemoryRelationRead(id=relation_id, created_at=created_at, **relation.model_dump())

    def get_relation(self, relation_id: str) -> MemoryRelationRead | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_relations WHERE id = ?",
                (relation_id,),
            ).fetchone()
        return self._row_to_relation(row) if row else None

    def list_relations(
        self,
        *,
        from_id: str | None = None,
        to_id: str | None = None,
        connected_to_id: str | None = None,
        relation_type: str | None = None,
        confidence: Confidence | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRelationRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        filters: list[str] = []
        params: list[Any] = []
        if from_id is not None:
            filters.append("from_memory_id = ?")
            params.append(from_id)
        if to_id is not None:
            filters.append("to_memory_id = ?")
            params.append(to_id)
        if connected_to_id is not None:
            filters.append("(from_memory_id = ? OR to_memory_id = ?)")
            params.extend([connected_to_id, connected_to_id])
        if relation_type is not None:
            filters.append("relation_type = ?")
            params.append(relation_type)
        if confidence is not None:
            filters.append("confidence = ?")
            params.append(confidence)

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_relations
                {where}
                ORDER BY created_at ASC, rowid ASC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_relation(row) for row in rows]

    def detect_graph_conflicts(
        self,
        *,
        scope: str | None = None,
        relation_type: str | None = None,
        limit: int = 100,
    ) -> list[GraphConflictRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")

        filters = ["confidence IN (?, ?)"]
        params: list[Any] = ["confirmed", "likely"]
        if relation_type is not None:
            filters.append("relation_type = ?")
            params.append(relation_type)

        where = " AND ".join(filters)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_relations
                WHERE {where}
                ORDER BY created_at ASC, rowid ASC
                """,
                params,
            ).fetchall()

        scope_filter = scope.strip() if scope and scope.strip() else None
        grouped: dict[tuple[str, str], list[tuple[MemoryRelationRead, list[MemoryItemRead]]]] = {}
        for row in rows:
            relation = self._row_to_relation(row)
            from_entity = self.get_entity(relation.from_id)
            target_entity = self.get_entity(relation.to_id)
            if from_entity is None or target_entity is None:
                continue
            if scope_filter is not None and from_entity.scope != scope_filter:
                continue

            active_memories = self._active_relation_memories(relation, scope=scope_filter)
            if not active_memories:
                continue
            grouped.setdefault((relation.from_id, relation.relation_type), []).append(
                (relation, active_memories)
            )

        conflicts: list[GraphConflictRead] = []
        for (from_id, group_relation_type), relation_group in grouped.items():
            target_ids = _unique_ordered([relation.to_id for relation, _ in relation_group])
            if len(target_ids) < 2:
                continue

            from_entity = self.get_entity(from_id)
            if from_entity is None:
                continue
            target_entities = [
                entity
                for target_id in target_ids
                if (entity := self.get_entity(target_id)) is not None
            ]
            relation_items = [relation for relation, _ in relation_group]
            memories = self._unique_memories(
                [memory for _, active_memories in relation_group for memory in active_memories]
            )
            conflict = GraphConflictRead(
                conflict_key=f"{from_id}:{group_relation_type}",
                scope=from_entity.scope,
                relation_type=group_relation_type,
                from_entity=from_entity,
                target_entities=target_entities,
                relations=relation_items,
                memories=memories,
                reason=(
                    f"Entity '{from_entity.name}' has relation '{group_relation_type}' "
                    f"pointing to {len(target_entities)} different targets."
                ),
            )
            conflicts.append(conflict)
            if len(conflicts) >= limit:
                break

        return conflicts

    def create_conflict_reviews(
        self,
        *,
        scope: str | None = None,
        relation_type: str | None = None,
        limit: int = 100,
    ) -> list[ConflictReviewItemRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")

        reviews: list[ConflictReviewItemRead] = []
        for conflict in self.detect_graph_conflicts(
            scope=scope,
            relation_type=relation_type,
            limit=limit,
        ):
            relation_ids = [relation.id for relation in conflict.relations]
            if self._has_blocking_conflict_review(conflict.conflict_key, relation_ids):
                continue
            review = self.create_conflict_review(
                self._build_conflict_review_candidate(conflict)
            )
            reviews.append(review)
            if len(reviews) >= limit:
                break
        return reviews

    def create_conflict_review(
        self,
        review: ConflictReviewItemCreate,
    ) -> ConflictReviewItemRead:
        review_id = _new_id("conf")
        created_at = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conflict_review_items (
                    id,
                    conflict_key,
                    scope,
                    relation_type,
                    from_entity_id,
                    target_entity_ids_json,
                    relation_ids_json,
                    memory_ids_json,
                    recommended_action,
                    recommended_keep_memory_ids_json,
                    reason,
                    required_action,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    review_id,
                    review.conflict_key,
                    review.scope,
                    review.relation_type,
                    review.from_entity_id,
                    _json_dumps(review.target_entity_ids),
                    _json_dumps(review.relation_ids),
                    _json_dumps(review.memory_ids),
                    review.recommended_action,
                    _json_dumps(review.recommended_keep_memory_ids),
                    review.reason,
                    review.required_action,
                    created_at.isoformat(),
                ),
            )
        return ConflictReviewItemRead(
            id=review_id,
            status="pending",
            created_at=created_at,
            **review.model_dump(),
        )

    def get_conflict_review(self, review_id: str) -> ConflictReviewItemRead | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conflict_review_items WHERE id = ?",
                (review_id,),
            ).fetchone()
        return self._row_to_conflict_review(row) if row else None

    def list_conflict_reviews(
        self,
        *,
        status: ConflictReviewStatus | None = None,
        scope: str | None = None,
        relation_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ConflictReviewItemRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        filters: list[str] = []
        params: list[Any] = []
        if status is not None:
            filters.append("status = ?")
            params.append(status)
        if scope is not None:
            filters.append("scope = ?")
            params.append(scope)
        if relation_type is not None:
            filters.append("relation_type = ?")
            params.append(relation_type)

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM conflict_review_items
                {where}
                ORDER BY created_at ASC, rowid ASC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_conflict_review(row) for row in rows]

    def resolve_conflict_review(
        self,
        review_id: str,
        *,
        action: ConflictReviewAction,
        keep_memory_ids: list[str] | None = None,
        reason: str | None = None,
    ) -> ConflictReviewItemRead:
        review = self._require_conflict_review(review_id)
        if review.status != "pending":
            raise MemoryPolicyError("only pending conflict reviews can be resolved")

        resolution_reason = reason or f"Resolved conflict review with action={action}."
        if action == "ask_user":
            self._mark_conflict_review(
                review.id,
                "needs_user",
                resolution_action=action,
                resolution_reason=resolution_reason,
            )
            return self._require_conflict_review(review.id)

        if action == "archive_all":
            for memory_id in review.memory_ids:
                memory = self._require_memory(memory_id)
                if memory.status != "archived":
                    self.archive_memory(memory.id, resolution_reason)
            self._mark_conflict_review(
                review.id,
                "resolved",
                resolution_action=action,
                resolution_reason=resolution_reason,
            )
            return self._require_conflict_review(review.id)

        if action == "keep_both_scoped":
            self._mark_conflict_review(
                review.id,
                "resolved",
                resolution_action=action,
                resolution_reason=resolution_reason,
            )
            return self._require_conflict_review(review.id)

        resolved_keep_ids = self._resolve_keep_memory_ids(review, action, keep_memory_ids)
        for memory_id in review.memory_ids:
            memory = self._require_memory(memory_id)
            if memory.id in resolved_keep_ids or memory.status != "active":
                continue
            self._change_memory_status(
                memory.id,
                "superseded",
                change_type="supersede",
                reason=resolution_reason,
                source_event_ids=self._resolution_source_event_ids(resolved_keep_ids),
            )

        self._mark_conflict_review(
            review.id,
            "resolved",
            resolution_action=action,
            resolution_reason=resolution_reason,
        )
        return self._require_conflict_review(review.id)

    def propose_consolidations(
        self,
        *,
        scope: str | None = None,
        memory_type: MemoryType | None = None,
        min_group_size: int = 2,
        limit: int = 20,
    ) -> list[ConsolidationCandidateRead]:
        if min_group_size < 2:
            raise ValueError("min_group_size must be at least two")
        if limit < 1:
            raise ValueError("limit must be greater than zero")

        filters = [
            "status = 'active'",
            "confidence IN (?, ?)",
        ]
        params: list[Any] = list(CONSOLIDATION_CONFIDENCES)
        if scope is not None:
            filters.append("scope = ?")
            params.append(scope)
        if memory_type is not None:
            filters.append("memory_type = ?")
            params.append(memory_type)

        where = " AND ".join(filters)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_items
                WHERE {where}
                ORDER BY scope ASC, memory_type ASC, subject ASC, rowid ASC
                """,
                params,
            ).fetchall()

        groups: dict[tuple[str, str, str], list[MemoryItemRead]] = {}
        for memory in [self._row_to_memory(row) for row in rows]:
            key = (memory.scope, memory.memory_type, memory.subject)
            groups.setdefault(key, []).append(memory)

        candidates: list[ConsolidationCandidateRead] = []
        for group in groups.values():
            if len(group) < min_group_size:
                continue
            source_memory_ids = [memory.id for memory in group]
            if self._has_pending_consolidation(source_memory_ids):
                continue

            first = group[0]
            confidence: Confidence = (
                "confirmed"
                if all(memory.confidence == "confirmed" for memory in group)
                else "likely"
            )
            tags = sorted(
                {tag for memory in group for tag in memory.tags}
                | {"consolidated"}
            )
            candidate = self.create_consolidation_candidate(
                ConsolidationCandidateCreate(
                    source_memory_ids=source_memory_ids,
                    proposed_content=self._build_consolidated_content(group),
                    memory_type=first.memory_type,
                    scope=first.scope,
                    subject=first.subject,
                    reason=(
                        f"Consolidates {len(group)} active memories with the same "
                        "scope, type, and subject."
                    ),
                    confidence=confidence,
                    tags=tags,
                )
            )
            candidates.append(candidate)
            if len(candidates) >= limit:
                break

        return candidates

    def create_consolidation_candidate(
        self,
        candidate: ConsolidationCandidateCreate,
    ) -> ConsolidationCandidateRead:
        candidate_id = _new_id("cons")
        created_at = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO consolidation_candidates (
                    id,
                    source_memory_ids_json,
                    proposed_content,
                    memory_type,
                    scope,
                    subject,
                    reason,
                    confidence,
                    tags_json,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    candidate_id,
                    _json_dumps(candidate.source_memory_ids),
                    candidate.proposed_content,
                    candidate.memory_type,
                    candidate.scope,
                    candidate.subject,
                    candidate.reason,
                    candidate.confidence,
                    _json_dumps(candidate.tags),
                    created_at.isoformat(),
                ),
            )
        return ConsolidationCandidateRead(
            id=candidate_id,
            status="pending",
            created_at=created_at,
            **candidate.model_dump(),
        )

    def get_consolidation_candidate(
        self,
        candidate_id: str,
    ) -> ConsolidationCandidateRead | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM consolidation_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        return self._row_to_consolidation_candidate(row) if row else None

    def list_consolidation_candidates(
        self,
        *,
        status: ConsolidationStatus | None = None,
        scope: str | None = None,
        memory_type: MemoryType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ConsolidationCandidateRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        filters: list[str] = []
        params: list[Any] = []
        if status is not None:
            filters.append("status = ?")
            params.append(status)
        if scope is not None:
            filters.append("scope = ?")
            params.append(scope)
        if memory_type is not None:
            filters.append("memory_type = ?")
            params.append(memory_type)

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM consolidation_candidates
                {where}
                ORDER BY created_at ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_consolidation_candidate(row) for row in rows]

    def commit_consolidation(
        self,
        candidate_id: str,
        *,
        reason: str | None = None,
    ) -> MemoryItemRead:
        candidate = self._require_consolidation_candidate(candidate_id)
        if candidate.status != "pending":
            raise MemoryPolicyError("only pending consolidation candidates can be committed")

        source_memories = [self._require_memory(memory_id) for memory_id in candidate.source_memory_ids]
        for memory in source_memories:
            if memory.status != "active":
                raise MemoryPolicyError("only active memories can be consolidated")
            if (
                memory.memory_type != candidate.memory_type
                or memory.scope != candidate.scope
                or memory.subject != candidate.subject
            ):
                raise MemoryPolicyError(
                    "source memories must match the consolidation type, scope, and subject"
                )

        change_reason = reason or candidate.reason
        source_event_ids = _unique_ordered(
            [
                event_id
                for memory in source_memories
                for event_id in memory.source_event_ids
            ]
        )
        new_memory = self._insert_memory(
            content=candidate.proposed_content,
            memory_type=candidate.memory_type,
            scope=candidate.scope,
            subject=candidate.subject,
            confidence=candidate.confidence,
            source_event_ids=source_event_ids,
            tags=candidate.tags,
            change_reason=change_reason,
            candidate_status=None,
            candidate_id=candidate.id,
        )
        for memory in source_memories:
            self._change_memory_status(
                memory.id,
                "superseded",
                change_type="supersede",
                reason=change_reason,
                source_event_ids=source_event_ids,
            )
        self._mark_consolidation_candidate(candidate.id, "committed")
        return new_memory

    def reject_consolidation(
        self,
        candidate_id: str,
        *,
        reason: str | None = None,
    ) -> ConsolidationCandidateRead:
        candidate = self._require_consolidation_candidate(candidate_id)
        if candidate.status != "pending":
            raise MemoryPolicyError("only pending consolidation candidates can be rejected")
        self._mark_consolidation_candidate(candidate.id, "rejected")
        updated = self.get_consolidation_candidate(candidate.id)
        if updated is None:
            raise MemoryNotFoundError(candidate.id)
        return updated

    def search_memory(
        self,
        input: SearchMemoryInput,
        *,
        log: bool = True,
        source: RetrievalSource = "search",
        task: str | None = None,
        task_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[MemoryItemRead]:
        query = input.query.strip()
        semantic_enabled = input.retrieval_mode in {"semantic", "hybrid"} and bool(
            input.query_embedding
        )
        semantic_scores = (
            self._semantic_memory_scores(
                input.query_embedding,
                model=input.embedding_model,
            )
            if semantic_enabled
            else {}
        )
        fts_ids = self._fts_memory_ids(query) if query else set()
        filters = ["status = 'active'"]
        params: list[Any] = []

        if input.memory_types:
            placeholders = ", ".join("?" for _ in input.memory_types)
            filters.append(f"memory_type IN ({placeholders})")
            params.extend(input.memory_types)

        if input.scopes:
            placeholders = ", ".join("?" for _ in input.scopes)
            filters.append(f"scope IN ({placeholders})")
            params.extend(input.scopes)

        if semantic_enabled and input.retrieval_mode == "semantic":
            if semantic_scores:
                filters.append("id IN (" + ", ".join("?" for _ in semantic_scores) + ")")
                params.extend(sorted(semantic_scores))
            else:
                filters.append("0 = 1")

        keyword_required = bool(query) and (input.retrieval_mode == "keyword" or not semantic_enabled)
        if keyword_required:
            like = _like_pattern(query)
            filters.append(
                "(content LIKE ? ESCAPE '\\' OR subject LIKE ? ESCAPE '\\' OR tags_json LIKE ? ESCAPE '\\'"
                + (" OR id IN (" + ", ".join("?" for _ in fts_ids) + ")" if fts_ids else "")
                + ")"
            )
            params.extend([like, like, like])
            params.extend(sorted(fts_ids))

        where = " AND ".join(filters)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_items
                WHERE {where}
                """,
                params,
            ).fetchall()

        memories = [self._row_to_memory(row) for row in rows]
        scored = [
            (self._score_memory(memory, input, fts_ids, semantic_scores), memory)
            for memory in memories
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        limited = [memory for _, memory in scored[: input.limit]]
        self._mark_used(limited)
        if log:
            memory_ids = [memory.id for memory in limited]
            self.record_retrieval_log(
                RetrievalLogCreate(
                    query=input.query,
                    task=task,
                    task_type=task_type or input.task_type,
                    scope=input.scopes[0] if len(input.scopes) == 1 else None,
                    source=source,
                    retrieved_memory_ids=memory_ids,
                    used_memory_ids=memory_ids,
                    metadata={
                        "memory_types": input.memory_types,
                        "scopes": input.scopes,
                        "limit": input.limit,
                        "retrieval_mode": input.retrieval_mode,
                        "semantic_enabled": semantic_enabled,
                        "embedding_model": input.embedding_model,
                        **(metadata or {}),
                    },
                )
            )
        return limited

    def record_retrieval_log(self, log: RetrievalLogCreate) -> RetrievalLogRead:
        log_id = _new_id("ret")
        created_at = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO retrieval_logs (
                    id,
                    query,
                    task,
                    task_type,
                    scope,
                    source,
                    retrieved_memory_ids_json,
                    used_memory_ids_json,
                    skipped_memory_ids_json,
                    warnings_json,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log_id,
                    log.query,
                    log.task,
                    log.task_type,
                    log.scope,
                    log.source,
                    _json_dumps(_unique_ordered(log.retrieved_memory_ids)),
                    _json_dumps(_unique_ordered(log.used_memory_ids)),
                    _json_dumps(_unique_ordered(log.skipped_memory_ids)),
                    _json_dumps(log.warnings),
                    _json_dumps(log.metadata),
                    created_at.isoformat(),
                ),
            )
        return RetrievalLogRead(id=log_id, created_at=created_at, **log.model_dump())

    def get_retrieval_log(self, log_id: str) -> RetrievalLogRead | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM retrieval_logs WHERE id = ?",
                (log_id,),
            ).fetchone()
        return self._row_to_retrieval_log(row) if row else None

    def list_retrieval_logs(
        self,
        *,
        source: RetrievalSource | None = None,
        scope: str | None = None,
        task_type: str | None = None,
        memory_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RetrievalLogRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        filters: list[str] = []
        params: list[Any] = []
        if source is not None:
            filters.append("source = ?")
            params.append(source)
        if scope is not None:
            filters.append("scope = ?")
            params.append(scope)
        if task_type is not None:
            filters.append("task_type = ?")
            params.append(task_type)
        if memory_id is not None:
            memory_match = f'%"{memory_id}"%'
            filters.append(
                """
                (
                    retrieved_memory_ids_json LIKE ?
                    OR used_memory_ids_json LIKE ?
                    OR skipped_memory_ids_json LIKE ?
                )
                """
            )
            params.extend([memory_match, memory_match, memory_match])

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM retrieval_logs
                {where}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_retrieval_log(row) for row in rows]

    def add_retrieval_feedback(
        self,
        log_id: str,
        *,
        feedback: RetrievalFeedback,
        reason: str | None = None,
    ) -> RetrievalLogRead:
        self._require_retrieval_log(log_id)
        feedback_at = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE retrieval_logs
                SET feedback = ?,
                    feedback_reason = ?,
                    feedback_at = ?
                WHERE id = ?
                """,
                (feedback, reason.strip() if reason else None, feedback_at.isoformat(), log_id),
            )
        return self._require_retrieval_log(log_id)

    def get_memory_usage_stats(self, memory_id: str) -> MemoryUsageStatsRead:
        memory = self._require_memory(memory_id)
        return self._build_memory_usage_stats(memory)

    def list_memory_usage_stats(
        self,
        *,
        scope: str | None = None,
        memory_type: MemoryType | None = None,
        status: MemoryStatus | None = "active",
        recommended_action: MemoryMaintenanceAction | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryUsageStatsRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        filters: list[str] = []
        params: list[Any] = []
        if scope is not None:
            filters.append("scope = ?")
            params.append(scope)
        if memory_type is not None:
            filters.append("memory_type = ?")
            params.append(memory_type)
        if status is not None:
            filters.append("status = ?")
            params.append(status)

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_items
                {where}
                ORDER BY updated_at DESC, rowid DESC
                """,
                params,
            ).fetchall()

        stats = [self._build_memory_usage_stats(self._row_to_memory(row)) for row in rows]
        if recommended_action is not None:
            stats = [
                item for item in stats if item.recommended_action == recommended_action
            ]
        return stats[offset : offset + limit]

    def create_maintenance_reviews(
        self,
        *,
        scope: str | None = None,
        memory_type: MemoryType | None = None,
        recommended_action: MemoryMaintenanceAction | None = None,
        limit: int = 100,
    ) -> list[MaintenanceReviewItemRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")

        stats = self.list_memory_usage_stats(
            scope=scope,
            memory_type=memory_type,
            status=None,
            recommended_action=recommended_action,
            limit=10000,
        )
        reviews: list[MaintenanceReviewItemRead] = []
        for item in stats:
            if item.recommended_action == "keep":
                continue
            if self._has_blocking_maintenance_review(item.memory_id, item.recommended_action):
                continue
            reviews.append(
                self.create_maintenance_review(
                    self._build_maintenance_review_candidate(item)
                )
            )
            if len(reviews) >= limit:
                break
        return reviews

    def create_maintenance_review(
        self,
        review: MaintenanceReviewItemCreate,
    ) -> MaintenanceReviewItemRead:
        self._require_memory(review.memory_id)
        review_id = _new_id("maint")
        created_at = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO maintenance_review_items (
                    id,
                    memory_id,
                    recommended_action,
                    usage_score,
                    retrieved_count,
                    used_count,
                    skipped_count,
                    useful_feedback_count,
                    not_useful_feedback_count,
                    reasons_json,
                    required_action,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    review_id,
                    review.memory_id,
                    review.recommended_action,
                    review.usage_score,
                    review.retrieved_count,
                    review.used_count,
                    review.skipped_count,
                    review.useful_feedback_count,
                    review.not_useful_feedback_count,
                    _json_dumps(review.reasons),
                    review.required_action,
                    created_at.isoformat(),
                ),
            )
        return MaintenanceReviewItemRead(
            id=review_id,
            status="pending",
            created_at=created_at,
            **review.model_dump(),
        )

    def get_maintenance_review(
        self,
        review_id: str,
    ) -> MaintenanceReviewItemRead | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM maintenance_review_items WHERE id = ?",
                (review_id,),
            ).fetchone()
        return self._row_to_maintenance_review(row) if row else None

    def list_maintenance_reviews(
        self,
        *,
        status: MaintenanceReviewStatus | None = None,
        recommended_action: MemoryMaintenanceAction | None = None,
        memory_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MaintenanceReviewItemRead]:
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        filters: list[str] = []
        params: list[Any] = []
        if status is not None:
            filters.append("status = ?")
            params.append(status)
        if recommended_action is not None:
            filters.append("recommended_action = ?")
            params.append(recommended_action)
        if memory_id is not None:
            filters.append("memory_id = ?")
            params.append(memory_id)

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM maintenance_review_items
                {where}
                ORDER BY created_at ASC, rowid ASC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_maintenance_review(row) for row in rows]

    def resolve_maintenance_review(
        self,
        review_id: str,
        *,
        action: MemoryMaintenanceAction,
        reason: str | None = None,
    ) -> MaintenanceReviewItemRead:
        review = self._require_maintenance_review(review_id)
        if review.status != "pending":
            raise MemoryPolicyError("only pending maintenance reviews can be resolved")

        resolution_reason = reason or f"Resolved maintenance review with action={action}."
        memory = self._require_memory(review.memory_id)

        if action == "review":
            self._mark_maintenance_review(
                review.id,
                "needs_user",
                resolution_action=action,
                resolution_reason=resolution_reason,
            )
            return self._require_maintenance_review(review.id)

        if action == "keep":
            self._mark_maintenance_review(
                review.id,
                "dismissed",
                resolution_action=action,
                resolution_reason=resolution_reason,
            )
            return self._require_maintenance_review(review.id)

        if action == "mark_stale":
            if memory.status == "active":
                self.mark_stale(memory.id, resolution_reason)
            elif memory.status != "stale":
                raise MemoryPolicyError("only active or already stale memories can be marked stale")
            self._mark_maintenance_review(
                review.id,
                "resolved",
                resolution_action=action,
                resolution_reason=resolution_reason,
            )
            return self._require_maintenance_review(review.id)

        if action == "archive":
            if memory.status == "archived":
                raise MemoryPolicyError("memory is already archived")
            self.archive_memory(memory.id, resolution_reason)
            self._mark_maintenance_review(
                review.id,
                "resolved",
                resolution_action=action,
                resolution_reason=resolution_reason,
            )
            return self._require_maintenance_review(review.id)

        raise MemoryPolicyError(f"unsupported maintenance action: {action}")

    def _insert_memory_from_candidate(
        self,
        candidate: MemoryCandidateRead,
        *,
        change_reason: str,
        candidate_status: CandidateStatus,
    ) -> MemoryItemRead:
        return self._insert_memory(
            content=candidate.content,
            memory_type=candidate.memory_type,
            scope=candidate.scope,
            subject=candidate.subject,
            confidence=candidate.confidence,
            source_event_ids=candidate.source_event_ids,
            tags=candidate.reuse_cases,
            change_reason=change_reason,
            candidate_status=candidate_status,
            candidate_id=candidate.id,
        )

    def _insert_memory(
        self,
        *,
        content: str,
        memory_type: MemoryType,
        scope: str,
        subject: str,
        confidence: Confidence,
        source_event_ids: list[str],
        tags: list[str],
        change_reason: str,
        candidate_status: CandidateStatus | None,
        candidate_id: str,
    ) -> MemoryItemRead:
        memory_id = _new_id("mem")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_items (
                    id,
                    content,
                    memory_type,
                    scope,
                    subject,
                    status,
                    confidence,
                    source_event_ids_json,
                    tags_json,
                    created_at,
                    updated_at,
                    last_verified_at
                )
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    content,
                    memory_type,
                    scope,
                    subject,
                    confidence,
                    _json_dumps(source_event_ids),
                    _json_dumps(tags),
                    now.isoformat(),
                    now.isoformat(),
                    now.isoformat() if confidence == "confirmed" else None,
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_versions (
                    id,
                    memory_id,
                    version,
                    content,
                    change_type,
                    change_reason,
                    source_event_ids_json,
                    created_at
                )
                VALUES (?, ?, 1, ?, 'create', ?, ?, ?)
                """,
                (
                    _new_id("ver"),
                    memory_id,
                    content,
                    change_reason,
                    _json_dumps(source_event_ids),
                    now.isoformat(),
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_items_fts (memory_id, subject, content, tags)
                VALUES (?, ?, ?, ?)
                """,
                (memory_id, subject, content, " ".join(tags)),
            )
            if candidate_status is not None:
                conn.execute(
                    "UPDATE memory_candidates SET status = ? WHERE id = ?",
                    (candidate_status, candidate_id),
                )
        memory = self.get_memory(memory_id)
        if memory is None:
            raise MemoryNotFoundError(memory_id)
        return memory

    def mark_stale(self, memory_id: str, reason: str) -> MemoryItemRead:
        memory = self._require_memory(memory_id)
        if memory.status != "active":
            raise MemoryPolicyError("only active memories can be marked stale")
        return self._change_memory_status(
            memory.id,
            "stale",
            change_type="stale",
            reason=reason,
            source_event_ids=memory.source_event_ids,
        )

    def archive_memory(self, memory_id: str, reason: str) -> MemoryItemRead:
        memory = self._require_memory(memory_id)
        if memory.status == "archived":
            raise MemoryPolicyError("memory is already archived")
        return self._change_memory_status(
            memory.id,
            "archived",
            change_type="archive",
            reason=reason,
            source_event_ids=memory.source_event_ids,
        )

    def supersede_memory(
        self,
        old_memory_id: str,
        candidate_id: str,
        reason: str,
    ) -> MemoryItemRead:
        old_memory = self._require_memory(old_memory_id)
        if old_memory.status not in {"active", "stale"}:
            raise MemoryPolicyError("only active or stale memories can be superseded")
        candidate = self._require_candidate(candidate_id)
        if candidate.status != "pending":
            raise MemoryPolicyError("only pending candidates can supersede a memory")
        if (
            candidate.memory_type != old_memory.memory_type
            or candidate.scope != old_memory.scope
            or candidate.subject != old_memory.subject
        ):
            raise MemoryPolicyError("candidate must match the memory type, scope, and subject")

        self._change_memory_status(
            old_memory.id,
            "superseded",
            change_type="supersede",
            reason=reason,
            source_event_ids=candidate.source_event_ids,
        )
        return self._insert_memory_from_candidate(
            candidate,
            change_reason=reason,
            candidate_status="committed",
        )

    @staticmethod
    def _build_structured_reason(
        candidate: MemoryCandidateRead, decision: PolicyAction, reason: str
    ) -> dict[str, str]:
        return {
            "decision": decision,
            "decision_basis": reason,
            "long_term_value": f"{candidate.scores.long_term:.2f}",
            "evidence": f"{candidate.evidence_type}:{candidate.scores.evidence:.2f}",
            "reuse": f"{','.join(candidate.reuse_cases) or 'none'}:{candidate.scores.reuse:.2f}",
            "risk": f"{candidate.risk}:{candidate.scores.risk:.2f}",
            "specificity": f"{candidate.scores.specificity:.2f}",
            "time_validity": candidate.time_validity,
        }

    def _create_policy_decision(
        self,
        *,
        candidate_id: str,
        decision: PolicyAction,
        reason: str,
        structured_reason: dict[str, str],
        matched_memory_ids: list[str],
        required_action: str | None,
    ) -> PolicyDecisionRead:
        decision_id = _new_id("dec")
        created_at = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO policy_decisions (
                    id,
                    candidate_id,
                    decision,
                    reason,
                    structured_reason_json,
                    matched_memory_ids_json,
                    required_action,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    candidate_id,
                    decision,
                    reason,
                    _json_dumps(structured_reason),
                    _json_dumps(matched_memory_ids),
                    required_action,
                    created_at.isoformat(),
                ),
            )
            if decision == "reject":
                conn.execute(
                    "UPDATE memory_candidates SET status = 'rejected' WHERE id = ?",
                    (candidate_id,),
                )
        return PolicyDecisionRead(
            id=decision_id,
            candidate_id=candidate_id,
            decision=decision,
            reason=reason,
            structured_reason=structured_reason,
            matched_memory_ids=matched_memory_ids,
            required_action=required_action,
            created_at=created_at,
        )

    def _find_duplicate_memories(self, candidate: MemoryCandidateRead) -> list[MemoryItemRead]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_items
                WHERE status = 'active'
                  AND memory_type = ?
                  AND scope = ?
                  AND subject = ?
                  AND content = ?
                """,
                (candidate.memory_type, candidate.scope, candidate.subject, candidate.content),
            ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def _find_conflicting_memories(self, candidate: MemoryCandidateRead) -> list[MemoryItemRead]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_items
                WHERE status = 'active'
                  AND memory_type = ?
                  AND scope = ?
                  AND subject = ?
                  AND content != ?
                """,
                (candidate.memory_type, candidate.scope, candidate.subject, candidate.content),
            ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def _fts_memory_ids(self, query: str) -> set[str]:
        fts_query = _make_fts_query(query)
        if not fts_query:
            return set()
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT memory_id FROM memory_items_fts
                    WHERE memory_items_fts MATCH ?
                    """,
                    (fts_query,),
                ).fetchall()
        except sqlite3.OperationalError:
            return set()
        return {row["memory_id"] for row in rows}

    def _semantic_memory_scores(
        self,
        query_embedding: list[float],
        *,
        model: str | None = None,
    ) -> dict[str, float]:
        query_vector = _normalize_vector_payload(query_embedding)
        params: list[Any] = []
        where = ""
        if model is not None:
            where = "WHERE model = ?"
            params.append(model)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT memory_id, vector_json FROM memory_embeddings
                {where}
                """,
                params,
            ).fetchall()

        scores: dict[str, float] = {}
        for row in rows:
            vector = _json_loads(row["vector_json"]) or []
            if len(vector) != len(query_vector):
                continue
            score = _cosine_similarity(query_vector, [float(item) for item in vector])
            memory_id = row["memory_id"]
            scores[memory_id] = max(score, scores.get(memory_id, -1.0))
        return scores

    @staticmethod
    def _score_memory(
        memory: MemoryItemRead,
        input: SearchMemoryInput,
        fts_ids: set[str],
        semantic_scores: dict[str, float] | None = None,
    ) -> tuple[float, str]:
        score = 0.0
        query = input.query.strip()
        if memory.id in fts_ids:
            score += 20
        if query and (query in memory.content or query in memory.subject):
            score += 30
        if semantic_scores and memory.id in semantic_scores:
            semantic_score = max(0.0, semantic_scores[memory.id])
            score += semantic_score * (80 if input.retrieval_mode == "semantic" else 45)
        if input.scopes and memory.scope in input.scopes:
            score += 10 + max(0, len(input.scopes) - input.scopes.index(memory.scope))
        if input.memory_types and memory.memory_type in input.memory_types:
            score += 5
        if memory.confidence == "confirmed":
            score += 5
        elif memory.confidence == "likely":
            score += 3
        return score, memory.updated_at.isoformat()

    def _mark_used(self, memories: list[MemoryItemRead]) -> None:
        if not memories:
            return
        now = _utc_now().isoformat()
        with self._connect() as conn:
            conn.executemany(
                "UPDATE memory_items SET last_used_at = ? WHERE id = ?",
                [(now, memory.id) for memory in memories],
            )

    def _mark_candidate(self, candidate_id: str, status: CandidateStatus) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE memory_candidates SET status = ? WHERE id = ?", (status, candidate_id))

    def _mark_consolidation_candidate(
        self,
        candidate_id: str,
        status: ConsolidationStatus,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE consolidation_candidates SET status = ? WHERE id = ?",
                (status, candidate_id),
            )

    def _change_memory_status(
        self,
        memory_id: str,
        status: MemoryStatus,
        *,
        change_type: VersionChangeType,
        reason: str,
        source_event_ids: list[str],
    ) -> MemoryItemRead:
        memory = self._require_memory(memory_id)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_items
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now.isoformat(), memory.id),
            )
            self._append_memory_version(
                conn,
                memory_id=memory.id,
                content=memory.content,
                change_type=change_type,
                change_reason=reason,
                source_event_ids=source_event_ids,
                created_at=now,
            )

        updated = self.get_memory(memory.id)
        if updated is None:
            raise MemoryNotFoundError(memory.id)
        return updated

    def _append_memory_version(
        self,
        conn: sqlite3.Connection,
        *,
        memory_id: str,
        content: str,
        change_type: VersionChangeType,
        change_reason: str,
        source_event_ids: list[str],
        created_at: datetime,
    ) -> None:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM memory_versions WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        next_version = int(row["next_version"])
        conn.execute(
            """
            INSERT INTO memory_versions (
                id,
                memory_id,
                version,
                content,
                change_type,
                change_reason,
                source_event_ids_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id("ver"),
                memory_id,
                next_version,
                content,
                change_type,
                change_reason,
                _json_dumps(source_event_ids),
                created_at.isoformat(),
            ),
        )

    def _update_memory_status(self, memory_id: str, status: MemoryStatus) -> None:
        now = _utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_items
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now, memory_id),
            )

    def _require_candidate(self, candidate_id: str) -> MemoryCandidateRead:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise MemoryNotFoundError(candidate_id)
        return candidate

    def _require_policy_decision(self, decision_id: str) -> PolicyDecisionRead:
        decision = self.get_policy_decision(decision_id)
        if decision is None:
            raise MemoryNotFoundError(decision_id)
        return decision

    def _require_memory(self, memory_id: str) -> MemoryItemRead:
        memory = self.get_memory(memory_id)
        if memory is None:
            raise MemoryNotFoundError(memory_id)
        return memory

    def _require_consolidation_candidate(
        self,
        candidate_id: str,
    ) -> ConsolidationCandidateRead:
        candidate = self.get_consolidation_candidate(candidate_id)
        if candidate is None:
            raise MemoryNotFoundError(candidate_id)
        return candidate

    def _require_conflict_review(self, review_id: str) -> ConflictReviewItemRead:
        review = self.get_conflict_review(review_id)
        if review is None:
            raise MemoryNotFoundError(review_id)
        return review

    def _require_retrieval_log(self, log_id: str) -> RetrievalLogRead:
        log = self.get_retrieval_log(log_id)
        if log is None:
            raise MemoryNotFoundError(log_id)
        return log

    def _require_maintenance_review(self, review_id: str) -> MaintenanceReviewItemRead:
        review = self.get_maintenance_review(review_id)
        if review is None:
            raise MemoryNotFoundError(review_id)
        return review

    def _has_blocking_maintenance_review(
        self,
        memory_id: str,
        recommended_action: MemoryMaintenanceAction,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM maintenance_review_items
                WHERE memory_id = ?
                  AND recommended_action = ?
                  AND status IN ('pending', 'needs_user')
                LIMIT 1
                """,
                (memory_id, recommended_action),
            ).fetchone()
        return row is not None

    @staticmethod
    def _build_maintenance_review_candidate(
        stats: MemoryUsageStatsRead,
    ) -> MaintenanceReviewItemCreate:
        return MaintenanceReviewItemCreate(
            memory_id=stats.memory_id,
            recommended_action=stats.recommended_action,
            usage_score=stats.usage_score,
            retrieved_count=stats.retrieved_count,
            used_count=stats.used_count,
            skipped_count=stats.skipped_count,
            useful_feedback_count=stats.useful_feedback_count,
            not_useful_feedback_count=stats.not_useful_feedback_count,
            reasons=stats.reasons,
            required_action=(
                "Review usage signals and explicitly choose keep, review, mark_stale, or archive."
            ),
        )

    def _mark_maintenance_review(
        self,
        review_id: str,
        status: MaintenanceReviewStatus,
        *,
        resolution_action: MemoryMaintenanceAction,
        resolution_reason: str,
    ) -> None:
        resolved_at = _utc_now().isoformat() if status in {"resolved", "dismissed", "needs_user"} else None
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE maintenance_review_items
                SET status = ?,
                    resolution_action = ?,
                    resolution_reason = ?,
                    resolved_at = ?
                WHERE id = ?
                """,
                (status, resolution_action, resolution_reason, resolved_at, review_id),
            )

    def _build_memory_usage_stats(self, memory: MemoryItemRead) -> MemoryUsageStatsRead:
        logs = self._retrieval_logs_for_memory(memory.id)
        retrieved_count = 0
        used_count = 0
        skipped_count = 0
        useful_count = 0
        not_useful_count = 0
        mixed_count = 0
        unknown_count = 0
        last_retrieved_at: datetime | None = None
        last_used_log_at: datetime | None = None
        last_feedback_at: datetime | None = None

        for log in logs:
            involved = False
            if memory.id in log.retrieved_memory_ids:
                involved = True
                retrieved_count += 1
                last_retrieved_at = _max_datetime(last_retrieved_at, log.created_at)
            if memory.id in log.used_memory_ids:
                involved = True
                used_count += 1
                last_used_log_at = _max_datetime(last_used_log_at, log.created_at)
            if memory.id in log.skipped_memory_ids:
                involved = True
                skipped_count += 1

            if not involved or log.feedback is None:
                continue
            if log.feedback == "useful":
                useful_count += 1
            elif log.feedback == "not_useful":
                not_useful_count += 1
            elif log.feedback == "mixed":
                mixed_count += 1
            elif log.feedback == "unknown":
                unknown_count += 1
            last_feedback_at = _max_datetime(last_feedback_at, log.feedback_at)

        usage_score = (
            used_count * 2.0
            + useful_count * 3.0
            + mixed_count
            - skipped_count * 0.5
            - not_useful_count * 3.0
        )
        recommended_action, reasons = self._recommend_memory_maintenance(
            memory,
            retrieved_count=retrieved_count,
            used_count=used_count,
            skipped_count=skipped_count,
            useful_count=useful_count,
            not_useful_count=not_useful_count,
        )
        return MemoryUsageStatsRead(
            memory_id=memory.id,
            memory_type=memory.memory_type,
            scope=memory.scope,
            subject=memory.subject,
            status=memory.status,
            confidence=memory.confidence,
            retrieved_count=retrieved_count,
            used_count=used_count,
            skipped_count=skipped_count,
            useful_feedback_count=useful_count,
            not_useful_feedback_count=not_useful_count,
            mixed_feedback_count=mixed_count,
            unknown_feedback_count=unknown_count,
            last_retrieved_at=last_retrieved_at,
            last_used_log_at=last_used_log_at,
            last_feedback_at=last_feedback_at,
            usage_score=usage_score,
            recommended_action=recommended_action,
            reasons=reasons,
        )

    def _retrieval_logs_for_memory(self, memory_id: str) -> list[RetrievalLogRead]:
        memory_match = f'%"{memory_id}"%'
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM retrieval_logs
                WHERE retrieved_memory_ids_json LIKE ?
                   OR used_memory_ids_json LIKE ?
                   OR skipped_memory_ids_json LIKE ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (memory_match, memory_match, memory_match),
            ).fetchall()
        return [self._row_to_retrieval_log(row) for row in rows]

    @staticmethod
    def _recommend_memory_maintenance(
        memory: MemoryItemRead,
        *,
        retrieved_count: int,
        used_count: int,
        skipped_count: int,
        useful_count: int,
        not_useful_count: int,
    ) -> tuple[MemoryMaintenanceAction, list[str]]:
        reasons: list[str] = []
        if memory.status in {"archived", "rejected", "superseded"}:
            return "keep", [f"memory is already {memory.status}"]

        if useful_count > not_useful_count:
            return "keep", ["useful feedback outweighs negative feedback"]

        if memory.status == "stale":
            if not_useful_count >= 2:
                return "archive", ["stale memory has repeated not_useful feedback"]
            if retrieved_count > 0 and used_count == 0:
                return "archive", ["stale memory is retrieved but not used"]
            return "keep", ["stale memory has no strong archive signal"]

        if not_useful_count >= 2:
            return "mark_stale", ["active memory has repeated not_useful feedback"]

        if retrieved_count >= 3 and used_count == 0:
            return "review", ["memory is repeatedly retrieved but never used"]

        if skipped_count >= 3 and used_count == 0:
            return "review", ["memory is repeatedly skipped during context composition"]

        if retrieved_count == 0 and used_count == 0:
            reasons.append("no retrieval usage has been observed yet")
        else:
            reasons.append("usage signals do not require maintenance")
        return "keep", reasons

    def _has_blocking_conflict_review(self, conflict_key: str, relation_ids: list[str]) -> bool:
        canonical_relation_ids = sorted(set(relation_ids))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT relation_ids_json, status, resolution_action FROM conflict_review_items
                WHERE conflict_key = ?
                """,
                (conflict_key,),
            ).fetchall()
        for row in rows:
            existing = _json_loads(row["relation_ids_json"]) or []
            if sorted(set(existing)) != canonical_relation_ids:
                continue
            if row["status"] in {"pending", "needs_user"}:
                return True
            if row["status"] == "resolved" and row["resolution_action"] == "keep_both_scoped":
                return True
        return False

    def _build_conflict_review_candidate(
        self,
        conflict: GraphConflictRead,
    ) -> ConflictReviewItemCreate:
        sorted_memories = sorted(
            conflict.memories,
            key=lambda memory: (memory.last_verified_at or memory.updated_at, memory.updated_at),
        )
        newest_memory = sorted_memories[-1]
        return ConflictReviewItemCreate(
            conflict_key=conflict.conflict_key,
            scope=conflict.scope,
            relation_type=conflict.relation_type,
            from_entity_id=conflict.from_entity.id,
            target_entity_ids=[entity.id for entity in conflict.target_entities],
            relation_ids=[relation.id for relation in conflict.relations],
            memory_ids=[memory.id for memory in conflict.memories],
            recommended_action="accept_new",
            recommended_keep_memory_ids=[newest_memory.id],
            reason=(
                f"Detected {len(conflict.target_entities)} active targets for "
                f"{conflict.from_entity.name}.{conflict.relation_type}. "
                f"Recommend keeping the newest verified memory."
            ),
            required_action="Review source memories and choose which current fact should remain active.",
        )

    def _resolve_keep_memory_ids(
        self,
        review: ConflictReviewItemRead,
        action: ConflictReviewAction,
        keep_memory_ids: list[str] | None,
    ) -> set[str]:
        if keep_memory_ids:
            unknown_ids = set(keep_memory_ids) - set(review.memory_ids)
            if unknown_ids:
                raise MemoryPolicyError("keep_memory_ids must belong to the conflict review")
            return set(keep_memory_ids)

        if action == "accept_new":
            if not review.recommended_keep_memory_ids:
                raise MemoryPolicyError("accept_new requires a memory to keep")
            return set(review.recommended_keep_memory_ids)

        if action == "keep_existing":
            for memory_id in review.memory_ids:
                memory = self._require_memory(memory_id)
                if memory.status == "active":
                    return {memory.id}
            raise MemoryPolicyError("keep_existing requires at least one active memory")

        raise MemoryPolicyError(f"action '{action}' does not choose memories to keep")

    def _resolution_source_event_ids(self, keep_memory_ids: set[str]) -> list[str]:
        source_event_ids: list[str] = []
        for memory_id in keep_memory_ids:
            memory = self.get_memory(memory_id)
            if memory is None:
                continue
            source_event_ids.extend(memory.source_event_ids)
        return _unique_ordered(source_event_ids)

    def _mark_conflict_review(
        self,
        review_id: str,
        status: ConflictReviewStatus,
        *,
        resolution_action: ConflictReviewAction,
        resolution_reason: str,
    ) -> None:
        resolved_at = _utc_now().isoformat() if status in {"resolved", "needs_user"} else None
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE conflict_review_items
                SET status = ?,
                    resolution_action = ?,
                    resolution_reason = ?,
                    resolved_at = ?
                WHERE id = ?
                """,
                (status, resolution_action, resolution_reason, resolved_at, review_id),
            )

    def _active_relation_memories(
        self,
        relation: MemoryRelationRead,
        *,
        scope: str | None,
    ) -> list[MemoryItemRead]:
        allowed_scopes = {"global"}
        if scope:
            allowed_scopes.add(scope)

        memories: list[MemoryItemRead] = []
        for memory_id in relation.source_memory_ids:
            memory = self.get_memory(memory_id)
            if memory is None or memory.status != "active":
                continue
            if scope is not None and memory.scope not in allowed_scopes:
                continue
            memories.append(memory)
        return memories

    @staticmethod
    def _unique_memories(memories: list[MemoryItemRead]) -> list[MemoryItemRead]:
        seen: set[str] = set()
        unique: list[MemoryItemRead] = []
        for memory in memories:
            if memory.id in seen:
                continue
            seen.add(memory.id)
            unique.append(memory)
        return unique

    def _has_pending_consolidation(self, source_memory_ids: list[str]) -> bool:
        canonical_source_ids = sorted(set(source_memory_ids))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source_memory_ids_json FROM consolidation_candidates
                WHERE status = 'pending'
                """
            ).fetchall()
        for row in rows:
            existing = _json_loads(row["source_memory_ids_json"]) or []
            if sorted(set(existing)) == canonical_source_ids:
                return True
        return False

    @staticmethod
    def _build_consolidated_content(memories: list[MemoryItemRead]) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for memory in memories:
            content = memory.content.strip()
            if content in seen:
                continue
            seen.add(content)
            lines.append(f"- {content}")
        return "[Consolidated memory]\n" + "\n".join(lines)

    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_candidate(row: sqlite3.Row) -> MemoryCandidateRead:
        return MemoryCandidateRead(
            id=row["id"],
            content=row["content"],
            memory_type=row["memory_type"],
            scope=row["scope"],
            subject=row["subject"],
            source_event_ids=_json_loads(row["source_event_ids_json"]),
            reason=row["reason"],
            claim=row["claim"] or None,
            evidence_type=row["evidence_type"],
            time_validity=row["time_validity"],
            reuse_cases=_json_loads(row["reuse_cases_json"]),
            scores=CandidateScores(**(_json_loads(row["scores_json"]) or {})),
            confidence=row["confidence"],
            risk=row["risk"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_policy_decision(row: sqlite3.Row) -> PolicyDecisionRead:
        return PolicyDecisionRead(
            id=row["id"],
            candidate_id=row["candidate_id"],
            decision=row["decision"],
            reason=row["reason"],
            structured_reason=_json_loads(row["structured_reason_json"]) or {},
            matched_memory_ids=_json_loads(row["matched_memory_ids_json"]),
            required_action=row["required_action"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_consolidation_candidate(row: sqlite3.Row) -> ConsolidationCandidateRead:
        return ConsolidationCandidateRead(
            id=row["id"],
            source_memory_ids=_json_loads(row["source_memory_ids_json"]),
            proposed_content=row["proposed_content"],
            memory_type=row["memory_type"],
            scope=row["scope"],
            subject=row["subject"],
            reason=row["reason"],
            confidence=row["confidence"],
            tags=_json_loads(row["tags_json"]),
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> MemoryEntityRead:
        return MemoryEntityRead(
            id=row["id"],
            name=row["name"],
            entity_type=row["entity_type"],
            scope=row["scope"],
            aliases=_json_loads(row["aliases_json"]) or [],
            metadata=_json_loads(row["metadata_json"]) or {},
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_relation(row: sqlite3.Row) -> MemoryRelationRead:
        return MemoryRelationRead(
            id=row["id"],
            from_id=row["from_memory_id"],
            relation_type=row["relation_type"],
            to_id=row["to_memory_id"],
            confidence=row["confidence"],
            source_event_ids=_json_loads(row["source_event_ids_json"]) or [],
            source_memory_ids=_json_loads(row["source_memory_ids_json"]) or [],
            metadata=_json_loads(row["metadata_json"]) or {},
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_conflict_review(row: sqlite3.Row) -> ConflictReviewItemRead:
        resolved_at = row["resolved_at"]
        return ConflictReviewItemRead(
            id=row["id"],
            conflict_key=row["conflict_key"],
            scope=row["scope"],
            relation_type=row["relation_type"],
            from_entity_id=row["from_entity_id"],
            target_entity_ids=_json_loads(row["target_entity_ids_json"]) or [],
            relation_ids=_json_loads(row["relation_ids_json"]) or [],
            memory_ids=_json_loads(row["memory_ids_json"]) or [],
            recommended_action=row["recommended_action"],
            recommended_keep_memory_ids=_json_loads(
                row["recommended_keep_memory_ids_json"]
            )
            or [],
            reason=row["reason"],
            required_action=row["required_action"],
            status=row["status"],
            resolution_action=row["resolution_action"],
            resolution_reason=row["resolution_reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
            resolved_at=datetime.fromisoformat(resolved_at) if resolved_at else None,
        )

    @staticmethod
    def _row_to_maintenance_review(row: sqlite3.Row) -> MaintenanceReviewItemRead:
        resolved_at = row["resolved_at"]
        return MaintenanceReviewItemRead(
            id=row["id"],
            memory_id=row["memory_id"],
            recommended_action=row["recommended_action"],
            usage_score=row["usage_score"],
            retrieved_count=row["retrieved_count"],
            used_count=row["used_count"],
            skipped_count=row["skipped_count"],
            useful_feedback_count=row["useful_feedback_count"],
            not_useful_feedback_count=row["not_useful_feedback_count"],
            reasons=_json_loads(row["reasons_json"]) or [],
            required_action=row["required_action"],
            status=row["status"],
            resolution_action=row["resolution_action"],
            resolution_reason=row["resolution_reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
            resolved_at=datetime.fromisoformat(resolved_at) if resolved_at else None,
        )

    @staticmethod
    def _row_to_retrieval_log(row: sqlite3.Row) -> RetrievalLogRead:
        feedback_at = row["feedback_at"]
        return RetrievalLogRead(
            id=row["id"],
            query=row["query"],
            task=row["task"],
            task_type=row["task_type"],
            scope=row["scope"],
            source=row["source"],
            retrieved_memory_ids=_json_loads(row["retrieved_memory_ids_json"]) or [],
            used_memory_ids=_json_loads(row["used_memory_ids_json"]) or [],
            skipped_memory_ids=_json_loads(row["skipped_memory_ids_json"]) or [],
            warnings=_json_loads(row["warnings_json"]) or [],
            metadata=_json_loads(row["metadata_json"]) or {},
            feedback=row["feedback"],
            feedback_reason=row["feedback_reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
            feedback_at=datetime.fromisoformat(feedback_at) if feedback_at else None,
        )

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> MemoryItemRead:
        last_used_at = row["last_used_at"]
        last_verified_at = row["last_verified_at"]
        return MemoryItemRead(
            id=row["id"],
            content=row["content"],
            memory_type=row["memory_type"],
            scope=row["scope"],
            subject=row["subject"],
            status=row["status"],
            confidence=row["confidence"],
            source_event_ids=_json_loads(row["source_event_ids_json"]),
            tags=_json_loads(row["tags_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_used_at=datetime.fromisoformat(last_used_at) if last_used_at else None,
            last_verified_at=datetime.fromisoformat(last_verified_at) if last_verified_at else None,
        )

    @staticmethod
    def _row_to_embedding(row: sqlite3.Row) -> MemoryEmbeddingRead:
        return MemoryEmbeddingRead(
            memory_id=row["memory_id"],
            model=row["model"],
            vector=[float(item) for item in (_json_loads(row["vector_json"]) or [])],
            dimensions=row["dimensions"],
            embedded_text=row["embedded_text"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_version(row: sqlite3.Row) -> MemoryVersionRead:
        return MemoryVersionRead(
            id=row["id"],
            memory_id=row["memory_id"],
            version=row["version"],
            content=row["content"],
            change_type=row["change_type"],
            change_reason=row["change_reason"],
            source_event_ids=_json_loads(row["source_event_ids_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
