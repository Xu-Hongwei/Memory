from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, replace
from http import client as http_client
from typing import Any, get_args
from urllib import error as urllib_error
from urllib import request as urllib_request

from pydantic import ValidationError

from memory_system.schemas import (
    CandidateScores,
    Confidence,
    EventRead,
    EvidenceType,
    MemoryCandidateCreate,
    MemoryItemRead,
    MemoryRouteItem,
    MemoryType,
    RecallPlan,
    RecallStrategy,
    RemoteAdapterConfigRead,
    RemoteCandidateExtractionResult,
    RemoteEmbeddingResult,
    RemoteMemoryRouteResult,
    RemoteRecallJudgeResult,
    RemoteRetrievalGuardDecisionRead,
    RetrievalGuardDecision,
    Risk,
    SessionCloseoutDecision,
    SessionCloseoutResult,
    SessionMemoryItemRead,
    SessionMemoryType,
    TaskBoundaryDecision,
    TimeValidity,
)

REMOTE_MEMORY_TYPES = set(get_args(MemoryType))
REMOTE_RECALL_STRATEGIES = set(get_args(RecallStrategy))
REMOTE_SESSION_MEMORY_TYPES = set(get_args(SessionMemoryType))
REMOTE_EVIDENCE_TYPES = set(get_args(EvidenceType))
REMOTE_TIME_VALIDITIES = set(get_args(TimeValidity))
REMOTE_CONFIDENCES = set(get_args(Confidence))
REMOTE_RISKS = set(get_args(Risk))
REMOTE_ROUTE_VALUES = {"long_term", "session", "ignore", "reject", "ask_user"}
REMOTE_CLOSEOUT_ACTIONS = {"keep", "discard", "summarize", "promote_candidate"}

DEFAULT_LLM_MODEL = "deepseek-v4-flash"
DEFAULT_EMBEDDING_MODEL = "tongyi-embedding-vision-flash-2026-03-06"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
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
REMOTE_TROUBLESHOOTING_CUE_SETS = (
    REMOTE_TROUBLESHOOTING_CUES,
    ("problem", "lesson", "solution"),
    ("problem", "experience", "solution"),
    ("issue", "lesson", "fix"),
    ("error", "root cause", "fix"),
)
REMOTE_VERIFIED_CUES = (
    "\u5df2\u786e\u8ba4",
    "\u786e\u8ba4",
    "\u5df2\u9a8c\u8bc1",
    "\u9a8c\u8bc1\u901a\u8fc7",
    "confirmed",
    "verified",
    "passed",
)
REMOTE_ENVIRONMENT_CUES = (
    "\u73af\u5883",
    "\u5f00\u53d1\u73af\u5883",
    "\u8fd0\u884c\u73af\u5883",
    "\u9879\u76ee\u76ee\u5f55",
    "\u5f53\u524d\u9879\u76ee",
    "\u5f53\u524d\u5de5\u4f5c\u533a",
    "\u5f53\u524d\u72b6\u6001",
    "\u72b6\u6001",
    "\u6a21\u578b\u540d",
    "\u9ed8\u8ba4 shell",
    "\u8fdc\u7a0b embedding",
    "powershell",
    "shell",
    "embedding model",
    "remote embedding",
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
    "tool rule",
    "verification command",
    "focused pytest",
    "pytest file",
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
REMOTE_LOW_EVIDENCE_PREFERENCE_CUES = (
    "\u53ef\u80fd",
    "\u4e5f\u8bb8",
    "\u5927\u6982",
    "\u4f3c\u4e4e",
    "\u597d\u50cf",
    "\u8fd8\u6ca1\u60f3\u597d",
    "\u8fd8\u4e0d\u786e\u5b9a",
    "\u4e0d\u786e\u5b9a\u4ee5\u540e",
    "\u4e0d\u786e\u5b9a\u8981\u4e0d\u8981",
    "\u4e0d\u786e\u5b9a\u662f\u4e0d\u662f",
    "\u5148\u8bd5\u8bd5",
    "maybe",
    "probably",
    "not sure",
    "perhaps",
    "i might",
    "i may",
    "i'm not sure",
    "i am not sure",
    "not sure whether",
    "not sure if",
    "i have not decided",
    "i haven't decided",
    "there is a chance",
    "chance i prefer",
    "ask before treating this as stable",
    "please ask before treating this as stable",
    "treating this as stable",
)
REMOTE_UNDERSPECIFIED_PREFERENCE_PHRASES = (
    "\u4ee5\u540e\u90fd\u8fd9\u6837",
    "\u4ee5\u540e\u4e5f\u8fd9\u6837",
    "\u4ee5\u540e\u6309\u8fd9\u4e2a\u6765",
    "\u4e4b\u540e\u90fd\u8fd9\u6837",
    "\u4e0b\u6b21\u4e5f\u8fd9\u6837",
    "keep doing it like this",
    "keep doing it this way",
    "keep doing this",
    "keep using this",
    "do it like this going forward",
    "use this style going forward",
    "same style going forward",
    "do this next time too",
    "make future ones like that",
)
REMOTE_PREFERENCE_OBJECT_CUES = (
    "\u56de\u7b54",
    "\u6587\u6863",
    "\u4ee3\u7801",
    "\u6d4b\u8bd5",
    "\u6a21\u578b",
    "\u8bb0\u5fc6",
    "\u5efa\u8bae",
    "\u8ba1\u5212",
    "\u65e5\u7a0b",
    "\u9009\u62e9",
    "\u5174\u8da3",
    "\u63d0\u9192",
    "\u6458\u8981",
    "\u6e05\u5355",
    "\u5b66\u4e60",
    "\u65c5\u884c",
    "\u8d2d\u7269",
    "\u4f1a\u8bae",
    "\u5065\u5eb7",
    "\u63a8\u8350",
    "\u5730\u533a",
    "\u57ce\u5e02",
    "\u7ed3\u679c",
    "\u9879\u76ee",
    "\u9519\u8bef",
    "\u62a5\u9519",
    "\u65b9\u6848",
    "\u63d0\u4ea4",
    "\u7ed3\u6784",
    "\u53ec\u56de",
    "\u4e0a\u4e0b\u6587",
    "\u683c\u5f0f",
    "\u98ce\u683c",
    "\u8bed\u8a00",
    "\u6ce8\u91ca",
    "\u6392\u7248",
    "\u8bf4\u660e",
    "tone",
    "answer",
    "response",
    "docs",
    "documentation",
    "code",
    "test",
    "model",
    "memory",
    "recall",
    "context",
    "summary",
    "schedule",
    "plan",
    "recommendation",
    "travel",
    "shopping",
    "meeting",
    "reminder",
    "study",
    "material",
    "result",
    "project",
    "error",
    "bug",
    "commit",
    "structure",
    "explanation",
    "choice",
    "health",
    "city",
    "location",
    "workflow",
    "format",
    "style",
    "language",
    "comments",
    "fixture",
    "fixtures",
    "naming",
    "case",
    "cases",
)
REMOTE_TEMPORARY_PREFERENCE_CUES = (
    "\u8fd9\u6b21",
    "\u672c\u6b21",
    "\u8fd9\u4e00\u8f6e",
    "\u672c\u8f6e",
    "\u4eca\u5929\u5148",
    "\u53ea\u662f\u8fd9\u6b21",
    "\u53ea\u5728\u8fd9\u4e2a\u4f8b\u5b50",
    "\u5f53\u524d\u4f8b\u5b50",
    "\u5f53\u524d\u60c5\u7eea",
    "\u5148\u53eb",
    "\u53ef\u80fd\u4f1a\u6539\u540d",
    "\u540e\u9762\u53ef\u80fd\u4f1a\u6539\u540d",
    "\u5206\u652f\u5148",
    "\u8fd9\u4e2a\u5206\u652f",
    "for this task",
    "for now",
    "this task only",
    "this case only",
    "for this run",
    "this run only",
    "today only",
    "this time only",
    "just for this example",
    "current example",
    "current mood",
    "passing reaction",
    "can run later",
    "full suite can run later",
)
REMOTE_DO_NOT_MEMORY_CUES = (
    "\u4e0d\u8981\u8bb0\u8fd9\u4e2a",
    "\u522b\u8bb0\u8fd9\u4e2a",
    "\u4e0d\u7528\u8bb0",
    "\u4e0d\u8981\u5f53\u6210\u504f\u597d",
    "\u4e0d\u8981\u8bb0\u8fdb\u957f\u671f\u8bb0\u5fc6",
    "\u4e0d\u8981\u5199\u8fdb\u957f\u671f\u8bb0\u5fc6",
    "do not remember this",
    "don't remember this",
    "do not treat this as a preference",
    "don't treat this as a preference",
    "do not treat it as a preference",
    "don't treat it as a preference",
    "do not treat that as a preference",
    "don't treat that as a preference",
    "do not treat this as my",
    "don't treat this as my",
    "do not treat it as my",
    "don't treat it as my",
    "do not treat that as my",
    "don't treat that as my",
    "not my preference",
    "not my travel preference",
    "not a preference",
    "do not store this",
    "don't store this",
    "stay out of long-term memory",
    "without turning it into",
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
            using_deepseek_env=False,
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
        deepseek_base_url = _optional_text(os.environ.get("DEEPSEEK_BASE_URL"))
        deepseek_api_key = _optional_text(os.environ.get("DEEPSEEK_API_KEY"))
        deepseek_model = _optional_text(os.environ.get("DEEPSEEK_MODEL"))
        dashscope_base_url = _optional_text(os.environ.get("DASHSCOPE_BASE_URL"))
        dashscope_api_key = _optional_text(os.environ.get("DASHSCOPE_API_KEY"))
        dashscope_model = _optional_text(os.environ.get("DASHSCOPE_MODEL"))
        using_deepseek_env = base_url is None and (
            deepseek_base_url is not None or deepseek_api_key is not None or deepseek_model is not None
        )
        using_dashscope_env = base_url is None and dashscope_base_url is not None
        base_url = base_url or deepseek_base_url or (
            DEFAULT_DEEPSEEK_BASE_URL if using_deepseek_env else None
        ) or dashscope_base_url
        api_key = api_key or deepseek_api_key or dashscope_api_key
        compatibility = _resolve_compatibility(
            os.environ.get(f"{prefix}_COMPATIBILITY"),
            base_url=base_url,
            using_dashscope_env=using_dashscope_env,
            using_deepseek_env=using_deepseek_env,
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
            llm_model=_optional_text(os.environ.get(f"{prefix}_LLM_MODEL"))
            or deepseek_model
            or dashscope_model
            or DEFAULT_LLM_MODEL,
            embedding_model=DEFAULT_EMBEDDING_MODEL,
        )

    @classmethod
    def llm_from_env(cls) -> RemoteAdapterConfig:
        config = cls.from_env("LLM_REMOTE") if _has_env_prefix("LLM_REMOTE") else cls.from_env()
        model = _optional_text(os.environ.get("LLM_REMOTE_MODEL"))
        if model:
            config = replace(config, llm_model=model)
        return config

    @classmethod
    def embedding_from_env(cls) -> RemoteAdapterConfig:
        if _has_env_prefix("EMBEDDING_REMOTE"):
            return cls._embedding_from_specific_env("EMBEDDING_REMOTE")
        if _has_remote_config_prefix("MEMORY_REMOTE"):
            return cls.from_env()
        dashscope_base_url = _optional_text(os.environ.get("DASHSCOPE_BASE_URL"))
        dashscope_api_key = _optional_text(os.environ.get("DASHSCOPE_API_KEY"))
        if dashscope_base_url or dashscope_api_key:
            model = _optional_text(os.environ.get("DASHSCOPE_EMBEDDING_MODEL")) or DEFAULT_EMBEDDING_MODEL
            timeout_seconds = _remote_timeout_from_env("EMBEDDING_REMOTE")
            return cls(
                base_url=dashscope_base_url,
                api_key=dashscope_api_key,
                compatibility=OPENAI_COMPATIBILITY,
                embedding_compatibility=DASHSCOPE_MULTIMODAL_COMPATIBILITY,
                timeout_seconds=timeout_seconds,
                embedding_path=DASHSCOPE_MULTIMODAL_EMBEDDING_URL,
                embedding_model=model,
            )
        return cls.from_env()

    @classmethod
    def _embedding_from_specific_env(cls, prefix: str) -> RemoteAdapterConfig:
        model = (
            _optional_text(os.environ.get(f"{prefix}_MODEL"))
            or _optional_text(os.environ.get(f"{prefix}_EMBEDDING_MODEL"))
            or DEFAULT_EMBEDDING_MODEL
        )
        base_url = _optional_text(os.environ.get(f"{prefix}_BASE_URL"))
        api_key = _optional_text(os.environ.get(f"{prefix}_API_KEY"))
        dashscope_base_url = _optional_text(os.environ.get("DASHSCOPE_BASE_URL"))
        dashscope_api_key = _optional_text(os.environ.get("DASHSCOPE_API_KEY"))
        using_dashscope_env = False
        if base_url is None and dashscope_base_url is not None:
            base_url = dashscope_base_url
            using_dashscope_env = True
        if api_key is None and using_dashscope_env:
            api_key = dashscope_api_key
        compatibility = _resolve_compatibility(
            os.environ.get(f"{prefix}_COMPATIBILITY"),
            base_url=base_url,
            using_dashscope_env=using_dashscope_env,
            using_deepseek_env=False,
        )
        embedding_compatibility = _resolve_embedding_compatibility(
            os.environ.get(f"{prefix}_EMBEDDING_COMPATIBILITY")
            or os.environ.get(f"{prefix}_COMPATIBILITY"),
            compatibility=compatibility,
            embedding_model=model,
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
            timeout_seconds=_remote_timeout_from_env(prefix),
            embedding_path=os.environ.get(f"{prefix}_EMBEDDING_PATH", default_embedding_path),
            embedding_model=model,
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
                "MEMORY_REMOTE_BASE_URL, DEEPSEEK_BASE_URL, or DASHSCOPE_BASE_URL is not configured"
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
        last_error: BaseException | None = None
        for attempt in range(3):
            try:
                with urllib_request.urlopen(
                    request,
                    timeout=self.config.timeout_seconds,
                ) as response:
                    raw = response.read().decode("utf-8")
                break
            except urllib_error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise RemoteAdapterError(f"remote returned HTTP {exc.code}: {detail[:300]}") from exc
            except urllib_error.URLError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RemoteAdapterError(f"remote request failed: {exc.reason}") from exc
            except TimeoutError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RemoteAdapterError("remote request timed out") from exc
            except http_client.IncompleteRead as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RemoteAdapterError(f"remote response was incomplete: {exc}") from exc
            except OSError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RemoteAdapterError(f"remote request failed: {exc}") from exc
        else:
            raise RemoteAdapterError(f"remote request failed: {last_error}")

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
        self.config = config or RemoteAdapterConfig.llm_from_env()
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
                "Only propose long-term, reusable, non-sensitive memories. "
                "Each candidate must contain exactly one atomic claim; split multi-fact events."
            )
        )
        if event.sanitized or _contains_sensitive_remote_text(event.content):
            return RemoteCandidateExtractionResult(
                provider="remote",
                candidates=[],
                warnings=["filtered_sensitive_remote_event"],
                metadata={"skipped_remote_call": True},
            )
        if _is_remote_pending_question_event(event):
            return RemoteCandidateExtractionResult(
                provider="remote",
                candidates=[],
                warnings=["filtered_pending_question_remote_event"],
                metadata={"skipped_remote_call": True},
            )
        if _is_remote_temporary_event_context(event):
            return RemoteCandidateExtractionResult(
                provider="remote",
                candidates=[],
                warnings=["filtered_temporary_remote_event"],
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

    def route_memories(
        self,
        events: list[EventRead],
        *,
        recent_events: list[EventRead] | None = None,
        current_task_state: dict[str, Any] | None = None,
        active_session_memories: list[dict[str, Any]] | None = None,
        instructions: str | None = None,
    ) -> RemoteMemoryRouteResult:
        safe_events, rejected_items, warnings = _safe_route_events(events)
        safe_recent_events, _recent_rejected, recent_warnings = _safe_route_events(
            recent_events or []
        )
        warnings.extend(f"recent_{warning}" for warning in recent_warnings)
        if not safe_events:
            return RemoteMemoryRouteResult(
                provider="remote",
                items=rejected_items,
                warnings=[*warnings, "no_safe_route_events"],
                metadata={"skipped_remote_call": True},
            )

        resolved_instructions = _with_remote_route_instructions(instructions)
        payload = _build_memory_route_payload(
            safe_events,
            recent_events=safe_recent_events,
            current_task_state=current_task_state,
            active_session_memories=active_session_memories or [],
            instructions=resolved_instructions,
            model=self.config.llm_model,
        )
        if self.config.compatibility == OPENAI_COMPATIBILITY:
            raw = self.http.post_json(
                self.config.llm_extract_path,
                _build_openai_memory_route_payload(payload, self.config.llm_model),
            )
            raw = _parse_openai_chat_json(raw)
        else:
            raw = self.http.post_json(self.config.llm_extract_path, payload)
        result = _parse_memory_route_result(
            raw,
            safe_events,
            recent_events=safe_recent_events,
            current_task_state=current_task_state,
        )
        combined_warnings = [*warnings, *result.warnings]
        combined_items = [*rejected_items, *result.items]
        return result.model_copy(
            update={
                "items": combined_items,
                "warnings": combined_warnings,
                "metadata": {
                    **result.metadata,
                    "safe_event_count": len(safe_events),
                    "rejected_event_count": len(rejected_items),
                },
            }
        )

    def closeout_session_memories(
        self,
        *,
        session_id: str,
        session_memories: list[SessionMemoryItemRead],
        task_boundary: TaskBoundaryDecision | None = None,
        current_task_state: dict[str, Any] | None = None,
        recent_events: list[EventRead] | None = None,
        instructions: str | None = None,
    ) -> SessionCloseoutResult:
        safe_items: list[SessionMemoryItemRead] = []
        warnings: list[str] = []
        for item in session_memories:
            if _contains_sensitive_remote_text(item.content):
                warnings.append(f"filtered_sensitive_session_memory:{item.id}")
                continue
            safe_items.append(item)
        if not safe_items:
            return SessionCloseoutResult(
                provider="remote",
                session_id=session_id,
                task_boundary=task_boundary,
                warnings=[*warnings, "no_safe_session_memories"],
                metadata={"skipped_remote_call": True},
            )

        payload = _build_session_closeout_payload(
            session_id=session_id,
            session_memories=safe_items,
            task_boundary=task_boundary,
            current_task_state=current_task_state or {},
            recent_events=recent_events or [],
            instructions=instructions,
            model=self.config.llm_model,
        )
        if self.config.compatibility == OPENAI_COMPATIBILITY:
            raw = self.http.post_json(
                self.config.llm_extract_path,
                _build_openai_session_closeout_payload(payload, self.config.llm_model),
            )
            raw = _parse_openai_chat_json(raw)
        else:
            raw = self.http.post_json(self.config.llm_extract_path, payload)
        result = _parse_session_closeout_result(
            raw,
            session_id=session_id,
            session_memories=safe_items,
            task_boundary=task_boundary,
        )
        return result.model_copy(update={"warnings": [*warnings, *result.warnings]})

    def plan_recall(
        self,
        *,
        task: str,
        scope: str | None = None,
        limit_per_query: int = 5,
        instructions: str | None = None,
    ) -> RecallPlan:
        if not task.strip():
            raise RemoteAdapterError("remote recall planner task must not be empty")
        if _contains_sensitive_remote_recall_text(task):
            raise RemoteAdapterError("sensitive recall planner task was not sent remotely")

        payload = _build_recall_planner_payload(
            task=task,
            scope=scope,
            limit_per_query=limit_per_query,
            instructions=instructions,
            model=self.config.llm_model,
        )
        if self.config.compatibility == OPENAI_COMPATIBILITY:
            raw = self.http.post_json(
                self.config.llm_extract_path,
                _build_openai_recall_planner_payload(payload, self.config.llm_model),
            )
            raw = _parse_openai_chat_json(raw)
        else:
            raw = self.http.post_json(self.config.llm_extract_path, payload)
        return _parse_recall_plan_result(
            raw,
            task=task,
            scope=scope,
            limit_per_query=limit_per_query,
            model=self.config.llm_model,
        )

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

    def judge_retrieval_batch(
        self,
        requests: list[dict[str, Any]],
        *,
        instructions: str | None = None,
    ) -> dict[str, RemoteRecallJudgeResult]:
        resolved_instructions = _with_remote_recall_judge_instructions(instructions)
        results: dict[str, RemoteRecallJudgeResult] = {}
        remote_cases: list[dict[str, Any]] = []
        allowed_ids_by_request: dict[str, list[str]] = {}
        query_by_request: dict[str, str] = {}
        warnings_by_request: dict[str, list[str]] = {}

        for index, request in enumerate(requests):
            request_id = str(request.get("request_id") or index)
            query = str(request.get("query") or "")
            query_by_request[request_id] = query
            memories = [
                memory
                for memory in request.get("memories", [])
                if isinstance(memory, MemoryItemRead)
            ]
            allowed_memory_ids = [memory.id for memory in memories]
            if not query.strip():
                results[request_id] = RemoteRecallJudgeResult(
                    provider="remote",
                    model=self.config.llm_model,
                    query=query,
                    decision="rejected",
                    reason="Empty query cannot recall a memory.",
                    warnings=["empty_query_skipped_remote_recall_judge"],
                    metadata={"skipped_remote_call": True, "request_id": request_id},
                )
                continue
            if _contains_sensitive_remote_recall_text(query):
                results[request_id] = RemoteRecallJudgeResult(
                    provider="remote",
                    model=self.config.llm_model,
                    query=query,
                    decision="rejected",
                    reason="Sensitive recall query was not sent to the remote model.",
                    warnings=["filtered_sensitive_recall_query"],
                    metadata={"skipped_remote_call": True, "request_id": request_id},
                )
                continue

            filtered_memories = [
                memory
                for memory in memories
                if not _contains_sensitive_remote_recall_text(memory.subject)
                and not _contains_sensitive_remote_recall_text(memory.content)
            ]
            filtered_ids = [memory.id for memory in filtered_memories]
            request_warnings: list[str] = []
            if len(filtered_memories) != len(memories):
                request_warnings.append("filtered_sensitive_recall_candidate")
            if not filtered_memories:
                results[request_id] = RemoteRecallJudgeResult(
                    provider="remote",
                    model=self.config.llm_model,
                    query=query,
                    decision="rejected",
                    reason="No safe candidate memories were available for remote recall judging.",
                    warnings=[*request_warnings, "no_recall_candidates"],
                    metadata={
                        "skipped_remote_call": True,
                        "candidate_memory_ids": allowed_memory_ids,
                        "request_id": request_id,
                    },
                )
                continue

            local_decisions = [
                decision
                for decision in request.get("local_decisions", [])
                if isinstance(decision, RemoteRetrievalGuardDecisionRead)
            ]
            scopes = _string_list(request.get("scopes", []))
            single_payload = _build_recall_judge_payload(
                query=query,
                memories=filtered_memories,
                local_decisions=local_decisions,
                scopes=scopes,
                task=request.get("task") if isinstance(request.get("task"), str) else None,
                instructions=resolved_instructions,
                model=self.config.llm_model,
            )
            remote_cases.append(
                {
                    "request_id": request_id,
                    "query": single_payload["query"],
                    "scopes": single_payload["scopes"],
                    "task": single_payload["task"],
                    "candidates": single_payload["candidates"],
                }
            )
            allowed_ids_by_request[request_id] = filtered_ids
            warnings_by_request[request_id] = request_warnings

        if not remote_cases:
            return results

        payload = _build_recall_judge_batch_payload(
            remote_cases,
            model=self.config.llm_model,
            instructions=resolved_instructions,
        )
        if self.config.compatibility == OPENAI_COMPATIBILITY:
            raw = self.http.post_json(
                self.config.llm_extract_path,
                _build_openai_recall_judge_batch_payload(payload, self.config.llm_model),
            )
            raw = _parse_openai_chat_json(raw)
        else:
            raw = self.http.post_json(self.config.llm_extract_path, payload)
        parsed = _parse_recall_judge_batch_results(
            raw,
            query_by_request=query_by_request,
            allowed_ids_by_request=allowed_ids_by_request,
        )
        for request_id, result in parsed.items():
            request_warnings = warnings_by_request.get(request_id, [])
            if request_warnings:
                result = result.model_copy(
                    update={"warnings": [*request_warnings, *result.warnings]}
                )
            if not result.model:
                result = result.model_copy(update={"model": self.config.llm_model})
            result = result.model_copy(
                update={"metadata": {**result.metadata, "request_id": request_id}}
            )
            results[request_id] = result
        for request_id in allowed_ids_by_request:
            if request_id not in results:
                results[request_id] = RemoteRecallJudgeResult(
                    provider="remote",
                    model=self.config.llm_model,
                    query=query_by_request.get(request_id, ""),
                    decision="ambiguous",
                    reason="Remote batch recall judge did not return a result for this request.",
                    warnings=["missing_batch_recall_judge_result"],
                    metadata={
                        "request_id": request_id,
                        "allowed_memory_ids": allowed_ids_by_request[request_id],
                    },
                )
        return results


class RemoteEmbeddingClient:
    def __init__(
        self,
        config: RemoteAdapterConfig | None = None,
        http: RemoteHTTPClient | None = None,
    ) -> None:
        self.config = config or RemoteAdapterConfig.embedding_from_env()
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


def _safe_route_events(
    events: list[EventRead],
) -> tuple[list[EventRead], list[MemoryRouteItem], list[str]]:
    safe_events: list[EventRead] = []
    rejected_items: list[MemoryRouteItem] = []
    warnings: list[str] = []
    for event in events:
        if event.sanitized or _contains_sensitive_remote_text(event.content):
            warnings.append("filtered_sensitive_route_event")
            rejected_items.append(
                MemoryRouteItem(
                    route="reject",
                    content="Sensitive event omitted from remote memory routing.",
                    reason="Sensitive content must not be sent to the remote route judge.",
                    scope=event.scope,
                    subject=event.source,
                    source_event_ids=[event.id],
                    risk="high",
                    metadata={"skipped_remote_call": True},
                )
            )
            continue
        safe_events.append(event)
    return safe_events, rejected_items, warnings


def _parse_memory_route_result(
    raw: Any,
    events: list[EventRead],
    *,
    recent_events: list[EventRead] | None = None,
    current_task_state: dict[str, Any] | None = None,
) -> RemoteMemoryRouteResult:
    provider = "remote"
    warnings: list[str] = []
    metadata: dict[str, Any] = {}

    if isinstance(raw, list):
        items_raw = raw
    elif isinstance(raw, dict):
        provider = str(raw.get("provider") or provider)
        warnings = _string_list(raw.get("warnings", []))
        metadata_value = raw.get("metadata", {})
        metadata = metadata_value if isinstance(metadata_value, dict) else {"value": metadata_value}
        task_boundary, task_boundary_warnings = _parse_task_boundary(
            raw.get("task_boundary") or raw.get("taskBoundary")
        )
        warnings.extend(task_boundary_warnings)
        items_raw = raw.get("items", raw.get("routes", raw.get("memory_routes", [])))
        if not items_raw and isinstance(raw.get("candidates"), list):
            items_raw = [
                {"route": "long_term", **candidate}
                for candidate in raw.get("candidates", [])
                if isinstance(candidate, dict)
            ]
        if items_raw is None:
            items_raw = []
    else:
        raise RemoteAdapterError("remote memory route response must be an object or list")
    if not isinstance(raw, dict):
        task_boundary = None

    if not isinstance(items_raw, list):
        raise RemoteAdapterError("remote memory route response must contain an items list")

    items: list[MemoryRouteItem] = []
    for raw_item in items_raw:
        if not isinstance(raw_item, dict):
            raise RemoteAdapterError("remote memory route item must be an object")
        data = _flatten_route_item(raw_item)
        route = str(data.get("route") or data.get("decision") or "").strip().lower()
        if route not in REMOTE_ROUTE_VALUES:
            warnings.append(f"invalid_memory_route:{route or '<empty>'}")
            route = "ask_user"
        data["route"] = route
        data, normalize_warnings = _normalize_route_item_data(data)
        warnings.extend(normalize_warnings)
        try:
            items.append(MemoryRouteItem.model_validate(_with_route_defaults(data, events)))
        except ValidationError as exc:
            raise RemoteAdapterError(f"remote memory route did not match schema: {exc}") from exc

    items, governance_warnings = _govern_memory_route_items(
        items,
        writable_event_ids={event.id for event in events},
        event_by_id={event.id: event for event in [*events, *(recent_events or [])]},
    )
    warnings.extend(governance_warnings)
    task_boundary, boundary_warnings = _govern_task_boundary(
        task_boundary,
        events=events,
        recent_events=recent_events or [],
        current_task_state=current_task_state or {},
    )
    warnings.extend(boundary_warnings)
    return RemoteMemoryRouteResult(
        provider=provider,
        items=items,
        task_boundary=task_boundary,
        warnings=warnings,
        metadata=metadata,
    )


def _parse_task_boundary(raw: Any) -> tuple[TaskBoundaryDecision | None, list[str]]:
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, ["invalid_task_boundary"]
    normalized = dict(raw)
    warnings: list[str] = []
    if normalized.get("action") not in {
        "same_task",
        "new_task",
        "switch_task",
        "task_done",
        "task_cancelled",
        "unclear",
        "no_change",
    }:
        normalized["action"] = "unclear"
        warnings.append("defaulted_task_boundary_action")
    if normalized.get("confidence") not in {"high", "medium", "low", "unknown"}:
        normalized["confidence"] = "unknown"
        warnings.append("defaulted_task_boundary_confidence")
    if normalized.get("previous_task_status") not in {"active", "done", "cancelled", "unknown"}:
        normalized["previous_task_status"] = "unknown"
        warnings.append("defaulted_task_boundary_previous_status")
    if not isinstance(normalized.get("reason"), str) or not normalized["reason"].strip():
        normalized["reason"] = "Remote task boundary judge proposed this decision."
        warnings.append("defaulted_task_boundary_reason")
    for key in ("current_task_id", "current_task_title", "next_task_title"):
        value = normalized.get(key)
        if value is not None and not isinstance(value, str):
            normalized[key] = str(value)
            warnings.append(f"coerced_task_boundary_{key}")
        elif isinstance(value, str) and not value.strip():
            normalized[key] = None
    try:
        return TaskBoundaryDecision.model_validate(normalized), warnings
    except ValidationError as exc:
        raise RemoteAdapterError(f"remote task boundary did not match schema: {exc}") from exc


def _govern_task_boundary(
    boundary: TaskBoundaryDecision | None,
    *,
    events: list[EventRead],
    recent_events: list[EventRead],
    current_task_state: dict[str, Any],
) -> tuple[TaskBoundaryDecision | None, list[str]]:
    del recent_events, current_task_state
    if boundary is None:
        return None, []
    has_explicit_switch = _task_boundary_has_explicit_switch_signal(events)
    if (
        not has_explicit_switch
        and _task_boundary_has_explicit_cancel_signal(events)
        and boundary.action != "task_cancelled"
    ):
        return (
            boundary.model_copy(
                update={
                    "action": "task_cancelled",
                    "confidence": "medium",
                    "next_task_title": None,
                    "reason": (
                        "Local task-boundary gate normalized this to task_cancelled "
                        "because the current event explicitly stops or cancels the active work."
                    ),
                }
        ),
        ["normalized_task_boundary_cancel_signal"],
    )
    if (
        not has_explicit_switch
        and _task_boundary_has_explicit_done_signal(events)
        and boundary.action != "task_done"
    ):
        return (
            boundary.model_copy(
                update={
                    "action": "task_done",
                    "confidence": "medium",
                    "next_task_title": None,
                    "reason": (
                        "Local task-boundary gate normalized this to task_done because "
                        "the current event explicitly ends or completes the active work."
                    ),
                }
            ),
            ["normalized_task_boundary_done_signal"],
        )
    if has_explicit_switch:
        inferred_next = _infer_next_task_title(events) or boundary.next_task_title
        if boundary.action in {"new_task", "switch_task"}:
            if boundary.next_task_title or inferred_next is None:
                return boundary, []
            return (
                boundary.model_copy(update={"next_task_title": inferred_next}),
                ["inferred_task_boundary_next_title"],
            )
        return (
            boundary.model_copy(
                update={
                    "action": "switch_task",
                    "confidence": "medium",
                    "next_task_title": inferred_next,
                    "reason": (
                        "Local task-boundary gate normalized this to switch_task "
                        "because the current event explicitly starts or moves to another task."
                    ),
                }
            ),
            ["normalized_task_boundary_switch_signal"],
        )
    if boundary.action in {"new_task", "switch_task"}:
        return _soften_weak_task_switch(boundary, events)
    return boundary, []


def _soften_weak_task_switch(
    boundary: TaskBoundaryDecision,
    events: list[EventRead],
) -> tuple[TaskBoundaryDecision, list[str]]:
    if boundary.next_task_title:
        return boundary, []
    inferred_next = _infer_next_task_title(events)
    if inferred_next:
        return (
            boundary.model_copy(update={"next_task_title": inferred_next}),
            ["inferred_task_boundary_next_title"],
        )
    if boundary.confidence == "high":
        return boundary, []
    reason = (
        "Local task-boundary gate weakened this decision because the remote model "
        "proposed a task switch without an explicit switch target in the current event."
    )
    return (
        boundary.model_copy(
            update={
                "action": "unclear",
                "confidence": "low",
                "next_task_title": None,
                "reason": reason,
            }
        ),
        ["weakened_task_boundary_switch_evidence"],
    )


def _task_boundary_has_explicit_switch_signal(events: list[EventRead]) -> bool:
    text = _task_boundary_text(events)
    switch_cues = (
        "next, work on",
        "next, implement",
        "next, do",
        "next let's",
        "next step is",
        "switch to",
        "move on to",
        "start working on",
        "now start",
        "now work on",
        "let's work on",
        "\u63a5\u4e0b\u6765\u505a",
        "\u4e0b\u4e00\u6b65\u505a",
        "\u6362\u6210",
        "\u6362\u4e00\u4e2a",
        "\u73b0\u5728\u5f00\u59cb",
        "\u5f00\u59cb\u505a",
        "\u8fdb\u5165",
        "\u8f6c\u5230",
    )
    return any(cue in text for cue in switch_cues)


def _task_boundary_has_explicit_done_signal(events: list[EventRead]) -> bool:
    text = _task_boundary_text(events)
    done_cues = (
        "this part is complete",
        "this part is done",
        "this is complete",
        "this is done",
        "this is good enough",
        "good enough for now",
        "end this step",
        "stop here",
        "\u8fd9\u90e8\u5206\u5b8c\u6210\u4e86",
        "\u8fd9\u4e2a\u5df2\u7ecf\u53ef\u4ee5\u4e86",
        "\u8fd9\u4e00\u6b65\u7ed3\u675f",
        "\u5148\u505c\u5728\u8fd9\u91cc",
        "\u6682\u65f6\u4e0d\u7528\u7ee7\u7eed",
    )
    return any(cue in text for cue in done_cues)


def _task_boundary_has_explicit_cancel_signal(events: list[EventRead]) -> bool:
    text = _task_boundary_text(events)
    cancel_cues = (
        "cancel this",
        "cancel the",
        "do not work on",
        "not continuing",
        "we are not continuing",
        "stop; we are not continuing",
        "stop, we are not continuing",
        "\u4e0d\u505a\u4e86",
        "\u53d6\u6d88",
        "\u5148\u522b\u7ba1",
        "\u522b\u7ba1\u8fd9\u4e2a",
        "\u505c\uff0c\u4e0d\u7ee7\u7eed",
        "\u505c,\u4e0d\u7ee7\u7eed",
    )
    return any(cue in text for cue in cancel_cues)


def _infer_next_task_title(events: list[EventRead]) -> str | None:
    raw_text = " ".join(event.content.strip() for event in events if event.content.strip())
    patterns = (
        r"\u6362\u6210(.+)",
        r"\u63a5\u4e0b\u6765\u5f00\u59cb\u505a(.+)",
        r"\u63a5\u4e0b\u6765\u505a(.+)",
        r"\u4e0b\u4e00\u6b65\u505a(.+)",
        r"\u73b0\u5728\u8fdb\u5165(.+)",
        r"\u8fdb\u5165(.+)",
        r"\u8f6c\u5230(.+)",
        r"next,\s*work on\s+(.+)",
        r"next,\s*implement\s+(.+)",
        r"next,\s*do\s+(.+)",
        r"move on to\s+(.+)",
        r"switch to\s+(.+)",
        r"work on\s+(.+)",
        r"start working on\s+(.+)",
        r"now start\s+(.+)",
        r"let's work on\s+(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if match:
            title = _clean_inferred_task_title(match.group(1))
            if title:
                return title
    return None


def _clean_inferred_task_title(text: str) -> str | None:
    title = re.split(r"[.?!;；。！？]", text.strip(), maxsplit=1)[0].strip()
    title = re.sub(r"^(the|a|an)\s+", "", title, flags=re.IGNORECASE).strip()
    return title or None


def _task_boundary_text(events: list[EventRead]) -> str:
    return "\n".join(event.content for event in events).lower()


def _parse_session_closeout_result(
    raw: Any,
    *,
    session_id: str,
    session_memories: list[SessionMemoryItemRead],
    task_boundary: TaskBoundaryDecision | None,
) -> SessionCloseoutResult:
    if not isinstance(raw, dict):
        raise RemoteAdapterError("remote session closeout response must be an object")
    provider = str(raw.get("provider") or "remote")
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    warnings = _string_list(raw.get("warnings"))
    task_summary = _optional_text(raw.get("task_summary") or raw.get("summary"))
    items_by_id = {item.id: item for item in session_memories}
    decisions_raw = raw.get("decisions", raw.get("items", []))
    if not isinstance(decisions_raw, list):
        raise RemoteAdapterError("remote session closeout response must contain a decisions list")

    decisions: list[SessionCloseoutDecision] = []
    decided_ids: set[str] = set()
    for raw_decision in decisions_raw:
        if not isinstance(raw_decision, dict):
            warnings.append("invalid_closeout_decision")
            continue
        memory_id = str(
            raw_decision.get("session_memory_id")
            or raw_decision.get("memory_id")
            or raw_decision.get("id")
            or ""
        ).strip()
        item = items_by_id.get(memory_id)
        if item is None:
            warnings.append(f"unknown_closeout_session_memory:{memory_id or '<empty>'}")
            continue
        action = str(raw_decision.get("action") or "keep").strip().lower()
        if action not in REMOTE_CLOSEOUT_ACTIONS:
            action = "keep"
            warnings.append("defaulted_closeout_action")
        reason = str(raw_decision.get("reason") or "Remote closeout judge proposed this action.").strip()
        summary = _optional_text(raw_decision.get("summary"))
        candidate = None
        if action == "promote_candidate":
            candidate, candidate_warnings = _closeout_candidate_from_raw(raw_decision.get("candidate"), item)
            warnings.extend(candidate_warnings)
            if candidate is None:
                action = "summarize"
                summary = summary or item.content
                warnings.append("downgraded_closeout_promotion_without_candidate")
        decisions.append(
            SessionCloseoutDecision(
                session_memory_id=item.id,
                action=action,
                reason=reason,
                summary=summary,
                candidate=candidate,
            )
        )
        decided_ids.add(item.id)

    for item in session_memories:
        if item.id in decided_ids:
            continue
        decisions.append(
            SessionCloseoutDecision(
                session_memory_id=item.id,
                action="keep",
                reason="Remote closeout judge did not return a decision for this item.",
            )
        )
        warnings.append(f"defaulted_missing_closeout_decision:{item.id}")

    return SessionCloseoutResult(
        provider=provider,
        session_id=session_id,
        task_summary=task_summary,
        task_boundary=task_boundary,
        decisions=decisions,
        warnings=warnings,
        metadata=metadata,
    )


def _closeout_candidate_from_raw(
    raw: Any,
    item: SessionMemoryItemRead,
) -> tuple[MemoryCandidateCreate | None, list[str]]:
    warnings: list[str] = []
    if not isinstance(raw, dict):
        return None, ["missing_closeout_candidate"]
    content = str(raw.get("content") or raw.get("claim") or item.content).strip()
    if not content:
        return None, ["missing_closeout_candidate_content"]
    if _contains_sensitive_remote_text(content):
        return None, ["filtered_sensitive_closeout_candidate"]
    memory_type = str(raw.get("memory_type") or _memory_type_from_session_closeout(item)).strip()
    if memory_type not in REMOTE_MEMORY_TYPES:
        memory_type = _memory_type_from_session_closeout(item)
        warnings.append("defaulted_closeout_candidate_memory_type")
    evidence_type = str(raw.get("evidence_type") or "inferred").strip()
    if evidence_type not in REMOTE_EVIDENCE_TYPES:
        evidence_type = "inferred"
        warnings.append("defaulted_closeout_candidate_evidence_type")
    time_validity = str(raw.get("time_validity") or "persistent").strip()
    if time_validity not in {"persistent", "until_changed"}:
        time_validity = "persistent"
        warnings.append("defaulted_closeout_candidate_time_validity")
    confidence = str(raw.get("confidence") or "likely").strip()
    if confidence not in REMOTE_CONFIDENCES:
        confidence = "likely"
        warnings.append("defaulted_closeout_candidate_confidence")
    risk = str(raw.get("risk") or "low").strip()
    if risk not in REMOTE_RISKS:
        risk = "low"
        warnings.append("defaulted_closeout_candidate_risk")
    scores_raw = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    try:
        scores = CandidateScores.model_validate(scores_raw)
    except ValidationError:
        scores = CandidateScores(long_term=0.6, evidence=0.6, reuse=0.5, risk=0.1)
        warnings.append("defaulted_closeout_candidate_scores")
    source_event_ids = _string_list(raw.get("source_event_ids")) or list(item.source_event_ids)
    if not source_event_ids:
        source_event_ids = [item.id]
        warnings.append("defaulted_closeout_candidate_source_event_ids")
    try:
        return (
            MemoryCandidateCreate(
                content=content,
                memory_type=memory_type,
                scope=str(raw.get("scope") or item.scope or "session").strip(),
                subject=str(raw.get("subject") or item.subject).strip(),
                source_event_ids=source_event_ids,
                reason=str(
                    raw.get("reason")
                    or "Promoted from session closeout because it may be reusable."
                ).strip(),
                claim=_optional_text(raw.get("claim")) or content,
                evidence_type=evidence_type,
                time_validity=time_validity,
                reuse_cases=_string_list(raw.get("reuse_cases")) or ["future_similar_tasks"],
                scores=scores,
                confidence=confidence,
                risk=risk,
            ),
            warnings,
        )
    except ValidationError:
        return None, [*warnings, "invalid_closeout_candidate"]


def _memory_type_from_session_closeout(item: SessionMemoryItemRead) -> MemoryType:
    if item.memory_type == "temporary_rule":
        return "workflow"
    if item.memory_type == "pending_decision":
        return "decision"
    if item.memory_type == "working_fact":
        return "project_fact"
    if item.memory_type == "emotional_state":
        return "reflection"
    return "reflection"


def _flatten_route_item(item: dict[str, Any]) -> dict[str, Any]:
    flattened = dict(item)
    candidate = flattened.pop("candidate", None)
    if isinstance(candidate, dict):
        candidate_data = dict(candidate)
        candidate_data.update(flattened)
        return candidate_data
    return flattened


def _with_route_defaults(item: dict[str, Any], events: list[EventRead]) -> dict[str, Any]:
    routed = dict(item)
    event_by_id = {event.id: event for event in events}
    source_event_ids = _string_list(
        routed.get("source_event_ids")
        or ([routed["source_event_id"]] if routed.get("source_event_id") else [])
    )
    if not source_event_ids and events:
        source_event_ids = [events[0].id]
    primary_event = event_by_id.get(source_event_ids[0]) if source_event_ids else None
    primary_event = primary_event or (events[0] if events else None)
    if primary_event is not None:
        if not isinstance(routed.get("content"), str) or not routed["content"].strip():
            routed["content"] = primary_event.content
        if not isinstance(routed.get("scope"), str) or not routed["scope"].strip():
            routed["scope"] = primary_event.scope
        if not isinstance(routed.get("subject"), str) or not routed["subject"].strip():
            routed["subject"] = primary_event.source
    routed["source_event_ids"] = source_event_ids
    if not isinstance(routed.get("reason"), str) or not routed["reason"].strip():
        routed["reason"] = "Remote route judge proposed this memory route."
    if not isinstance(routed.get("claim"), str) or not routed["claim"].strip():
        routed["claim"] = routed.get("content")
    return routed


def _normalize_route_item_data(item: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    normalized = dict(item)
    warnings: list[str] = []

    memory_type = normalized.get("memory_type")
    session_memory_type = normalized.get("session_memory_type")
    if isinstance(memory_type, str) and memory_type in REMOTE_SESSION_MEMORY_TYPES:
        if not isinstance(session_memory_type, str) or session_memory_type not in REMOTE_SESSION_MEMORY_TYPES:
            normalized["session_memory_type"] = memory_type
        normalized["memory_type"] = None
        warnings.append("normalized_route_memory_type_to_session_memory_type")
    elif memory_type is not None and memory_type not in REMOTE_MEMORY_TYPES:
        normalized["memory_type"] = None
        warnings.append("normalized_invalid_route_memory_type")

    if session_memory_type is not None and session_memory_type not in REMOTE_SESSION_MEMORY_TYPES:
        normalized["session_memory_type"] = None
        warnings.append("normalized_invalid_route_session_memory_type")

    if normalized.get("evidence_type") not in REMOTE_EVIDENCE_TYPES:
        normalized["evidence_type"] = "unknown"
        warnings.append("defaulted_route_evidence_type")
    if normalized.get("time_validity") not in REMOTE_TIME_VALIDITIES:
        normalized["time_validity"] = "session" if normalized.get("route") == "session" else "unknown"
        warnings.append("defaulted_route_time_validity")
    if normalized.get("confidence") not in REMOTE_CONFIDENCES:
        normalized["confidence"] = "unknown"
        warnings.append("defaulted_route_confidence")
    if normalized.get("risk") not in REMOTE_RISKS:
        normalized["risk"] = "low"
        warnings.append("defaulted_route_risk")
    if not isinstance(normalized.get("reuse_cases"), list):
        normalized["reuse_cases"] = []
        warnings.append("defaulted_route_reuse_cases")
    if not isinstance(normalized.get("scores"), dict):
        normalized["scores"] = {}
        warnings.append("defaulted_route_scores")
    if not isinstance(normalized.get("metadata"), dict):
        normalized["metadata"] = {}
        warnings.append("defaulted_route_metadata")

    return normalized, warnings


def _govern_memory_route_items(
    items: list[MemoryRouteItem],
    *,
    writable_event_ids: set[str] | None = None,
    event_by_id: dict[str, EventRead] | None = None,
) -> tuple[list[MemoryRouteItem], list[str]]:
    warnings: list[str] = []
    governed: list[MemoryRouteItem] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if (
            writable_event_ids is not None
            and item.route != "ignore"
            and not (set(item.source_event_ids) & writable_event_ids)
        ):
            warnings.append("filtered_context_only_route_item")
            continue

        if (
            writable_event_ids is not None
            and event_by_id is not None
            and item.route in {"long_term", "session"}
            and _route_item_has_only_ack_writable_sources(item, writable_event_ids, event_by_id)
        ):
            warnings.append("filtered_ack_only_route_item")
            continue

        if _contains_sensitive_remote_text(item.content) or _contains_sensitive_remote_text(
            item.claim or ""
        ):
            warnings.append("filtered_sensitive_memory_route_item")
            governed.append(
                item.model_copy(
                    update={
                        "route": "reject",
                        "content": "Sensitive route item omitted.",
                        "claim": None,
                        "reason": "Route item contained sensitive text.",
                        "risk": "high",
                    }
                )
            )
            continue

        update: dict[str, Any] = {}
        if item.route == "long_term" and item.time_validity == "session":
            warnings.append("rerouted_session_validity_item")
            update["route"] = "session"
        if (update.get("route") or item.route) == "session":
            update["time_validity"] = "session"
            if item.session_memory_type is None:
                update["session_memory_type"] = _route_session_type_from_item(item)
        if (update.get("route") or item.route) == "long_term" and item.memory_type is None:
            warnings.append("long_term_route_missing_memory_type")
            update["route"] = "ask_user"

        normalized = item.model_copy(update=update) if update else item
        key = (
            normalized.route,
            _normalize_remote_text(normalized.content),
            _normalize_remote_text(normalized.subject or ""),
        )
        if key in seen:
            warnings.append("deduped_memory_route_item")
            continue
        seen.add(key)
        governed.append(normalized)
    return governed, warnings


def _route_session_type_from_item(item: MemoryRouteItem) -> str:
    lowered = f"{item.content} {item.subject or ''}".lower()
    if any(cue in lowered for cue in ("不理解", "有点乱", "焦虑", "压力", "confused", "anxious")):
        return "emotional_state"
    if item.memory_type == "decision":
        return "pending_decision"
    if item.memory_type in {"tool_rule", "workflow", "user_preference"}:
        return "temporary_rule"
    if item.memory_type in {"project_fact", "environment_fact", "troubleshooting"}:
        return "working_fact"
    return "scratch_note"


def _route_item_has_only_ack_writable_sources(
    item: MemoryRouteItem,
    writable_event_ids: set[str],
    event_by_id: dict[str, EventRead],
) -> bool:
    writable_sources = [
        event_by_id[event_id]
        for event_id in item.source_event_ids
        if event_id in writable_event_ids and event_id in event_by_id
    ]
    if not writable_sources or not all(
        _is_ack_only_route_event(event.content) for event in writable_sources
    ):
        return False
    context_sources = [
        event_by_id[event_id]
        for event_id in item.source_event_ids
        if event_id not in writable_event_ids and event_id in event_by_id
    ]
    return not any(_is_confirmable_assistant_memory_proposal(event) for event in context_sources)


def _is_ack_only_route_event(text: str) -> bool:
    normalized = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE).lower()
    if not normalized:
        return True
    ack_values = {
        "ok",
        "okay",
        "yes",
        "yep",
        "sure",
        "good",
        "fine",
        "thanks",
        "thankyou",
        "gotit",
        "understood",
        "可以",
        "好的",
        "好",
        "嗯",
        "嗯嗯",
        "行",
        "对",
        "是的",
        "没错",
        "收到",
        "明白",
        "了解",
        "谢谢",
        "继续",
    }
    return normalized in ack_values


def _is_confirmable_assistant_memory_proposal(event: EventRead) -> bool:
    if event.event_type != "assistant_message":
        return False
    lowered = event.content.lower()
    memory_cues = (
        "以后",
        "默认",
        "长期",
        "记住",
        "偏好",
        "future",
        "going forward",
        "default",
        "remember",
        "preference",
    )
    proposal_cues = (
        "是否",
        "要不要",
        "可以",
        "建议",
        "吗",
        "?",
        "should",
        "would you like",
        "do you want",
        "can i",
        "i suggest",
    )
    return any(cue in lowered for cue in memory_cues) and any(
        cue in lowered for cue in proposal_cues
    )


def route_item_to_memory_candidate(
    item: MemoryRouteItem,
    event: EventRead | None = None,
) -> MemoryCandidateCreate | None:
    if item.route != "long_term" or item.memory_type is None:
        return None
    source_event_ids = item.source_event_ids or ([event.id] if event is not None else [])
    if not source_event_ids:
        return None
    return MemoryCandidateCreate(
        content=item.content,
        memory_type=item.memory_type,
        scope=item.scope or (event.scope if event is not None else "global"),
        subject=item.subject or (event.source if event is not None else "remote route"),
        source_event_ids=source_event_ids,
        reason=item.reason,
        claim=item.claim or item.content,
        evidence_type=item.evidence_type,
        time_validity=item.time_validity,
        reuse_cases=item.reuse_cases,
        scores=item.scores,
        confidence=item.confidence,
        risk=item.risk,
    )


def _build_memory_route_payload(
    events: list[EventRead],
    *,
    recent_events: list[EventRead],
    current_task_state: dict[str, Any] | None,
    active_session_memories: list[dict[str, Any]],
    instructions: str,
    model: str,
) -> dict[str, Any]:
    return {
        "schema": "memory_system.remote_memory_route.v1",
        "model": model,
        "events": [event.model_dump(mode="json") for event in events],
        "recent_events": [event.model_dump(mode="json") for event in recent_events],
        "event_roles": {
            "events": (
                "Writable source events. Only these events may trigger long_term, "
                "session, reject, or ask_user route items."
            ),
            "recent_events": (
                "Read-only context. Use it to resolve references, judge long_term "
                "versus session, and decide task boundaries, but do not create a "
                "memory item from recent_events alone."
            ),
        },
        "source_id_policy": [
            "Every non-ignore item must include at least one source_event_ids value from events[].id.",
            "A non-ignore item may also include recent_events[].id as supporting context.",
            "Never emit a non-ignore item whose source_event_ids only come from recent_events.",
            "Acknowledgement-only events such as ok, yes, 好的, 可以, 收到, or 明白 do not create long_term/session memory unless the item also cites the assistant proposal being confirmed.",
        ],
        "current_task_state": current_task_state or {},
        "active_session_memories": active_session_memories,
        "instructions": instructions,
        "task_boundary_actions": [
            "same_task",
            "new_task",
            "switch_task",
            "task_done",
            "task_cancelled",
            "unclear",
            "no_change",
        ],
        "routes": {
            "long_term": "Stable reusable memory for future conversations or tasks.",
            "session": (
                "Useful only for the current conversation or task, including temporary "
                "constraints, working state, pending decisions, and current emotional "
                "or comprehension state."
            ),
            "ignore": "Low-information replies, greetings, thanks, simple confirmations, or chatter.",
            "reject": "Sensitive, unsafe, or private-secret content.",
            "ask_user": (
                "Immediate user confirmation is required before proceeding, especially "
                "explicit ask/confirm-before-continuing instructions."
            ),
        },
        "session_memory_types": [
            "task_state",
            "temporary_rule",
            "working_fact",
            "pending_decision",
            "emotional_state",
            "scratch_note",
        ],
        "output": {
            "provider": "string",
            "warnings": ["string"],
            "metadata": {},
            "task_boundary": {
                "action": (
                    "same_task|new_task|switch_task|task_done|"
                    "task_cancelled|unclear|no_change"
                ),
                "confidence": "high|medium|low|unknown",
                "current_task_id": "string|null",
                "current_task_title": "string|null",
                "next_task_title": "string|null",
                "previous_task_status": "active|done|cancelled|unknown",
                "reason": "why this task boundary was selected",
            },
            "items": [
                {
                    "route": "long_term|session|ignore|reject|ask_user",
                    "content": "one atomic claim or route explanation",
                    "reason": "why this route was selected",
                    "memory_type": (
                        "user_preference|project_fact|tool_rule|environment_fact|"
                        "troubleshooting|decision|workflow|reflection|null"
                    ),
                    "session_memory_type": (
                        "task_state|temporary_rule|working_fact|pending_decision|"
                        "emotional_state|scratch_note|null"
                    ),
                    "scope": "string",
                    "subject": "string",
                    "source_event_ids": [
                        "at least one events[].id, optionally plus recent_events[].id"
                    ],
                    "claim": "string",
                    "evidence_type": (
                        "direct_user_statement|file_observation|tool_result|test_result|"
                        "user_confirmation|inferred|unknown"
                    ),
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
                    "metadata": {},
                }
            ],
        },
    }


def _build_session_closeout_payload(
    *,
    session_id: str,
    session_memories: list[SessionMemoryItemRead],
    task_boundary: TaskBoundaryDecision | None,
    current_task_state: dict[str, Any],
    recent_events: list[EventRead],
    instructions: str | None,
    model: str,
) -> dict[str, Any]:
    return {
        "schema": "memory_system.session_closeout.v1",
        "model": model,
        "session_id": session_id,
        "task_boundary": task_boundary.model_dump(mode="json") if task_boundary else None,
        "current_task_state": current_task_state,
        "recent_events": [event.model_dump(mode="json") for event in recent_events],
        "session_memories": [item.model_dump(mode="json") for item in session_memories],
        "instructions": instructions
        or (
            "Classify each session memory at task closeout. Use keep only if the item is still "
            "needed after the boundary. Use discard for transient details, temporary rules, "
            "scratch notes, and emotional states that should not persist. Use summarize for "
            "items useful only as part of a short task recap. Use promote_candidate only for "
            "stable, verified, reusable facts, workflows, decisions, troubleshooting lessons, "
            "or durable user preferences. Never promote secrets or sensitive content. Return "
            "exactly one decision for every session_memories item and copy the exact "
            "session_memories[].id into session_memory_id; do not omit undecided items."
        ),
        "actions": {
            "keep": "Still useful after this boundary; leave active.",
            "discard": "No longer useful after task closeout; dismiss it.",
            "summarize": "Use only in the task_summary; dismiss the original item.",
            "promote_candidate": (
                "Convert into a long-term MemoryCandidateCreate candidate for local policy gate."
            ),
        },
        "output": {
            "provider": "string",
            "warnings": ["string"],
            "metadata": {},
            "task_summary": "short task recap or null",
            "decisions": [
                {
                    "session_memory_id": "one of session_memories[].id",
                    "action": "keep|discard|summarize|promote_candidate",
                    "reason": "why this closeout action was selected",
                    "summary": "short recap text when action=summarize, otherwise null",
                    "candidate": (
                        "MemoryCandidateCreate object when action=promote_candidate, otherwise null"
                    ),
                }
            ],
        },
    }


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


def _build_recall_planner_payload(
    *,
    task: str,
    scope: str | None,
    limit_per_query: int,
    instructions: str | None,
    model: str,
) -> dict[str, Any]:
    return {
        "schema": "memory_system.remote_recall_planner.v1",
        "model": model,
        "task": task,
        "scope": scope,
        "limit_per_query": limit_per_query,
        "instructions": instructions,
        "allowed": {
            "memory_types": sorted(REMOTE_MEMORY_TYPES),
            "strategies": sorted(REMOTE_RECALL_STRATEGIES),
            "planner_sources": ["remote"],
        },
        "output": {
            "intent": "string",
            "facets": ["verification|troubleshooting|memory_system|remote|continuation|language|..."],
            "identifiers": ["string"],
            "constraints": {},
            "query_terms": ["few focused search queries"],
            "memory_types": ["allowed memory type"],
            "scopes": ["scope string"],
            "strategy_hint": "auto|keyword|guarded_hybrid|selective_llm_guarded_hybrid",
            "include_graph": "boolean",
            "include_session": "boolean",
            "needs_llm_judge": "boolean",
            "confidence": "0.0-1.0",
            "reasons": ["string"],
            "warnings": ["string"],
        },
    }


def _parse_recall_plan_result(
    raw: Any,
    *,
    task: str,
    scope: str | None,
    limit_per_query: int,
    model: str,
) -> RecallPlan:
    if not isinstance(raw, dict):
        raise RemoteAdapterError("remote recall planner response must be an object")
    payload = raw.get("plan") if isinstance(raw.get("plan"), dict) else raw
    warnings = _string_list(payload.get("warnings", []))

    memory_types = [
        item for item in _string_list(payload.get("memory_types", [])) if item in REMOTE_MEMORY_TYPES
    ]
    if not memory_types:
        memory_types = ["user_preference", "project_fact", "workflow"]
        warnings.append("remote_planner_missing_memory_types")

    query_terms = _string_list(payload.get("query_terms", []))
    if not query_terms:
        query_terms = [task]
        warnings.append("remote_planner_missing_query_terms")
    query_terms = query_terms[:10]

    scopes = _recall_plan_scopes(payload.get("scopes", []), scope)

    strategy_raw = str(payload.get("strategy_hint") or "auto").strip()
    strategy_hint: RecallStrategy
    if strategy_raw in REMOTE_RECALL_STRATEGIES:
        strategy_hint = strategy_raw  # type: ignore[assignment]
    else:
        strategy_hint = "auto"
        warnings.append(f"invalid_remote_planner_strategy:{strategy_raw}")

    confidence = _bounded_float(payload.get("confidence"), default=0.5)
    constraints_value = payload.get("constraints", {})
    constraints = constraints_value if isinstance(constraints_value, dict) else {"value": constraints_value}

    try:
        return RecallPlan(
            task=task,
            scope=scope.strip() if scope and scope.strip() else None,
            intent=str(payload.get("intent") or "general").strip() or "general",
            query_terms=query_terms,
            memory_types=memory_types,  # type: ignore[arg-type]
            scopes=scopes,
            limit_per_query=limit_per_query,
            reasons=_string_list(payload.get("reasons", [])) or ["remote recall planner"],
            facets=_string_list(payload.get("facets", [])),
            identifiers=_string_list(payload.get("identifiers", [])),
            constraints=constraints,
            strategy_hint=strategy_hint,
            include_graph=_coerce_bool(payload.get("include_graph"), default=False),
            include_session=_coerce_bool(payload.get("include_session"), default=True),
            needs_llm_judge=_coerce_bool(payload.get("needs_llm_judge"), default=False),
            confidence=confidence,
            planner_source="remote",
            planner_warnings=[*warnings, f"model={model}"],
        )
    except ValidationError as exc:
        raise RemoteAdapterError(f"remote recall planner did not match schema: {exc}") from exc


def _recall_plan_scopes(raw_scopes: Any, scope: str | None) -> list[str]:
    scopes = _string_list(raw_scopes)
    requested_scope = scope.strip() if scope and scope.strip() else None
    if requested_scope and requested_scope not in scopes:
        scopes.insert(0, requested_scope)
    if "global" not in scopes:
        scopes.append("global")
    return scopes


def _bounded_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return default


def _build_openai_recall_planner_payload(
    payload: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a recall planner for an agent memory system. "
                    "Return only a valid JSON object. Do not include markdown. "
                    "Your job is to understand the task and produce a structured "
                    "recall plan, not a long keyword list. Prefer a few focused "
                    "query_terms. Use allowed memory_types and strategy_hint values only. "
                    "Set include_session for continuation, pending decisions, current "
                    "task constraints, or references such as previous/continue/刚才/继续. "
                    "Set include_graph for architecture, module relationship, or memory "
                    "system relationship questions. Use guarded_hybrid for semantic or "
                    "remote/model/evaluation tasks when available, keyword for exact "
                    "commands or identifiers, and selective_llm_guarded_hybrid only when "
                    "LLM judging is useful for noisy or ambiguous recall."
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


def _build_recall_judge_batch_payload(
    cases: list[dict[str, Any]],
    *,
    model: str,
    instructions: str,
) -> dict[str, Any]:
    return {
        "schema": "memory_system.remote_recall_judge_batch.v1",
        "model": model,
        "instructions": instructions,
        "cases": cases,
        "output": {
            "results": [
                {
                    "request_id": "string",
                    "provider": "string",
                    "decision": "accepted|ambiguous|rejected",
                    "selected_memory_ids": ["string"],
                    "reason": "string",
                    "risk": "low|medium|high",
                    "warnings": ["string"],
                    "metadata": {},
                }
            ]
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


def _parse_recall_judge_batch_results(
    raw: Any,
    *,
    query_by_request: dict[str, str],
    allowed_ids_by_request: dict[str, list[str]],
) -> dict[str, RemoteRecallJudgeResult]:
    if not isinstance(raw, dict):
        raise RemoteAdapterError("remote batch recall judge response must be an object")
    raw_results = raw.get("results")
    if not isinstance(raw_results, list):
        raise RemoteAdapterError("remote batch recall judge response must include results")
    parsed: dict[str, RemoteRecallJudgeResult] = {}
    for item in raw_results:
        if not isinstance(item, dict):
            raise RemoteAdapterError("remote batch recall judge result must be an object")
        request_id = str(
            item.get("request_id")
            or item.get("case_id")
            or item.get("id")
            or ""
        ).strip()
        if not request_id or request_id not in allowed_ids_by_request:
            continue
        parsed[request_id] = _parse_recall_judge_result(
            item,
            query=query_by_request.get(request_id, ""),
            allowed_memory_ids=allowed_ids_by_request[request_id],
        )
    return parsed


def _govern_remote_candidates(
    candidates: list[MemoryCandidateCreate],
    event: EventRead,
) -> tuple[list[MemoryCandidateCreate], list[str]]:
    warnings: list[str] = []
    if _contains_sensitive_remote_text(event.content):
        if candidates:
            warnings.append("filtered_sensitive_remote_event")
        return [], warnings
    if _is_remote_pending_question_event(event):
        if candidates:
            warnings.append("filtered_pending_question_remote_event")
        return [], warnings

    governed: list[MemoryCandidateCreate] = []
    seen_candidate_keys: set[tuple[str, str, str, str]] = set()
    for candidate in candidates:
        if _contains_sensitive_remote_text(candidate.content) or _contains_sensitive_remote_text(
            candidate.claim or ""
        ):
            warnings.append("filtered_sensitive_remote_candidate")
            continue
        if _is_remote_temporary_event_context(event):
            warnings.append("filtered_temporary_remote_event")
            continue
        if _is_remote_user_rejected_preference(event.content, candidate):
            warnings.append("filtered_remote_preference_rejected_by_user")
            continue
        if _is_remote_temporary_preference_context(event.content, candidate):
            warnings.append("filtered_temporary_remote_preference")
            continue
        if _is_remote_casual_preference_noise(event.content, candidate):
            warnings.append("filtered_casual_remote_preference")
            continue

        normalized_type = _authoritative_remote_memory_type(event)
        if normalized_type and normalized_type != candidate.memory_type:
            warnings.append(
                f"normalized_remote_candidate_type:{candidate.memory_type}->{normalized_type}"
            )
            candidate = candidate.model_copy(update={"memory_type": normalized_type})
        candidate, normalize_warnings = _normalize_remote_candidate(candidate, event)
        warnings.extend(normalize_warnings)
        if _is_remote_inferred_troubleshooting_derivative(event, candidate):
            warnings.append("filtered_inferred_troubleshooting_derivative")
            continue
        if _is_remote_low_evidence_preference(event.content, candidate):
            warnings.append("downgraded_remote_low_evidence_preference")
            candidate = _downgrade_remote_preference_for_confirmation(candidate, event)

        dedupe_keys = _remote_candidate_dedupe_keys(candidate)
        if any(key in seen_candidate_keys for key in dedupe_keys):
            warnings.append("deduped_remote_candidate")
            continue
        seen_candidate_keys.update(dedupe_keys)
        governed.append(candidate)

    return governed, warnings


def _remote_candidate_dedupe_keys(
    candidate: MemoryCandidateCreate,
) -> set[tuple[str, str, str, str]]:
    keys = {
        (
            candidate.memory_type,
            candidate.scope,
            _normalize_remote_text(candidate.subject),
            _normalize_remote_text(candidate.content),
        ),
        (
            candidate.memory_type,
            "*",
            _normalize_remote_text(candidate.subject),
            _normalize_remote_text(candidate.content),
        )
    }
    if candidate.claim:
        keys.add(
            (
                candidate.memory_type,
                candidate.scope,
                _normalize_remote_text(candidate.subject),
                _normalize_remote_text(candidate.claim),
            )
        )
        keys.add(
            (
                candidate.memory_type,
                "*",
                _normalize_remote_text(candidate.subject),
                _normalize_remote_text(candidate.claim),
            )
        )
    return keys


def _normalize_remote_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _remote_fallback_candidates(
    event: EventRead,
) -> tuple[list[MemoryCandidateCreate], list[str]]:
    if event.sanitized or _contains_sensitive_remote_text(event.content):
        return [], []
    if _is_remote_pending_question_event(event):
        return [], ["filtered_pending_question_remote_event"]
    if _is_remote_troubleshooting(event.content):
        return [
            _build_remote_fallback_candidate(
                event,
                memory_type="troubleshooting",
                subject="verified troubleshooting note",
                reason="Local remote governance fallback captured a verified troubleshooting record.",
                reuse_cases=["troubleshooting", "future_debugging"],
                time_validity="until_changed",
            )
        ], ["local_remote_fallback:troubleshooting"]
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
    if _is_remote_low_evidence_preference_text(event.content):
        return [
            _build_remote_fallback_candidate(
                event,
                memory_type="user_preference",
                subject="low-evidence user preference",
                reason=(
                    "Local remote governance fallback captured a low-evidence "
                    "preference for user confirmation."
                ),
                reuse_cases=["style_guidance", "future_responses"],
                time_validity="persistent",
                confidence="inferred",
                scores=CandidateScores(
                    long_term=0.7,
                    evidence=0.4,
                    reuse=0.6,
                    risk=0.2,
                    specificity=0.3,
                ),
                evidence_type="unknown"
                if event.metadata.get("memory_type") and not event.metadata.get("evidence_type")
                else None,
            )
        ], ["local_remote_fallback:low_evidence_user_preference"]
    if _is_remote_stable_preference_text(event.content):
        return [
            _build_remote_fallback_candidate(
                event,
                memory_type="user_preference",
                subject="stable user preference",
                reason="Local remote governance fallback captured a stable user preference.",
                reuse_cases=["style_guidance", "future_responses"],
                time_validity="persistent",
            )
        ], ["local_remote_fallback:stable_user_preference"]
    metadata_type = _metadata_remote_memory_type(event)
    if metadata_type and metadata_type not in {"troubleshooting", "user_preference"}:
        return [
            _build_remote_fallback_candidate(
                event,
                memory_type=metadata_type,
                subject=_remote_metadata_subject(event, metadata_type),
                reason="Local remote governance fallback used the event's explicit memory type.",
                reuse_cases=["project_context", "future_work"],
                time_validity=_metadata_remote_time_validity(event, metadata_type),
            )
        ], [f"local_remote_fallback:metadata_{metadata_type}"]
    if event.event_type != "file_observation" and _is_remote_environment_fact(
        event.content, event
    ):
        return [
            _build_remote_fallback_candidate(
                event,
                memory_type="environment_fact",
                subject=_remote_metadata_subject(event, "environment_fact"),
                reason="Local remote governance fallback captured a confirmed environment fact.",
                reuse_cases=["setup", "verification"],
                time_validity="until_changed",
            )
        ], ["local_remote_fallback:environment_fact"]
    if _is_remote_verified_project_fact(event):
        return [
            _build_remote_fallback_candidate(
                event,
                memory_type="project_fact",
                subject=_remote_project_fact_subject(event),
                reason="Local remote governance fallback captured a verified project fact.",
                reuse_cases=["project_context", "future_work"],
                time_validity="until_changed",
            )
        ], ["local_remote_fallback:project_fact"]
    if _is_remote_tool_rule(event.content):
        return [
            _build_remote_fallback_candidate(
                event,
                memory_type="tool_rule",
                subject="fixed tool rule",
                reason="Local remote governance fallback captured a fixed tool rule.",
                reuse_cases=["tool_usage", "validation"],
                time_validity="until_changed",
            )
        ], ["local_remote_fallback:tool_rule"]
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
    confidence: str = "confirmed",
    scores: CandidateScores | None = None,
    evidence_type: str | None = None,
) -> MemoryCandidateCreate:
    return MemoryCandidateCreate(
        content=event.content,
        memory_type=memory_type,
        scope=event.scope,
        subject=subject,
        source_event_ids=[event.id],
        reason=reason,
        claim=event.content,
        evidence_type=evidence_type or _event_evidence_type(event),
        time_validity=time_validity,
        reuse_cases=reuse_cases,
        scores=scores
        or CandidateScores(
            long_term=0.85,
            evidence=0.9,
            reuse=0.8,
            risk=0.2,
            specificity=0.75,
        ),
        confidence=confidence,
        risk="low",
    )


def _authoritative_remote_memory_type(event: EventRead) -> MemoryType | None:
    preferred = _preferred_remote_memory_type(event)
    metadata_type = _metadata_remote_memory_type(event)
    if metadata_type:
        if preferred in {"troubleshooting", "user_preference"} and preferred != metadata_type:
            return preferred
        return metadata_type
    if preferred == "project_fact" and metadata_type in {
        "environment_fact",
        "tool_rule",
        "workflow",
        "troubleshooting",
    }:
        return metadata_type
    return preferred or metadata_type


def _metadata_remote_memory_type(event: EventRead) -> MemoryType | None:
    raw = event.metadata.get("memory_type")
    if isinstance(raw, str) and raw in REMOTE_MEMORY_TYPES:
        return raw  # type: ignore[return-value]
    return None


def _normalize_remote_candidate(
    candidate: MemoryCandidateCreate,
    event: EventRead,
) -> tuple[MemoryCandidateCreate, list[str]]:
    update: dict[str, Any] = {}
    warnings: list[str] = []

    metadata_subject = event.metadata.get("subject")
    if isinstance(metadata_subject, str) and metadata_subject.strip():
        subject = metadata_subject.strip()
        if subject != candidate.subject:
            update["subject"] = subject
            warnings.append("normalized_remote_candidate_subject_from_event_metadata")

    metadata_claim = event.metadata.get("claim")
    if isinstance(metadata_claim, str) and metadata_claim.strip():
        claim = metadata_claim.strip()
        if claim != (candidate.claim or ""):
            update["claim"] = claim
            warnings.append("normalized_remote_candidate_claim_from_event_metadata")

    metadata_evidence = event.metadata.get("evidence_type")
    if isinstance(metadata_evidence, str) and metadata_evidence.strip():
        if metadata_evidence != candidate.evidence_type:
            update["evidence_type"] = metadata_evidence
            warnings.append("normalized_remote_candidate_evidence_from_event_metadata")

    event_evidence_type = _event_evidence_type(event)
    should_anchor_evidence_to_event = (
        event_evidence_type != "unknown"
        and candidate.evidence_type != event_evidence_type
        and (
            candidate.evidence_type in {"unknown", "inferred"}
            or _is_remote_troubleshooting(event.content)
        )
    )
    if should_anchor_evidence_to_event:
        update["evidence_type"] = event_evidence_type
        warnings.append("normalized_remote_candidate_evidence_from_event")

    if event.metadata.get("memory_type") or event.metadata.get("subject"):
        if candidate.content != event.content:
            update["content"] = event.content
            warnings.append("normalized_remote_candidate_content_from_event")

    if not update:
        return candidate, []
    return candidate.model_copy(update=update), warnings


def _preferred_remote_memory_type(event: EventRead) -> MemoryType | None:
    content = event.content
    if _is_remote_troubleshooting(content):
        return "troubleshooting"
    if _is_remote_global_user_preference(event):
        return "user_preference"
    if _is_remote_verified_project_fact(event):
        return "project_fact"
    if _is_remote_workflow(content, event.scope):
        return "workflow"
    if _is_remote_environment_fact(content, event):
        return "environment_fact"
    if _is_remote_tool_rule(content):
        return "tool_rule"
    if _is_remote_verified_project_fact(event):
        return "project_fact"
    return None


def _is_remote_troubleshooting(content: str) -> bool:
    lowered = content.lower()
    return any(
        all(cue.lower() in lowered for cue in cue_set)
        for cue_set in REMOTE_TROUBLESHOOTING_CUE_SETS
    ) and any(cue.lower() in lowered for cue in REMOTE_VERIFIED_CUES)


def _is_remote_global_user_preference(event: EventRead) -> bool:
    if event.event_type != "user_message":
        return False
    if event.scope.lower().startswith("repo:"):
        return False
    metadata_type = _metadata_remote_memory_type(event)
    if metadata_type and metadata_type != "user_preference":
        return False
    return (
        _is_remote_policy_preference(event.content)
        or _is_remote_stable_preference_text(event.content)
        or _is_remote_low_evidence_preference_text(event.content)
    )


def _is_remote_low_evidence_preference(
    content: str,
    candidate: MemoryCandidateCreate,
) -> bool:
    return candidate.memory_type == "user_preference" and _is_remote_low_evidence_preference_text(
        content
    )


def _is_remote_environment_fact(content: str, event: EventRead) -> bool:
    lowered = content.lower()
    if event.event_type == "file_observation" and _contains_remote_cue(
        content,
        ("\u9879\u76ee\u8bf4\u660e", "project overview", "readme"),
    ):
        return False
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


def _is_remote_temporary_event_context(event: EventRead) -> bool:
    if event.event_type != "user_message":
        return False
    if _contains_remote_cue(event.content, REMOTE_EXPLICIT_MEMORY_CUES):
        return False
    return _contains_remote_cue(event.content, REMOTE_TEMPORARY_PREFERENCE_CUES)


def _is_remote_pending_question_event(event: EventRead) -> bool:
    if event.event_type != "user_message":
        return False
    lowered = event.content.lower()
    has_question = "?" in event.content or "\uff1f" in event.content
    has_confirmation_cue = any(
        cue in lowered
        for cue in (
            "\u7b49\u6211\u4eec\u786e\u8ba4",
            "\u7b49\u786e\u8ba4",
            "\u5f85\u786e\u8ba4",
            "\u786e\u8ba4\u540e",
            "after we confirm",
            "once we confirm",
            "wait until confirmed",
            "pending confirmation",
            "should ",
            "whether ",
        )
    )
    has_choice_cue = "\u8fd8\u662f" in lowered or " or " in lowered
    return has_confirmation_cue and (has_question or has_choice_cue)


def _is_remote_user_rejected_preference(
    content: str,
    candidate: MemoryCandidateCreate,
) -> bool:
    if candidate.memory_type != "user_preference":
        return False
    if _is_remote_policy_preference(content):
        return False
    return _contains_remote_cue(content, REMOTE_DO_NOT_MEMORY_CUES)


def _is_remote_temporary_preference_context(
    content: str,
    candidate: MemoryCandidateCreate,
) -> bool:
    if candidate.memory_type != "user_preference":
        return False
    if _contains_remote_cue(content, REMOTE_EXPLICIT_MEMORY_CUES):
        return False
    return _contains_remote_cue(content, REMOTE_TEMPORARY_PREFERENCE_CUES)


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


def _is_remote_inferred_troubleshooting_derivative(
    event: EventRead,
    candidate: MemoryCandidateCreate,
) -> bool:
    return (
        candidate.memory_type == "troubleshooting"
        and _is_remote_troubleshooting(event.content)
        and (
            candidate.evidence_type == "inferred"
            or (
                _normalize_remote_text(candidate.content) != _normalize_remote_text(event.content)
                and candidate.scores.evidence < 0.5
            )
        )
    )


def _is_remote_low_evidence_preference_text(content: str) -> bool:
    if _is_remote_policy_preference(content):
        return False
    if _contains_remote_cue(content, REMOTE_DO_NOT_MEMORY_CUES):
        return False
    if _contains_remote_cue(content, REMOTE_TEMPORARY_PREFERENCE_CUES) and not _contains_remote_cue(
        content,
        REMOTE_EXPLICIT_MEMORY_CUES,
    ):
        return False
    has_low_evidence_cue = _contains_remote_cue(
        content,
        REMOTE_LOW_EVIDENCE_PREFERENCE_CUES,
    )
    has_underspecified_cue = _contains_remote_cue(
        content,
        REMOTE_UNDERSPECIFIED_PREFERENCE_PHRASES,
    )
    if has_underspecified_cue:
        return True
    return has_low_evidence_cue and _contains_remote_cue(content, REMOTE_PREFERENCE_OBJECT_CUES)


def _is_remote_stable_preference_text(content: str) -> bool:
    if _is_remote_policy_preference(content):
        return False
    if _contains_remote_cue(content, REMOTE_DO_NOT_MEMORY_CUES):
        return False
    if _contains_remote_cue(content, REMOTE_TEMPORARY_PREFERENCE_CUES):
        return False
    return _contains_remote_cue(content, REMOTE_EXPLICIT_MEMORY_CUES) and _contains_remote_cue(
        content,
        REMOTE_PREFERENCE_OBJECT_CUES,
    )


def _downgrade_remote_preference_for_confirmation(
    candidate: MemoryCandidateCreate,
    event: EventRead,
) -> MemoryCandidateCreate:
    scores = candidate.scores.model_copy(
        update={
            "long_term": 0.7,
            "evidence": 0.4,
            "reuse": 0.6,
            "risk": max(candidate.scores.risk, 0.2),
            "specificity": min(candidate.scores.specificity or 0.3, 0.3),
        }
    )
    reason = (
        f"{candidate.reason.rstrip()} "
        "Local remote governance marked this preference as low-evidence; ask the user before writing."
    )
    update: dict[str, Any] = {
        "scores": scores,
        "confidence": "inferred",
        "reason": reason,
        "time_validity": "unknown",
    }
    if event.metadata.get("memory_type") and not event.metadata.get("evidence_type"):
        update["evidence_type"] = "unknown"
    return candidate.model_copy(update=update)


def _is_remote_policy_preference(content: str) -> bool:
    lowered = content.lower()
    has_explicit_memory_cue = any(
        cue.lower() in lowered for cue in REMOTE_EXPLICIT_MEMORY_CUES
    )
    has_policy_cue = any(cue.lower() in lowered for cue in REMOTE_POLICY_PREFERENCE_CUES)
    return has_explicit_memory_cue and has_policy_cue


def _contains_remote_cue(content: str, cues: tuple[str, ...]) -> bool:
    lowered = content.lower()
    return any(cue.lower() in lowered for cue in cues)


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
    if event.event_type == "file_observation":
        lowered = event.content.lower()
        return any(cue.lower() in lowered for cue in REMOTE_VERIFIED_CUES)
    if event.event_type != "tool_result":
        return False
    lowered = event.content.lower()
    has_verified_cue = any(cue.lower() in lowered for cue in REMOTE_VERIFIED_CUES)
    has_source_reference = _contains_remote_cue(
        event.content,
        ("source is", "source:", "\u6765\u6e90", "\u6e90\u6587\u4ef6"),
    )
    return has_verified_cue and has_source_reference


def _remote_project_fact_subject(event: EventRead) -> str:
    metadata_subject = event.metadata.get("subject")
    if isinstance(metadata_subject, str) and metadata_subject.strip():
        return metadata_subject.strip()
    source = event.source.strip() if event.source else "source observation"
    return f"verified project fact from {source}"


def _remote_metadata_subject(event: EventRead, memory_type: MemoryType) -> str:
    metadata_subject = event.metadata.get("subject")
    if isinstance(metadata_subject, str) and metadata_subject.strip():
        return metadata_subject.strip()
    return str(memory_type).replace("_", " ")


def _metadata_remote_time_validity(event: EventRead, memory_type: MemoryType) -> str:
    raw = event.metadata.get("time_validity")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if memory_type == "user_preference":
        return "persistent"
    return "until_changed"


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
        "prefer user_preference for stable global user-message preferences about how the agent should respond; "
        "reject casual same-day likes unless explicitly stable; each candidate must have exactly one atomic claim; "
        "split unrelated facts into separate candidates and set time_validity to persistent, until_changed, session, "
        "or unknown according to the event."
    )
    return f"{instructions.rstrip()}{governance}"


def _with_remote_route_instructions(instructions: str | None) -> str:
    base = instructions or (
        "Classify memory value for the provided events. Return only JSON. "
        "Split unrelated information into atomic route items."
    )
    governance = (
        " Memory route rules: use long_term only for stable, reusable future memory; "
        "use session for information useful to the current conversation or task but not "
        "durable, including temporary constraints, working state, pending decisions, "
        "and current emotional or comprehension state; use ignore for common replies, "
        "thanks, greetings, simple confirmations, or chatter with no memory value; "
        "do not collapse a compound event into one route. If one event contains both "
        "a durable preference/workflow and a temporary current-task state, return "
        "separate long_term and session items for the same source event. "
        "Phrases such as by default, going forward, future reports, future answers, "
        "or long-term preference usually indicate long_term/user_preference when "
        "they describe the user's preferred answer, report, or explanation style. "
        "use reject for sensitive/private-secret content; use ask_user only when "
        "the user explicitly instructs the agent to ask now, pause, stop, or not "
        "proceed before immediate confirmation. Route that item as ask_user, not "
        "session/pending_decision and not long_term/decision. "
        "Inside compound events, still extract a separate ask_user item for any "
        "clause that says ask me before proceeding, do not proceed until confirmed, "
        "or equivalent Chinese instructions such as 先问我/没确认不要动. "
        "When a possible future long-term preference or project rule is explicitly "
        "uncertain but useful to keep in the current conversation, use "
        "session with session_memory_type=pending_decision instead of ask_user. "
        "A phrase like 'pending confirmation' by itself is a pending_decision "
        "record, not ask_user, unless it also tells the agent to ask or block now. "
        "Validation order, release order, test order, or fixed repo process should "
        "be long_term/workflow when stated as a durable procedure. "
        "For session emotional state, do not make a stable personality claim; describe "
        "only the current state needed to adjust the ongoing interaction. "
        "Every non-ignore item must include source_event_ids and one atomic claim. "
        "Treat events as the only writable source events. Treat recent_events as "
        "read-only context that can resolve references, help decide long_term versus "
        "session, and help judge task boundaries, but must not create memory by "
        "itself. Every non-ignore item must cite at least one events[].id in "
        "source_event_ids; it may also cite recent_events[].id as supporting context. "
        "Never emit a non-ignore item whose source_event_ids only come from "
        "recent_events. Simple acknowledgement-only events such as ok, yes, 好的, "
        "可以, 收到, or 明白 must not create long_term or session memory from "
        "recent_events by themselves; only treat them as memory confirmation when "
        "source_event_ids also cites the specific assistant proposal being confirmed."
        " Also judge task boundaries from events plus recent_events and current_task_state. "
        "Use same_task/no_change when the user continues the current work, new_task or "
        "switch_task only for clear semantic task starts or pivots, task_done when the "
        "user says the work is complete, task_cancelled when the user stops or abandons it, "
        "and unclear when context is insufficient. Judge by whether the delivery goal "
        "changed, not by whether the user mentioned a new action. Testing, verifying, "
        "rerunning, explaining, giving examples, syncing docs, or repairing the current "
        "change are usually same_task. Do not infer a task switch from a short "
        "acknowledgement unless recent_events clearly show the user is accepting a proposed "
        "next task. If recent_events proposed a next task and the current user event accepts "
        "it, and that proposed task differs from current_task_state.title, use switch_task "
        "or new_task with high confidence."
    )
    return f"{base.rstrip()}{governance}"


def _with_remote_recall_judge_instructions(instructions: str | None) -> str:
    base = instructions or (
        "Judge whether the provided memory candidates should be recalled for the query. "
        "Return only JSON. Do not invent memory IDs or facts."
    )
    governance = (
        " Recall governance rules: first decide whether each candidate is factual evidence "
        "or behavior guidance. For factual memory types such as project_fact, "
        "environment_fact, troubleshooting, and decision, return accepted only when the "
        "candidate directly answers or materially grounds the query. For behavior-guidance "
        "memory types such as user_preference, workflow, and tool_rule, return accepted "
        "when the candidate should guide how the agent responds or acts for the current "
        "query, even if it does not literally answer the query. "
        "Do not accept generic guidance unless it would change the response or action. "
        "When the query asks for a concrete private value, credential, identifier, "
        "or secret, do not select a candidate merely because it is about the same "
        "private domain or says secrets should not be stored; select only candidates "
        "that contain the exact requested safe fact, otherwise reject. "
        "When the query asks for a factual project state or configured value, do not "
        "let a user_preference replace the factual answer. "
        "Return rejected when no candidate answers or applies to the query; "
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
            "If a global user_message states a stable personal preference about answer style, documentation style, testing explanations, or agent behavior, prefer memory_type='user_preference' even when it mentions tools, workflows, release planning, or verification commands.",
            "Each candidate must contain one atomic claim only; split unrelated facts, preferences, workflows, or rules into separate candidates.",
            "Set time_validity deliberately: persistent for stable user preferences, until_changed for repo facts/workflows/tool rules, session for temporary state, and unknown only when the event is reusable but persistence is unclear.",
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
                    "evidence_span": "short source text supporting this single claim",
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
                    " Use user_preference for stable global user-message preferences about agent behavior."
                    " Return one atomic claim per candidate and split unrelated facts into separate candidates."
                    " Set time_validity deliberately instead of defaulting to unknown."
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


def _build_openai_memory_route_payload(
    payload: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict memory route judge for an agent. "
                    "Return only a valid JSON object with an items array and task_boundary. "
                    "Route each atomic item as long_term, session, ignore, reject, or ask_user. "
                    "Use long_term only for stable reusable future memory. "
                    "Use session for current conversation or task value, including temporary "
                    "constraints, working state, pending decisions, and current emotional "
                    "or comprehension state. "
                    "Do not collapse a compound event into one route. If one event contains "
                    "both a durable preference/workflow and a temporary current-task state, "
                    "return separate long_term and session items for the same source event. "
                    "Phrases such as by default, going forward, future reports, future "
                    "answers, or long-term preference usually indicate "
                    "long_term/user_preference when they describe the user's preferred "
                    "answer, report, or explanation style. "
                    "Use ignore for common replies, greetings, thanks, simple confirmations, "
                    "and low-information chatter. "
                    "Use reject for sensitive or private-secret content. "
                    "Use session with session_memory_type=pending_decision for uncertain "
                    "possible future preferences or project rules that should be retained "
                    "during the current conversation. "
                    "Use ask_user only when the user explicitly instructs the agent to ask "
                    "now, pause, stop, or not proceed before immediate confirmation. "
                    "Do not route those blocking-confirmation instructions as "
                    "session/pending_decision or long_term/decision. "
                    "Inside compound events, still extract a separate ask_user item for "
                    "any clause that says ask me before proceeding, do not proceed until "
                    "confirmed, or equivalent Chinese instructions such as 先问我/没确认不要动. "
                    "A phrase like 'pending confirmation' by itself is a "
                    "session/pending_decision record, not ask_user, unless it also tells "
                    "the agent to ask or block now. "
                    "Validation order, release order, test order, or fixed repo process "
                    "should be long_term/workflow when stated as a durable procedure. "
                    "Never turn current emotional state into a stable personality claim. "
                    "Every non-ignore item must include source_event_ids. "
                    "Treat events as the only writable source events. Treat "
                    "recent_events as read-only context that can resolve references, "
                    "help decide long_term versus session, and help judge task "
                    "boundaries, but must not create memory by itself. Every non-ignore "
                    "item must cite at least one events[].id in source_event_ids; it may "
                    "also cite recent_events[].id as supporting context. Never emit a "
                    "non-ignore item whose source_event_ids only come from recent_events. "
                    "Simple acknowledgement-only events such as ok, yes, 好的, 可以, "
                    "收到, or 明白 must not create long_term or session memory from "
                    "recent_events by themselves; only treat them as memory confirmation "
                    "when source_event_ids also cites the specific assistant proposal "
                    "being confirmed."
                    " Also return task_boundary by judging task continuity from events, "
                    "recent_events, and current_task_state. Use same_task/no_change when "
                    "the user continues the current work, new_task or switch_task only for "
                    "clear semantic task starts or pivots, task_done when work is complete, "
                    "task_cancelled when the user stops or abandons it, and unclear when "
                    "context is insufficient. Judge by whether the delivery goal changed, "
                    "not by whether the user mentioned a new action. Testing, verifying, "
                    "rerunning, explaining, giving examples, syncing docs, or repairing "
                    "the current change are usually same_task. Do not infer a task switch from a short "
                    "acknowledgement unless recent_events clearly show the user is accepting "
                    "a proposed next task. If recent_events proposed a next task and the "
                    "current user event accepts it, and that proposed task differs from "
                    "current_task_state.title, use switch_task or new_task with high confidence."
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


def _build_openai_session_closeout_payload(
    payload: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict session memory closeout judge for an agent. "
                    "Return only a valid JSON object with task_summary and decisions. "
                    "You are deciding what to do with short-term session memories when "
                    "a task is done, cancelled, or switched. Use keep only when an item "
                    "is still needed after the boundary. Use discard for temporary "
                    "rules, scratch notes, transient task state, and current emotional "
                    "states that should not persist. Use summarize for items useful "
                    "only in a task recap. Use promote_candidate only for stable, "
                    "verified, reusable facts, workflows, decisions, troubleshooting "
                    "lessons, or durable user preferences. Promoted candidates must "
                    "follow MemoryCandidateCreate and still pass local policy later. "
                    "Never promote sensitive content or secrets. Return one decision "
                    "for every session_memories[].id."
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
                    "For factual memories, accept only candidates that directly answer or "
                    "materially ground the user's query. "
                    "For user_preference, workflow, and tool_rule memories, accept "
                    "candidates that should guide how the agent responds or acts, even "
                    "when they do not literally answer the query. "
                    "Do not accept generic guidance unless it would change the response or action. "
                    "When the query asks for a concrete private value, credential, "
                    "identifier, or secret, do not select a candidate merely because it is "
                    "about the same private domain or says secrets should not be stored; "
                    "select only candidates that contain the exact requested safe fact, "
                    "otherwise reject. "
                    "When the query asks for a factual project state or configured value, "
                    "do not let a user_preference replace the factual answer. "
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


def _build_openai_recall_judge_batch_payload(
    payload: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict batch memory recall judge for an agent. "
                    "Return only a valid JSON object with a results array. "
                    "Each result must include the original request_id. "
                    "For factual memories, accept only candidates that directly answer or "
                    "materially ground each query. "
                    "For user_preference, workflow, and tool_rule memories, accept "
                    "candidates that should guide how the agent responds or acts, even "
                    "when they do not literally answer the query. "
                    "Do not accept generic guidance unless it would change the response or action. "
                    "When a query asks for a concrete private value, credential, "
                    "identifier, or secret, do not select a candidate merely because it is "
                    "about the same private domain or says secrets should not be stored; "
                    "select only candidates that contain the exact requested safe fact, "
                    "otherwise reject. "
                    "When a query asks for a factual project state or configured value, "
                    "do not let a user_preference replace the factual answer. "
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
    if isinstance(raw, dict) and (
        "candidates" in raw
        or "results" in raw
        or "items" in raw
        or "routes" in raw
        or "plan" in raw
        or "query_terms" in raw
    ):
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
        repaired = _extract_json_object_text(content)
        if repaired and repaired != content:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass
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


def _extract_json_object_text(content: str) -> str | None:
    stripped = content.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
        stripped = stripped.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        return None
    return stripped[start : end + 1]


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
    using_deepseek_env: bool,
) -> str:
    if raw:
        normalized = raw.strip().lower().replace("-", "_")
        if normalized in {"openai", "openai_compatible", "compatible"}:
            return OPENAI_COMPATIBILITY
        if normalized == GENERIC_COMPATIBILITY:
            return GENERIC_COMPATIBILITY
    if using_dashscope_env or using_deepseek_env or _looks_openai_compatible(base_url):
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
    return (
        "compatible-mode" in normalized
        or "api.deepseek.com" in normalized
        or normalized.rstrip("/").endswith("/v1")
    )


def _has_env_prefix(prefix: str) -> bool:
    prefix_with_sep = f"{prefix}_"
    return any(key.startswith(prefix_with_sep) for key in os.environ)


def _has_remote_config_prefix(prefix: str) -> bool:
    return any(
        _optional_text(os.environ.get(f"{prefix}_{suffix}"))
        for suffix in (
            "BASE_URL",
            "API_KEY",
            "COMPATIBILITY",
            "LLM_MODEL",
            "EMBEDDING_COMPATIBILITY",
            "EMBEDDING_MODEL",
            "EMBEDDING_PATH",
        )
    )


def _remote_timeout_from_env(prefix: str) -> float:
    raw = os.environ.get(f"{prefix}_TIMEOUT_SECONDS") or os.environ.get(
        "MEMORY_REMOTE_TIMEOUT_SECONDS",
        "30",
    )
    try:
        return float(raw)
    except ValueError:
        return 10.0


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
