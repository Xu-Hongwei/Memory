from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory_system.remote import (  # noqa: E402
    RemoteAdapterConfig,
    RemoteAdapterError,
    RemoteLLMClient,
)
from memory_system.schemas import EventRead, MemoryRouteItem  # noqa: E402


DEFAULT_FIXTURE = ROOT / "tests/fixtures/golden_cases/session_route.jsonl"


@dataclass(frozen=True)
class ExpectedRoute:
    route: str
    session_memory_type: str | None = None
    memory_type: str | None = None
    context_role: str = "excluded"
    remote_preflight_reject: bool = False


@dataclass(frozen=True)
class ActualRoute:
    route: str
    session_memory_type: str | None = None
    memory_type: str | None = None
    subject: str | None = None
    reason: str | None = None


@dataclass
class RouteOutcome:
    actual: list[ActualRoute]
    selected: ActualRoute | None
    warnings: list[str]
    latency_ms: float | None
    provider: str | None = None
    remote_error: str | None = None
    skipped_remote_call: bool = False


@dataclass
class CaseEvaluation:
    fixture: Path
    case: dict[str, Any]
    expected: ExpectedRoute
    outcome: RouteOutcome
    route_failure: str | None
    strict_failure: str | None
    serious_failure: str | None


@dataclass
class RouteStats:
    cases: int = 0
    route_passed: int = 0
    strict_passed: int = 0
    remote_error: int = 0
    route_mismatch: int = 0
    session_type_mismatch: int = 0
    memory_type_mismatch: int = 0
    extra_noise: int = 0
    serious_failures: int = 0
    skipped_remote_calls: int = 0
    latency_ms_total: float = 0.0
    latency_ms_count: int = 0

    @property
    def route_accuracy(self) -> float:
        return round(self.route_passed / self.cases, 4) if self.cases else 0.0

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
        payload["route_accuracy"] = self.route_accuracy
        payload["strict_accuracy"] = self.strict_accuracy
        payload["average_latency_ms"] = self.average_latency_ms
        return payload


@dataclass
class RouteFailure:
    fixture: str
    name: str
    category: str
    content: str
    expected: ExpectedRoute
    actual: list[ActualRoute]
    selected: ActualRoute | None
    route_failure: str | None
    strict_failure: str | None
    serious_failure: str | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class EvaluationResult:
    summary: RouteStats
    category_summary: dict[str, RouteStats]
    failures: list[RouteFailure]
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
                    "actual": [asdict(item) for item in failure.actual],
                    "selected": asdict(failure.selected) if failure.selected else None,
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


def expected_route(case: dict[str, Any]) -> ExpectedRoute:
    expected = case["expected"]
    return ExpectedRoute(
        route=expected["route"],
        session_memory_type=expected.get("session_memory_type"),
        memory_type=expected.get("memory_type"),
        context_role=expected.get("context_role", "excluded"),
        remote_preflight_reject=bool(expected.get("remote_preflight_reject", False)),
    )


def event_from_case(case: dict[str, Any]) -> EventRead:
    event = case["event"]
    return EventRead(
        id=f"evt_{case['name']}",
        event_type=event["event_type"],
        content=event["content"],
        source=event["source"],
        scope=event["scope"],
        metadata=event.get("metadata", {}),
        created_at=datetime.now(timezone.utc),
    )


def actual_from_item(item: MemoryRouteItem) -> ActualRoute:
    return ActualRoute(
        route=item.route,
        session_memory_type=item.session_memory_type,
        memory_type=item.memory_type,
        subject=item.subject,
        reason=item.reason,
    )


def _score_item(expected: ExpectedRoute, item: ActualRoute) -> tuple[int, int, int]:
    route_score = 1 if item.route == expected.route else 0
    session_score = (
        1
        if expected.session_memory_type is not None
        and item.session_memory_type == expected.session_memory_type
        else 0
    )
    memory_score = (
        1
        if expected.memory_type is not None and item.memory_type == expected.memory_type
        else 0
    )
    return route_score, session_score, memory_score


def select_primary_item(expected: ExpectedRoute, actual: list[ActualRoute]) -> ActualRoute | None:
    if not actual:
        return None
    return max(actual, key=lambda item: _score_item(expected, item))


def has_extra_noise(expected: ExpectedRoute, actual: list[ActualRoute], selected: ActualRoute | None) -> bool:
    if not actual or selected is None:
        return False
    if expected.route == "ignore":
        return any(item.route != "ignore" for item in actual)
    if expected.route == "reject":
        return any(item.route != "reject" for item in actual)
    return any(item is not selected and item.route not in {expected.route, "ignore"} for item in actual)


def classify_route_failure(
    expected: ExpectedRoute,
    outcome: RouteOutcome,
) -> tuple[str | None, str | None, str | None]:
    if outcome.remote_error:
        return "remote_error", "remote_error", "remote_error"
    selected = outcome.selected
    if selected is None:
        if expected.route == "ignore":
            return None, None, None
        return "missing_route", "missing_route", _serious_missing_route(expected)
    if selected.route != expected.route:
        failure = f"route_mismatch:{selected.route}"
        return failure, failure, _serious_route_mismatch(expected, selected)

    route_failure = None
    strict_failure = None
    if expected.route == "session" and selected.session_memory_type != expected.session_memory_type:
        strict_failure = "session_type_mismatch"
    elif expected.route == "long_term" and selected.memory_type != expected.memory_type:
        strict_failure = "memory_type_mismatch"

    if has_extra_noise(expected, outcome.actual, selected):
        strict_failure = strict_failure or "extra_noise"

    return route_failure, strict_failure, None


def _serious_missing_route(expected: ExpectedRoute) -> str | None:
    if expected.route in {"reject", "ask_user", "long_term"}:
        return f"missing_{expected.route}"
    if expected.route == "session" and expected.context_role == "critical":
        return "missing_critical_session"
    return None


def _serious_route_mismatch(expected: ExpectedRoute, selected: ActualRoute) -> str | None:
    if expected.route == "reject":
        return f"sensitive_not_rejected:{selected.route}"
    if expected.route == "ask_user":
        return f"confirmation_not_requested:{selected.route}"
    if expected.route == "long_term" and selected.route != "long_term":
        return f"long_term_missed:{selected.route}"
    if expected.route == "session" and expected.context_role == "critical":
        return f"critical_session_missed:{selected.route}"
    if expected.route == "ignore" and selected.route in {"long_term", "session"}:
        return f"ignore_became_noise:{selected.route}"
    return None


def evaluate_case(
    item: tuple[Path, dict[str, Any]],
    *,
    remote_llm: RemoteLLMClient,
    instructions: str | None,
) -> CaseEvaluation:
    path, case = item
    expected = expected_route(case)
    event = event_from_case(case)
    started = time.perf_counter()
    try:
        result = remote_llm.route_memories([event], instructions=instructions)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        actual = [actual_from_item(route_item) for route_item in result.items]
        selected = select_primary_item(expected, actual)
        outcome = RouteOutcome(
            actual=actual,
            selected=selected,
            warnings=result.warnings,
            latency_ms=latency_ms,
            provider=result.provider,
            skipped_remote_call=bool(result.metadata.get("skipped_remote_call", False)),
        )
    except RemoteAdapterError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        outcome = RouteOutcome(
            actual=[],
            selected=None,
            warnings=[str(exc)],
            latency_ms=latency_ms,
            remote_error=str(exc),
        )
    route_failure, strict_failure, serious_failure = classify_route_failure(expected, outcome)
    return CaseEvaluation(
        fixture=path,
        case=case,
        expected=expected,
        outcome=outcome,
        route_failure=route_failure,
        strict_failure=strict_failure,
        serious_failure=serious_failure,
    )


def evaluate_case_batch(
    cases: list[tuple[Path, dict[str, Any]]],
    *,
    remote_llm: RemoteLLMClient,
    instructions: str | None,
    case_concurrency: int,
) -> list[CaseEvaluation]:
    if case_concurrency < 1:
        raise ValueError("case_concurrency must be greater than zero")
    if case_concurrency == 1:
        return [
            evaluate_case(item, remote_llm=remote_llm, instructions=instructions)
            for item in cases
        ]

    evaluations_by_index: dict[int, CaseEvaluation] = {}
    with ThreadPoolExecutor(max_workers=case_concurrency) as executor:
        futures = {
            executor.submit(
                evaluate_case,
                item,
                remote_llm=remote_llm,
                instructions=instructions,
            ): index
            for index, item in enumerate(cases)
        }
        for future in as_completed(futures):
            evaluations_by_index[futures[future]] = future.result()
    return [evaluations_by_index[index] for index in range(len(cases))]


def update_stats(stats: RouteStats, evaluation: CaseEvaluation) -> None:
    stats.cases += 1
    if evaluation.outcome.latency_ms is not None:
        stats.latency_ms_total += evaluation.outcome.latency_ms
        stats.latency_ms_count += 1
    if evaluation.outcome.skipped_remote_call:
        stats.skipped_remote_calls += 1
    if evaluation.route_failure is None:
        stats.route_passed += 1
    if evaluation.route_failure is None and evaluation.strict_failure is None:
        stats.strict_passed += 1
    if evaluation.route_failure == "remote_error":
        stats.remote_error += 1
    elif evaluation.route_failure is not None:
        stats.route_mismatch += 1
    if evaluation.strict_failure == "session_type_mismatch":
        stats.session_type_mismatch += 1
    elif evaluation.strict_failure == "memory_type_mismatch":
        stats.memory_type_mismatch += 1
    elif evaluation.strict_failure == "extra_noise":
        stats.extra_noise += 1
    if evaluation.serious_failure:
        stats.serious_failures += 1


def evaluate_session_routes(
    cases: list[tuple[Path, dict[str, Any]]],
    *,
    remote_llm: RemoteLLMClient | None = None,
    instructions: str | None = None,
    case_concurrency: int = 1,
    selection: dict[str, Any] | None = None,
    failure_limit: int = 20,
) -> EvaluationResult:
    remote = remote_llm or RemoteLLMClient(RemoteAdapterConfig.llm_from_env())
    evaluations = evaluate_case_batch(
        cases,
        remote_llm=remote,
        instructions=instructions,
        case_concurrency=case_concurrency,
    )

    summary = RouteStats()
    category_summary: dict[str, RouteStats] = defaultdict(RouteStats)
    failures: list[RouteFailure] = []
    warnings: list[str] = []
    for evaluation in evaluations:
        category = str(evaluation.case.get("category", "unknown"))
        update_stats(summary, evaluation)
        update_stats(category_summary[category], evaluation)
        if evaluation.outcome.warnings:
            counts = Counter(evaluation.outcome.warnings)
            warnings.extend(
                f"{evaluation.case['name']}:{warning} x{count}"
                for warning, count in counts.items()
            )
        if (
            evaluation.route_failure
            or evaluation.strict_failure
            or evaluation.serious_failure
        ) and len(failures) < failure_limit:
            failures.append(
                RouteFailure(
                    fixture=evaluation.fixture.name,
                    name=evaluation.case["name"],
                    category=category,
                    content=evaluation.case["event"]["content"],
                    expected=evaluation.expected,
                    actual=evaluation.outcome.actual,
                    selected=evaluation.outcome.selected,
                    route_failure=evaluation.route_failure,
                    strict_failure=evaluation.strict_failure,
                    serious_failure=evaluation.serious_failure,
                    warnings=evaluation.outcome.warnings,
                )
            )

    return EvaluationResult(
        summary=summary,
        category_summary=dict(category_summary),
        failures=failures,
        selection=selection or {},
        warnings=warnings,
    )


def _fixture_paths(values: Iterable[Path] | None) -> tuple[Path, ...]:
    return tuple(values or (DEFAULT_FIXTURE,))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate remote memory routing against session_route golden cases."
    )
    parser.add_argument("--fixture", action="append", type=Path)
    parser.add_argument("--category", action="append")
    parser.add_argument("--sample-size", type=int)
    parser.add_argument("--sample-seed", type=int, default=20260430)
    parser.add_argument("--sample-per-category", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case-concurrency", type=int, default=1)
    parser.add_argument("--failure-limit", type=int, default=20)
    parser.add_argument("--instructions")
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _format_actual(items: list[ActualRoute]) -> str:
    if not items:
        return "[]"
    return "[" + ", ".join(
        f"{item.route}/{item.session_memory_type or item.memory_type or '-'}"
        for item in items
    ) + "]"


def _print_text_result(result: EvaluationResult, *, failure_limit: int) -> None:
    summary = result.summary
    print(
        "SUMMARY "
        f"cases={summary.cases} "
        f"route_passed={summary.route_passed} "
        f"strict_passed={summary.strict_passed} "
        f"route_accuracy={summary.route_accuracy:.4f} "
        f"strict_accuracy={summary.strict_accuracy:.4f} "
        f"route_mismatch={summary.route_mismatch} "
        f"session_type_mismatch={summary.session_type_mismatch} "
        f"memory_type_mismatch={summary.memory_type_mismatch} "
        f"extra_noise={summary.extra_noise} "
        f"serious_failures={summary.serious_failures} "
        f"remote_error={summary.remote_error} "
        f"skipped_remote_calls={summary.skipped_remote_calls} "
        f"avg_latency_ms={summary.average_latency_ms}"
    )
    print("CATEGORY SUMMARY")
    for category, stats in sorted(result.category_summary.items()):
        print(
            f"- {category}: cases={stats.cases} "
            f"route={stats.route_passed}/{stats.cases} "
            f"strict={stats.strict_passed}/{stats.cases} "
            f"serious={stats.serious_failures}"
        )
    if not result.failures:
        print("FAILURES none")
        return
    print("FAILURES")
    for failure in result.failures[:failure_limit]:
        expected_type = failure.expected.session_memory_type or failure.expected.memory_type or "-"
        print(
            f"! {failure.name} [{failure.category}] "
            f"expected={failure.expected.route}/{expected_type} "
            f"actual={_format_actual(failure.actual)} "
            f"route_failure={failure.route_failure or 'pass'} "
            f"strict_failure={failure.strict_failure or 'pass'} "
            f"serious={failure.serious_failure or '-'}"
        )
        if failure.warnings:
            print("  warnings=" + " | ".join(failure.warnings[:3]))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = _fixture_paths(args.fixture)
    cases = load_cases(paths)
    categories = set(args.category or []) or None
    selected = select_cases(
        cases,
        categories=categories,
        sample_size=args.sample_size,
        sample_seed=args.sample_seed,
        sample_per_category=args.sample_per_category,
        limit=args.limit,
    )
    selection = {
        "fixtures": [str(path) for path in paths],
        "case_count": len(selected),
        "categories": sorted(categories) if categories else None,
        "sample_size": args.sample_size,
        "sample_seed": args.sample_seed,
        "sample_per_category": args.sample_per_category,
        "limit": args.limit,
        "case_concurrency": args.case_concurrency,
        "case_names": [case["name"] for _path, case in selected],
    }
    result = evaluate_session_routes(
        selected,
        instructions=args.instructions,
        case_concurrency=args.case_concurrency,
        selection=selection,
        failure_limit=args.failure_limit,
    )
    payload = result.to_dict(failure_limit=args.failure_limit)
    if args.report_path:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text_result(result, failure_limit=args.failure_limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
