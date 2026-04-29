from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory_system import EventCreate, EventLog, MemoryItemCreate, MemoryStore  # noqa: E402
from memory_system.remote import (  # noqa: E402
    RemoteAdapterConfig,
    RemoteAdapterError,
    RemoteLLMClient,
)
from memory_system.schemas import MemoryCandidateCreate  # noqa: E402


DEFAULT_FIXTURES = (
    ROOT / "tests/fixtures/golden_cases/write_policy.jsonl",
    ROOT / "tests/fixtures/golden_cases/write_policy_time_validity.jsonl",
    ROOT / "tests/fixtures/golden_cases/write_policy_cn_realistic.jsonl",
    ROOT / "tests/fixtures/golden_cases/write_policy_en_realistic.jsonl",
)


@dataclass
class CandidateOutcome:
    memory_type: str
    evidence_type: str
    decision: str | None = None
    confidence: str | None = None
    risk: str | None = None
    subject: str | None = None


@dataclass
class CaseFailure:
    fixture: str
    name: str
    category: str
    failure_type: str
    content: str
    expected: list[dict[str, Any]]
    actual: list[CandidateOutcome]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ModeOutcome:
    actual: list[CandidateOutcome]
    warnings: list[str]
    latency_ms: float | None
    failure_type: str | None


@dataclass
class CaseEvaluation:
    fixture: Path
    case: dict[str, Any]
    category: str
    content: str
    expected: list[CandidateOutcome]
    local: ModeOutcome
    remote_after_gate: ModeOutcome | None = None


@dataclass
class ModeStats:
    cases: int = 0
    passed: int = 0
    fp: int = 0
    fn: int = 0
    type_mismatch: int = 0
    evidence_mismatch: int = 0
    decision_mismatch: int = 0
    remote_error: int = 0
    latency_ms_total: float = 0.0
    latency_ms_count: int = 0

    @property
    def failed(self) -> int:
        return (
            self.fp
            + self.fn
            + self.type_mismatch
            + self.evidence_mismatch
            + self.decision_mismatch
            + self.remote_error
        )

    @property
    def pass_rate(self) -> float:
        return round(self.passed / self.cases, 4) if self.cases else 0.0

    @property
    def average_latency_ms(self) -> float | None:
        if not self.latency_ms_count:
            return None
        return round(self.latency_ms_total / self.latency_ms_count, 2)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["failed"] = self.failed
        payload["pass_rate"] = self.pass_rate
        payload["average_latency_ms"] = self.average_latency_ms
        return payload


@dataclass
class EvaluationResult:
    modes: dict[str, ModeStats]
    category_summary: dict[str, dict[str, ModeStats]]
    failures: dict[str, list[CaseFailure]]
    selection: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, *, failure_limit: int) -> dict[str, Any]:
        return {
            "modes": {mode: stats.to_dict() for mode, stats in self.modes.items()},
            "category_summary": {
                category: {mode: stats.to_dict() for mode, stats in mode_stats.items()}
                for category, mode_stats in sorted(self.category_summary.items())
            },
            "failures": {
                mode: [asdict(failure) for failure in failures[:failure_limit]]
                for mode, failures in self.failures.items()
            },
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
            loaded.append((path, case))
    return loaded


def select_cases(
    cases: list[tuple[Path, dict[str, Any]]],
    *,
    categories: set[str] | None = None,
    sample_per_category: int | None = None,
    sample_size: int | None = None,
    sample_seed: int | None = None,
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
        for path, case in selected:
            grouped[str(case.get("category", "unknown"))].append((path, case))
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


def expected_outcomes(case: dict[str, Any]) -> list[CandidateOutcome]:
    return [
        CandidateOutcome(
            memory_type=item["memory_type"],
            evidence_type=item["evidence_type"],
            decision=item["decision"],
        )
        for item in case["expected"]["candidates"]
    ]


def fresh_store(case: dict[str, Any]) -> tuple[EventLog, MemoryStore]:
    db_path = ":memory:"
    events = EventLog(db_path)
    memories = MemoryStore(db_path)
    for memory in case.get("existing_memories", []):
        memories.add_memory(MemoryItemCreate(**memory))
    return events, memories


def local_actual(case: dict[str, Any]) -> tuple[list[CandidateOutcome], list[str], float | None]:
    events, memories = fresh_store(case)
    event = events.record_event(EventCreate(**case["event"]))
    started = time.perf_counter()
    candidates = memories.propose_memory(event)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    outcomes: list[CandidateOutcome] = []
    for candidate in candidates:
        decision = memories.evaluate_candidate(candidate.id)
        outcomes.append(
            CandidateOutcome(
                memory_type=candidate.memory_type,
                evidence_type=candidate.evidence_type,
                decision=decision.decision,
                confidence=candidate.confidence,
                risk=candidate.risk,
                subject=candidate.subject,
            )
        )
    return outcomes, [], latency_ms


def remote_actual(
    case: dict[str, Any],
    remote_llm: RemoteLLMClient,
    *,
    instructions: str | None,
) -> tuple[list[CandidateOutcome], list[str], float | None]:
    events, memories = fresh_store(case)
    event = events.record_event(EventCreate(**case["event"]))
    started = time.perf_counter()
    extracted = remote_llm.extract_candidates(event, instructions=instructions)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    outcomes: list[CandidateOutcome] = []
    for candidate in extracted.candidates:
        stored = memories.create_candidate(MemoryCandidateCreate(**candidate.model_dump()))
        decision = memories.evaluate_candidate(stored.id)
        outcomes.append(
            CandidateOutcome(
                memory_type=stored.memory_type,
                evidence_type=stored.evidence_type,
                decision=decision.decision,
                confidence=stored.confidence,
                risk=stored.risk,
                subject=stored.subject,
            )
        )
    return outcomes, extracted.warnings, latency_ms


def classify_failure(
    expected: list[CandidateOutcome],
    actual: list[CandidateOutcome],
    *,
    remote_error: str | None = None,
    allow_omitted_rejects: bool = False,
) -> str | None:
    if remote_error:
        return "remote_error"
    if not expected and not actual:
        return None
    if not expected and actual:
        return "fp"
    if expected and not actual:
        if allow_omitted_rejects and all(item.decision == "reject" for item in expected):
            return None
        return "fn"

    expected_types = sorted(item.memory_type for item in expected)
    actual_types = sorted(item.memory_type for item in actual)
    if expected_types != actual_types:
        return "type_mismatch"

    expected_evidence = sorted(item.evidence_type for item in expected)
    actual_evidence = sorted(item.evidence_type for item in actual)
    if expected_evidence != actual_evidence:
        return "evidence_mismatch"

    expected_decisions = sorted(item.decision for item in expected)
    actual_decisions = sorted(item.decision for item in actual)
    if expected_decisions != actual_decisions:
        return "decision_mismatch"

    return None


def update_stats(
    stats: ModeStats,
    *,
    failure_type: str | None,
    latency_ms: float | None,
) -> None:
    stats.cases += 1
    if latency_ms is not None:
        stats.latency_ms_total += latency_ms
        stats.latency_ms_count += 1
    if failure_type is None:
        stats.passed += 1
        return
    if failure_type == "fp":
        stats.fp += 1
    elif failure_type == "fn":
        stats.fn += 1
    elif failure_type == "type_mismatch":
        stats.type_mismatch += 1
    elif failure_type == "evidence_mismatch":
        stats.evidence_mismatch += 1
    elif failure_type == "decision_mismatch":
        stats.decision_mismatch += 1
    elif failure_type == "remote_error":
        stats.remote_error += 1


def evaluate_case(
    item: tuple[Path, dict[str, Any]],
    *,
    include_remote: bool,
    remote_llm: RemoteLLMClient | None,
    instructions: str | None,
) -> CaseEvaluation:
    path, case = item
    category = str(case.get("category", "unknown"))
    expected = expected_outcomes(case)
    content = str(case["event"]["content"])

    actual, local_warnings, latency_ms = local_actual(case)
    local_failure = classify_failure(expected, actual)
    local = ModeOutcome(
        actual=actual,
        warnings=local_warnings,
        latency_ms=latency_ms,
        failure_type=local_failure,
    )

    remote_outcome: ModeOutcome | None = None
    if include_remote and remote_llm is not None:
        remote_error = None
        try:
            actual, remote_warnings, latency_ms = remote_actual(
                case,
                remote_llm,
                instructions=instructions,
            )
        except RemoteAdapterError as exc:
            actual = []
            remote_warnings = []
            latency_ms = None
            remote_error = str(exc)
        remote_failure = classify_failure(
            expected,
            actual,
            remote_error=remote_error,
            allow_omitted_rejects=True,
        )
        remote_outcome = ModeOutcome(
            actual=actual,
            warnings=[remote_error] if remote_error else remote_warnings,
            latency_ms=latency_ms,
            failure_type=remote_failure,
        )

    return CaseEvaluation(
        fixture=path,
        case=case,
        category=category,
        content=content,
        expected=expected,
        local=local,
        remote_after_gate=remote_outcome,
    )


def evaluate_case_batch(
    cases: list[tuple[Path, dict[str, Any]]],
    *,
    include_remote: bool,
    remote_llm: RemoteLLMClient | None,
    instructions: str | None,
    case_concurrency: int,
) -> list[CaseEvaluation]:
    if case_concurrency < 1:
        raise ValueError("case_concurrency must be greater than zero")
    if case_concurrency == 1:
        return [
            evaluate_case(
                item,
                include_remote=include_remote,
                remote_llm=remote_llm,
                instructions=instructions,
            )
            for item in cases
        ]

    evaluations_by_index: dict[int, CaseEvaluation] = {}
    with ThreadPoolExecutor(max_workers=case_concurrency) as executor:
        futures = {
            executor.submit(
                evaluate_case,
                item,
                include_remote=include_remote,
                remote_llm=remote_llm,
                instructions=instructions,
            ): index
            for index, item in enumerate(cases)
        }
        for future in as_completed(futures):
            evaluations_by_index[futures[future]] = future.result()
    return [evaluations_by_index[index] for index in range(len(cases))]


def evaluate_cases(
    cases: list[tuple[Path, dict[str, Any]]],
    *,
    include_remote: bool,
    instructions: str | None,
    failure_limit: int,
    selection: dict[str, Any] | None = None,
    case_concurrency: int = 1,
) -> EvaluationResult:
    if case_concurrency < 1:
        raise ValueError("case_concurrency must be greater than zero")
    modes = {"local": ModeStats()}
    category_summary: dict[str, dict[str, ModeStats]] = defaultdict(lambda: {"local": ModeStats()})
    failures: dict[str, list[CaseFailure]] = defaultdict(list)
    warnings: list[str] = []
    remote_llm: RemoteLLMClient | None = None

    if include_remote:
        modes["remote_after_gate"] = ModeStats()
        remote_llm = RemoteLLMClient(RemoteAdapterConfig.llm_from_env())

    evaluations = evaluate_case_batch(
        cases,
        include_remote=include_remote,
        remote_llm=remote_llm,
        instructions=instructions,
        case_concurrency=case_concurrency,
    )

    for evaluation in evaluations:
        case = evaluation.case
        category = evaluation.category

        update_stats(
            modes["local"],
            failure_type=evaluation.local.failure_type,
            latency_ms=evaluation.local.latency_ms,
        )
        update_stats(
            category_summary[category]["local"],
            failure_type=evaluation.local.failure_type,
            latency_ms=evaluation.local.latency_ms,
        )
        if evaluation.local.failure_type and len(failures["local"]) < failure_limit:
            failures["local"].append(
                CaseFailure(
                    fixture=evaluation.fixture.name,
                    name=case["name"],
                    category=category,
                    failure_type=evaluation.local.failure_type,
                    content=evaluation.content,
                    expected=[asdict(item) for item in evaluation.expected],
                    actual=evaluation.local.actual,
                    warnings=evaluation.local.warnings,
                )
            )

        if not include_remote or evaluation.remote_after_gate is None:
            continue

        category_summary[category].setdefault("remote_after_gate", ModeStats())
        remote = evaluation.remote_after_gate
        update_stats(
            modes["remote_after_gate"],
            failure_type=remote.failure_type,
            latency_ms=remote.latency_ms,
        )
        update_stats(
            category_summary[category]["remote_after_gate"],
            failure_type=remote.failure_type,
            latency_ms=remote.latency_ms,
        )
        if remote.warnings:
            warning_counts = Counter(remote.warnings)
            warnings.extend(f"{case['name']}:{warning} x{count}" for warning, count in warning_counts.items())
        if remote.failure_type and len(failures["remote_after_gate"]) < failure_limit:
            failures["remote_after_gate"].append(
                CaseFailure(
                    fixture=evaluation.fixture.name,
                    name=case["name"],
                    category=category,
                    failure_type=remote.failure_type,
                    content=evaluation.content,
                    expected=[asdict(item) for item in evaluation.expected],
                    actual=remote.actual,
                    warnings=remote.warnings,
                )
            )

    return EvaluationResult(
        modes=modes,
        category_summary=category_summary,
        failures=failures,
        selection=selection or {},
        warnings=warnings[:failure_limit],
    )


def print_text(result: EvaluationResult, *, failure_limit: int) -> None:
    print("Write gate evaluation")
    for mode, stats in result.modes.items():
        payload = stats.to_dict()
        print(
            f"- {mode}: cases={payload['cases']} passed={payload['passed']} "
            f"failed={payload['failed']} pass_rate={payload['pass_rate']} "
            f"fp={payload['fp']} fn={payload['fn']} type={payload['type_mismatch']} "
            f"evidence={payload['evidence_mismatch']} decision={payload['decision_mismatch']} "
            f"remote_error={payload['remote_error']} avg_ms={payload['average_latency_ms']}"
        )

    print("\nCategory failures")
    for category, by_mode in sorted(result.category_summary.items()):
        parts = []
        for mode, stats in by_mode.items():
            if stats.failed:
                parts.append(
                    f"{mode}:failed={stats.failed},fp={stats.fp},fn={stats.fn},"
                    f"type={stats.type_mismatch},decision={stats.decision_mismatch}"
                )
        if parts:
            print(f"- {category}: " + "; ".join(parts))
    if not any(stats.failed for stats in result.modes.values()):
        print("- none")

    for mode, failures in result.failures.items():
        if not failures:
            continue
        print(f"\nSample failures: {mode}")
        for failure in failures[:failure_limit]:
            actual = [asdict(item) for item in failure.actual]
            print(
                f"- {failure.name} [{failure.category}/{failure.failure_type}] "
                f"expected={failure.expected} actual={actual}"
            )
            print(f"  {failure.content}")
            for warning in failure.warnings:
                print(f"  warning: {warning}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate write-gate fixtures with local rules and optional remote extraction."
    )
    parser.add_argument(
        "--fixture",
        action="append",
        type=Path,
        help="JSONL fixture to evaluate. Defaults to all write_policy fixtures.",
    )
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument(
        "--sample-per-category",
        type=int,
        help="Keep at most N cases per category after fixture/category filtering.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        help="Randomly sample N cases after fixture/category/per-category filtering.",
    )
    parser.add_argument(
        "--sample-seed",
        type=int,
        help="Seed for reproducible random sampling.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--remote", action="store_true", help="Also call remote LLM extraction.")
    parser.add_argument(
        "--case-concurrency",
        type=int,
        default=1,
        help="Number of write-gate cases to evaluate concurrently.",
    )
    parser.add_argument("--instructions")
    parser.add_argument("--failure-limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fixture_paths = tuple(args.fixture or DEFAULT_FIXTURES)
    cases = load_cases(fixture_paths)
    cases = select_cases(
        cases,
        categories=set(args.category) if args.category else None,
        sample_per_category=args.sample_per_category,
        sample_size=args.sample_size,
        sample_seed=args.sample_seed,
        limit=args.limit,
    )
    selection = {
        "fixtures": [path.name for path in fixture_paths],
        "categories": args.category,
        "sample_per_category": args.sample_per_category,
        "sample_size": args.sample_size,
        "sample_seed": args.sample_seed,
        "limit": args.limit,
        "case_concurrency": args.case_concurrency,
        "case_count": len(cases),
        "case_names": [str(case.get("name", "")) for _, case in cases],
    }
    result = evaluate_cases(
        cases,
        include_remote=args.remote,
        instructions=args.instructions,
        failure_limit=args.failure_limit,
        selection=selection,
        case_concurrency=args.case_concurrency,
    )
    if args.json:
        print(json.dumps(result.to_dict(failure_limit=args.failure_limit), ensure_ascii=False, indent=2))
    else:
        print_text(result, failure_limit=args.failure_limit)
    return 1 if any(stats.failed for stats in result.modes.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
