from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from pydantic import ValidationError

from memory_system.schemas import (
    EventRead,
    MemoryCandidateCreate,
    MemoryItemRead,
    MemoryType,
    RemoteAdapterConfigRead,
    RemoteCandidateExtractionResult,
    RemoteEmbeddingResult,
    RemoteRecallJudgeResult,
    RemoteRetrievalGuardDecisionRead,
    RetrievalGuardDecision,
    Risk,
)

DEFAULT_LLM_MODEL = "qwen3.6-flash"
DEFAULT_EMBEDDING_MODEL = "tongyi-embedding-vision-flash-2026-03-06"
GENERIC_COMPATIBILITY = "generic"
OPENAI_COMPATIBILITY = "openai_compatible"
DASHSCOPE_MULTIMODAL_COMPATIBILITY = "dashscope_multimodal"
DASHSCOPE_MULTIMODAL_EMBEDDING_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)
REMOTE_SENSITIVE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\[REDACTED\]",
        r"\btoken\b",
        r"\bsecret\b",
        r"\bapi[-_ ]?key\b",
        r"\bpassword\b",
        r"\bcookie\b",
        r"\bbearer\b",
        r"\bauthorization\b",
    )
)
REMOTE_RECALL_SENSITIVE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\[REDACTED\]",
        r"\btoken\s*[:=]\s*\S+",
        r"\bsecret\s*[:=]\s*\S+",
        r"\bapi[-_ ]?key\s*[:=]\s*\S+",
        r"\bpassword\s*[:=]\s*\S+",
        r"\bcookie\s*[:=]\s*\S+",
        r"\bauthorization\s*[:=]\s*\S+",
        r"\bbearer\s+[A-Za-z0-9._-]{8,}",
    )
)
REMOTE_TROUBLESHOOTING_CUES = (
    "\u95ee\u9898",
    "\u7ecf\u9a8c",
    "\u89e3\u51b3\u65b9\u5f0f",
)
REMOTE_VERIFIED_CUES = (
    "\u5df2\u786e\u8ba4",
    "\u786e\u8ba4",
    "\u5df2\u9a8c\u8bc1",
    "\u9a8c\u8bc1\u901a\u8fc7",
    "passed",
)
REMOTE_ENVIRONMENT_CUES = (
    "\u73af\u5883",
    "\u5f00\u53d1\u73af\u5883",
    "\u8fd0\u884c\u73af\u5883",
    "\u9879\u76ee\u76ee\u5f55",
    "\u5f53\u524d\u9879\u76ee",
    "\u5f53\u524d\u5de5\u4f5c\u533a",
    "\u9ed8\u8ba4 shell",
    "powershell",
    "shell",
    "code page",
    "chcp",
    "windows",
    "version",
    "\u7248\u672c",
)
REMOTE_ENVIRONMENT_SOFT_CUES = (
    "python",
    "pytest",
    "sqlite",
)
REMOTE_PROJECT_CONTEXT_CUES = (
    "\u5f53\u524d\u9879\u76ee",
    "\u672c\u9879\u76ee",
    "\u5f53\u524d\u5de5\u4f5c\u533a",
)
REMOTE_TOOL_RULE_CUES = (
    "\u56fa\u5b9a\u4f7f\u7528",
    "\u547d\u4ee4\u662f",
    "\u542f\u52a8\u547d\u4ee4",
    "\u683c\u5f0f\u68c0\u67e5",
    "\u5b89\u88c5",
    "python -m",
    "ruff check",
    "uvicorn",
    "pip install",
)
REMOTE_CASUAL_CONTEXT_CUES = (
    "\u521a\u624d",
    "\u4eca\u5929",
    "\u4eca\u665a",
    "\u4e0b\u5348",
    "\u4e0a\u5348",
    "\u73b0\u5728",
    "\u672c\u8f6e",
    "right now",
    "today",
)
REMOTE_EXPLICIT_MEMORY_CUES = (
    "\u8bb0\u4f4f",
    "\u4ee5\u540e",
    "\u9ed8\u8ba4",
    "\u504f\u597d",
    "\u59cb\u7ec8",
    "remember",
    "default",
    "prefer",
    "always",
)
REMOTE_POLICY_PREFERENCE_CUES = (
    "\u8bb0\u5fc6",
    "\u957f\u671f\u8bb0\u5fc6",
    "\u4e00\u6b21\u6027",
    "\u654f\u611f\u4fe1\u606f",
    "memory",
    "sensitive",
)
REMOTE_IMPORT_REVIEW_WORKFLOW_CUES = (
    "\u5bfc\u5165\u8fdc\u7a0b\u5019\u9009",
    "\u8fdc\u7a0b\u5019\u9009",
    "\u4eba\u5de5\u5ba1\u67e5",
    "\u4e0d\u81ea\u52a8\u63d0\u4ea4",
    "\u4e0d\u81ea\u52a8\u5199\u5165",
    "remote candidate",
    "manual review",
)
REMOTE_WORKFLOW_CUES = (
    "\u53d1\u5e03\u524d",
    "\u4e0a\u7ebf\u524d",
    "\u56fa\u5b9a\u6d41\u7a0b",
    "\u6d41\u7a0b",
    "\u8981\u5148\u8fd0\u884c",
    "\u5148\u8fd0\u884c",
    "\u6bcf\u6b21",
    "\u68c0\u67e5\u6e05\u5355",
    "pre-release",
    "pre release",
    "before release",
    "release checklist",
    "workflow",
)


class RemoteAdapterError(RuntimeError):
    """Raised when a remote adapter call fails."""


class RemoteAdapterNotConfiguredError(RemoteAdapterError):
    """Raised when a remote adapter is used without a base URL."""


@dataclass(frozen=True)
class RemoteAdapterConfig:
    base_url: str | None = None
    api_key: str | None = None
    compatibility: str = GENERIC_COMPATIBILITY
    embedding_compatibility: str = GENERIC_COMPATIBILITY
    timeout_seconds: float = 30.0
    llm_extract_path: str = "/memory/extract"
    embedding_path: str = "/embeddings"
    health_path: str = "/health"
    llm_model: str = DEFAULT_LLM_MODEL
    embedding_model: str = DEFAULT_EMBEDDING_MODEL

    def __post_init__(self) -> None:
        compatibility = _resolve_compatibility(
            self.compatibility,
            base_url=self.base_url,
            using_dashscope_env=False,
        )
        object.__setattr__(self, "compatibility", compatibility)
        if compatibility == OPENAI_COMPATIBILITY and self.llm_extract_path == "/memory/extract":
            object.__setattr__(self, "llm_extract_path", "/chat/completions")
        if compatibility == OPENAI_COMPATIBILITY and self.health_path == "/health":
            object.__setattr__(self, "health_path", "/models")
        if self.embedding_compatibility not in {
            GENERIC_COMPATIBILITY,
            OPENAI_COMPATIBILITY,
            DASHSCOPE_MULTIMODAL_COMPATIBILITY,
        }:
            object.__setattr__(self, "embedding_compatibility", GENERIC_COMPATIBILITY)

    @classmethod
    def from_env(cls, prefix: str = "MEMORY_REMOTE") -> RemoteAdapterConfig:
        timeout = os.environ.get(f"{prefix}_TIMEOUT_SECONDS", "30")
        try:
            timeout_seconds = float(timeout)
        except ValueError:
            timeout_seconds = 10.0

        base_url = _optional_text(os.environ.get(f"{prefix}_BASE_URL"))
        api_key = _optional_text(os.environ.get(f"{prefix}_API_KEY"))
        dashscope_base_url = _optional_text(os.environ.get("DASHSCOPE_BASE_URL"))
        dashscope_api_key = _optional_text(os.environ.get("DASHSCOPE_API_KEY"))
        using_dashscope_env = base_url is None and dashscope_base_url is not None
        base_url = base_url or dashscope_base_url
        api_key = api_key or dashscope_api_key
        compatibility = _resolve_compatibility(
            os.environ.get(f"{prefix}_COMPATIBILITY"),
            base_url=base_url,
            using_dashscope_env=using_dashscope_env,
        )
        default_llm_path = (
            "/chat/completions"
            if compatibility == OPENAI_COMPATIBILITY
            else "/memory/extract"
        )
        default_health_path = "/models" if compatibility == OPENAI_COMPATIBILITY else "/health"
        embedding_compatibility = _resolve_embedding_compatibility(
            os.environ.get(f"{prefix}_EMBEDDING_COMPATIBILITY"),
            compatibility=compatibility,
            embedding_model=DEFAULT_EMBEDDING_MODEL,
            using_dashscope_env=using_dashscope_env,
        )
        default_embedding_path = (
            DASHSCOPE_MULTIMODAL_EMBEDDING_URL
            if embedding_compatibility == DASHSCOPE_MULTIMODAL_COMPATIBILITY
            else "/embeddings"
        )

        return cls(
            base_url=base_url,
            api_key=api_key,
            compatibility=compatibility,
            embedding_compatibility=embedding_compatibility,
            timeout_seconds=timeout_seconds,
            llm_extract_path=os.environ.get(f"{prefix}_LLM_EXTRACT_PATH", default_llm_path),
            embedding_path=os.environ.get(f"{prefix}_EMBEDDING_PATH", default_embedding_path),
            health_path=os.environ.get(f"{prefix}_HEALTH_PATH", default_health_path),
            llm_model=DEFAULT_LLM_MODEL,
            embedding_model=DEFAULT_EMBEDDING_MODEL,
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def to_read_model(self) -> RemoteAdapterConfigRead:
        return RemoteAdapterConfigRead(
            configured=self.configured,
            base_url=self.base_url.rstrip("/") if self.base_url else None,
            compatibility=self.compatibility,
            embedding_compatibility=self.embedding_compatibility,
            timeout_seconds=self.timeout_seconds,
            api_key_configured=bool(self.api_key),
            llm_extract_path=self.llm_extract_path,
            embedding_path=self.embedding_path,
            health_path=self.health_path,
            llm_model=self.llm_model,
            embedding_model=self.embedding_model,
        )


class RemoteHTTPClient:
    def __init__(self, config: RemoteAdapterConfig) -> None:
        self.config = config

    def get_json(self, path: str) -> Any:
        return self._request_json("GET", path)

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request_json("POST", path, payload)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        if not self.config.base_url:
            raise RemoteAdapterNotConfiguredError(
                "MEMORY_REMOTE_BASE_URL or DASHSCOPE_BASE_URL is not configured"
            )

        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        request = urllib_request.Request(
            _join_url(self.config.base_url, path),
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib_request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RemoteAdapterError(f"remote returned HTTP {exc.code}: {detail[:300]}") from exc
        except urllib_error.URLError as exc:
            raise RemoteAdapterError(f"remote request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RemoteAdapterError("remote request timed out") from exc

        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RemoteAdapterError("remote returned invalid JSON") from exc


class RemoteLLMClient:
    def __init__(
        self,
        config: RemoteAdapterConfig | None = None,
        http: RemoteHTTPClient | None = None,
    ) -> None:
        self.config = config or RemoteAdapterConfig.from_env()
        self.http = http or RemoteHTTPClient(self.config)

    def health(self) -> Any:
        return self.http.get_json(self.config.health_path)

    def extract_candidates(
        self,
        event: EventRead,
        *,
        instructions: str | None = None,
    ) -> RemoteCandidateExtractionResult:
        resolved_instructions = _with_remote_governance_instructions(
            instructions
            or (
                "Return JSON with a candidates array using the MemoryCandidateCreate schema. "
                "Only propose long-term, reusable, non-sensitive memories."
            )
        )
        if event.sanitized or _contains_sensitive_remote_text(event.content):
            return RemoteCandidateExtractionResult(
                provider="remote",
                candidates=[],
                warnings=["filtered_sensitive_remote_event"],
                metadata={"skipped_remote_call": True},
            )
        if self.config.compatibility == OPENAI_COMPATIBILITY:
            raw = self.http.post_json(
                self.config.llm_extract_path,
                _build_openai_extraction_payload(event, self.config.llm_model, resolved_instructions),
            )
            raw = _parse_openai_chat_json(raw)
            return _parse_candidate_extraction(raw, event)

        payload = {
            "schema": "memory_system.remote_candidate_extraction.v1",
            "model": self.config.llm_model,
            "event": event.model_dump(mode="json"),
            "instructions": resolved_instructions,
        }
        raw = self.http.post_json(self.config.llm_extract_path, payload)
        return _parse_candidate_extraction(raw, event)

    def judge_retrieval(
        self,
        *,
        query: str,
        memories: list[MemoryItemRead],
        local_decisions: list[RemoteRetrievalGuardDecisionRead] | None = None,
        scopes: list[str] | None = None,
        task: str | None = None,
        instructions: str | None = None,
    ) -> RemoteRecallJudgeResult:
        allowed_memory_ids = [memory.id for memory in memories]
        if not query.strip():
            return RemoteRecallJudgeResult(
                provider="remote",
                model=self.config.llm_model,
                query=query,
                decision="rejected",
                reason="Empty query cannot recall a memory.",
                warnings=["empty_query_skipped_remote_recall_judge"],
                metadata={"skipped_remote_call": True},
            )
        if _contains_sensitive_remote_recall_text(query):
            return RemoteRecallJudgeResult(
                provider="remote",
                model=self.config.llm_model,
                query=query,
                decision="rejected",
                reason="Sensitive recall query was not sent to the remote model.",
                warnings=["filtered_sensitive_recall_query"],
                metadata={"skipped_remote_call": True},
            )

        filtered_memories = [
            memory
            for memory in memories
            if not _contains_sensitive_remote_recall_text(memory.subject)
            and not _contains_sensitive_remote_recall_text(memory.content)
        ]
        filtered_ids = [memory.id for memory in filtered_memories]
        warnings: list[str] = []
        if len(filtered_memories) != len(memories):
            warnings.append("filtered_sensitive_recall_candidate")
        if not filtered_memories:
            return RemoteRecallJudgeResult(
                provider="remote",
                model=self.config.llm_model,
                query=query,
                decision="rejected",
                reason="No safe candidate memories were available for remote recall judging.",
                warnings=[*warnings, "no_recall_candidates"],
                metadata={
                    "skipped_remote_call": True,
                    "candidate_memory_ids": allowed_memory_ids,
                },
            )

        resolved_instructions = _with_remote_recall_judge_instructions(instructions)
        payload = _build_recall_judge_payload(
            query=query,
            memories=filtered_memories,
            local_decisions=local_decisions or [],
            scopes=scopes or [],
            task=task,
            instructions=resolved_instructions,
            model=self.config.llm_model,
        )
        if self.config.compatibility == OPENAI_COMPATIBILITY:
            raw = self.http.post_json(
                self.config.llm_extract_path,
                _build_openai_recall_judge_payload(payload, self.config.llm_model),
            )
            raw = _parse_openai_chat_json(raw)
        else:
            raw = self.http.post_json(self.config.llm_extract_path, payload)
        result = _parse_recall_judge_result(raw, query=query, allowed_memory_ids=filtered_ids)
        if warnings:
            result = result.model_copy(update={"warnings": [*warnings, *result.warnings]})
        return result if result.model else result.model_copy(update={"model": self.config.llm_model})


class RemoteEmbeddingClient:
    def __init__(
        self,
        config: RemoteAdapterConfig | None = None,
        http: RemoteHTTPClient | None = None,
    ) -> None:
        self.config = config or RemoteAdapterConfig.from_env()
        self.http = http or RemoteHTTPClient(self.config)

    def embed_texts(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RemoteEmbeddingResult:
        normalized_texts = [text.strip() for text in texts if text.strip()]
        if not normalized_texts:
            raise ValueError("texts must not be empty")

        resolved_model = model or self.config.embedding_model
        if self.config.embedding_compatibility == DASHSCOPE_MULTIMODAL_COMPATIBILITY:
            raw = self.http.post_json(
                self.config.embedding_path,
                {
                    "model": resolved_model,
                    "input": {
                        "contents": [{"text": text} for text in normalized_texts],
                    },
                },
            )
            return _parse_embedding_result(raw).model_copy(update={"model": resolved_model})

        if self.config.compatibility == OPENAI_COMPATIBILITY:
            raw = self.http.post_json(
                self.config.embedding_path,
                {
                    "model": resolved_model,
                    "input": normalized_texts,
                },
            )
            result = _parse_embedding_result(raw)
            return result if result.model else result.model_copy(update={"model": resolved_model})

        raw = self.http.post_json(
            self.config.embedding_path,
            {
                "schema": "memory_system.remote_embedding.v1",
                "texts": normalized_texts,
                "model": resolved_model,
                "metadata": metadata or {},
            },
        )
        result = _parse_embedding_result(raw)
        return result if result.model else result.model_copy(update={"model": resolved_model})


def _parse_candidate_extraction(raw: Any, event: EventRead) -> RemoteCandidateExtractionResult:
    provider = "remote"
    warnings: list[str] = []
    metadata: dict[str, Any] = {}

    if isinstance(raw, list):
        candidates_raw = raw
    elif isinstance(raw, dict):
        provider = str(raw.get("provider") or provider)
        warnings = _string_list(raw.get("warnings", []))
        metadata_value = raw.get("metadata", {})
        metadata = metadata_value if isinstance(metadata_value, dict) else {"value": metadata_value}
        candidates_raw = raw.get("candidates", raw.get("memory_candidates", []))
    else:
        raise RemoteAdapterError("remote extraction response must be an object or list")

    if not isinstance(candidates_raw, list):
        raise RemoteAdapterError("remote extraction response must contain a candidates list")

    candidates: list[MemoryCandidateCreate] = []
    for item in candidates_raw:
        if not isinstance(item, dict):
            raise RemoteAdapterError("remote candidate must be an object")
        try:
            candidates.append(MemoryCandidateCreate.model_validate(_with_event_defaults(item, event)))
        except ValidationError as exc:
            raise RemoteAdapterError(f"remote candidate did not match schema: {exc}") from exc
    candidates, governance_warnings = _govern_remote_candidates(candidates, event)
    warnings.extend(governance_warnings)
    if not candidates:
        candidates, fallback_warnings = _remote_fallback_candidates(event)
        warnings.extend(fallback_warnings)

    return RemoteCandidateExtractionResult(
        provider=provider,
        candidates=candidates,
        warnings=warnings,
        metadata=metadata,
    )


def _build_recall_judge_payload(
    *,
    query: str,
    memories: list[MemoryItemRead],
    local_decisions: list[RemoteRetrievalGuardDecisionRead],
    scopes: list[str],
    task: str | None,
    instructions: str,
    model: str,
) -> dict[str, Any]:
    decision_by_id = {decision.memory_id: decision for decision in local_decisions}
    candidates: list[dict[str, Any]] = []
    for rank, memory in enumerate(memories, start=1):
        local = decision_by_id.get(memory.id)
        payload: dict[str, Any] = {
            "memory_id": memory.id,
            "subject": memory.subject,
            "content": memory.content,
            "memory_type": memory.memory_type,
            "scope": memory.scope,
            "confidence": memory.confidence,
            "status": memory.status,
            "tags": memory.tags,
            "rank": local.rank if local else rank,
        }
        if local:
            payload.update(
                {
                    "local_decision": local.decision,
                    "local_reason": local.reason,
                    "similarity": local.similarity,
                    "score_margin": local.score_margin,
                    "intent_score": local.intent_score,
                }
            )
        candidates.append(payload)
    return {
        "schema": "memory_system.remote_recall_judge.v1",
        "model": model,
        "query": query,
        "scopes": scopes,
        "task": task,
        "instructions": instructions,
        "candidates": candidates,
        "output": {
            "provider": "string",
            "decision": "accepted|ambiguous|rejected",
            "selected_memory_ids": ["string"],
            "reason": "string",
            "risk": "low|medium|high",
            "warnings": ["string"],
            "metadata": {},
        },
    }


def _parse_recall_judge_result(
    raw: Any,
    *,
    query: str,
    allowed_memory_ids: list[str],
) -> RemoteRecallJudgeResult:
    if not isinstance(raw, dict):
        raise RemoteAdapterError("remote recall judge response must be an object")

    provider = str(raw.get("provider") or "remote")
    model = raw.get("model") if isinstance(raw.get("model"), str) else None
    warnings = _string_list(raw.get("warnings", []))
    metadata_value = raw.get("metadata", {})
    metadata = metadata_value if isinstance(metadata_value, dict) else {"value": metadata_value}
    metadata.setdefault("allowed_memory_ids", allowed_memory_ids)

    decision_raw = str(raw.get("decision") or "ambiguous").strip().lower()
    decision: RetrievalGuardDecision
    if decision_raw in {"accepted", "ambiguous", "rejected"}:
        decision = decision_raw  # type: ignore[assignment]
    else:
        decision = "ambiguous"
        warnings.append(f"invalid_recall_judge_decision:{decision_raw}")

    selected_raw = raw.get("selected_memory_ids", raw.get("memory_ids", []))
    selected = _string_list(selected_raw)
    unknown_selected = [memory_id for memory_id in selected if memory_id not in allowed_memory_ids]
    if unknown_selected:
        warnings.append("filtered_unknown_selected_memory_ids")
    selected = [memory_id for memory_id in selected if memory_id in allowed_memory_ids]

    if decision == "accepted" and not selected:
        decision = "ambiguous"
        warnings.append("accepted_without_selected_memory")
    if decision != "accepted":
        selected = []

    risk_raw = str(raw.get("risk") or "medium").strip().lower()
    risk: Risk = risk_raw if risk_raw in {"low", "medium", "high"} else "medium"  # type: ignore[assignment]
    reason = str(raw.get("reason") or "Remote recall judge returned no reason.").strip()
    return RemoteRecallJudgeResult(
        provider=provider,
        model=model,
        query=query,
        decision=decision,
        selected_memory_ids=selected,
        reason=reason,
        risk=risk,
        warnings=warnings,
        metadata=metadata,
    )


def _govern_remote_candidates(
    candidates: list[MemoryCandidateCreate],
    event: EventRead,
) -> tuple[list[MemoryCandidateCreate], list[str]]:
    warnings: list[str] = []
    if _contains_sensitive_remote_text(event.content):
        if candidates:
            warnings.append("filtered_sensitive_remote_event")
        return [], warnings

    governed: list[MemoryCandidateCreate] = []
    for candidate in candidates:
        if _contains_sensitive_remote_text(candidate.content) or _contains_sensitive_remote_text(
            candidate.claim or ""
        ):
            warnings.append("filtered_sensitive_remote_candidate")
            continue
        if _is_remote_casual_preference_noise(event.content, candidate):
            warnings.append("filtered_casual_remote_preference")
            continue

        normalized_type = _preferred_remote_memory_type(event)
        if normalized_type and normalized_type != candidate.memory_type:
            warnings.append(
                f"normalized_remote_candidate_type:{candidate.memory_type}->{normalized_type}"
            )
            candidate = candidate.model_copy(update={"memory_type": normalized_type})
        governed.append(candidate)

    return governed, warnings


def _remote_fallback_candidates(
    event: EventRead,
) -> tuple[list[MemoryCandidateCreate], list[str]]:
    if event.sanitized or _contains_sensitive_remote_text(event.content):
        return [], []
    if _is_remote_policy_preference(event.content):
        return [
            _build_remote_fallback_candidate(
                event,
                memory_type="user_preference",
                subject="memory governance preference",
                reason="Local remote governance fallback captured a stable memory policy preference.",
                reuse_cases=["memory_governance", "future_responses"],
                time_validity="persistent",
            )
        ], ["local_remote_fallback:user_preference"]
    if _is_remote_import_review_workflow(event.content, event.scope):
        return [
            _build_remote_fallback_candidate(
                event,
                memory_type="workflow",
                subject="remote candidate import review",
                reason="Local remote governance fallback captured a fixed remote-import workflow.",
                reuse_cases=["remote_import", "memory_governance"],
                time_validity="persistent",
            )
        ], ["local_remote_fallback:workflow"]
    return [], []


def _build_remote_fallback_candidate(
    event: EventRead,
    *,
    memory_type: MemoryType,
    subject: str,
    reason: str,
    reuse_cases: list[str],
    time_validity: str,
) -> MemoryCandidateCreate:
    return MemoryCandidateCreate(
        content=event.content,
        memory_type=memory_type,
        scope=event.scope,
        subject=subject,
        source_event_ids=[event.id],
        reason=reason,
        claim=event.content,
        evidence_type=_event_evidence_type(event),
        time_validity=time_validity,
        reuse_cases=reuse_cases,
        scores={
            "long_term": 0.85,
            "evidence": 0.9,
            "reuse": 0.8,
            "risk": 0.2,
            "specificity": 0.75,
        },
        confidence="confirmed",
        risk="low",
    )


def _preferred_remote_memory_type(event: EventRead) -> MemoryType | None:
    content = event.content
    if _is_remote_troubleshooting(content):
        return "troubleshooting"
    if _is_remote_workflow(content, event.scope):
        return "workflow"
    if _is_remote_environment_fact(content):
        return "environment_fact"
    if _is_remote_tool_rule(content):
        return "tool_rule"
    if _is_remote_verified_project_fact(event):
        return "project_fact"
    return None


def _is_remote_troubleshooting(content: str) -> bool:
    lowered = content.lower()
    return all(cue.lower() in lowered for cue in REMOTE_TROUBLESHOOTING_CUES) and any(
        cue.lower() in lowered for cue in REMOTE_VERIFIED_CUES
    )


def _is_remote_environment_fact(content: str) -> bool:
    lowered = content.lower()
    has_verified_cue = any(cue.lower() in lowered for cue in REMOTE_VERIFIED_CUES)
    has_environment_cue = any(cue.lower() in lowered for cue in REMOTE_ENVIRONMENT_CUES)
    has_contextual_soft_cue = any(
        cue.lower() in lowered for cue in REMOTE_PROJECT_CONTEXT_CUES
    ) and any(cue.lower() in lowered for cue in REMOTE_ENVIRONMENT_SOFT_CUES)
    if _is_remote_tool_rule(content) and not (has_environment_cue or has_contextual_soft_cue):
        return False
    return has_verified_cue and (has_environment_cue or has_contextual_soft_cue)


def _is_remote_workflow(content: str, scope: str) -> bool:
    lowered = content.lower()
    if not scope.lower().startswith("repo:"):
        return False
    return any(cue.lower() in lowered for cue in REMOTE_WORKFLOW_CUES)


def _is_remote_tool_rule(content: str) -> bool:
    lowered = content.lower()
    return any(cue.lower() in lowered for cue in REMOTE_TOOL_RULE_CUES)


def _is_remote_casual_preference_noise(
    content: str,
    candidate: MemoryCandidateCreate,
) -> bool:
    if candidate.memory_type != "user_preference":
        return False
    lowered = content.lower()
    has_casual_context = any(cue.lower() in lowered for cue in REMOTE_CASUAL_CONTEXT_CUES)
    has_explicit_memory_cue = any(
        cue.lower() in lowered for cue in REMOTE_EXPLICIT_MEMORY_CUES
    )
    return has_casual_context and not has_explicit_memory_cue


def _is_remote_policy_preference(content: str) -> bool:
    lowered = content.lower()
    has_explicit_memory_cue = any(
        cue.lower() in lowered for cue in REMOTE_EXPLICIT_MEMORY_CUES
    )
    has_policy_cue = any(cue.lower() in lowered for cue in REMOTE_POLICY_PREFERENCE_CUES)
    return has_explicit_memory_cue and has_policy_cue


def _is_remote_import_review_workflow(content: str, scope: str) -> bool:
    if not scope.lower().startswith("repo:"):
        return False
    lowered = content.lower()
    return all(
        any(cue.lower() in lowered for cue in group)
        for group in (
            ("\u8fdc\u7a0b\u5019\u9009", "remote candidate"),
            ("\u4eba\u5de5\u5ba1\u67e5", "manual review"),
            ("\u4e0d\u81ea\u52a8\u63d0\u4ea4", "\u4e0d\u81ea\u52a8\u5199\u5165"),
        )
    )


def _is_remote_verified_project_fact(event: EventRead) -> bool:
    if event.event_type not in {"file_observation", "tool_result", "test_result"}:
        return False
    lowered = event.content.lower()
    return any(cue.lower() in lowered for cue in REMOTE_VERIFIED_CUES)


def _contains_sensitive_remote_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in REMOTE_SENSITIVE_PATTERNS)


def _contains_sensitive_remote_recall_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in REMOTE_RECALL_SENSITIVE_PATTERNS)


def _event_evidence_type(event: EventRead) -> str:
    if event.event_type in {"file_observation", "tool_result", "test_result", "user_confirmation"}:
        return event.event_type
    if event.event_type == "user_message":
        return "direct_user_statement"
    return "unknown"


def _with_remote_governance_instructions(instructions: str) -> str:
    governance = (
        " Governance rules: produce no candidate for sensitive [REDACTED]/token/secret/"
        "api key/password/cookie/bearer/authorization content; prefer troubleshooting "
        "for verified problem/experience/solution records; prefer environment_fact for "
        "confirmed runtime or machine state; prefer workflow for fixed repo processes; "
        "prefer project_fact for verified source observations; prefer tool_rule for fixed commands; "
        "reject casual same-day likes unless explicitly stable."
    )
    return f"{instructions.rstrip()}{governance}"


def _with_remote_recall_judge_instructions(instructions: str | None) -> str:
    base = instructions or (
        "Judge whether the provided memory candidates should be recalled for the query. "
        "Return only JSON. Do not invent memory IDs or facts."
    )
    governance = (
        " Recall governance rules: return rejected when no candidate directly answers the query; "
        "return rejected for requests about secrets, tokens, passwords, private credentials, or unknown private facts; "
        "return ambiguous when several candidates are plausibly relevant or when the answer needs current verification; "
        "return accepted only when selected_memory_ids are directly supported by the provided candidates; "
        "treat local_decision=accepted as a strong signal and keep it unless the candidate is clearly unrelated; "
        "select only candidate memory_id values from the request."
    )
    return f"{base.rstrip()}{governance}"


def _parse_embedding_result(raw: Any) -> RemoteEmbeddingResult:
    provider = "remote"
    model = None
    metadata: dict[str, Any] = {}

    if not isinstance(raw, dict):
        raise RemoteAdapterError("remote embedding response must be an object")

    provider = str(raw.get("provider") or provider)
    if isinstance(raw.get("model"), str):
        model = raw["model"]
    metadata_value = raw.get("metadata", {})
    metadata = metadata_value if isinstance(metadata_value, dict) else {"value": metadata_value}

    vectors_raw = raw.get("vectors")
    if vectors_raw is None and isinstance(raw.get("data"), list):
        vectors_raw = [item.get("embedding") for item in raw["data"] if isinstance(item, dict)]
    if vectors_raw is None and isinstance(raw.get("output"), dict):
        output_embeddings = raw["output"].get("embeddings")
        if isinstance(output_embeddings, list):
            vectors_raw = [
                item.get("embedding") for item in output_embeddings if isinstance(item, dict)
            ]
    if not isinstance(vectors_raw, list):
        raise RemoteAdapterError("remote embedding response must contain vectors")

    vectors = [_float_vector(vector) for vector in vectors_raw]
    dimensions = len(vectors[0]) if vectors else 0
    if any(len(vector) != dimensions for vector in vectors):
        raise RemoteAdapterError("remote embedding vectors must have consistent dimensions")

    return RemoteEmbeddingResult(
        provider=provider,
        vectors=vectors,
        model=model,
        dimensions=dimensions,
        metadata=metadata,
    )


def _build_openai_extraction_payload(
    event: EventRead,
    model: str,
    instructions: str,
) -> dict[str, Any]:
    user_payload = {
        "schema": "memory_system.remote_candidate_extraction.v1",
        "event": event.model_dump(mode="json"),
        "instructions": instructions,
        "governance_rules": [
            "Return an empty candidates array for one-off requests, temporary state, guesses, or sensitive content.",
            "Do not propose candidates when the event mentions [REDACTED], token, secret, api key, password, cookie, bearer, or authorization values.",
            "Do not turn casual same-day likes or chatty context into user_preference unless the user explicitly asks to remember it or states a stable preference.",
            "If the event uses the structure '\u95ee\u9898 / \u7ecf\u9a8c / \u89e3\u51b3\u65b9\u5f0f' and says '\u9a8c\u8bc1\u901a\u8fc7' or equivalent, prefer memory_type='troubleshooting'.",
            "If the event confirms runtime or machine state, such as PowerShell, code page, Windows, Python, pytest, SQLite, paths, or shell settings, prefer memory_type='environment_fact'.",
            "If the event describes a fixed repo process, release checklist, or repeated pre-release command sequence, prefer memory_type='workflow'.",
            "If the event observes a verified fact in a source file or document, prefer memory_type='project_fact'.",
            "If the event defines a fixed command or tool usage rule, prefer memory_type='tool_rule'.",
        ],
        "output": {
            "provider": "string",
            "warnings": ["string"],
            "metadata": {},
            "candidates": [
                {
                    "content": "string",
                    "memory_type": "user_preference|project_fact|tool_rule|environment_fact|troubleshooting|decision|workflow|reflection",
                    "scope": "string",
                    "subject": "string",
                    "source_event_ids": ["string"],
                    "reason": "string",
                    "claim": "string",
                    "evidence_type": "direct_user_statement|file_observation|tool_result|test_result|user_confirmation|inferred|unknown",
                    "time_validity": "persistent|until_changed|session|unknown",
                    "reuse_cases": ["string"],
                    "scores": {
                        "long_term": 0.0,
                        "evidence": 0.0,
                        "reuse": 0.0,
                        "risk": 0.0,
                        "specificity": 0.0,
                    },
                    "confidence": "confirmed|likely|inferred|unknown",
                    "risk": "low|medium|high",
                }
            ],
        },
    }
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You extract governed long-term memory candidates for an agent. "
                    "Return only a valid JSON object. Do not include markdown. "
                    "Reject one-off requests, unverified guesses, sensitive data, and temporary state. "
                    "Reject casual same-day likes unless they are explicitly stable preferences. "
                    "Prefer troubleshooting for verified problem/experience/solution cases, "
                    "environment_fact for confirmed runtime state, and workflow for fixed repo processes."
                    " Use project_fact for verified source/document observations and tool_rule for fixed commands."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, default=str),
            },
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }


def _build_openai_recall_judge_payload(
    payload: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict memory recall judge for an agent. "
                    "Return only a valid JSON object. Do not include markdown. "
                    "Accept only candidate memories that directly answer the user's query. "
                    "Reject no-match and sensitive/private-secret requests. "
                    "Use ambiguous for close or verification-dependent cases. "
                    "Treat local_decision=accepted as a strong signal; only overturn it when clearly irrelevant."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }


def _parse_openai_chat_json(raw: Any) -> Any:
    if isinstance(raw, dict) and "candidates" in raw:
        return raw
    if not isinstance(raw, dict):
        raise RemoteAdapterError("OpenAI-compatible chat response must be an object")
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RemoteAdapterError("OpenAI-compatible chat response has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise RemoteAdapterError("OpenAI-compatible chat choice must be an object")
    message = first.get("message", {})
    if not isinstance(message, dict):
        raise RemoteAdapterError("OpenAI-compatible chat message must be an object")
    content = _message_content_to_text(message.get("content"))
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RemoteAdapterError("OpenAI-compatible chat content was not valid JSON") from exc


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts).strip()
    raise RemoteAdapterError("OpenAI-compatible chat message content is empty")


def _with_event_defaults(item: dict[str, Any], event: EventRead) -> dict[str, Any]:
    candidate = dict(item)
    candidate.setdefault("content", event.content)
    candidate.setdefault("scope", event.scope)
    candidate.setdefault("subject", event.metadata.get("subject") or event.source)
    candidate.setdefault("source_event_ids", [event.id])
    candidate.setdefault("reason", "Remote extractor proposed this memory candidate.")
    candidate.setdefault("claim", candidate.get("content"))
    return candidate


def _float_vector(value: Any) -> list[float]:
    if not isinstance(value, list) or not value:
        raise RemoteAdapterError("remote embedding vector must be a non-empty list")
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise RemoteAdapterError("remote embedding vector must contain numbers") from exc


def _join_url(base_url: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    base = base_url.rstrip("/")
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{base}{normalized_path}"


def _resolve_compatibility(
    raw: str | None,
    *,
    base_url: str | None,
    using_dashscope_env: bool,
) -> str:
    if raw:
        normalized = raw.strip().lower().replace("-", "_")
        if normalized in {"openai", "openai_compatible", "compatible"}:
            return OPENAI_COMPATIBILITY
        if normalized == GENERIC_COMPATIBILITY:
            return GENERIC_COMPATIBILITY
    if using_dashscope_env or _looks_openai_compatible(base_url):
        return OPENAI_COMPATIBILITY
    return GENERIC_COMPATIBILITY


def _resolve_embedding_compatibility(
    raw: str | None,
    *,
    compatibility: str,
    embedding_model: str,
    using_dashscope_env: bool,
) -> str:
    if raw:
        normalized = raw.strip().lower().replace("-", "_")
        if normalized in {"dashscope", "dashscope_multimodal", "multimodal"}:
            return DASHSCOPE_MULTIMODAL_COMPATIBILITY
        if normalized in {"openai", "openai_compatible", "compatible"}:
            return OPENAI_COMPATIBILITY
        if normalized == GENERIC_COMPATIBILITY:
            return GENERIC_COMPATIBILITY
    if using_dashscope_env and "embedding_vision" in embedding_model.replace("-", "_"):
        return DASHSCOPE_MULTIMODAL_COMPATIBILITY
    if compatibility == OPENAI_COMPATIBILITY:
        return OPENAI_COMPATIBILITY
    return GENERIC_COMPATIBILITY


def _looks_openai_compatible(base_url: str | None) -> bool:
    if not base_url:
        return False
    normalized = base_url.lower()
    return "compatible-mode" in normalized or normalized.rstrip("/").endswith("/v1")


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
