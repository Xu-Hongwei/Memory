from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EventType = Literal[
    "user_message",
    "assistant_message",
    "tool_result",
    "file_observation",
    "test_result",
    "user_confirmation",
]


class EventCreate(BaseModel):
    event_type: EventType
    content: str
    source: str
    scope: str = "global"
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content", "source", "scope")
    @classmethod
    def require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped


class EventRead(EventCreate):
    model_config = ConfigDict(frozen=True)

    id: str
    created_at: datetime
    sanitized: bool = False


MemoryType = Literal[
    "user_preference",
    "project_fact",
    "tool_rule",
    "environment_fact",
    "troubleshooting",
    "decision",
    "workflow",
    "reflection",
]

Confidence = Literal["confirmed", "likely", "inferred", "unknown"]
Risk = Literal["low", "medium", "high"]
CandidateStatus = Literal["pending", "committed", "rejected"]
ConsolidationStatus = Literal["pending", "committed", "rejected"]
ConflictReviewStatus = Literal["pending", "resolved", "needs_user", "dismissed"]
ConflictReviewAction = Literal[
    "accept_new",
    "keep_existing",
    "keep_both_scoped",
    "ask_user",
    "archive_all",
]
RetrievalSource = Literal[
    "search",
    "context",
    "task_recall",
    "graph_recall",
    "orchestrated_recall",
    "manual",
]
RetrievalFeedback = Literal["useful", "not_useful", "mixed", "unknown"]
MemoryMaintenanceAction = Literal["keep", "review", "mark_stale", "archive"]
MaintenanceReviewStatus = Literal["pending", "resolved", "needs_user", "dismissed"]
PolicyAction = Literal["write", "reject", "ask_user", "merge", "update"]
MemoryStatus = Literal["active", "stale", "archived", "rejected", "superseded"]
VersionChangeType = Literal["create", "update", "merge", "archive", "stale", "supersede"]
EvidenceType = Literal[
    "direct_user_statement",
    "file_observation",
    "tool_result",
    "test_result",
    "user_confirmation",
    "inferred",
    "unknown",
]
TimeValidity = Literal["persistent", "until_changed", "session", "unknown"]
EntityType = Literal[
    "repo",
    "file",
    "tool",
    "command",
    "error",
    "solution",
    "preference",
    "module",
    "concept",
    "unknown",
]
RetrievalMode = Literal["keyword", "semantic", "hybrid"]
RetrievalGuardDecision = Literal["accepted", "ambiguous", "rejected"]
RecallStrategy = Literal[
    "auto",
    "keyword",
    "guarded_hybrid",
    "selective_llm_guarded_hybrid",
]


class CandidateScores(BaseModel):
    long_term: float = 0.0
    evidence: float = 0.0
    reuse: float = 0.0
    risk: float = 0.0
    specificity: float = 0.0


class MemoryCandidateCreate(BaseModel):
    content: str
    memory_type: MemoryType
    scope: str
    subject: str
    source_event_ids: list[str]
    reason: str
    claim: str | None = None
    evidence_type: EvidenceType = "unknown"
    time_validity: TimeValidity = "unknown"
    reuse_cases: list[str] = Field(default_factory=list)
    scores: CandidateScores = Field(default_factory=CandidateScores)
    confidence: Confidence = "unknown"
    risk: Risk = "low"

    @field_validator("content", "scope", "subject", "reason")
    @classmethod
    def require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped

    @field_validator("source_event_ids")
    @classmethod
    def require_sources(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("source_event_ids must not be empty")
        return value


class MemoryCandidateRead(MemoryCandidateCreate):
    model_config = ConfigDict(frozen=True)

    id: str
    status: CandidateStatus = "pending"
    created_at: datetime


class PolicyDecisionRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    candidate_id: str
    decision: PolicyAction
    reason: str
    structured_reason: dict[str, str] = Field(default_factory=dict)
    matched_memory_ids: list[str] = Field(default_factory=list)
    required_action: str | None = None
    created_at: datetime


class MemoryItemCreate(BaseModel):
    content: str
    memory_type: MemoryType
    scope: str
    subject: str
    confidence: Confidence
    source_event_ids: list[str]
    tags: list[str] = Field(default_factory=list)

    @field_validator("content", "scope", "subject")
    @classmethod
    def require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped


class MemoryItemRead(MemoryItemCreate):
    model_config = ConfigDict(frozen=True)

    id: str
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None
    last_verified_at: datetime | None = None


class MemoryVersionRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    memory_id: str
    version: int
    content: str
    change_type: VersionChangeType
    change_reason: str
    source_event_ids: list[str]
    created_at: datetime


class MemoryEmbeddingRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_id: str
    model: str
    vector: list[float]
    dimensions: int
    embedded_text: str
    created_at: datetime
    updated_at: datetime


class ConsolidationCandidateCreate(BaseModel):
    source_memory_ids: list[str]
    proposed_content: str
    memory_type: MemoryType
    scope: str
    subject: str
    reason: str
    confidence: Confidence = "confirmed"
    tags: list[str] = Field(default_factory=list)

    @field_validator("proposed_content", "scope", "subject", "reason")
    @classmethod
    def require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped

    @field_validator("source_memory_ids")
    @classmethod
    def require_source_memories(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("source_memory_ids must not be empty")
        return value


class ConsolidationCandidateRead(ConsolidationCandidateCreate):
    model_config = ConfigDict(frozen=True)

    id: str
    status: ConsolidationStatus = "pending"
    created_at: datetime


class MemoryEntityCreate(BaseModel):
    name: str
    entity_type: EntityType = "unknown"
    scope: str = "global"
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "scope")
    @classmethod
    def require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped


class MemoryEntityRead(MemoryEntityCreate):
    model_config = ConfigDict(frozen=True)

    id: str
    created_at: datetime
    updated_at: datetime


class MemoryRelationCreate(BaseModel):
    from_id: str
    relation_type: str
    to_id: str
    confidence: Confidence = "confirmed"
    source_memory_ids: list[str] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("from_id", "relation_type", "to_id")
    @classmethod
    def require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped


class MemoryRelationRead(MemoryRelationCreate):
    model_config = ConfigDict(frozen=True)

    id: str
    created_at: datetime


class SearchMemoryInput(BaseModel):
    query: str = ""
    task_type: str | None = None
    memory_types: list[MemoryType] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    limit: int = 10
    retrieval_mode: RetrievalMode = "keyword"
    query_embedding: list[float] = Field(default_factory=list)
    embedding_model: str | None = None

    @field_validator("limit")
    @classmethod
    def require_positive_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("limit must be greater than zero")
        return value

    @field_validator("query_embedding")
    @classmethod
    def require_numeric_embedding(cls, value: list[float]) -> list[float]:
        return [float(item) for item in value]


class ContextBlock(BaseModel):
    content: str
    memory_ids: list[str]
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class RecallPlan(BaseModel):
    task: str
    scope: str | None = None
    intent: str
    query_terms: list[str]
    memory_types: list[MemoryType]
    scopes: list[str]
    limit_per_query: int = 5
    reasons: list[str] = Field(default_factory=list)


class TaskRecallResult(BaseModel):
    plan: RecallPlan
    memories: list[MemoryItemRead]
    context: ContextBlock


class OrchestratedRecallStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    strategy: str
    retrieved_memory_ids: list[str] = Field(default_factory=list)
    accepted_memory_ids: list[str] = Field(default_factory=list)
    skipped_memory_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestratedRecallResult(BaseModel):
    task: str
    scope: str | None = None
    strategy: RecallStrategy = "auto"
    selected_strategy: str
    memory_needed: bool = True
    plan: RecallPlan | None = None
    memories: list[MemoryItemRead] = Field(default_factory=list)
    context: ContextBlock
    steps: list[OrchestratedRecallStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphRecallResult(BaseModel):
    task: str
    scope: str | None = None
    seed_entities: list[MemoryEntityRead]
    relations: list[MemoryRelationRead]
    memories: list[MemoryItemRead]
    context: ContextBlock
    warnings: list[str] = Field(default_factory=list)


class GraphConflictRead(BaseModel):
    conflict_key: str
    scope: str
    relation_type: str
    from_entity: MemoryEntityRead
    target_entities: list[MemoryEntityRead]
    relations: list[MemoryRelationRead]
    memories: list[MemoryItemRead]
    reason: str


class ConflictReviewItemCreate(BaseModel):
    conflict_key: str
    scope: str
    relation_type: str
    from_entity_id: str
    target_entity_ids: list[str]
    relation_ids: list[str]
    memory_ids: list[str]
    recommended_action: ConflictReviewAction
    recommended_keep_memory_ids: list[str] = Field(default_factory=list)
    reason: str
    required_action: str | None = None

    @field_validator("conflict_key", "scope", "relation_type", "from_entity_id", "reason")
    @classmethod
    def require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped


class ConflictReviewItemRead(ConflictReviewItemCreate):
    model_config = ConfigDict(frozen=True)

    id: str
    status: ConflictReviewStatus = "pending"
    resolution_action: ConflictReviewAction | None = None
    resolution_reason: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class RetrievalLogCreate(BaseModel):
    query: str = ""
    task: str | None = None
    task_type: str | None = None
    scope: str | None = None
    source: RetrievalSource = "manual"
    retrieved_memory_ids: list[str] = Field(default_factory=list)
    used_memory_ids: list[str] = Field(default_factory=list)
    skipped_memory_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("query", "task", "task_type", "scope", mode="before")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return value.strip()


class RetrievalLogRead(RetrievalLogCreate):
    model_config = ConfigDict(frozen=True)

    id: str
    feedback: RetrievalFeedback | None = None
    feedback_reason: str | None = None
    created_at: datetime
    feedback_at: datetime | None = None


class MemoryUsageStatsRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_id: str
    memory_type: MemoryType
    scope: str
    subject: str
    status: MemoryStatus
    confidence: Confidence
    retrieved_count: int = 0
    used_count: int = 0
    skipped_count: int = 0
    useful_feedback_count: int = 0
    not_useful_feedback_count: int = 0
    mixed_feedback_count: int = 0
    unknown_feedback_count: int = 0
    last_retrieved_at: datetime | None = None
    last_used_log_at: datetime | None = None
    last_feedback_at: datetime | None = None
    usage_score: float = 0.0
    recommended_action: MemoryMaintenanceAction = "keep"
    reasons: list[str] = Field(default_factory=list)


class MaintenanceReviewItemCreate(BaseModel):
    memory_id: str
    recommended_action: MemoryMaintenanceAction
    usage_score: float = 0.0
    retrieved_count: int = 0
    used_count: int = 0
    skipped_count: int = 0
    useful_feedback_count: int = 0
    not_useful_feedback_count: int = 0
    reasons: list[str] = Field(default_factory=list)
    required_action: str | None = None

    @field_validator("memory_id")
    @classmethod
    def require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped


class MaintenanceReviewItemRead(MaintenanceReviewItemCreate):
    model_config = ConfigDict(frozen=True)

    id: str
    status: MaintenanceReviewStatus = "pending"
    resolution_action: MemoryMaintenanceAction | None = None
    resolution_reason: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class RemoteAdapterConfigRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    configured: bool
    base_url: str | None = None
    compatibility: str = "generic"
    embedding_compatibility: str = "generic"
    timeout_seconds: float = 10.0
    api_key_configured: bool = False
    llm_extract_path: str = "/memory/extract"
    embedding_path: str = "/embeddings"
    health_path: str = "/health"
    llm_model: str | None = None
    embedding_model: str | None = None


class RemoteCandidateExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "remote"
    candidates: list[MemoryCandidateCreate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RemoteCandidateImportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "remote"
    candidates: list[MemoryCandidateRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RemoteCandidateEvaluationItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    event_type: EventType
    scope: str
    source: str
    local_candidates: list[MemoryCandidateCreate] = Field(default_factory=list)
    remote_candidates: list[MemoryCandidateCreate] = Field(default_factory=list)
    local_types: list[MemoryType] = Field(default_factory=list)
    remote_types: list[MemoryType] = Field(default_factory=list)
    overlap_types: list[MemoryType] = Field(default_factory=list)
    local_only_types: list[MemoryType] = Field(default_factory=list)
    remote_only_types: list[MemoryType] = Field(default_factory=list)
    remote_latency_ms: float | None = None
    remote_error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RemoteCandidateEvaluationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_count: int = 0
    remote_success_count: int = 0
    remote_error_count: int = 0
    local_candidate_count: int = 0
    remote_candidate_count: int = 0
    both_empty_event_count: int = 0
    overlap_event_count: int = 0
    local_only_event_count: int = 0
    remote_only_event_count: int = 0
    divergent_event_count: int = 0
    average_remote_latency_ms: float | None = None


class RemoteCandidateEvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "remote"
    summary: RemoteCandidateEvaluationSummary
    items: list[RemoteCandidateEvaluationItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RemoteEmbeddingRequest(BaseModel):
    texts: list[str]
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("texts")
    @classmethod
    def require_texts(cls, value: list[str]) -> list[str]:
        texts = [item.strip() for item in value if item.strip()]
        if not texts:
            raise ValueError("texts must not be empty")
        return texts


class RemoteEmbeddingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "remote"
    vectors: list[list[float]]
    model: str | None = None
    dimensions: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RemoteEmbeddingBackfillResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "remote"
    model: str | None = None
    requested_count: int = 0
    embedded_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    batch_count: int = 0
    dimensions: int | None = None
    dry_run: bool = False
    memory_ids: list[str] = Field(default_factory=list)
    skipped_memory_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RemoteRetrievalJudgeRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "remote"
    model: str | None = None
    decision: RetrievalGuardDecision
    reason: str
    risk: Risk = "medium"
    selected_aliases: list[str] = Field(default_factory=list)
    selected_memory_ids: list[str] = Field(default_factory=list)
    candidate_aliases: list[str] = Field(default_factory=list)
    candidate_memory_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RemoteRetrievalEvaluationItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_name: str
    category: str | None = None
    query: str
    expected_aliases: list[str] = Field(default_factory=list)
    results_by_mode: dict[str, list[str]] = Field(default_factory=dict)
    missing_by_mode: dict[str, list[str]] = Field(default_factory=dict)
    unexpected_by_mode: dict[str, list[str]] = Field(default_factory=dict)
    ambiguous_by_mode: dict[str, list[str]] = Field(default_factory=dict)
    passed_by_mode: dict[str, bool] = Field(default_factory=dict)
    judge_by_mode: dict[str, RemoteRetrievalJudgeRead] = Field(default_factory=dict)


class RemoteRetrievalEvaluationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_count: int = 0
    modes: list[str] = Field(default_factory=list)
    passed_by_mode: dict[str, int] = Field(default_factory=dict)
    failed_by_mode: dict[str, int] = Field(default_factory=dict)
    false_negative_by_mode: dict[str, int] = Field(default_factory=dict)
    unexpected_by_mode: dict[str, int] = Field(default_factory=dict)
    ambiguous_by_mode: dict[str, int] = Field(default_factory=dict)
    top1_hit_by_mode: dict[str, int] = Field(default_factory=dict)
    embedded_memory_count: int = 0
    embedded_query_count: int = 0
    judge_called_by_mode: dict[str, int] = Field(default_factory=dict)
    judge_skipped_by_mode: dict[str, int] = Field(default_factory=dict)
    judge_skip_reason_by_mode: dict[str, dict[str, int]] = Field(default_factory=dict)


class RemoteRetrievalCategorySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: str
    case_count: int = 0
    passed_by_mode: dict[str, int] = Field(default_factory=dict)
    failed_by_mode: dict[str, int] = Field(default_factory=dict)
    false_negative_by_mode: dict[str, int] = Field(default_factory=dict)
    unexpected_by_mode: dict[str, int] = Field(default_factory=dict)
    ambiguous_by_mode: dict[str, int] = Field(default_factory=dict)
    top1_hit_by_mode: dict[str, int] = Field(default_factory=dict)
    judge_called_by_mode: dict[str, int] = Field(default_factory=dict)
    judge_skipped_by_mode: dict[str, int] = Field(default_factory=dict)
    judge_skip_reason_by_mode: dict[str, dict[str, int]] = Field(default_factory=dict)


class RemoteRetrievalEvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "remote"
    model: str | None = None
    summary: RemoteRetrievalEvaluationSummary
    category_summary: dict[str, RemoteRetrievalCategorySummary] = Field(default_factory=dict)
    items: list[RemoteRetrievalEvaluationItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RemoteRetrievalGuardDecisionRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_id: str
    subject: str
    decision: RetrievalGuardDecision
    reason: str
    rank: int
    similarity: float | None = None
    score_margin: float | None = None
    intent_score: float | None = None


class RemoteGuardedSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "remote"
    model: str | None = None
    query: str
    memories: list[MemoryItemRead] = Field(default_factory=list)
    decisions: list[RemoteRetrievalGuardDecisionRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RemoteRecallJudgeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "remote"
    model: str | None = None
    query: str
    decision: RetrievalGuardDecision
    selected_memory_ids: list[str] = Field(default_factory=list)
    reason: str
    risk: Risk = "medium"
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RemoteLLMGuardedSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "remote"
    model: str | None = None
    query: str
    memories: list[MemoryItemRead] = Field(default_factory=list)
    local_guard: RemoteGuardedSearchResult
    judge: RemoteRecallJudgeResult
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
