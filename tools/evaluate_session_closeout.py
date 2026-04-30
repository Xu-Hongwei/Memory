from __future__ import annotations

import argparse
import json
import random
import re
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
from memory_system.schemas import (  # noqa: E402
    EventRead,
    SessionCloseoutDecision,
    SessionCloseoutResult,
    SessionMemoryItemCreate,
    SessionMemoryItemRead,
    TaskBoundaryDecision,
)
from memory_system.session_memory import SessionMemoryStore  # noqa: E402


DEFAULT_FIXTURE = ROOT / "tests/fixtures/golden_cases/session_closeout.jsonl"
SENSITIVE_PATTERN = re.compile(
    r"\[REDACTED\]|\btoken\b|\bsecret\b|\bapi[-_ ]?key\b|\bpassword\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ExpectedCloseoutItem:
    action: str
    acceptable_actions: tuple[str, ...]
    candidate_memory_types: tuple[str, ...] = ()
    forbid_promote: bool = False


@dataclass(frozen=True)
class ActualCloseoutItem:
    action: str
    candidate_memory_type: str | None = None
    reason: str | None = None
    summary: str | None = None
    candidate_content: str | None = None


@dataclass(frozen=True)
class ItemEvaluation:
    alias: str
    expected: ExpectedCloseoutItem
    actual: ActualCloseoutItem
    action_failure: str | None
    strict_failure: str | None
    unsafe_promotion: bool = False


@dataclass
class CloseoutOutcome:
    actual_by_alias: dict[str, ActualCloseoutItem]
    warnings: list[str]
    latency_ms: float | None
    provider: str | None = None
    remote_error: str | None = None
    skipped_remote_call: bool = False


@dataclass
class CaseEvaluation:
    fixture: Path
    case: dict[str, Any]
    expected_by_alias: dict[str, ExpectedCloseoutItem]
    outcome: CloseoutOutcome
    items: list[ItemEvaluation]
    case_failure: str | None


@dataclass
class CloseoutStats:
    cases: int = 0
    case_passed: int = 0
    items: int = 0
    action_passed: int = 0
    strict_passed: int = 0
    remote_error: int = 0
    skipped_remote_calls: int = 0
    action_mismatch: int = 0
    candidate_type_mismatch: int = 0
    forbidden_promotions: int = 0
    unsafe_promotions: int = 0
    missing_decisions: int = 0
    latency_ms_total: float = 0.0
    latency_ms_count: int = 0

    @property
    def case_accuracy(self) -> float:
        return round(self.case_passed / self.cases, 4) if self.cases else 0.0

    @property
    def action_accuracy(self) -> float:
        return round(self.action_passed / self.items, 4) if self.items else 0.0

    @property
    def strict_accuracy(self) -> float:
        return round(self.strict_passed / self.items, 4) if self.items else 0.0

    @property
    def average_latency_ms(self) -> float | None:
        if not self.latency_ms_count:
            return None
        return round(self.latency_ms_total / self.latency_ms_count, 2)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["case_accuracy"] = self.case_accuracy
        payload["action_accuracy"] = self.action_accuracy
        payload["strict_accuracy"] = self.strict_accuracy
        payload["average_latency_ms"] = self.average_latency_ms
        return payload


@dataclass
class CloseoutFailure:
    fixture: str
    name: str
    category: str
    alias: str
    session_memory: dict[str, Any]
    expected: ExpectedCloseoutItem
    actual: ActualCloseoutItem
    action_failure: str | None
    strict_failure: str | None
    unsafe_promotion: bool
    warnings: list[str] = field(default_factory=list)
    remote_error: str | None = None


@dataclass
class EvaluationResult:
    summary: CloseoutStats
    category_summary: dict[str, CloseoutStats]
    failures: list[CloseoutFailure]
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


def expected_items(case: dict[str, Any]) -> dict[str, ExpectedCloseoutItem]:
    raw_items = case["expected"]["items"]
    expected: dict[str, ExpectedCloseoutItem] = {}
    for alias, raw in raw_items.items():
        acceptable = raw.get("acceptable_actions") or [raw["action"]]
        expected[str(alias)] = ExpectedCloseoutItem(
            action=str(raw["action"]),
            acceptable_actions=tuple(str(action) for action in acceptable),
            candidate_memory_types=tuple(
                str(memory_type) for memory_type in raw.get("candidate_memory_types", [])
            ),
            forbid_promote=bool(raw.get("forbid_promote", False)),
        )
    return expected


def evaluate_case(
    item: tuple[Path, dict[str, Any]],
    *,
    remote_llm: RemoteLLMClient,
    instructions: str | None,
) -> CaseEvaluation:
    path, case = item
    expected_by_alias = expected_items(case)
    session_id = str(case["session_id"])
    store = SessionMemoryStore()
    stored_items: list[SessionMemoryItemRead] = []
    alias_by_id: dict[str, str] = {}
    memory_by_alias: dict[str, dict[str, Any]] = {}
    for raw_memory in case["session_memories"]:
        alias = str(raw_memory["alias"])
        memory_by_alias[alias] = raw_memory
        payload = {key: value for key, value in raw_memory.items() if key != "alias"}
        payload["session_id"] = session_id
        stored = store.add_item(SessionMemoryItemCreate.model_validate(payload))
        stored_items.append(stored)
        alias_by_id[stored.id] = alias

    task_boundary = TaskBoundaryDecision.model_validate(case["task_boundary"])
    recent_events = [
        _event_from_raw(raw, event_id=f"{case['name']}_recent_{index}")
        for index, raw in enumerate(case.get("recent_events", []))
    ]
    started = time.perf_counter()
    try:
        result = remote_llm.closeout_session_memories(
            session_id=session_id,
            session_memories=stored_items,
            task_boundary=task_boundary,
            current_task_state=case.get("current_task_state") or {},
            recent_events=recent_events,
            instructions=instructions,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        outcome = _outcome_from_result(
            result,
            alias_by_id=alias_by_id,
            expected_by_alias=expected_by_alias,
            latency_ms=latency_ms,
        )
    except RemoteAdapterError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        outcome = CloseoutOutcome(
            actual_by_alias={},
            warnings=[str(exc)],
            latency_ms=latency_ms,
            remote_error=str(exc),
        )

    item_evaluations = [
        _evaluate_item(
            alias,
            expected,
            outcome.actual_by_alias.get(alias, ActualCloseoutItem(action="missing")),
            session_memory=memory_by_alias[alias],
        )
        for alias, expected in expected_by_alias.items()
    ]
    case_failure = _case_failure(outcome, item_evaluations)
    return CaseEvaluation(
        fixture=path,
        case=case,
        expected_by_alias=expected_by_alias,
        outcome=outcome,
        items=item_evaluations,
        case_failure=case_failure,
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


def evaluate_session_closeouts(
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

    summary = CloseoutStats()
    category_summary: dict[str, CloseoutStats] = defaultdict(CloseoutStats)
    failures: list[CloseoutFailure] = []
    warnings: list[str] = []
    for evaluation in evaluations:
        category = str(evaluation.case.get("category", "unknown"))
        _update_stats(summary, evaluation)
        _update_stats(category_summary[category], evaluation)
        if evaluation.outcome.warnings:
            counts = Counter(evaluation.outcome.warnings)
            warnings.extend(
                f"{evaluation.case['name']}:{warning} x{count}"
                for warning, count in counts.items()
            )
        if len(failures) >= failure_limit:
            continue
        memory_by_alias = {
            str(memory["alias"]): memory for memory in evaluation.case["session_memories"]
        }
        for item_eval in evaluation.items:
            if not (
                item_eval.action_failure
                or item_eval.strict_failure
                or item_eval.unsafe_promotion
                or evaluation.outcome.remote_error
            ):
                continue
            failures.append(
                CloseoutFailure(
                    fixture=evaluation.fixture.name,
                    name=evaluation.case["name"],
                    category=category,
                    alias=item_eval.alias,
                    session_memory=memory_by_alias[item_eval.alias],
                    expected=item_eval.expected,
                    actual=item_eval.actual,
                    action_failure=item_eval.action_failure,
                    strict_failure=item_eval.strict_failure,
                    unsafe_promotion=item_eval.unsafe_promotion,
                    warnings=evaluation.outcome.warnings,
                    remote_error=evaluation.outcome.remote_error,
                )
            )
            if len(failures) >= failure_limit:
                break

    return EvaluationResult(
        summary=summary,
        category_summary=dict(category_summary),
        failures=failures,
        selection=selection or {},
        warnings=warnings,
    )


def _outcome_from_result(
    result: SessionCloseoutResult,
    *,
    alias_by_id: dict[str, str],
    expected_by_alias: dict[str, ExpectedCloseoutItem],
    latency_ms: float,
) -> CloseoutOutcome:
    actual_by_alias: dict[str, ActualCloseoutItem] = {}
    for decision in result.decisions:
        alias = alias_by_id.get(decision.session_memory_id)
        if alias is None or alias not in expected_by_alias:
            continue
        actual_by_alias[alias] = _actual_from_decision(decision)
    for alias in expected_by_alias:
        actual_by_alias.setdefault(alias, ActualCloseoutItem(action="missing"))
    return CloseoutOutcome(
        actual_by_alias=actual_by_alias,
        warnings=list(result.warnings),
        latency_ms=latency_ms,
        provider=result.provider,
        skipped_remote_call=bool(result.metadata.get("skipped_remote_call", False)),
    )


def _actual_from_decision(decision: SessionCloseoutDecision) -> ActualCloseoutItem:
    candidate = decision.candidate
    return ActualCloseoutItem(
        action=decision.action,
        candidate_memory_type=candidate.memory_type if candidate else None,
        reason=decision.reason,
        summary=decision.summary,
        candidate_content=candidate.content if candidate else None,
    )


def _evaluate_item(
    alias: str,
    expected: ExpectedCloseoutItem,
    actual: ActualCloseoutItem,
    *,
    session_memory: dict[str, Any],
) -> ItemEvaluation:
    action_failure = None
    strict_failure = None
    if actual.action not in expected.acceptable_actions:
        action_failure = f"expected {expected.acceptable_actions}, got {actual.action}"

    if expected.forbid_promote and actual.action == "promote_candidate":
        strict_failure = "forbidden_promotion"
    elif actual.action == "promote_candidate":
        if expected.candidate_memory_types and (
            actual.candidate_memory_type not in expected.candidate_memory_types
        ):
            strict_failure = (
                f"candidate_type_mismatch:{actual.candidate_memory_type or 'missing'}"
            )
        elif actual.candidate_memory_type is None:
            strict_failure = "missing_candidate"

    unsafe_promotion = actual.action == "promote_candidate" and (
        expected.forbid_promote
        or _contains_sensitive_text(str(session_memory.get("content", "")))
        or _contains_sensitive_text(actual.candidate_content or "")
    )
    if unsafe_promotion and strict_failure is None:
        strict_failure = "unsafe_promotion"

    return ItemEvaluation(
        alias=alias,
        expected=expected,
        actual=actual,
        action_failure=action_failure,
        strict_failure=strict_failure,
        unsafe_promotion=unsafe_promotion,
    )


def _case_failure(
    outcome: CloseoutOutcome,
    item_evaluations: list[ItemEvaluation],
) -> str | None:
    if outcome.remote_error:
        return "remote_error"
    failures = [
        item.alias
        for item in item_evaluations
        if item.action_failure or item.strict_failure or item.unsafe_promotion
    ]
    if failures:
        return "item_failures:" + ",".join(failures)
    return None


def _update_stats(stats: CloseoutStats, evaluation: CaseEvaluation) -> None:
    stats.cases += 1
    if evaluation.case_failure is None:
        stats.case_passed += 1
    if evaluation.outcome.latency_ms is not None:
        stats.latency_ms_total += evaluation.outcome.latency_ms
        stats.latency_ms_count += 1
    if evaluation.outcome.remote_error:
        stats.remote_error += 1
    if evaluation.outcome.skipped_remote_call:
        stats.skipped_remote_calls += 1

    for item in evaluation.items:
        stats.items += 1
        if item.actual.action == "missing":
            stats.missing_decisions += 1
        if item.action_failure is None:
            stats.action_passed += 1
        else:
            stats.action_mismatch += 1
        if item.action_failure is None and item.strict_failure is None:
            stats.strict_passed += 1
        elif item.strict_failure == "forbidden_promotion":
            stats.forbidden_promotions += 1
        elif item.strict_failure and item.strict_failure.startswith("candidate_type_mismatch"):
            stats.candidate_type_mismatch += 1
        if item.unsafe_promotion:
            stats.unsafe_promotions += 1


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


def _contains_sensitive_text(text: str) -> bool:
    return bool(SENSITIVE_PATTERN.search(text))


def _fixture_paths(values: Iterable[Path] | None) -> tuple[Path, ...]:
    return tuple(values or (DEFAULT_FIXTURE,))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate remote session-memory closeout against golden cases."
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


def _print_text_result(result: EvaluationResult, *, failure_limit: int) -> None:
    summary = result.summary
    print(
        "SUMMARY "
        f"cases={summary.cases} "
        f"case_passed={summary.case_passed} "
        f"items={summary.items} "
        f"action_passed={summary.action_passed} "
        f"strict_passed={summary.strict_passed} "
        f"case_accuracy={summary.case_accuracy:.4f} "
        f"action_accuracy={summary.action_accuracy:.4f} "
        f"strict_accuracy={summary.strict_accuracy:.4f} "
        f"action_mismatch={summary.action_mismatch} "
        f"candidate_type_mismatch={summary.candidate_type_mismatch} "
        f"forbidden_promotions={summary.forbidden_promotions} "
        f"unsafe_promotions={summary.unsafe_promotions} "
        f"missing_decisions={summary.missing_decisions} "
        f"remote_error={summary.remote_error} "
        f"skipped_remote_calls={summary.skipped_remote_calls} "
        f"avg_latency_ms={summary.average_latency_ms}"
    )
    print("CATEGORY SUMMARY")
    for category, stats in sorted(result.category_summary.items()):
        print(
            f"- {category}: cases={stats.cases} "
            f"case={stats.case_passed}/{stats.cases} "
            f"action={stats.action_passed}/{stats.items} "
            f"strict={stats.strict_passed}/{stats.items} "
            f"unsafe={stats.unsafe_promotions}"
        )
    if not result.failures:
        print("FAILURES none")
        return
    print("FAILURES")
    for failure in result.failures[:failure_limit]:
        expected_types = ",".join(failure.expected.candidate_memory_types) or "-"
        print(
            f"! {failure.name} [{failure.category}] alias={failure.alias} "
            f"expected={failure.expected.acceptable_actions}/{expected_types} "
            f"actual={failure.actual.action}/{failure.actual.candidate_memory_type or '-'} "
            f"action_failure={failure.action_failure or 'pass'} "
            f"strict_failure={failure.strict_failure or 'pass'} "
            f"unsafe={failure.unsafe_promotion}"
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
    result = evaluate_session_closeouts(
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
