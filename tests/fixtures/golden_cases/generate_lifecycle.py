from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "lifecycle.jsonl"
SCOPE = "repo:C:/workspace/lifecycle"


def memory(alias: str, content: str, *, subject: str, memory_type: str = "project_fact") -> dict[str, Any]:
    return {
        "alias": alias,
        "content": content,
        "memory_type": memory_type,
        "scope": SCOPE,
        "subject": subject,
        "confidence": "confirmed",
        "source_event_ids": [f"evt_{alias}"],
        "tags": ["lifecycle"],
    }


def candidate(alias: str, content: str, *, subject: str, memory_type: str = "project_fact") -> dict[str, Any]:
    return {
        "alias": alias,
        "content": content,
        "memory_type": memory_type,
        "scope": SCOPE,
        "subject": subject,
        "source_event_ids": [f"evt_{alias}"],
        "reason": "Verified replacement candidate.",
        "confidence": "confirmed",
        "risk": "low",
    }


def add_case(
    cases: list[dict[str, Any]],
    *,
    category: str,
    name: str,
    memories: list[dict[str, Any]],
    action: dict[str, Any],
    expected: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
) -> None:
    case: dict[str, Any] = {
        "category": category,
        "name": name,
        "memories": memories,
        "action": action,
        "expected": expected,
    }
    if candidates:
        case["candidates"] = candidates
    cases.append(case)


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    for index in range(75):
        token = f"LIFE_STALE_{index:03d}"
        alias = f"stale_memory_{index:03d}"
        add_case(
            cases,
            category="mark_stale_excludes_retrieval",
            name=f"mark_stale_excludes_retrieval_{index:03d}",
            memories=[
                memory(
                    alias,
                    f"{token} start command is npm run dev.",
                    subject=f"start command {index:03d}",
                )
            ],
            action={"type": "mark_stale", "alias": alias, "reason": "Source file changed."},
            expected={
                "statuses": {alias: "stale"},
                "search_query": token,
                "search_aliases": [],
                "versions": {alias: ["create", "stale"]},
            },
        )

    for index in range(75):
        token = f"LIFE_ARCHIVE_{index:03d}"
        alias = f"archive_memory_{index:03d}"
        add_case(
            cases,
            category="archive_excludes_retrieval",
            name=f"archive_excludes_retrieval_{index:03d}",
            memories=[
                memory(
                    alias,
                    f"{token} obsolete workflow uses old debug folder.",
                    subject=f"obsolete workflow {index:03d}",
                    memory_type="workflow",
                )
            ],
            action={"type": "archive", "alias": alias, "reason": "Workflow retired."},
            expected={
                "statuses": {alias: "archived"},
                "search_query": token,
                "search_aliases": [],
                "versions": {alias: ["create", "archive"]},
            },
        )

    for index in range(75):
        token = f"LIFE_SUPERSEDE_{index:03d}"
        old_alias = f"supersede_old_{index:03d}"
        new_alias = f"supersede_new_{index:03d}"
        add_case(
            cases,
            category="supersede_replaces_active",
            name=f"supersede_replaces_active_{index:03d}",
            memories=[
                memory(
                    old_alias,
                    f"{token} start command is npm run dev.",
                    subject=f"start command {index:03d}",
                )
            ],
            candidates=[
                candidate(
                    new_alias,
                    f"{token} start command is pnpm dev.",
                    subject=f"start command {index:03d}",
                )
            ],
            action={
                "type": "supersede",
                "old_alias": old_alias,
                "candidate_alias": new_alias,
                "reason": "User confirmed replacement.",
            },
            expected={
                "statuses": {old_alias: "superseded", new_alias: "active"},
                "search_query": token,
                "search_aliases": [new_alias],
                "versions": {old_alias: ["create", "supersede"], new_alias: ["create"]},
            },
        )

    for index in range(75):
        token = f"LIFE_STALE_ARCHIVE_{index:03d}"
        alias = f"stale_archive_memory_{index:03d}"
        add_case(
            cases,
            category="stale_then_archive_versions",
            name=f"stale_then_archive_versions_{index:03d}",
            memories=[
                memory(
                    alias,
                    f"{token} old environment fact says Node 18 is required.",
                    subject=f"node version {index:03d}",
                    memory_type="environment_fact",
                )
            ],
            action={
                "type": "stale_then_archive",
                "alias": alias,
                "stale_reason": "Environment may have changed.",
                "archive_reason": "Old environment note is retired.",
            },
            expected={
                "statuses": {alias: "archived"},
                "search_query": token,
                "search_aliases": [],
                "versions": {alias: ["create", "stale", "archive"]},
            },
        )

    assert len(cases) == 300
    assert len({case["name"] for case in cases}) == 300
    return cases


def main() -> None:
    cases = build_cases()
    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
