from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from memory_system.context_composer import compose_context
from memory_system.event_log import EventLog, SensitiveContentError
from memory_system.graph_recall import graph_recall_for_task
from memory_system.memory_store import (
    MemoryNotFoundError,
    MemoryPolicyError,
    MemoryStore,
    build_memory_embedding_text,
)
from memory_system.remote import (
    RemoteAdapterConfig,
    RemoteAdapterError,
    RemoteAdapterNotConfiguredError,
    RemoteEmbeddingClient,
    RemoteLLMClient,
    route_item_to_memory_candidate,
)
from memory_system.remote_evaluation import (
    backfill_remote_memory_embeddings,
    evaluate_remote_candidate_quality,
    evaluate_remote_retrieval_fixture,
    load_events_for_remote_evaluation,
    remote_guarded_hybrid_search,
    remote_llm_guarded_hybrid_search,
    remote_selective_llm_guarded_hybrid_search,
)
from memory_system.recall_orchestrator import orchestrate_recall
from memory_system.session_memory import (
    SessionMemoryStore,
    compose_context_with_session,
    session_item_from_route_item,
)
from memory_system.task_recall import recall_for_task
from memory_system.schemas import (
    CandidateStatus,
    ConflictReviewAction,
    ConflictReviewItemRead,
    ConflictReviewStatus,
    ConsolidationCandidateRead,
    ConsolidationStatus,
    ContextBlock,
    EventCreate,
    EventRead,
    GraphConflictRead,
    GraphRecallResult,
    MaintenanceReviewItemRead,
    MaintenanceReviewStatus,
    MemoryEntityCreate,
    MemoryEntityRead,
    MemoryCandidateRead,
    MemoryEmbeddingRead,
    MemoryMaintenanceAction,
    MemoryItemRead,
    MemoryRelationCreate,
    MemoryRelationRead,
    MemoryStatus,
    MemoryUsageStatsRead,
    MemoryType,
    MemoryVersionRead,
    OrchestratedRecallResult,
    PolicyDecisionRead,
    RecallStrategy,
    RemoteAdapterConfigRead,
    RemoteCandidateExtractionResult,
    RemoteCandidateEvaluationResult,
    RemoteCandidateImportResult,
    RemoteEmbeddingBackfillResult,
    RemoteEmbeddingRequest,
    RemoteEmbeddingResult,
    RemoteGuardedSearchResult,
    RemoteLLMGuardedSearchResult,
    RemoteRetrievalEvaluationResult,
    RetrievalFeedback,
    RetrievalLogCreate,
    RetrievalLogRead,
    RetrievalSource,
    SearchMemoryInput,
    TaskBoundaryDecision,
    TaskRecallResult,
)


class CommitMemoryRequest(BaseModel):
    candidate_id: str
    decision_id: str


class ReviewRequest(BaseModel):
    reason: str | None = None


class MemoryEmbeddingIndexRequest(BaseModel):
    model: str | None = None


class MemoryEmbeddingBackfillRequest(BaseModel):
    model: str | None = None
    scope: str | None = None
    memory_type: MemoryType | None = None
    limit: int = Field(default=100, ge=1)
    batch_size: int = Field(default=16, ge=1)
    dry_run: bool = False


class ConflictReviewCreateRequest(BaseModel):
    scope: str | None = None
    relation_type: str | None = None
    limit: int = 100


class ConflictReviewResolveRequest(BaseModel):
    action: ConflictReviewAction
    keep_memory_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class SupersedeMemoryRequest(BaseModel):
    candidate_id: str
    reason: str | None = None


class ConsolidationProposeRequest(BaseModel):
    scope: str | None = None
    memory_type: MemoryType | None = None
    min_group_size: int = 2
    limit: int = 20


class CandidateEditRequest(BaseModel):
    updates: dict[str, Any] = Field(default_factory=dict)


class ContextComposeRequest(BaseModel):
    task: str
    memory_ids: list[str] = Field(default_factory=list)
    token_budget: int = 2000
    include_session: bool = True
    session_id: str = "default"
    session_limit: int = Field(default=5, ge=0)
    session_scopes: list[str] = Field(default_factory=list)


class TaskRecallRequest(BaseModel):
    task: str
    scope: str | None = None
    token_budget: int = 2000
    limit_per_query: int = 5
    include_session: bool = True
    session_id: str = "default"
    session_limit: int = Field(default=5, ge=0)


class GraphRecallRequest(BaseModel):
    task: str
    scope: str | None = None
    token_budget: int = 2000
    max_depth: int = 2
    limit: int = 10


class OrchestratedRecallRequest(BaseModel):
    task: str
    scope: str | None = None
    strategy: RecallStrategy = "auto"
    token_budget: int = Field(default=2000, ge=1)
    limit: int = Field(default=10, ge=1)
    memory_types: list[MemoryType] = Field(default_factory=list)
    include_graph: bool = True
    include_session: bool = True
    session_id: str = "default"
    session_limit: int = Field(default=5, ge=0)
    session_scopes: list[str] = Field(default_factory=list)
    use_remote_planner: bool = True
    use_remote: bool = False
    use_llm_judge: bool = True
    model: str | None = None
    guard_top_k: int = Field(default=3, ge=1)
    guard_min_similarity: float = Field(default=0.20, ge=0)
    guard_ambiguity_margin: float = Field(default=0.03, ge=0)
    selective_min_similarity: float = Field(default=0.20, ge=0)
    selective_ambiguity_margin: float = Field(default=0.03, ge=0)


class RetrievalFeedbackRequest(BaseModel):
    feedback: RetrievalFeedback
    reason: str | None = None


class MaintenanceReviewCreateRequest(BaseModel):
    scope: str | None = None
    memory_type: MemoryType | None = None
    recommended_action: MemoryMaintenanceAction | None = None
    limit: int = 100


class MaintenanceReviewResolveRequest(BaseModel):
    action: MemoryMaintenanceAction
    reason: str | None = None


class RemoteExtractRequest(BaseModel):
    instructions: str | None = None


class RemoteRouteRequest(BaseModel):
    event_ids: list[str] = Field(default_factory=list)
    recent_event_ids: list[str] = Field(default_factory=list)
    session_id: str = "default"
    current_task_state: dict[str, Any] = Field(default_factory=dict)
    include_session_memories: bool = True
    instructions: str | None = None


class SessionCloseoutRequest(BaseModel):
    session_id: str = "default"
    task_boundary: TaskBoundaryDecision | None = None
    current_task_state: dict[str, Any] = Field(default_factory=dict)
    recent_event_ids: list[str] = Field(default_factory=list)
    apply: bool = True
    create_candidates: bool = True
    instructions: str | None = None


class RemoteEvaluationRequest(BaseModel):
    event_ids: list[str] = Field(default_factory=list)
    source: str | None = None
    scope: str | None = None
    task_id: str | None = None
    limit: int = Field(default=20, ge=1)
    instructions: str | None = None


class RemoteRetrievalEvaluationRequest(BaseModel):
    fixture_path: str = "tests/fixtures/golden_cases/semantic_retrieval.jsonl"
    model: str | None = None
    limit: int | None = Field(default=None, ge=1)
    sample_size: int | None = Field(default=None, ge=1)
    sample_seed: int | None = None
    batch_size: int = Field(default=16, ge=1)
    case_concurrency: int = Field(default=1, ge=1)
    judge_concurrency: int = Field(default=1, ge=1)
    judge_group_size: int = Field(default=1, ge=1)
    embedding_cache_path: str | None = None
    guard_top_k: int = Field(default=3, ge=1)
    guard_min_similarity: float = Field(default=0.20, ge=0)
    guard_ambiguity_margin: float = Field(default=0.03, ge=0)
    include_llm_judge: bool = False
    include_selective_llm_judge: bool = False
    selective_min_similarity: float = Field(default=0.20, ge=0)
    selective_ambiguity_margin: float = Field(default=0.03, ge=0)


class RemoteGuardedHybridSearchRequest(SearchMemoryInput):
    guard_top_k: int = Field(default=3, ge=1)
    guard_min_similarity: float = Field(default=0.20, ge=0)
    guard_ambiguity_margin: float = Field(default=0.03, ge=0)
    selective_min_similarity: float = Field(default=0.20, ge=0)
    selective_ambiguity_margin: float = Field(default=0.03, ge=0)


class MemoryRuntime:
    def __init__(self, db_path: str | Path) -> None:
        self.events = EventLog(db_path)
        self.memories = MemoryStore(db_path)
        self.sessions = SessionMemoryStore()
        self.remote_config = RemoteAdapterConfig.llm_from_env()
        self.remote_embedding_config = RemoteAdapterConfig.embedding_from_env()

    def remote_status(self) -> RemoteAdapterConfigRead:
        return self.remote_config.to_read_model()

    def remote_llm(self) -> RemoteLLMClient:
        return RemoteLLMClient(self.remote_config)

    def remote_embedding(self) -> RemoteEmbeddingClient:
        return RemoteEmbeddingClient(self.remote_embedding_config)


def _primary_route_event(
    source_event_ids: list[str],
    event_by_id: dict[str, EventRead],
    fallback_events: list[EventRead],
) -> EventRead:
    for event_id in source_event_ids:
        event = event_by_id.get(event_id)
        if event is not None:
            return event
    return fallback_events[0]


def create_app(db_path: str | Path | None = None) -> FastAPI:
    resolved_db_path = Path(
        db_path or os.environ.get("MEMORY_SYSTEM_DB", "data/memory.sqlite")
    )
    app = FastAPI(title="Memory System", version="0.1.0")
    app.state.runtime = MemoryRuntime(resolved_db_path)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/remote/status", response_model=RemoteAdapterConfigRead)
    def remote_status() -> RemoteAdapterConfigRead:
        return app.state.runtime.remote_status()

    @app.get("/remote/health")
    def remote_health() -> Any:
        try:
            return app.state.runtime.remote_llm().health()
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post(
        "/remote/extract/{event_id}",
        response_model=RemoteCandidateExtractionResult,
    )
    def remote_extract_candidates(
        event_id: str,
        request: RemoteExtractRequest | None = None,
    ) -> RemoteCandidateExtractionResult:
        event = app.state.runtime.events.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        try:
            return app.state.runtime.remote_llm().extract_candidates(
                event,
                instructions=request.instructions if request else None,
            )
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post(
        "/candidates/from-event/{event_id}/remote",
        response_model=RemoteCandidateImportResult,
    )
    def import_remote_candidates(
        event_id: str,
        request: RemoteExtractRequest | None = None,
    ) -> RemoteCandidateImportResult:
        event = app.state.runtime.events.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        try:
            extracted = app.state.runtime.remote_llm().extract_candidates(
                event,
                instructions=request.instructions if request else None,
            )
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        candidates = [
            app.state.runtime.memories.create_candidate(candidate)
            for candidate in extracted.candidates
        ]
        return RemoteCandidateImportResult(
            provider=extracted.provider,
            candidates=candidates,
            warnings=extracted.warnings,
            metadata={
                **extracted.metadata,
                "event_id": event.id,
                "source": "remote_llm",
                "auto_committed": False,
            },
        )

    @app.post("/remote/route")
    def remote_route_memories(request: RemoteRouteRequest) -> dict[str, Any]:
        if not request.event_ids:
            raise HTTPException(status_code=400, detail="event_ids must not be empty")

        events = []
        for event_id in request.event_ids:
            event = app.state.runtime.events.get_event(event_id)
            if event is None:
                raise HTTPException(status_code=404, detail=f"event not found: {event_id}")
            events.append(event)

        recent_events = []
        for event_id in request.recent_event_ids:
            event = app.state.runtime.events.get_event(event_id)
            if event is None:
                raise HTTPException(status_code=404, detail=f"recent event not found: {event_id}")
            recent_events.append(event)

        active_session_memories: list[dict[str, Any]] = []
        if request.include_session_memories:
            active_session_memories = [
                item.model_dump(mode="json")
                for item in app.state.runtime.sessions.list_items(
                    session_id=request.session_id,
                )
            ]

        try:
            routed = app.state.runtime.remote_llm().route_memories(
                events,
                recent_events=recent_events,
                current_task_state=request.current_task_state,
                active_session_memories=active_session_memories,
                instructions=request.instructions,
            )
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        event_by_id = {event.id: event for event in [*events, *recent_events]}
        long_term: list[dict[str, Any]] = []
        session_memories: list[dict[str, Any]] = []
        ignored: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        ask_user: list[dict[str, Any]] = []

        for item in routed.items:
            primary_event = _primary_route_event(item.source_event_ids, event_by_id, events)
            route_payload = item.model_dump(mode="json")
            if item.route == "long_term":
                candidate = route_item_to_memory_candidate(item, primary_event)
                if candidate is None:
                    ask_user.append(
                        {
                            "route_item": route_payload,
                            "reason": "long_term route could not be converted into a candidate",
                        }
                    )
                    continue
                stored_candidate = app.state.runtime.memories.create_candidate(candidate)
                decision = app.state.runtime.memories.evaluate_candidate(stored_candidate.id)
                long_term.append(
                    {
                        "route_item": route_payload,
                        "candidate": stored_candidate.model_dump(mode="json"),
                        "decision": decision.model_dump(mode="json"),
                    }
                )
                continue

            if item.route == "session":
                session_item = session_item_from_route_item(
                    primary_event,
                    item,
                    session_id=request.session_id,
                )
                if session_item is None:
                    ask_user.append(
                        {
                            "route_item": route_payload,
                            "reason": "session route could not be converted into session memory",
                        }
                    )
                    continue
                stored_session = app.state.runtime.sessions.add_item(session_item)
                session_memories.append(stored_session.model_dump(mode="json"))
                continue

            if item.route == "ignore":
                ignored.append(route_payload)
            elif item.route == "reject":
                rejected.append(route_payload)
            elif item.route == "ask_user":
                ask_user.append(route_payload)

        return {
            "provider": routed.provider,
            "long_term": long_term,
            "session": session_memories,
            "ignored": ignored,
            "rejected": rejected,
            "ask_user": ask_user,
            "task_boundary": (
                routed.task_boundary.model_dump(mode="json")
                if routed.task_boundary is not None
                else None
            ),
            "warnings": routed.warnings,
            "metadata": {
                **routed.metadata,
                "event_ids": [event.id for event in events],
                "recent_event_ids": [event.id for event in recent_events],
                "source": "remote_memory_route",
                "auto_committed": False,
                "session_persisted": True,
                "session_id": request.session_id,
                "active_session_memory_count": len(active_session_memories),
                "task_boundary_observed": routed.task_boundary is not None,
            },
        }

    @app.post("/session/closeout")
    def closeout_session_memory(request: SessionCloseoutRequest) -> dict[str, Any]:
        session_items = app.state.runtime.sessions.list_items(session_id=request.session_id)
        recent_events = []
        for event_id in request.recent_event_ids:
            event = app.state.runtime.events.get_event(event_id)
            if event is None:
                raise HTTPException(status_code=404, detail=f"recent event not found: {event_id}")
            recent_events.append(event)

        try:
            closeout = app.state.runtime.remote_llm().closeout_session_memories(
                session_id=request.session_id,
                session_memories=session_items,
                task_boundary=request.task_boundary,
                current_task_state=request.current_task_state,
                recent_events=recent_events,
                instructions=request.instructions,
            )
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        promoted_candidates: list[dict[str, Any]] = []
        if request.apply and request.create_candidates:
            for decision in closeout.decisions:
                if decision.action != "promote_candidate" or decision.candidate is None:
                    continue
                stored_candidate = app.state.runtime.memories.create_candidate(decision.candidate)
                policy = app.state.runtime.memories.evaluate_candidate(stored_candidate.id)
                promoted_candidates.append(
                    {
                        "session_memory_id": decision.session_memory_id,
                        "candidate": stored_candidate.model_dump(mode="json"),
                        "decision": policy.model_dump(mode="json"),
                    }
                )

        dismissed = []
        if request.apply:
            dismissed = app.state.runtime.sessions.apply_closeout_decisions(closeout.decisions)

        remaining = app.state.runtime.sessions.list_items(session_id=request.session_id)
        return {
            "provider": closeout.provider,
            "session_id": request.session_id,
            "task_summary": closeout.task_summary,
            "task_boundary": (
                closeout.task_boundary.model_dump(mode="json")
                if closeout.task_boundary is not None
                else None
            ),
            "decisions": [
                decision.model_dump(mode="json") for decision in closeout.decisions
            ],
            "promoted_candidates": promoted_candidates,
            "dismissed_session": [item.model_dump(mode="json") for item in dismissed],
            "remaining_session": [item.model_dump(mode="json") for item in remaining],
            "warnings": closeout.warnings,
            "metadata": {
                **closeout.metadata,
                "source": "session_closeout",
                "session_id": request.session_id,
                "applied": request.apply,
                "create_candidates": request.create_candidates,
                "input_session_memory_count": len(session_items),
                "dismissed_count": len(dismissed),
                "promoted_candidate_count": len(promoted_candidates),
            },
        }

    @app.post("/remote/embed", response_model=RemoteEmbeddingResult)
    def remote_embed(request: RemoteEmbeddingRequest) -> RemoteEmbeddingResult:
        try:
            return app.state.runtime.remote_embedding().embed_texts(
                request.texts,
                model=request.model,
                metadata=request.metadata,
            )
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/remote/evaluate-candidates", response_model=RemoteCandidateEvaluationResult)
    def evaluate_remote_candidates(
        request: RemoteEvaluationRequest,
    ) -> RemoteCandidateEvaluationResult:
        try:
            events = load_events_for_remote_evaluation(
                app.state.runtime.events,
                event_ids=request.event_ids,
                source=request.source,
                scope=request.scope,
                task_id=request.task_id,
                limit=request.limit,
            )
            return evaluate_remote_candidate_quality(
                events,
                app.state.runtime.memories,
                app.state.runtime.remote_llm(),
                instructions=request.instructions,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(
        "/remote/evaluate-retrieval",
        response_model=RemoteRetrievalEvaluationResult,
    )
    def evaluate_remote_retrieval(
        request: RemoteRetrievalEvaluationRequest,
    ) -> RemoteRetrievalEvaluationResult:
        try:
            return evaluate_remote_retrieval_fixture(
                request.fixture_path,
                app.state.runtime.remote_embedding(),
                remote_llm=app.state.runtime.remote_llm()
                if request.include_llm_judge or request.include_selective_llm_judge
                else None,
                include_llm_judge=request.include_llm_judge,
                include_selective_llm_judge=request.include_selective_llm_judge,
                model=request.model,
                limit=request.limit,
                sample_size=request.sample_size,
                sample_seed=request.sample_seed,
                batch_size=request.batch_size,
                case_concurrency=request.case_concurrency,
                judge_concurrency=request.judge_concurrency,
                judge_group_size=request.judge_group_size,
                guard_top_k=request.guard_top_k,
                guard_min_similarity=request.guard_min_similarity,
                guard_ambiguity_margin=request.guard_ambiguity_margin,
                selective_min_similarity=request.selective_min_similarity,
                selective_ambiguity_margin=request.selective_ambiguity_margin,
                embedding_cache_path=request.embedding_cache_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/events", response_model=EventRead)
    def record_event(event: EventCreate) -> EventRead:
        try:
            return app.state.runtime.events.record_event(event)
        except SensitiveContentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/events/{event_id}", response_model=EventRead)
    def get_event(event_id: str) -> EventRead:
        event = app.state.runtime.events.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        return event

    @app.get("/events", response_model=list[EventRead])
    def list_events(
        source: str | None = None,
        scope: str | None = None,
        task_id: str | None = None,
        limit: int = Query(default=100, ge=1),
        offset: int = Query(default=0, ge=0),
    ) -> list[EventRead]:
        return app.state.runtime.events.list_events(
            source=source,
            scope=scope,
            task_id=task_id,
            limit=limit,
            offset=offset,
        )

    @app.post("/candidates/from-event/{event_id}", response_model=list[MemoryCandidateRead])
    def propose_candidates(event_id: str) -> list[MemoryCandidateRead]:
        event = app.state.runtime.events.get_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        return app.state.runtime.memories.propose_memory(event)

    @app.get("/candidates", response_model=list[MemoryCandidateRead])
    def list_candidates(
        status: CandidateStatus | None = None,
        scope: str | None = None,
        memory_type: MemoryType | None = None,
        limit: int = Query(default=100, ge=1),
        offset: int = Query(default=0, ge=0),
    ) -> list[MemoryCandidateRead]:
        return app.state.runtime.memories.list_candidates(
            status=status,
            scope=scope,
            memory_type=memory_type,
            limit=limit,
            offset=offset,
        )

    @app.get("/candidates/{candidate_id}", response_model=MemoryCandidateRead)
    def get_candidate(candidate_id: str) -> MemoryCandidateRead:
        candidate = app.state.runtime.memories.get_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        return candidate

    @app.patch("/candidates/{candidate_id}", response_model=MemoryCandidateRead)
    def edit_candidate(candidate_id: str, request: CandidateEditRequest) -> MemoryCandidateRead:
        try:
            return app.state.runtime.memories.edit_candidate(candidate_id, **request.updates)
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="candidate not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/candidates/{candidate_id}/evaluate", response_model=PolicyDecisionRead)
    def evaluate_candidate(candidate_id: str) -> PolicyDecisionRead:
        try:
            return app.state.runtime.memories.evaluate_candidate(candidate_id)
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="candidate not found") from exc

    @app.post("/candidates/{candidate_id}/approve", response_model=MemoryItemRead)
    def approve_candidate(candidate_id: str, request: ReviewRequest) -> MemoryItemRead:
        try:
            return app.state.runtime.memories.approve_candidate(
                candidate_id,
                reason=request.reason or "Manually approved candidate through API.",
            )
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="candidate not found") from exc
        except MemoryPolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/candidates/{candidate_id}/reject", response_model=PolicyDecisionRead)
    def reject_candidate(candidate_id: str, request: ReviewRequest) -> PolicyDecisionRead:
        try:
            return app.state.runtime.memories.reject_candidate(
                candidate_id,
                reason=request.reason or "Manually rejected candidate through API.",
            )
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="candidate not found") from exc

    @app.post("/memories/commit", response_model=MemoryItemRead)
    def commit_memory(request: CommitMemoryRequest) -> MemoryItemRead:
        try:
            return app.state.runtime.memories.commit_memory(
                request.candidate_id,
                request.decision_id,
            )
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MemoryPolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/memories/search", response_model=list[MemoryItemRead])
    def search_memory(input: SearchMemoryInput) -> list[MemoryItemRead]:
        return app.state.runtime.memories.search_memory(input)

    @app.post("/memories/search/remote-hybrid", response_model=list[MemoryItemRead])
    def remote_hybrid_search(input: SearchMemoryInput) -> list[MemoryItemRead]:
        if not input.query.strip():
            return app.state.runtime.memories.search_memory(input)
        try:
            embedded = app.state.runtime.remote_embedding().embed_texts(
                [input.query],
                model=input.embedding_model,
            )
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        model = embedded.model or input.embedding_model
        return app.state.runtime.memories.search_memory(
            input.model_copy(
                update={
                    "retrieval_mode": "hybrid",
                    "query_embedding": embedded.vectors[0],
                    "embedding_model": model,
                }
            ),
            metadata={"remote_embedding_model": model},
        )

    @app.post(
        "/memories/search/remote-guarded-hybrid",
        response_model=RemoteGuardedSearchResult,
    )
    def remote_guarded_hybrid(
        input: RemoteGuardedHybridSearchRequest,
    ) -> RemoteGuardedSearchResult:
        try:
            return remote_guarded_hybrid_search(
                app.state.runtime.memories,
                app.state.runtime.remote_embedding(),
                query=input.query,
                scopes=input.scopes,
                memory_types=input.memory_types,
                model=input.embedding_model,
                limit=input.limit,
                guard_top_k=input.guard_top_k,
                min_similarity=input.guard_min_similarity,
                ambiguity_margin=input.guard_ambiguity_margin,
            )
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post(
        "/memories/search/remote-llm-guarded-hybrid",
        response_model=RemoteLLMGuardedSearchResult,
    )
    def remote_llm_guarded_hybrid(
        input: RemoteGuardedHybridSearchRequest,
    ) -> RemoteLLMGuardedSearchResult:
        try:
            return remote_llm_guarded_hybrid_search(
                app.state.runtime.memories,
                app.state.runtime.remote_embedding(),
                app.state.runtime.remote_llm(),
                query=input.query,
                scopes=input.scopes,
                memory_types=input.memory_types,
                model=input.embedding_model,
                limit=input.limit,
                guard_top_k=input.guard_top_k,
                min_similarity=input.guard_min_similarity,
                ambiguity_margin=input.guard_ambiguity_margin,
            )
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post(
        "/memories/search/remote-selective-llm-guarded-hybrid",
        response_model=RemoteLLMGuardedSearchResult,
    )
    def remote_selective_llm_guarded_hybrid(
        input: RemoteGuardedHybridSearchRequest,
    ) -> RemoteLLMGuardedSearchResult:
        try:
            return remote_selective_llm_guarded_hybrid_search(
                app.state.runtime.memories,
                app.state.runtime.remote_embedding(),
                app.state.runtime.remote_llm(),
                query=input.query,
                scopes=input.scopes,
                memory_types=input.memory_types,
                model=input.embedding_model,
                limit=input.limit,
                guard_top_k=input.guard_top_k,
                min_similarity=input.guard_min_similarity,
                ambiguity_margin=input.guard_ambiguity_margin,
                selective_min_similarity=input.selective_min_similarity,
                selective_ambiguity_margin=input.selective_ambiguity_margin,
            )
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/memories/embeddings/remote-backfill", response_model=RemoteEmbeddingBackfillResult)
    def backfill_memory_embeddings(
        request: MemoryEmbeddingBackfillRequest,
    ) -> RemoteEmbeddingBackfillResult:
        try:
            return backfill_remote_memory_embeddings(
                app.state.runtime.memories,
                app.state.runtime.remote_embedding(),
                model=request.model,
                scope=request.scope,
                memory_type=request.memory_type,
                limit=request.limit,
                batch_size=request.batch_size,
                dry_run=request.dry_run,
            )
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/memories/{memory_id}/embedding/remote", response_model=MemoryEmbeddingRead)
    def index_memory_embedding(
        memory_id: str,
        request: MemoryEmbeddingIndexRequest,
    ) -> MemoryEmbeddingRead:
        memory = app.state.runtime.memories.get_memory(memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="memory not found")
        text = build_memory_embedding_text(memory)
        try:
            embedded = app.state.runtime.remote_embedding().embed_texts(
                [text],
                model=request.model,
            )
        except RemoteAdapterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        model = embedded.model or request.model
        if model is None:
            raise HTTPException(status_code=502, detail="remote embedding did not return a model")
        return app.state.runtime.memories.upsert_memory_embedding(
            memory.id,
            vector=embedded.vectors[0],
            model=model,
            embedded_text=text,
        )

    @app.get("/retrieval/logs", response_model=list[RetrievalLogRead])
    def list_retrieval_logs(
        source: RetrievalSource | None = None,
        scope: str | None = None,
        task_type: str | None = None,
        memory_id: str | None = None,
        limit: int = Query(default=100, ge=1),
        offset: int = Query(default=0, ge=0),
    ) -> list[RetrievalLogRead]:
        return app.state.runtime.memories.list_retrieval_logs(
            source=source,
            scope=scope,
            task_type=task_type,
            memory_id=memory_id,
            limit=limit,
            offset=offset,
        )

    @app.get("/retrieval/logs/{log_id}", response_model=RetrievalLogRead)
    def get_retrieval_log(log_id: str) -> RetrievalLogRead:
        log = app.state.runtime.memories.get_retrieval_log(log_id)
        if log is None:
            raise HTTPException(status_code=404, detail="retrieval log not found")
        return log

    @app.post("/retrieval/logs/{log_id}/feedback", response_model=RetrievalLogRead)
    def add_retrieval_feedback(
        log_id: str,
        request: RetrievalFeedbackRequest,
    ) -> RetrievalLogRead:
        try:
            return app.state.runtime.memories.add_retrieval_feedback(
                log_id,
                feedback=request.feedback,
                reason=request.reason,
            )
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="retrieval log not found") from exc

    @app.get("/memories/usage", response_model=list[MemoryUsageStatsRead])
    def list_memory_usage_stats(
        scope: str | None = None,
        memory_type: MemoryType | None = None,
        status: MemoryStatus | None = "active",
        recommended_action: MemoryMaintenanceAction | None = None,
        limit: int = Query(default=100, ge=1),
        offset: int = Query(default=0, ge=0),
    ) -> list[MemoryUsageStatsRead]:
        return app.state.runtime.memories.list_memory_usage_stats(
            scope=scope,
            memory_type=memory_type,
            status=status,
            recommended_action=recommended_action,
            limit=limit,
            offset=offset,
        )

    @app.get("/memories/{memory_id}/usage", response_model=MemoryUsageStatsRead)
    def get_memory_usage_stats(memory_id: str) -> MemoryUsageStatsRead:
        try:
            return app.state.runtime.memories.get_memory_usage_stats(memory_id)
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="memory not found") from exc

    @app.post(
        "/maintenance/reviews/from-usage",
        response_model=list[MaintenanceReviewItemRead],
    )
    def create_maintenance_reviews(
        request: MaintenanceReviewCreateRequest,
    ) -> list[MaintenanceReviewItemRead]:
        try:
            return app.state.runtime.memories.create_maintenance_reviews(
                scope=request.scope,
                memory_type=request.memory_type,
                recommended_action=request.recommended_action,
                limit=request.limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/maintenance/reviews", response_model=list[MaintenanceReviewItemRead])
    def list_maintenance_reviews(
        status: MaintenanceReviewStatus | None = None,
        recommended_action: MemoryMaintenanceAction | None = None,
        memory_id: str | None = None,
        limit: int = Query(default=100, ge=1),
        offset: int = Query(default=0, ge=0),
    ) -> list[MaintenanceReviewItemRead]:
        return app.state.runtime.memories.list_maintenance_reviews(
            status=status,
            recommended_action=recommended_action,
            memory_id=memory_id,
            limit=limit,
            offset=offset,
        )

    @app.get("/maintenance/reviews/{review_id}", response_model=MaintenanceReviewItemRead)
    def get_maintenance_review(review_id: str) -> MaintenanceReviewItemRead:
        review = app.state.runtime.memories.get_maintenance_review(review_id)
        if review is None:
            raise HTTPException(status_code=404, detail="maintenance review not found")
        return review

    @app.post(
        "/maintenance/reviews/{review_id}/resolve",
        response_model=MaintenanceReviewItemRead,
    )
    def resolve_maintenance_review(
        review_id: str,
        request: MaintenanceReviewResolveRequest,
    ) -> MaintenanceReviewItemRead:
        try:
            return app.state.runtime.memories.resolve_maintenance_review(
                review_id,
                action=request.action,
                reason=request.reason,
            )
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="maintenance review not found") from exc
        except MemoryPolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/memories/{memory_id}", response_model=MemoryItemRead)
    def get_memory(memory_id: str) -> MemoryItemRead:
        memory = app.state.runtime.memories.get_memory(memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail="memory not found")
        return memory

    @app.get("/memories/{memory_id}/versions", response_model=list[MemoryVersionRead])
    def list_memory_versions(memory_id: str) -> list[MemoryVersionRead]:
        if app.state.runtime.memories.get_memory(memory_id) is None:
            raise HTTPException(status_code=404, detail="memory not found")
        return app.state.runtime.memories.list_versions(memory_id)

    @app.post("/memories/{memory_id}/stale", response_model=MemoryItemRead)
    def mark_memory_stale(memory_id: str, request: ReviewRequest) -> MemoryItemRead:
        try:
            return app.state.runtime.memories.mark_stale(
                memory_id,
                reason=request.reason or "Marked stale through API.",
            )
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="memory not found") from exc
        except MemoryPolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/memories/{memory_id}/archive", response_model=MemoryItemRead)
    def archive_memory(memory_id: str, request: ReviewRequest) -> MemoryItemRead:
        try:
            return app.state.runtime.memories.archive_memory(
                memory_id,
                reason=request.reason or "Archived through API.",
            )
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="memory not found") from exc
        except MemoryPolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/memories/{memory_id}/supersede", response_model=MemoryItemRead)
    def supersede_memory(memory_id: str, request: SupersedeMemoryRequest) -> MemoryItemRead:
        try:
            return app.state.runtime.memories.supersede_memory(
                memory_id,
                request.candidate_id,
                reason=request.reason or "Superseded through API.",
            )
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MemoryPolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/graph/entities", response_model=MemoryEntityRead)
    def upsert_graph_entity(entity: MemoryEntityCreate) -> MemoryEntityRead:
        return app.state.runtime.memories.upsert_entity(entity)

    @app.get("/graph/entities", response_model=list[MemoryEntityRead])
    def list_graph_entities(
        query: str | None = None,
        scope: str | None = None,
        entity_type: str | None = None,
        limit: int = Query(default=100, ge=1),
        offset: int = Query(default=0, ge=0),
    ) -> list[MemoryEntityRead]:
        return app.state.runtime.memories.list_entities(
            query=query,
            scope=scope,
            entity_type=entity_type,
            limit=limit,
            offset=offset,
        )

    @app.get("/graph/entities/{entity_id}", response_model=MemoryEntityRead)
    def get_graph_entity(entity_id: str) -> MemoryEntityRead:
        entity = app.state.runtime.memories.get_entity(entity_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return entity

    @app.post("/graph/relations", response_model=MemoryRelationRead)
    def create_graph_relation(relation: MemoryRelationCreate) -> MemoryRelationRead:
        return app.state.runtime.memories.create_relation(relation)

    @app.get("/graph/relations", response_model=list[MemoryRelationRead])
    def list_graph_relations(
        from_id: str | None = None,
        to_id: str | None = None,
        connected_to_id: str | None = None,
        relation_type: str | None = None,
        limit: int = Query(default=100, ge=1),
        offset: int = Query(default=0, ge=0),
    ) -> list[MemoryRelationRead]:
        return app.state.runtime.memories.list_relations(
            from_id=from_id,
            to_id=to_id,
            connected_to_id=connected_to_id,
            relation_type=relation_type,
            limit=limit,
            offset=offset,
        )

    @app.get("/graph/conflicts", response_model=list[GraphConflictRead])
    def detect_graph_conflicts(
        scope: str | None = None,
        relation_type: str | None = None,
        limit: int = Query(default=100, ge=1),
    ) -> list[GraphConflictRead]:
        return app.state.runtime.memories.detect_graph_conflicts(
            scope=scope,
            relation_type=relation_type,
            limit=limit,
        )

    @app.post("/graph/conflict-reviews/from-conflicts", response_model=list[ConflictReviewItemRead])
    def create_conflict_reviews(
        request: ConflictReviewCreateRequest,
    ) -> list[ConflictReviewItemRead]:
        try:
            return app.state.runtime.memories.create_conflict_reviews(
                scope=request.scope,
                relation_type=request.relation_type,
                limit=request.limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/graph/conflict-reviews", response_model=list[ConflictReviewItemRead])
    def list_conflict_reviews(
        status: ConflictReviewStatus | None = None,
        scope: str | None = None,
        relation_type: str | None = None,
        limit: int = Query(default=100, ge=1),
        offset: int = Query(default=0, ge=0),
    ) -> list[ConflictReviewItemRead]:
        return app.state.runtime.memories.list_conflict_reviews(
            status=status,
            scope=scope,
            relation_type=relation_type,
            limit=limit,
            offset=offset,
        )

    @app.get("/graph/conflict-reviews/{review_id}", response_model=ConflictReviewItemRead)
    def get_conflict_review(review_id: str) -> ConflictReviewItemRead:
        review = app.state.runtime.memories.get_conflict_review(review_id)
        if review is None:
            raise HTTPException(status_code=404, detail="conflict review not found")
        return review

    @app.post(
        "/graph/conflict-reviews/{review_id}/resolve",
        response_model=ConflictReviewItemRead,
    )
    def resolve_conflict_review(
        review_id: str,
        request: ConflictReviewResolveRequest,
    ) -> ConflictReviewItemRead:
        try:
            return app.state.runtime.memories.resolve_conflict_review(
                review_id,
                action=request.action,
                keep_memory_ids=request.keep_memory_ids,
                reason=request.reason,
            )
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="conflict review not found") from exc
        except MemoryPolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/consolidation/propose", response_model=list[ConsolidationCandidateRead])
    def propose_consolidations(
        request: ConsolidationProposeRequest,
    ) -> list[ConsolidationCandidateRead]:
        try:
            return app.state.runtime.memories.propose_consolidations(
                scope=request.scope,
                memory_type=request.memory_type,
                min_group_size=request.min_group_size,
                limit=request.limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/consolidation/candidates", response_model=list[ConsolidationCandidateRead])
    def list_consolidation_candidates(
        status: ConsolidationStatus | None = None,
        scope: str | None = None,
        memory_type: MemoryType | None = None,
        limit: int = Query(default=100, ge=1),
        offset: int = Query(default=0, ge=0),
    ) -> list[ConsolidationCandidateRead]:
        return app.state.runtime.memories.list_consolidation_candidates(
            status=status,
            scope=scope,
            memory_type=memory_type,
            limit=limit,
            offset=offset,
        )

    @app.post("/consolidation/{candidate_id}/commit", response_model=MemoryItemRead)
    def commit_consolidation(candidate_id: str, request: ReviewRequest) -> MemoryItemRead:
        try:
            return app.state.runtime.memories.commit_consolidation(
                candidate_id,
                reason=request.reason,
            )
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="consolidation candidate not found") from exc
        except MemoryPolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/consolidation/{candidate_id}/reject", response_model=ConsolidationCandidateRead)
    def reject_consolidation(
        candidate_id: str,
        request: ReviewRequest,
    ) -> ConsolidationCandidateRead:
        try:
            return app.state.runtime.memories.reject_consolidation(
                candidate_id,
                reason=request.reason,
            )
        except MemoryNotFoundError as exc:
            raise HTTPException(status_code=404, detail="consolidation candidate not found") from exc
        except MemoryPolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/context/compose", response_model=ContextBlock)
    def compose_memory_context(request: ContextComposeRequest) -> ContextBlock:
        memories: list[MemoryItemRead] = []
        for memory_id in request.memory_ids:
            memory = app.state.runtime.memories.get_memory(memory_id)
            if memory is None:
                raise HTTPException(status_code=404, detail=f"memory not found: {memory_id}")
            memories.append(memory)
        session_items = []
        if request.include_session and request.session_limit > 0:
            memory_scopes = {memory.scope for memory in memories}
            session_scopes = request.session_scopes or list(memory_scopes)
            session_items = app.state.runtime.sessions.search(
                request.task,
                session_id=request.session_id,
                scopes=session_scopes,
                limit=request.session_limit,
            )

        block = (
            compose_context_with_session(
                request.task,
                session_items,
                memories,
                token_budget=request.token_budget,
            )
            if session_items
            else compose_context(
                request.task,
                memories,
                token_budget=request.token_budget,
            )
        )
        used_memory_ids = set(block.memory_ids)
        memory_scopes = {memory.scope for memory in memories}
        app.state.runtime.memories.record_retrieval_log(
            RetrievalLogCreate(
                query=request.task,
                task=request.task,
                task_type="context",
                scope=next(iter(memory_scopes)) if len(memory_scopes) == 1 else None,
                source="context",
                retrieved_memory_ids=request.memory_ids,
                used_memory_ids=block.memory_ids,
                skipped_memory_ids=[
                    memory.id for memory in memories if memory.id not in used_memory_ids
                ],
                warnings=block.warnings,
                metadata={
                    "token_budget": request.token_budget,
                    "include_session": request.include_session,
                    "session_id": request.session_id,
                    "session_limit": request.session_limit,
                    "session_memory_ids": block.metadata.get("session_memory_ids", ""),
                },
            )
        )
        return block

    @app.post("/recall/task", response_model=TaskRecallResult)
    def recall_task(request: TaskRecallRequest) -> TaskRecallResult:
        try:
            return recall_for_task(
                request.task,
                app.state.runtime.memories,
                scope=request.scope,
                token_budget=request.token_budget,
                limit_per_query=request.limit_per_query,
                session_store=app.state.runtime.sessions if request.include_session else None,
                session_id=request.session_id,
                session_limit=request.session_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/recall/graph", response_model=GraphRecallResult)
    def recall_graph(request: GraphRecallRequest) -> GraphRecallResult:
        try:
            return graph_recall_for_task(
                request.task,
                app.state.runtime.memories,
                scope=request.scope,
                token_budget=request.token_budget,
                max_depth=request.max_depth,
                limit=request.limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/recall/orchestrated", response_model=OrchestratedRecallResult)
    def recall_orchestrated(request: OrchestratedRecallRequest) -> OrchestratedRecallResult:
        remote_embedding = None
        remote_llm = None
        if request.use_remote or request.strategy in {
            "guarded_hybrid",
            "selective_llm_guarded_hybrid",
        }:
            try:
                remote_embedding = app.state.runtime.remote_embedding()
                if (
                    request.use_llm_judge
                    or request.use_remote_planner
                    or request.strategy == "selective_llm_guarded_hybrid"
                ):
                    remote_llm = app.state.runtime.remote_llm()
            except RemoteAdapterNotConfiguredError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        elif request.use_remote_planner:
            try:
                remote_llm = app.state.runtime.remote_llm()
            except RemoteAdapterNotConfiguredError:
                remote_llm = None
        try:
            return orchestrate_recall(
                request.task,
                app.state.runtime.memories,
                scope=request.scope,
                strategy=request.strategy,
                token_budget=request.token_budget,
                limit=request.limit,
                memory_types=request.memory_types,
                include_graph=request.include_graph,
                remote_embedding=remote_embedding,
                remote_llm=remote_llm,
                model=request.model,
                guard_top_k=request.guard_top_k,
                guard_min_similarity=request.guard_min_similarity,
                guard_ambiguity_margin=request.guard_ambiguity_margin,
                selective_min_similarity=request.selective_min_similarity,
                selective_ambiguity_margin=request.selective_ambiguity_margin,
                session_store=app.state.runtime.sessions if request.include_session else None,
                session_id=request.session_id,
                session_limit=request.session_limit,
                session_scopes=request.session_scopes or None,
            )
        except RemoteAdapterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
