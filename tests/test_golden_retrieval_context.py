from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_system import MemoryItemCreate, MemoryStore, SearchMemoryInput, compose_context


def load_cases() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "golden_cases" / "retrieval_context.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def seed_memories(memories: MemoryStore, definitions: list[dict]) -> dict[str, object]:
    created = {}
    for definition in definitions:
        alias = definition["alias"]
        status = definition.get("status", "active")
        payload = {
            key: value
            for key, value in definition.items()
            if key not in {"alias", "status"}
        }
        memory = memories.add_memory(MemoryItemCreate(**payload))
        if status != "active":
            if status == "stale":
                memory = memories.mark_stale(memory.id, "Seeded stale memory for golden test.")
            elif status == "archived":
                memory = memories.archive_memory(memory.id, "Seeded archived memory for golden test.")
            else:
                memories._update_memory_status(memory.id, status)
                memory = memories.get_memory(memory.id)
        created[alias] = memory
    return created


def aliases_for_results(alias_by_id: dict[str, str], ids: list[str]) -> list[str]:
    return [alias_by_id[memory_id] for memory_id in ids]


def test_golden_retrieval_context_suite_shape():
    cases = load_cases()
    categories = {case.get("category") for case in cases}

    assert len(cases) == 400
    assert len({case["name"] for case in cases}) == len(cases)
    assert categories == {
        "context_budget",
        "context_includes_confirmed",
        "context_low_confidence_warnings",
        "context_skips_inactive",
        "retrieval_confidence_ranking",
        "retrieval_current_scope_priority",
        "retrieval_excludes_inactive",
        "retrieval_global_fallback",
        "retrieval_limit",
        "retrieval_type_filter",
    }


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["name"])
def test_golden_retrieval_and_context_cases(case):
    memories = MemoryStore(":memory:")
    by_alias = seed_memories(memories, case["memories"])
    alias_by_id = {memory.id: alias for alias, memory in by_alias.items()}

    if case["mode"] == "retrieval":
        results = memories.search_memory(SearchMemoryInput(**case["search"]))
        result_aliases = aliases_for_results(alias_by_id, [memory.id for memory in results])
        expected = case["expected"]

        if "exact_aliases" in expected:
            assert result_aliases == expected["exact_aliases"]
        if "ordered_prefix" in expected:
            prefix = expected["ordered_prefix"]
            assert result_aliases[: len(prefix)] == prefix
        if "result_count" in expected:
            assert len(result_aliases) == expected["result_count"]
        for alias in expected.get("absent_aliases", []):
            assert alias not in result_aliases
        return

    context_input = case["context"]
    block = compose_context(
        context_input["task"],
        [by_alias[alias] for alias in context_input["input_aliases"]],
        token_budget=context_input["token_budget"],
    )
    block_aliases = aliases_for_results(alias_by_id, block.memory_ids)
    expected = case["expected"]

    for alias in expected.get("included_aliases", []):
        assert alias in block_aliases
    for alias in expected.get("excluded_aliases", []):
        assert alias not in block_aliases
    for fragment in expected.get("content_contains", []):
        assert fragment in block.content
    for fragment in expected.get("warning_contains", []):
        assert any(fragment in warning for warning in block.warnings)
