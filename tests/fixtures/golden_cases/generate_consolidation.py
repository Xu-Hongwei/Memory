from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "consolidation.jsonl"
SCOPE = "repo:C:/workspace/consolidation"
OTHER_SCOPE = "repo:C:/workspace/consolidation-other"


def memory(
    alias: str,
    content: str,
    *,
    memory_type: str = "project_fact",
    scope: str = SCOPE,
    subject: str = "consolidation subject",
    confidence: str = "confirmed",
    status: str = "active",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "alias": alias,
        "content": content,
        "memory_type": memory_type,
        "scope": scope,
        "subject": subject,
        "confidence": confidence,
        "source_event_ids": [f"evt_{alias}"],
        "status": status,
        "tags": tags or ["consolidation"],
    }


def add_case(
    cases: list[dict[str, Any]],
    *,
    category: str,
    name: str,
    memories: list[dict[str, Any]],
    expected: dict[str, Any],
    action: dict[str, Any] | None = None,
) -> None:
    cases.append(
        {
            "category": category,
            "name": name,
            "synthetic": True,
            "memories": memories,
            "action": action or {"type": "propose_only"},
            "expected": expected,
        }
    )


def merge_expected(
    *,
    source_aliases: list[str],
    token: str,
    consolidated_alias: str = "consolidated",
) -> dict[str, Any]:
    return {
        "candidate_count": 1,
        "source_aliases": source_aliases,
        "statuses": {
            **{alias: "superseded" for alias in source_aliases},
            consolidated_alias: "active",
        },
        "search_query": token,
        "search_aliases": [consolidated_alias],
        "versions": {
            **{alias: ["create", "supersede"] for alias in source_aliases},
            consolidated_alias: ["create"],
        },
    }


def no_candidate_expected() -> dict[str, Any]:
    return {"candidate_count": 0}


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    for index in range(60):
        token = f"CONS_PREF_{index:03d}"
        first = f"pref_first_{index:03d}"
        second = f"pref_second_{index:03d}"
        add_case(
            cases,
            category="merge_user_preference",
            name=f"merge_user_preference_{index:03d}",
            memories=[
                memory(
                    first,
                    f"{token} user prefers concise Chinese documentation.",
                    memory_type="user_preference",
                    scope="global",
                    subject="documentation style",
                    tags=["docs"],
                ),
                memory(
                    second,
                    f"{token} user wants facts separated from inference.",
                    memory_type="user_preference",
                    scope="global",
                    subject="documentation style",
                    tags=["style"],
                ),
            ],
            action={"type": "propose_and_commit", "scope": "global", "memory_type": "user_preference"},
            expected=merge_expected(source_aliases=[first, second], token=token),
        )

    for index in range(60):
        token = f"CONS_FACT_{index:03d}"
        first = f"fact_first_{index:03d}"
        second = f"fact_second_{index:03d}"
        add_case(
            cases,
            category="merge_project_fact",
            name=f"merge_project_fact_{index:03d}",
            memories=[
                memory(
                    first,
                    f"{token} package manager is pnpm.",
                    subject="project setup",
                    tags=["setup"],
                ),
                memory(
                    second,
                    f"{token} development command is pnpm dev.",
                    subject="project setup",
                    tags=["command"],
                ),
            ],
            action={"type": "propose_and_commit", "scope": SCOPE, "memory_type": "project_fact"},
            expected=merge_expected(source_aliases=[first, second], token=token),
        )

    for index in range(45):
        token = f"CONS_SCOPE_{index:03d}"
        add_case(
            cases,
            category="skip_cross_scope",
            name=f"skip_cross_scope_{index:03d}",
            memories=[
                memory(
                    f"scope_a_{index:03d}",
                    f"{token} repo A uses npm.",
                    scope=SCOPE,
                    subject="start command",
                ),
                memory(
                    f"scope_b_{index:03d}",
                    f"{token} repo B uses pnpm.",
                    scope=OTHER_SCOPE,
                    subject="start command",
                ),
            ],
            expected=no_candidate_expected(),
        )

    for index in range(45):
        token = f"CONS_TYPE_{index:03d}"
        add_case(
            cases,
            category="skip_different_type",
            name=f"skip_different_type_{index:03d}",
            memories=[
                memory(
                    f"type_fact_{index:03d}",
                    f"{token} project fact note.",
                    memory_type="project_fact",
                    subject="same subject",
                ),
                memory(
                    f"type_workflow_{index:03d}",
                    f"{token} workflow note.",
                    memory_type="workflow",
                    subject="same subject",
                ),
            ],
            expected=no_candidate_expected(),
        )

    for index in range(45):
        token = f"CONS_INACTIVE_{index:03d}"
        add_case(
            cases,
            category="skip_inactive",
            name=f"skip_inactive_{index:03d}",
            memories=[
                memory(
                    f"inactive_active_{index:03d}",
                    f"{token} active setup note.",
                    subject="inactive mix",
                ),
                memory(
                    f"inactive_stale_{index:03d}",
                    f"{token} stale setup note.",
                    subject="inactive mix",
                    status="stale",
                ),
            ],
            expected=no_candidate_expected(),
        )

    for index in range(45):
        token = f"CONS_LOWCONF_{index:03d}"
        add_case(
            cases,
            category="skip_low_confidence",
            name=f"skip_low_confidence_{index:03d}",
            memories=[
                memory(
                    f"lowconf_confirmed_{index:03d}",
                    f"{token} confirmed setup note.",
                    subject="confidence mix",
                ),
                memory(
                    f"lowconf_inferred_{index:03d}",
                    f"{token} inferred setup note.",
                    subject="confidence mix",
                    confidence="inferred",
                ),
            ],
            expected=no_candidate_expected(),
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
