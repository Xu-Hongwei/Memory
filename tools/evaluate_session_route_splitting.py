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

from memory_system.remote import RemoteAdapterConfig, RemoteAdapterError, RemoteLLMClient  # noqa: E402
from memory_system.schemas import EventRead, MemoryRouteItem  # noqa: E402


DEFAULT_FIXTURE = ROOT / "tests/fixtures/golden_cases/session_route_splitting.jsonl"


@dataclass(frozen=True)
class ExpectedSplitItem:
    label: str
    route: str
    source_event_ids: tuple[str, ...] = ()
    session_memory_type: str | None = None
    memory_type: str | None = None
    context_role: str = "excluded"


@dataclass(frozen=True)
class ActualSplitItem:
    route: str
    source_event_ids: tuple[str, ...] = ()
    session_memory_type: str | None = None
    memory_type: str | None = None
    subject: str | None = None
    reason: str | None = None


@dataclass
class SplitItemEvaluation:
    expected: ExpectedSplitItem
    selected: ActualSplitItem | None
    route_failure: str | None
    strict_failure: str | None
    serious_failure: str | None


@dataclass
class SplitCaseEvaluation:
    fixture: Path
    case: dict[str, Any]
    expected: list[ExpectedSplitItem]
    actual: list[ActualSplitItem]
    item_evaluations: list[SplitItemEvaluation]
    unused_actual: list[ActualSplitItem]
    warnings: list[str]
    latency_ms: float | None
    provider: str | None = None
    remote_error: str | None = None
    skipped_remote_call: bool = False

    @property
    def route_passed(self) -> bool:
        return self.remote_error is None and all(
            item.route_failure is None for item in self.item_evaluations
        )

    @property
    def strict_passed(self) -> bool:
        return (
            self.route_passed
            and not self.extra_noise
            and all(item.strict_failure is None for item in self.item_evaluations)
        )

    @property
    def extra_noise(self) -> bool:
        return any(item.route != "ignore" for item in self.unused_actual)


@dataclass
class SplitStats:
    cases: int = 0
    route_passed_cases: int = 0
    strict_passed_cases: int = 0
    expected_items: int = 0
    route_passed_items: int = 0
    strict_passed_items: int = 0
    remote_error: int = 0
    missing_items: int = 0
    route_mismatch: int = 0
    session_type_mismatch: int = 0
    memory_type_mismatch: int = 0
    source_mismatch: int = 0
    extra_noise_cases: int = 0
    serious_failures: int = 0
    skipped_remote_calls: int = 0
    latency_ms_total: float = 0.0
    latency_ms_count: int = 0

    @property
    def route_case_accuracy(self) -> float:
        return round(self.route_passed_cases / self.cases, 4) if self.cases else 0.0

    @property
    def strict_case_accuracy(self) -> float:
        return round(self.strict_passed_cases / self.cases, 4) if self.cases else 0.0

    @property
    def route_item_accuracy(self) -> float:
        if not self.expected_items:
            return 0.0
        return round(self.route_passed_items / self.expected_items, 4)

    @property
    def strict_item_accuracy(self) -> float:
        if not self.expected_items:
            return 0.0
        return round(self.strict_passed_items / self.expected_items, 4)

    @property
    def average_latency_ms(self) -> float | None:
        if not self.latency_ms_count:
            return None
        return round(self.latency_ms_total / self.latency_ms_count, 2)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["route_case_accuracy"] = self.route_case_accuracy
        payload["strict_case_accuracy"] = self.strict_case_accuracy
        payload["route_item_accuracy"] = self.route_item_accuracy
        payload["strict_item_accuracy"] = self.strict_item_accuracy
        payload["average_latency_ms"] = self.average_latency_ms
        return payload


@dataclass
class SplitFailure:
    fixture: str
    name: str
    category: str
    contents: list[str]
    expected: list[ExpectedSplitItem]
    actual: list[ActualSplitItem]
    item_failures: list[SplitItemEvaluation]
    unused_actual: list[ActualSplitItem]
    warnings: list[str] = field(default_factory=list)
    remote_error: str | None = None


@dataclass
class SplitEvaluationResult:
    summary: SplitStats
    category_summary: dict[str, SplitStats]
    failures: list[SplitFailure]
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
                    "expected": [asdict(item) for item in failure.expected],
                    "actual": [asdict(item) for item in failure.actual],
                    "item_failures": [
                        {
                            **asdict(item),
                            "expected": asdict(item.expected),
                            "selected": asdict(item.selected) if item.selected else None,
                        }
                        for item in failure.item_failures
                    ],
                    "unused_actual": [asdict(item) for item in failure.unused_actual],
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
    limit: int | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    selected = list(cases)
    if categories:
        selected = [(path, case) for path, case in selected if case.get("category") in categories]
    rng = random.Random(sample_seed)
    if sample_size is not None:
        if sample_size < 1:
            raise ValueError("--sample-size must be greater than zero")
        selected = rng.sample(selected, min(sample_size, len(selected)))
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be greater than zero")
        selected = selected[:limit]
    return selected


def events_from_case(case: dict[str, Any]) -> tuple[list[EventRead], dict[str, str]]:
    raw_events = case.get("events")
    if raw_events is None and "event" in case:
        raw_events = [{**case["event"], "alias": "event"}]
    if not isinstance(raw_events, list) or not raw_events:
        raise ValueError(f"{case.get('name', '<unknown>')}: expected non-empty events list")

    events: list[EventRead] = []
    alias_to_id: dict[str, str] = {}
    for index, raw_event in enumerate(raw_events):
        alias = str(raw_event.get("alias") or f"event_{index:02d}")
        event_id = str(raw_event.get("id") or f"evt_{case['name']}_{alias}")
        alias_to_id[alias] = event_id
        events.append(
            EventRead(
                id=event_id,
                event_type=raw_event["event_type"],
                content=raw_event["content"],
                source=raw_event["source"],
                scope=raw_event["scope"],
                metadata=raw_event.get("metadata", {}),
                created_at=datetime.now(timezone.utc),
            )
        )
    return events, alias_to_id


def expected_items_from_case(
    case: dict[str, Any],
    alias_to_id: dict[str, str],
) -> list[ExpectedSplitItem]:
    expected = case["expected"]
    raw_items = expected.get("items") or expected.get("expected_items")
    if raw_items is None:
        raw_items = [expected]
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError(f"{case.get('name', '<unknown>')}: expected items must be non-empty")

    items: list[ExpectedSplitItem] = []
    for index, raw_item in enumerate(raw_items):
        aliases = raw_item.get("source_event_aliases", [])
        source_event_ids = [alias_to_id.get(str(alias), str(alias)) for alias in aliases]
        source_event_ids.extend(str(value) for value in raw_item.get("source_event_ids", []))
        items.append(
            ExpectedSplitItem(
                label=str(raw_item.get("label") or f"expected_{index:02d}"),
                route=raw_item["route"],
                source_event_ids=tuple(dict.fromkeys(source_event_ids)),
                session_memory_type=raw_item.get("session_memory_type"),
                memory_type=raw_item.get("memory_type"),
                context_role=raw_item.get("context_role", "excluded"),
            )
        )
    return items


def actual_from_item(item: MemoryRouteItem) -> ActualSplitItem:
    return ActualSplitItem(
        route=item.route,
        source_event_ids=tuple(item.source_event_ids),
        session_memory_type=item.session_memory_type,
        memory_type=item.memory_type,
        subject=item.subject,
        reason=item.reason,
    )


def _expected_type(expected: ExpectedSplitItem) -> str | None:
    if expected.route == "session":
        return expected.session_memory_type
    if expected.route == "long_term":
        return expected.memory_type
    return None


def _actual_type(actual: ActualSplitItem) -> str | None:
    if actual.route == "session":
        return actual.session_memory_type
    if actual.route == "long_term":
        return actual.memory_type
    return None


def _source_matches(expected: ExpectedSplitItem, actual: ActualSplitItem) -> bool:
    if not expected.source_event_ids:
        return True
    return bool(set(expected.source_event_ids) & set(actual.source_event_ids))


def _match_score(expected: ExpectedSplitItem, actual: ActualSplitItem) -> tuple[int, int, int]:
    route_score = 1 if expected.route == actual.route else 0
    expected_type = _expected_type(expected)
    type_score = 1 if expected_type is None or expected_type == _actual_type(actual) else 0
    source_score = 1 if _source_matches(expected, actual) else 0
    return route_score, type_score, source_score


def _classify_item(
    expected: ExpectedSplitItem,
    selected: ActualSplitItem | None,
) -> tuple[str | None, str | None, str | None]:
    if selected is None:
        failure = "missing_route"
        return failure, failure, _serious_missing_route(expected)
    if selected.route != expected.route:
        failure = f"route_mismatch:{selected.route}"
        return failure, failure, _serious_route_mismatch(expected, selected)

    strict_failure = None
    expected_type = _expected_type(expected)
    if expected_type is not None and _actual_type(selected) != expected_type:
        strict_failure = (
            "session_type_mismatch" if expected.route == "session" else "memory_type_mismatch"
        )
    elif not _source_matches(expected, selected):
        strict_failure = "source_mismatch"
    return None, strict_failure, None


def _serious_missing_route(expected: ExpectedSplitItem) -> str | None:
    if expected.route in {"reject", "ask_user", "long_term"}:
        return f"missing_{expected.route}:{expected.label}"
    if expected.route == "session" and expected.context_role == "critical":
        return f"missing_critical_session:{expected.label}"
    return None


def _serious_route_mismatch(
    expected: ExpectedSplitItem,
    selected: ActualSplitItem,
) -> str | None:
    if expected.route == "reject":
        return f"sensitive_not_rejected:{selected.route}:{expected.label}"
    if expected.route == "ask_user":
        return f"confirmation_not_requested:{selected.route}:{expected.label}"
    if expected.route == "long_term" and selected.route != "long_term":
        return f"long_term_missed:{selected.route}:{expected.label}"
    if expected.route == "session" and expected.context_role == "critical":
        return f"critical_session_missed:{selected.route}:{expected.label}"
    if expected.route == "ignore" and selected.route in {"long_term", "session"}:
        return f"ignore_became_noise:{selected.route}:{expected.label}"
    return None


def match_expected_items(
    expected_items: list[ExpectedSplitItem],
    actual_items: list[ActualSplitItem],
) -> tuple[list[SplitItemEvaluation], list[ActualSplitItem]]:
    unused = list(actual_items)
    evaluations: list[SplitItemEvaluation] = []
    for expected in expected_items:
        selected = None
        if unused:
            selected = max(unused, key=lambda actual: _match_score(expected, actual))
            unused.remove(selected)
        route_failure, strict_failure, serious_failure = _classify_item(expected, selected)
        evaluations.append(
            SplitItemEvaluation(
                expected=expected,
                selected=selected,
                route_failure=route_failure,
                strict_failure=strict_failure,
                serious_failure=serious_failure,
            )
        )
    return evaluations, unused


def evaluate_case(
    item: tuple[Path, dict[str, Any]],
    *,
    remote_llm: RemoteLLMClient,
    instructions: str | None,
) -> SplitCaseEvaluation:
    path, case = item
    events, alias_to_id = events_from_case(case)
    expected = expected_items_from_case(case, alias_to_id)
    started = time.perf_counter()
    try:
        result = remote_llm.route_memories(events, instructions=instructions)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        actual = [actual_from_item(route_item) for route_item in result.items]
        item_evaluations, unused_actual = match_expected_items(expected, actual)
        return SplitCaseEvaluation(
            fixture=path,
            case=case,
            expected=expected,
            actual=actual,
            item_evaluations=item_evaluations,
            unused_actual=unused_actual,
            warnings=result.warnings,
            latency_ms=latency_ms,
            provider=result.provider,
            skipped_remote_call=bool(result.metadata.get("skipped_remote_call", False)),
        )
    except RemoteAdapterError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return SplitCaseEvaluation(
            fixture=path,
            case=case,
            expected=expected,
            actual=[],
            item_evaluations=[
                SplitItemEvaluation(
                    expected=item,
                    selected=None,
                    route_failure="remote_error",
                    strict_failure="remote_error",
                    serious_failure="remote_error",
                )
                for item in expected
            ],
            unused_actual=[],
            warnings=[str(exc)],
            latency_ms=latency_ms,
            remote_error=str(exc),
        )


def evaluate_case_batch(
    cases: list[tuple[Path, dict[str, Any]]],
    *,
    remote_llm: RemoteLLMClient,
    instructions: str | None,
    case_concurrency: int,
) -> list[SplitCaseEvaluation]:
    if case_concurrency < 1:
        raise ValueError("case_concurrency must be greater than zero")
    if case_concurrency == 1:
        return [
            evaluate_case(item, remote_llm=remote_llm, instructions=instructions) for item in cases
        ]

    by_index: dict[int, SplitCaseEvaluation] = {}
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
            by_index[futures[future]] = future.result()
    return [by_index[index] for index in range(len(cases))]


def update_stats(stats: SplitStats, evaluation: SplitCaseEvaluation) -> None:
    stats.cases += 1
    stats.expected_items += len(evaluation.expected)
    if evaluation.latency_ms is not None:
        stats.latency_ms_total += evaluation.latency_ms
        stats.latency_ms_count += 1
    if evaluation.remote_error:
        stats.remote_error += 1
    if evaluation.skipped_remote_call:
        stats.skipped_remote_calls += 1
    if evaluation.route_passed:
        stats.route_passed_cases += 1
    if evaluation.strict_passed:
        stats.strict_passed_cases += 1
    if evaluation.extra_noise:
        stats.extra_noise_cases += 1

    for item in evaluation.item_evaluations:
        if item.route_failure is None:
            stats.route_passed_items += 1
        elif item.route_failure == "missing_route":
            stats.missing_items += 1
        elif item.route_failure != "remote_error":
            stats.route_mismatch += 1
        if item.route_failure is None and item.strict_failure is None:
            stats.strict_passed_items += 1
        if item.strict_failure == "session_type_mismatch":
            stats.session_type_mismatch += 1
        elif item.strict_failure == "memory_type_mismatch":
            stats.memory_type_mismatch += 1
        elif item.strict_failure == "source_mismatch":
            stats.source_mismatch += 1
        if item.serious_failure:
            stats.serious_failures += 1


def evaluate_session_route_splitting(
    cases: list[tuple[Path, dict[str, Any]]],
    *,
    remote_llm: RemoteLLMClient | None = None,
    instructions: str | None = None,
    case_concurrency: int = 1,
    selection: dict[str, Any] | None = None,
    failure_limit: int = 20,
) -> SplitEvaluationResult:
    remote = remote_llm or RemoteLLMClient(RemoteAdapterConfig.llm_from_env())
    evaluations = evaluate_case_batch(
        cases,
        remote_llm=remote,
        instructions=instructions,
        case_concurrency=case_concurrency,
    )

    summary = SplitStats()
    category_summary: dict[str, SplitStats] = defaultdict(SplitStats)
    failures: list[SplitFailure] = []
    warnings: list[str] = []
    for evaluation in evaluations:
        category = str(evaluation.case.get("category", "unknown"))
        update_stats(summary, evaluation)
        update_stats(category_summary[category], evaluation)
        if evaluation.warnings:
            counts = Counter(evaluation.warnings)
            warnings.extend(
                f"{evaluation.case['name']}:{warning} x{count}" for warning, count in counts.items()
            )
        item_failures = [
            item
            for item in evaluation.item_evaluations
            if item.route_failure or item.strict_failure or item.serious_failure
        ]
        if (evaluation.remote_error or item_failures or evaluation.extra_noise) and len(
            failures
        ) < failure_limit:
            failures.append(
                SplitFailure(
                    fixture=evaluation.fixture.name,
                    name=evaluation.case["name"],
                    category=category,
                    contents=[event["content"] for event in evaluation.case["events"]],
                    expected=evaluation.expected,
                    actual=evaluation.actual,
                    item_failures=item_failures,
                    unused_actual=evaluation.unused_actual,
                    warnings=evaluation.warnings,
                    remote_error=evaluation.remote_error,
                )
            )

    return SplitEvaluationResult(
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
        description="Evaluate remote memory routing on multi-item and multi-event cases."
    )
    parser.add_argument("--fixture", action="append", type=Path)
    parser.add_argument("--category", action="append")
    parser.add_argument("--sample-size", type=int)
    parser.add_argument("--sample-seed", type=int, default=20260430)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case-concurrency", type=int, default=1)
    parser.add_argument("--failure-limit", type=int, default=20)
    parser.add_argument("--instructions")
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _format_actual(items: list[ActualSplitItem]) -> str:
    if not items:
        return "[]"
    return (
        "["
        + ", ".join(
            (
                f"{item.route}/{item.session_memory_type or item.memory_type or '-'}"
                f"@{','.join(item.source_event_ids) or '-'}"
            )
            for item in items
        )
        + "]"
    )


def _print_text_result(result: SplitEvaluationResult, *, failure_limit: int) -> None:
    summary = result.summary
    print(
        "SUMMARY "
        f"cases={summary.cases} "
        f"expected_items={summary.expected_items} "
        f"route_case_accuracy={summary.route_case_accuracy:.4f} "
        f"strict_case_accuracy={summary.strict_case_accuracy:.4f} "
        f"route_item_accuracy={summary.route_item_accuracy:.4f} "
        f"strict_item_accuracy={summary.strict_item_accuracy:.4f} "
        f"missing_items={summary.missing_items} "
        f"route_mismatch={summary.route_mismatch} "
        f"session_type_mismatch={summary.session_type_mismatch} "
        f"memory_type_mismatch={summary.memory_type_mismatch} "
        f"source_mismatch={summary.source_mismatch} "
        f"extra_noise_cases={summary.extra_noise_cases} "
        f"serious_failures={summary.serious_failures} "
        f"remote_error={summary.remote_error} "
        f"skipped_remote_calls={summary.skipped_remote_calls} "
        f"avg_latency_ms={summary.average_latency_ms}"
    )
    print("CATEGORY SUMMARY")
    for category, stats in sorted(result.category_summary.items()):
        print(
            f"- {category}: cases={stats.cases} "
            f"items={stats.expected_items} "
            f"route_cases={stats.route_passed_cases}/{stats.cases} "
            f"strict_cases={stats.strict_passed_cases}/{stats.cases} "
            f"route_items={stats.route_passed_items}/{stats.expected_items} "
            f"strict_items={stats.strict_passed_items}/{stats.expected_items} "
            f"serious={stats.serious_failures}"
        )
    if not result.failures:
        print("FAILURES none")
        return
    print("FAILURES")
    for failure in result.failures[:failure_limit]:
        print(f"! {failure.name} [{failure.category}] actual={_format_actual(failure.actual)}")
        for item in failure.item_failures:
            expected_type = item.expected.session_memory_type or item.expected.memory_type or "-"
            selected = _format_actual([item.selected]) if item.selected else "[]"
            print(
                f"  - {item.expected.label}: expected="
                f"{item.expected.route}/{expected_type} selected={selected} "
                f"route_failure={item.route_failure or 'pass'} "
                f"strict_failure={item.strict_failure or 'pass'} "
                f"serious={item.serious_failure or '-'}"
            )
        if failure.unused_actual:
            print(f"  unused={_format_actual(failure.unused_actual)}")
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
        limit=args.limit,
    )
    selection = {
        "fixtures": [str(path) for path in paths],
        "case_count": len(selected),
        "categories": sorted(categories) if categories else None,
        "sample_size": args.sample_size,
        "sample_seed": args.sample_seed,
        "limit": args.limit,
        "case_concurrency": args.case_concurrency,
        "case_names": [case["name"] for _path, case in selected],
    }
    result = evaluate_session_route_splitting(
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
