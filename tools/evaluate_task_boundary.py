from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory_system.remote import RemoteAdapterConfig, RemoteAdapterError, RemoteLLMClient  # noqa: E402
from memory_system.schemas import EventRead, TaskBoundaryDecision  # noqa: E402


DEFAULT_FIXTURE = ROOT / "tests/fixtures/golden_cases/task_boundary.jsonl"


@dataclass(frozen=True)
class ExpectedBoundary:
    action: str
    acceptable_actions: tuple[str, ...]
    next_task_title: str | None = None


@dataclass(frozen=True)
class ActualBoundary:
    action: str | None
    confidence: str | None = None
    next_task_title: str | None = None
    reason: str | None = None


@dataclass
class CaseOutcome:
    actual: ActualBoundary
    warnings: list[str]
    latency_ms: float | None
    provider: str | None = None
    remote_error: str | None = None


@dataclass
class BoundaryStats:
    cases: int = 0
    action_passed: int = 0
    strict_passed: int = 0
    missing_boundary: int = 0
    remote_error: int = 0
    action_mismatch: int = 0
    next_title_mismatch: int = 0
    local_gate_adjustments: int = 0
    latency_ms_total: float = 0.0
    latency_ms_count: int = 0

    @property
    def action_accuracy(self) -> float:
        return round(self.action_passed / self.cases, 4) if self.cases else 0.0

    @property
    def strict_accuracy(self) -> float:
        return round(self.strict_passed / self.cases, 4) if self.cases else 0.0

    @property
    def average_latency_ms(self) -> float | None:
        if not self.latency_ms_count:
            return None
        return round(self.latency_ms_total / self.latency_ms_count, 2)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action_accuracy"] = self.action_accuracy
        payload["strict_accuracy"] = self.strict_accuracy
        payload["average_latency_ms"] = self.average_latency_ms
        return payload


@dataclass
class BoundaryFailure:
    fixture: str
    name: str
    category: str
    event_text: str
    expected: ExpectedBoundary
    actual: ActualBoundary
    action_failure: str | None
    strict_failure: str | None
    warnings: list[str] = field(default_factory=list)
    remote_error: str | None = None


@dataclass
class EvaluationResult:
    summary: BoundaryStats
    category_summary: dict[str, BoundaryStats]
    failures: list[BoundaryFailure]
    selection: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, *, failure_limit: int) -> dict[str, Any]:
        return {
            "summary": self.summary.to_dict(),
            "category_summary": {
                category: stats.to_dict()
                for category, stats in sorted(self.category_summary.items())
            },
            "failures": [
                {
                    **asdict(failure),
                    "expected": asdict(failure.expected),
                    "actual": asdict(failure.actual),
                }
                for failure in self.failures[:failure_limit]
            ],
            "selection": self.selection,
            "warnings": self.warnings,
        }


def load_cases(paths: Iterable[Path]) -> list[tuple[Path, dict[str, Any]]]:
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
            if not isinstance(case, dict):
                raise ValueError(f"{path}:{line_number}: expected object")
            loaded.append((path, case))
    return loaded


def select_cases(
    cases: list[tuple[Path, dict[str, Any]]],
    *,
    categories: set[str] | None = None,
    sample_size: int | None = None,
    sample_seed: int | None = None,
    sample_per_category: int | None = None,
    limit: int | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    selected = list(cases)
    if categories:
        selected = [(path, case) for path, case in selected if case.get("category") in categories]

    rng = random.Random(sample_seed)
    if sample_per_category is not None:
        if sample_per_category < 1:
            raise ValueError("--sample-per-category must be greater than zero")
        grouped: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
        for item in selected:
            grouped[str(item[1].get("category", "unknown"))].append(item)
        sampled: list[tuple[Path, dict[str, Any]]] = []
        for category in sorted(grouped):
            group = grouped[category]
            if sample_seed is None:
                sampled.extend(group[:sample_per_category])
            else:
                sampled.extend(rng.sample(group, min(sample_per_category, len(group))))
        selected = sampled

    if sample_size is not None:
        if sample_size < 1:
            raise ValueError("--sample-size must be greater than zero")
        selected = rng.sample(selected, min(sample_size, len(selected)))

    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be greater than zero")
        selected = selected[:limit]

    return selected


def expected_boundary(case: dict[str, Any]) -> ExpectedBoundary:
    expected = case["expected"]
    acceptable = expected.get("acceptable_actions") or [expected["action"]]
    return ExpectedBoundary(
        action=str(expected["action"]),
        acceptable_actions=tuple(str(action) for action in acceptable),
        next_task_title=expected.get("next_task_title"),
    )


def evaluate_task_boundary_case(
    fixture: Path,
    case: dict[str, Any],
    *,
    remote_llm: RemoteLLMClient,
    instructions: str | None = None,
) -> tuple[ExpectedBoundary, CaseOutcome, str | None, str | None]:
    expected = expected_boundary(case)
    name = str(case.get("name", "case"))
    events = [
        _event_from_raw(raw, event_id=f"{name}_event_{index}")
        for index, raw in enumerate(case.get("events", []))
    ]
    recent_events = [
        _event_from_raw(raw, event_id=f"{name}_recent_{index}")
        for index, raw in enumerate(case.get("recent_events", []))
    ]
    start = time.perf_counter()
    try:
        result = remote_llm.route_memories(
            events,
            recent_events=recent_events,
            current_task_state=case.get("current_task_state") or {},
            instructions=instructions,
        )
    except RemoteAdapterError as exc:
        return (
            expected,
            CaseOutcome(
                actual=ActualBoundary(action=None),
                warnings=[],
                latency_ms=None,
                remote_error=str(exc),
            ),
            "remote_error",
            "remote_error",
        )
    latency_ms = (time.perf_counter() - start) * 1000
    actual = _actual_boundary(result.task_boundary)
    if actual.action is None:
        action_failure = "missing_task_boundary"
    elif actual.action not in expected.acceptable_actions:
        action_failure = f"expected {expected.acceptable_actions}, got {actual.action}"
    else:
        action_failure = None

    if action_failure is not None:
        strict_failure = action_failure
    elif expected.next_task_title and not _titles_match(
        expected.next_task_title,
        actual.next_task_title,
    ):
        strict_failure = (
            f"expected next_task_title like {expected.next_task_title!r}, "
            f"got {actual.next_task_title!r}"
        )
    else:
        strict_failure = None

    return (
        expected,
        CaseOutcome(
            actual=actual,
            warnings=list(result.warnings),
            latency_ms=latency_ms,
            provider=result.provider,
        ),
        action_failure,
        strict_failure,
    )


def evaluate_task_boundaries(
    fixture_paths: list[Path],
    *,
    remote_llm: RemoteLLMClient | None = None,
    categories: set[str] | None = None,
    sample_size: int | None = None,
    sample_seed: int | None = None,
    sample_per_category: int | None = None,
    limit: int | None = None,
    case_concurrency: int = 1,
    instructions: str | None = None,
) -> EvaluationResult:
    all_cases = load_cases(fixture_paths)
    selected = select_cases(
        all_cases,
        categories=categories,
        sample_size=sample_size,
        sample_seed=sample_seed,
        sample_per_category=sample_per_category,
        limit=limit,
    )
    client = remote_llm or RemoteLLMClient(RemoteAdapterConfig.llm_from_env())
    summary = BoundaryStats()
    category_summary: dict[str, BoundaryStats] = defaultdict(BoundaryStats)
    failures: list[BoundaryFailure] = []

    def run(item: tuple[Path, dict[str, Any]]) -> tuple[Path, dict[str, Any], ExpectedBoundary, CaseOutcome, str | None, str | None]:
        path, case = item
        expected, outcome, action_failure, strict_failure = evaluate_task_boundary_case(
            path,
            case,
            remote_llm=client,
            instructions=instructions,
        )
        return path, case, expected, outcome, action_failure, strict_failure

    if case_concurrency <= 1:
        results = [run(item) for item in selected]
    else:
        with ThreadPoolExecutor(max_workers=case_concurrency) as executor:
            futures = [executor.submit(run, item) for item in selected]
            results = [future.result() for future in as_completed(futures)]

    for path, case, expected, outcome, action_failure, strict_failure in results:
        _accumulate(
            summary,
            expected=expected,
            outcome=outcome,
            action_failure=action_failure,
            strict_failure=strict_failure,
        )
        category = str(case.get("category", "unknown"))
        _accumulate(
            category_summary[category],
            expected=expected,
            outcome=outcome,
            action_failure=action_failure,
            strict_failure=strict_failure,
        )
        if action_failure or strict_failure or outcome.remote_error:
            failures.append(
                BoundaryFailure(
                    fixture=str(path),
                    name=str(case.get("name", "")),
                    category=category,
                    event_text=" | ".join(
                        str(event.get("content", ""))
                        for event in case.get("events", [])
                        if isinstance(event, dict)
                    ),
                    expected=expected,
                    actual=outcome.actual,
                    action_failure=action_failure,
                    strict_failure=strict_failure,
                    warnings=outcome.warnings,
                    remote_error=outcome.remote_error,
                )
            )

    return EvaluationResult(
        summary=summary,
        category_summary=dict(category_summary),
        failures=failures,
        selection={
            "fixtures": [str(path) for path in fixture_paths],
            "loaded": len(all_cases),
            "selected": len(selected),
            "categories": sorted(categories or []),
            "sample_size": sample_size,
            "sample_seed": sample_seed,
            "sample_per_category": sample_per_category,
            "limit": limit,
            "case_concurrency": case_concurrency,
        },
    )


def _accumulate(
    stats: BoundaryStats,
    *,
    expected: ExpectedBoundary,
    outcome: CaseOutcome,
    action_failure: str | None,
    strict_failure: str | None,
) -> None:
    del expected
    stats.cases += 1
    if outcome.remote_error:
        stats.remote_error += 1
    if outcome.actual.action is None:
        stats.missing_boundary += 1
    if action_failure is None:
        stats.action_passed += 1
    else:
        stats.action_mismatch += 1
    if strict_failure is None:
        stats.strict_passed += 1
    elif strict_failure != action_failure:
        stats.next_title_mismatch += 1
    if any(
        warning
        in {
            "inferred_task_boundary_next_title",
            "normalized_task_boundary_cancel_signal",
            "normalized_task_boundary_done_signal",
            "normalized_task_boundary_switch_signal",
            "weakened_task_boundary_switch_evidence",
        }
        for warning in outcome.warnings
    ):
        stats.local_gate_adjustments += 1
    if outcome.latency_ms is not None:
        stats.latency_ms_total += outcome.latency_ms
        stats.latency_ms_count += 1


def _event_from_raw(raw: dict[str, Any], *, event_id: str) -> EventRead:
    return EventRead(
        id=event_id,
        event_type=raw.get("event_type", "user_message"),
        content=str(raw["content"]),
        source=str(raw.get("source") or "conversation"),
        scope=str(raw.get("scope") or "global"),
        metadata=dict(raw.get("metadata") or {}),
        created_at=datetime.now(timezone.utc),
    )


def _actual_boundary(boundary: TaskBoundaryDecision | None) -> ActualBoundary:
    if boundary is None:
        return ActualBoundary(action=None)
    return ActualBoundary(
        action=boundary.action,
        confidence=boundary.confidence,
        next_task_title=boundary.next_task_title,
        reason=boundary.reason,
    )


def _titles_match(expected: str, actual: str | None) -> bool:
    if not actual:
        return False
    expected_norm = _normalize_title(expected)
    actual_norm = _normalize_title(actual)
    return expected_norm in actual_norm or actual_norm in expected_norm


def _normalize_title(text: str) -> str:
    return "".join(ch.lower() for ch in text if ch.isalnum())


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate remote task boundary decisions.")
    parser.add_argument("--fixture", action="append", type=Path)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--sample-size", type=int)
    parser.add_argument("--sample-seed", type=int)
    parser.add_argument("--sample-per-category", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case-concurrency", type=int, default=1)
    parser.add_argument("--failure-limit", type=int, default=20)
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    fixtures = args.fixture or [DEFAULT_FIXTURE]
    result = evaluate_task_boundaries(
        fixtures,
        categories=set(args.category) if args.category else None,
        sample_size=args.sample_size,
        sample_seed=args.sample_seed,
        sample_per_category=args.sample_per_category,
        limit=args.limit,
        case_concurrency=args.case_concurrency,
    )
    payload = result.to_dict(failure_limit=args.failure_limit)
    if args.report_path:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(
        "task boundary: "
        f"action={result.summary.action_passed}/{result.summary.cases} "
        f"strict={result.summary.strict_passed}/{result.summary.cases} "
        f"gate_adjustments={result.summary.local_gate_adjustments} "
        f"remote_errors={result.summary.remote_error}"
    )
    for failure in result.failures[: args.failure_limit]:
        print(
            f"- {failure.name}: expected={failure.expected.acceptable_actions} "
            f"actual={failure.actual.action} strict={failure.strict_failure}"
        )


if __name__ == "__main__":
    main()
