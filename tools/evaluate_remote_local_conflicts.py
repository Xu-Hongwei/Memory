from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_system.remote import RemoteAdapterConfig, RemoteAdapterError, RemoteLLMClient  # noqa: E402
from tools.evaluate_write_gate import (  # noqa: E402
    DEFAULT_FIXTURES,
    CandidateOutcome,
    classify_failure,
    expected_outcomes,
    load_cases,
    local_actual,
    remote_actual,
)


@dataclass
class ConflictRow:
    name: str
    fixture: str
    category: str
    local_failure: str
    remote_failure: str
    local: list[CandidateOutcome]
    remote: list[CandidateOutcome]
    conflict: bool
    warnings: list[str]


def _outcome_key(outcomes: list[CandidateOutcome]) -> list[tuple[str, str, str | None]]:
    return sorted((item.memory_type, item.evidence_type, item.decision) for item in outcomes)


def _format_outcomes(outcomes: list[CandidateOutcome]) -> str:
    if not outcomes:
        return "[]"
    return "[" + ", ".join(
        f"{item.memory_type}/{item.evidence_type}/{item.decision}" for item in outcomes
    ) + "]"


def _fixture_paths(values: Iterable[Path] | None) -> tuple[Path, ...]:
    return tuple(values or DEFAULT_FIXTURES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare local write-gate decisions with remote-after-gate decisions."
    )
    parser.add_argument("--fixture", action="append", type=Path)
    parser.add_argument("--seed", type=int, default=20260428)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--batches", type=int, default=5)
    parser.add_argument("--failure-limit", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_cases(_fixture_paths(args.fixture))
    rng = random.Random(args.seed)
    rng.shuffle(cases)
    selected = cases[: args.batch_size * args.batches]
    remote = RemoteLLMClient(RemoteAdapterConfig.llm_from_env())

    totals = {
        "cases": 0,
        "local_pass": 0,
        "remote_pass": 0,
        "both_pass": 0,
        "local_better": 0,
        "remote_better": 0,
        "both_fail": 0,
        "conflicts": 0,
        "remote_errors": 0,
        "remote_ms_total": 0.0,
        "remote_ms_count": 0,
    }

    for batch_index in range(args.batches):
        batch = selected[
            batch_index * args.batch_size : (batch_index + 1) * args.batch_size
        ]
        rows: list[ConflictRow] = []
        batch_stats = {key: 0 for key in totals}
        batch_stats["remote_ms_total"] = 0.0

        for path, case in batch:
            expected = expected_outcomes(case)
            local_out, _, _ = local_actual(case)
            local_failure = classify_failure(expected, local_out)
            started = time.perf_counter()
            remote_error = None
            try:
                remote_out, remote_warnings, latency_ms = remote_actual(
                    case,
                    remote,
                    instructions=None,
                )
                remote_failure = classify_failure(expected, remote_out)
            except RemoteAdapterError as exc:
                remote_out = []
                remote_warnings = [str(exc)]
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                remote_error = str(exc)
                remote_failure = classify_failure(
                    expected,
                    remote_out,
                    remote_error=remote_error,
                )

            local_ok = local_failure is None
            remote_ok = remote_failure is None
            conflict = _outcome_key(local_out) != _outcome_key(remote_out)

            batch_stats["cases"] += 1
            batch_stats["local_pass"] += int(local_ok)
            batch_stats["remote_pass"] += int(remote_ok)
            batch_stats["both_pass"] += int(local_ok and remote_ok)
            batch_stats["local_better"] += int(local_ok and not remote_ok)
            batch_stats["remote_better"] += int(remote_ok and not local_ok)
            batch_stats["both_fail"] += int((not local_ok) and (not remote_ok))
            batch_stats["conflicts"] += int(conflict)
            batch_stats["remote_errors"] += int(remote_error is not None)
            if latency_ms is not None:
                batch_stats["remote_ms_total"] += latency_ms
                batch_stats["remote_ms_count"] += 1

            if (
                conflict
                or local_failure is not None
                or remote_failure is not None
                or len(rows) < args.failure_limit
            ):
                rows.append(
                    ConflictRow(
                        name=case["name"],
                        fixture=path.name,
                        category=str(case.get("category", "unknown")),
                        local_failure=local_failure or "pass",
                        remote_failure=remote_failure or "pass",
                        local=local_out,
                        remote=remote_out,
                        conflict=conflict,
                        warnings=remote_warnings,
                    )
                )

        for key, value in batch_stats.items():
            totals[key] += value
        avg = (
            batch_stats["remote_ms_total"] / batch_stats["remote_ms_count"]
            if batch_stats["remote_ms_count"]
            else 0.0
        )
        print(
            f"BATCH {batch_index + 1}: cases={batch_stats['cases']} "
            f"local_pass={batch_stats['local_pass']} "
            f"remote_pass={batch_stats['remote_pass']} "
            f"both_pass={batch_stats['both_pass']} "
            f"local_better={batch_stats['local_better']} "
            f"remote_better={batch_stats['remote_better']} "
            f"both_fail={batch_stats['both_fail']} "
            f"conflicts={batch_stats['conflicts']} "
            f"remote_errors={batch_stats['remote_errors']} "
            f"avg_remote_ms={avg:.2f}"
        )
        interesting = [
            row
            for row in rows
            if row.conflict or row.local_failure != "pass" or row.remote_failure != "pass"
        ]
        if not interesting:
            print("- no conflicts")
        for row in interesting[: args.failure_limit]:
            print(
                f"! {row.name} [{row.fixture} / {row.category}] "
                f"local={row.local_failure} {_format_outcomes(row.local)} "
                f"remote={row.remote_failure} {_format_outcomes(row.remote)} "
                f"conflict={row.conflict}"
            )
            if row.warnings:
                print("  warnings=" + " | ".join(row.warnings[:3]))

    avg_total = (
        totals["remote_ms_total"] / totals["remote_ms_count"]
        if totals["remote_ms_count"]
        else 0.0
    )
    print(
        f"TOTAL: cases={totals['cases']} local_pass={totals['local_pass']} "
        f"remote_pass={totals['remote_pass']} both_pass={totals['both_pass']} "
        f"local_better={totals['local_better']} remote_better={totals['remote_better']} "
        f"both_fail={totals['both_fail']} conflicts={totals['conflicts']} "
        f"remote_errors={totals['remote_errors']} avg_remote_ms={avg_total:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
