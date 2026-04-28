from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import pytest

from memory_system.remote import RemoteAdapterConfig, RemoteAdapterError, RemoteLLMClient
from memory_system.schemas import EventRead


FIXTURE = Path(__file__).parent / "fixtures" / "golden_cases" / "remote_candidate_quality_50.jsonl"


class EmptyRemoteHTTP:
    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []}


class FailingRemoteHTTP:
    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("sensitive fixture case should skip the remote call")


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]


def event_from_case(case: dict[str, Any]) -> EventRead:
    event = case["event"]
    return EventRead(
        id=case["name"],
        event_type=event["event_type"],
        content=event["content"],
        source=event["source"],
        scope=event["scope"],
        metadata=event.get("metadata", {}),
        created_at=datetime.now(timezone.utc),
    )


def expected_types(case: dict[str, Any]) -> list[str]:
    return case["expected"]["remote_types"]


def test_remote_candidate_quality_fixture_shape():
    cases = load_cases()
    categories = {case["category"] for case in cases}

    assert len(cases) == 50
    assert len({case["name"] for case in cases}) == len(cases)
    assert categories == {
        "environment_fact",
        "negative_casual",
        "negative_guess",
        "negative_one_off",
        "negative_reminder",
        "negative_sensitive",
        "negative_session",
        "negative_temporary",
        "project_fact",
        "tool_rule",
        "troubleshooting",
        "troubleshooting_sensitive",
        "user_preference",
        "workflow",
    }
    assert sum(1 for case in cases if case["expected"]["skipped_remote_call"]) == 4


@pytest.mark.parametrize(
    "case",
    [
        case
        for case in load_cases()
        if case["expected"]["skipped_remote_call"]
    ],
    ids=lambda case: case["name"],
)
def test_remote_candidate_quality_sensitive_cases_skip_http(case):
    result = RemoteLLMClient(
        RemoteAdapterConfig(base_url="http://example.invalid"),
        http=FailingRemoteHTTP(),
    ).extract_candidates(event_from_case(case))

    assert result.candidates == []
    assert result.metadata == {"skipped_remote_call": True}
    assert result.warnings == ["filtered_sensitive_remote_event"]


@pytest.mark.parametrize(
    "case",
    [
        case
        for case in load_cases()
        if case["name"]
        in {
            "remote_quality_user_preference_005",
            "remote_quality_user_preference_009",
            "remote_quality_workflow_043",
        }
    ],
    ids=lambda case: case["name"],
)
def test_remote_candidate_quality_fallback_cases_cover_previous_false_negatives(case):
    result = RemoteLLMClient(
        RemoteAdapterConfig(base_url="http://example.invalid"),
        http=EmptyRemoteHTTP(),
    ).extract_candidates(event_from_case(case))

    assert [candidate.memory_type for candidate in result.candidates] == expected_types(case)
    assert any(warning.startswith("local_remote_fallback:") for warning in result.warnings)


@pytest.mark.skipif(
    os.environ.get("MEMORY_RUN_REMOTE_QUALITY") != "1",
    reason="set MEMORY_RUN_REMOTE_QUALITY=1 to run the live remote quality fixture",
)
def test_remote_candidate_quality_live_fixture():
    config = RemoteAdapterConfig.from_env()
    if not config.configured:
        pytest.skip("remote adapter is not configured")

    cases = load_cases()
    max_workers = int(os.environ.get("MEMORY_REMOTE_QUALITY_WORKERS", "4"))
    results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_evaluate_live_case, config, case): case
            for case in cases
        }
        for future in as_completed(futures):
            results.append(future.result())

    summary = _summarize_live_results(results)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    assert summary["counts"].get("fp", 0) == 0
    assert summary["counts"].get("type_mismatch", 0) == 0
    assert summary["extra_noise_count"] == 0
    assert summary["counts"].get("fn", 0) <= int(
        os.environ.get("MEMORY_REMOTE_QUALITY_MAX_FN", "1")
    )


def _evaluate_live_case(
    config: RemoteAdapterConfig,
    case: dict[str, Any],
) -> dict[str, Any]:
    event = event_from_case(case)
    started = time.perf_counter()
    try:
        result = RemoteLLMClient(config).extract_candidates(event)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        remote_types = [candidate.memory_type for candidate in result.candidates]
        skipped = bool(result.metadata.get("skipped_remote_call"))
        error = None
        warnings = result.warnings
    except RemoteAdapterError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        remote_types = []
        skipped = False
        error = str(exc)
        warnings = []

    expected = expected_types(case)
    outcome = _quality_outcome(expected, remote_types, error)
    return {
        "name": case["name"],
        "category": case["category"],
        "expected_types": expected,
        "remote_types": remote_types,
        "warnings": warnings,
        "skipped_remote_call": skipped,
        "latency_ms": latency_ms,
        "outcome": outcome,
        "extra_noise": bool(expected and any(item not in expected for item in remote_types)),
        "error": error,
    }


def _quality_outcome(
    expected: list[str],
    remote_types: list[str],
    error: str | None,
) -> str:
    if error:
        return "error"
    if not expected and remote_types:
        return "fp"
    if not expected:
        return "tn"
    if any(item in remote_types for item in expected):
        return "tp"
    if remote_types:
        return "type_mismatch"
    return "fn"


def _summarize_live_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    by_category: dict[str, dict[str, int]] = {}
    latencies: list[float] = []
    for item in results:
        counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
        bucket = by_category.setdefault(item["category"], {})
        bucket[item["outcome"]] = bucket.get(item["outcome"], 0) + 1
        if item["error"] is None and not item["skipped_remote_call"]:
            latencies.append(item["latency_ms"])

    return {
        "total": len(results),
        "counts": counts,
        "by_category": by_category,
        "remote_candidate_count": sum(len(item["remote_types"]) for item in results),
        "extra_noise_count": sum(1 for item in results if item["extra_noise"]),
        "skipped_sensitive_remote_calls": sum(
            1 for item in results if item["skipped_remote_call"]
        ),
        "avg_latency_ms_non_skipped": round(mean(latencies), 1) if latencies else None,
        "mismatches": [
            item
            for item in sorted(results, key=lambda value: value["name"])
            if item["outcome"] not in {"tp", "tn"} or item["extra_noise"]
        ],
    }
