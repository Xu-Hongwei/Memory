from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory_system.remote import (  # noqa: E402
    RemoteAdapterConfig,
    RemoteEmbeddingClient,
    RemoteLLMClient,
)
from memory_system.remote_evaluation import evaluate_remote_retrieval_fixture  # noqa: E402
from memory_system.schemas import (  # noqa: E402
    RemoteRetrievalEvaluationItem,
    RemoteRetrievalEvaluationResult,
)


DEFAULT_FIXTURE = ROOT / "tests/fixtures/golden_cases/semantic_retrieval_public.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "data/remote_retrieval_benchmarks"
DEFAULT_EMBEDDING_CACHE = ROOT / "data/benchmark_remote_retrieval_embeddings.jsonl"
DEFAULT_LIMIT = 60


@dataclass(frozen=True)
class BenchmarkConfig:
    name: str
    include_selective_llm_judge: bool
    judge_group_size: int
    judge_concurrency: int
    target_mode: str


@dataclass(frozen=True)
class BenchmarkRow:
    name: str
    seconds: float
    target_mode: str
    passed: int
    failed: int
    false_negative: int
    unexpected: int
    ambiguous: int
    pending_tasks: int
    request_mode: str
    judge_group_size: int
    judge_concurrency: int
    single_calls: int
    batch_count: int
    batch_calls: int
    fallback_single_calls: int
    errors: int
    cache_hits: int
    cache_misses: int
    cache_writes: int
    report_path: str


def default_configs() -> tuple[BenchmarkConfig, ...]:
    return (
        BenchmarkConfig(
            name="baseline",
            include_selective_llm_judge=False,
            judge_group_size=1,
            judge_concurrency=1,
            target_mode="guarded_hybrid",
        ),
        BenchmarkConfig(
            name="single_seq",
            include_selective_llm_judge=True,
            judge_group_size=1,
            judge_concurrency=1,
            target_mode="selective_llm_guarded_hybrid",
        ),
        BenchmarkConfig(
            name="single_parallel4",
            include_selective_llm_judge=True,
            judge_group_size=1,
            judge_concurrency=4,
            target_mode="selective_llm_guarded_hybrid",
        ),
        BenchmarkConfig(
            name="batch2_conc2",
            include_selective_llm_judge=True,
            judge_group_size=2,
            judge_concurrency=2,
            target_mode="selective_llm_guarded_hybrid",
        ),
        BenchmarkConfig(
            name="batch4_conc2",
            include_selective_llm_judge=True,
            judge_group_size=4,
            judge_concurrency=2,
            target_mode="selective_llm_guarded_hybrid",
        ),
    )


def selected_configs(names: Iterable[str] | None) -> tuple[BenchmarkConfig, ...]:
    configs = default_configs()
    if not names:
        return configs
    by_name = {config.name: config for config in configs}
    selected: list[BenchmarkConfig] = []
    for name in names:
        if name not in by_name:
            choices = ", ".join(sorted(by_name))
            raise ValueError(f"unknown config {name!r}; choose one of: {choices}")
        selected.append(by_name[name])
    return tuple(selected)


def failure_type(item: RemoteRetrievalEvaluationItem, mode: str) -> str:
    parts: list[str] = []
    if item.warnings:
        parts.append("warning")
    if item.missing_by_mode.get(mode):
        parts.append("false_negative")
    if item.unexpected_by_mode.get(mode):
        parts.append("unexpected")
    if item.ambiguous_by_mode.get(mode):
        parts.append("ambiguous")
    return "+".join(parts) if parts else "failed"


def failure_rows(
    result: RemoteRetrievalEvaluationResult,
    *,
    mode: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in result.items:
        if item.passed_by_mode.get(mode, False):
            continue
        judge = item.judge_by_mode.get(mode)
        rows.append(
            {
                "case_name": item.case_name,
                "category": item.category,
                "failure_type": failure_type(item, mode),
                "query": item.query,
                "expected_aliases": item.expected_aliases,
                "actual_aliases": item.results_by_mode.get(mode, []),
                "missing_aliases": item.missing_by_mode.get(mode, []),
                "unexpected_aliases": item.unexpected_by_mode.get(mode, []),
                "ambiguous_aliases": item.ambiguous_by_mode.get(mode, []),
                "item_warnings": item.warnings,
                "judge": None
                if judge is None
                else {
                    "decision": judge.decision,
                    "reason": judge.reason,
                    "selected_aliases": judge.selected_aliases,
                    "candidate_aliases": judge.candidate_aliases,
                    "warnings": judge.warnings,
                    "metadata": judge.metadata,
                },
            }
        )
        if len(rows) >= limit:
            break
    return rows


def row_from_result(
    *,
    config: BenchmarkConfig,
    result: RemoteRetrievalEvaluationResult,
    seconds: float,
    report_path: Path,
) -> BenchmarkRow:
    mode = config.target_mode
    summary = result.summary
    judge_meta = result.metadata.get("judge", {})
    cache_meta = result.metadata.get("embedding_cache", {})
    if not isinstance(judge_meta, dict):
        judge_meta = {}
    if not isinstance(cache_meta, dict):
        cache_meta = {}
    return BenchmarkRow(
        name=config.name,
        seconds=round(seconds, 2),
        target_mode=mode,
        passed=int(summary.passed_by_mode.get(mode, 0)),
        failed=int(summary.failed_by_mode.get(mode, 0)),
        false_negative=int(summary.false_negative_by_mode.get(mode, 0)),
        unexpected=int(summary.unexpected_by_mode.get(mode, 0)),
        ambiguous=int(summary.ambiguous_by_mode.get(mode, 0)),
        pending_tasks=int(judge_meta.get("pending_tasks", 0) or 0),
        request_mode=str(judge_meta.get("mode", "none")),
        judge_group_size=int(judge_meta.get("group_size", 0) or 0),
        judge_concurrency=int(judge_meta.get("concurrency", 0) or 0),
        single_calls=int(judge_meta.get("single_calls", 0) or 0),
        batch_count=int(judge_meta.get("batch_count", 0) or 0),
        batch_calls=int(judge_meta.get("batch_calls", 0) or 0),
        fallback_single_calls=int(judge_meta.get("fallback_single_calls", 0) or 0),
        errors=int(judge_meta.get("errors", 0) or 0),
        cache_hits=int(cache_meta.get("hits", 0) or 0),
        cache_misses=int(cache_meta.get("misses", 0) or 0),
        cache_writes=int(cache_meta.get("writes", 0) or 0),
        report_path=str(report_path),
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def print_table(rows: list[BenchmarkRow]) -> None:
    headers = (
        "name",
        "seconds",
        "passed",
        "failed",
        "FN",
        "amb",
        "pending",
        "single",
        "batch",
        "errors",
    )
    print("\t".join(headers))
    for row in rows:
        print(
            "\t".join(
                str(value)
                for value in (
                    row.name,
                    row.seconds,
                    row.passed,
                    row.failed,
                    row.false_negative,
                    row.ambiguous,
                    row.pending_tasks,
                    row.single_calls,
                    row.batch_calls,
                    row.errors,
                )
            )
        )


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    configs = selected_configs(args.config)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    embedding_client = RemoteEmbeddingClient(RemoteAdapterConfig.embedding_from_env())
    llm_client = RemoteLLMClient(RemoteAdapterConfig.llm_from_env())
    rows: list[BenchmarkRow] = []
    failures: dict[str, list[dict[str, Any]]] = {}

    for config in configs:
        print(f"RUN {config.name}...", flush=True)
        effective_limit = args.limit
        if effective_limit is None and args.sample_size is None:
            effective_limit = DEFAULT_LIMIT
        started = time.perf_counter()
        result = evaluate_remote_retrieval_fixture(
            args.fixture,
            embedding_client,
            remote_llm=llm_client if config.include_selective_llm_judge else None,
            include_selective_llm_judge=config.include_selective_llm_judge,
            model=args.model,
            limit=effective_limit,
            batch_size=args.batch_size,
            embedding_cache_path=args.embedding_cache,
            case_concurrency=args.case_concurrency,
            judge_concurrency=config.judge_concurrency,
            judge_group_size=config.judge_group_size,
            sample_size=args.sample_size,
            sample_seed=args.sample_seed,
            guard_top_k=args.guard_top_k,
            guard_min_similarity=args.guard_min_similarity,
            guard_ambiguity_margin=args.guard_ambiguity_margin,
            selective_min_similarity=args.selective_min_similarity,
            selective_ambiguity_margin=args.selective_ambiguity_margin,
        )
        seconds = time.perf_counter() - started
        report_path = output_dir / f"{config.name}.json"
        report_payload = result.model_dump(mode="json")
        report_payload["benchmark"] = {
            "name": config.name,
            "seconds": round(seconds, 2),
            "target_mode": config.target_mode,
        }
        write_json(report_path, report_payload)
        rows.append(
            row_from_result(
                config=config,
                result=result,
                seconds=seconds,
                report_path=report_path,
            )
        )
        failures[config.name] = failure_rows(
            result,
            mode=config.target_mode,
            limit=args.failure_limit,
        )

    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "fixture": str(args.fixture),
        "limit": effective_limit,
        "sample_size": args.sample_size,
        "sample_seed": args.sample_seed,
        "embedding_cache": str(args.embedding_cache) if args.embedding_cache else None,
        "case_concurrency": args.case_concurrency,
        "rows": [asdict(row) for row in rows],
        "failures": failures,
    }
    summary_path = output_dir / "summary.json"
    write_json(summary_path, summary)
    print_table(rows)
    print(f"Summary: {summary_path}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark remote retrieval evaluation concurrency settings."
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sample-size", type=int)
    parser.add_argument("--sample-seed", type=int)
    parser.add_argument("--model")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--embedding-cache", type=Path, default=DEFAULT_EMBEDDING_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--case-concurrency", type=int, default=4)
    parser.add_argument("--config", action="append")
    parser.add_argument("--failure-limit", type=int, default=20)
    parser.add_argument("--guard-top-k", type=int, default=3)
    parser.add_argument("--guard-min-similarity", type=float, default=0.20)
    parser.add_argument("--guard-ambiguity-margin", type=float, default=0.03)
    parser.add_argument("--selective-min-similarity", type=float, default=0.20)
    parser.add_argument("--selective-ambiguity-margin", type=float, default=0.03)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_benchmark(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
