from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "conflict_reviews.jsonl"
SCOPE = "repo:C:/workspace/conflict-review"


def memory(alias: str, content: str, *, status: str = "active") -> dict[str, Any]:
    return {
        "alias": alias,
        "content": content,
        "memory_type": "project_fact",
        "scope": SCOPE,
        "subject": "conflict review",
        "confidence": "confirmed",
        "source_event_ids": [f"evt_{alias}"],
        "tags": ["conflict-review"],
        "status": status,
    }


def entity(alias: str, name: str, *, entity_type: str = "concept") -> dict[str, Any]:
    return {
        "alias": alias,
        "name": name,
        "entity_type": entity_type,
        "scope": SCOPE,
        "aliases": [],
    }


def relation(
    alias: str,
    from_alias: str,
    relation_type: str,
    to_alias: str,
    memory_alias: str,
    *,
    confidence: str = "confirmed",
) -> dict[str, Any]:
    return {
        "alias": alias,
        "from_alias": from_alias,
        "relation_type": relation_type,
        "to_alias": to_alias,
        "source_memory_aliases": [memory_alias],
        "confidence": confidence,
    }


def conflict_case(
    cases: list[dict[str, Any]],
    *,
    category: str,
    name: str,
    token: str,
    old_alias: str,
    new_alias: str,
    relation_type: str,
    old_target: str,
    new_target: str,
    resolve_action: str | None,
    expected: dict[str, Any],
    old_status: str = "active",
    new_relation_confidence: str = "confirmed",
    action_type: str = "create_and_resolve",
) -> None:
    cases.append(
        {
            "category": category,
            "name": name,
            "synthetic": True,
            "memories": [
                memory(old_alias, f"{token} old value is {old_target}.", status=old_status),
                memory(new_alias, f"{token} new value is {new_target}."),
            ],
            "entities": [
                entity("repo", SCOPE, entity_type="repo"),
                entity("old_target", old_target),
                entity("new_target", new_target),
            ],
            "relations": [
                relation("old_relation", "repo", relation_type, "old_target", old_alias),
                relation(
                    "new_relation",
                    "repo",
                    relation_type,
                    "new_target",
                    new_alias,
                    confidence=new_relation_confidence,
                ),
            ],
            "action": {
                "type": action_type,
                "scope": SCOPE,
                "relation_type": relation_type,
                "resolve_action": resolve_action,
            },
            "expected": expected,
        }
    )


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    for index in range(80):
        old_alias = f"accept_new_old_{index:03d}"
        new_alias = f"accept_new_new_{index:03d}"
        conflict_case(
            cases,
            category="accept_new_resolution",
            name=f"accept_new_resolution_{index:03d}",
            token=f"REVIEW_ACCEPT_NEW_{index:03d}",
            old_alias=old_alias,
            new_alias=new_alias,
            relation_type="has_start_command",
            old_target="npm run dev",
            new_target="pnpm dev",
            resolve_action="accept_new",
            expected={
                "review_count": 1,
                "review_status": "resolved",
                "recommended_keep_aliases": [new_alias],
                "statuses": {old_alias: "superseded", new_alias: "active"},
                "conflicts_after": 0,
            },
        )

    for index in range(50):
        old_alias = f"keep_existing_old_{index:03d}"
        new_alias = f"keep_existing_new_{index:03d}"
        conflict_case(
            cases,
            category="keep_existing_resolution",
            name=f"keep_existing_resolution_{index:03d}",
            token=f"REVIEW_KEEP_EXISTING_{index:03d}",
            old_alias=old_alias,
            new_alias=new_alias,
            relation_type="default_language",
            old_target="Chinese",
            new_target="English",
            resolve_action="keep_existing",
            expected={
                "review_count": 1,
                "review_status": "resolved",
                "statuses": {old_alias: "active", new_alias: "superseded"},
                "conflicts_after": 0,
            },
        )

    for index in range(40):
        old_alias = f"archive_all_old_{index:03d}"
        new_alias = f"archive_all_new_{index:03d}"
        conflict_case(
            cases,
            category="archive_all_resolution",
            name=f"archive_all_resolution_{index:03d}",
            token=f"REVIEW_ARCHIVE_ALL_{index:03d}",
            old_alias=old_alias,
            new_alias=new_alias,
            relation_type="uses_database",
            old_target="SQLite",
            new_target="Redis",
            resolve_action="archive_all",
            expected={
                "review_count": 1,
                "review_status": "resolved",
                "statuses": {old_alias: "archived", new_alias: "archived"},
                "conflicts_after": 0,
            },
        )

    for index in range(30):
        old_alias = f"ask_user_old_{index:03d}"
        new_alias = f"ask_user_new_{index:03d}"
        conflict_case(
            cases,
            category="ask_user_resolution",
            name=f"ask_user_resolution_{index:03d}",
            token=f"REVIEW_ASK_USER_{index:03d}",
            old_alias=old_alias,
            new_alias=new_alias,
            relation_type="has_start_command",
            old_target="npm run dev",
            new_target="pnpm dev",
            resolve_action="ask_user",
            expected={
                "review_count": 1,
                "review_status": "needs_user",
                "statuses": {old_alias: "active", new_alias: "active"},
                "conflicts_after": 1,
            },
        )

    for index in range(30):
        old_alias = f"duplicate_old_{index:03d}"
        new_alias = f"duplicate_new_{index:03d}"
        conflict_case(
            cases,
            category="duplicate_pending_review",
            name=f"duplicate_pending_review_{index:03d}",
            token=f"REVIEW_DUPLICATE_{index:03d}",
            old_alias=old_alias,
            new_alias=new_alias,
            relation_type="has_start_command",
            old_target="npm run dev",
            new_target="pnpm dev",
            resolve_action=None,
            action_type="create_twice",
            expected={"review_count": 1, "second_review_count": 0},
        )

    for index in range(30):
        alias_1 = f"same_target_first_{index:03d}"
        alias_2 = f"same_target_second_{index:03d}"
        cases.append(
            {
                "category": "same_target_no_review",
                "name": f"same_target_no_review_{index:03d}",
                "synthetic": True,
                "memories": [
                    memory(alias_1, f"REVIEW_NO_CONFLICT_{index:03d} first pnpm fact."),
                    memory(alias_2, f"REVIEW_NO_CONFLICT_{index:03d} second pnpm fact."),
                ],
                "entities": [
                    entity("repo", SCOPE, entity_type="repo"),
                    entity("pnpm", "pnpm dev"),
                ],
                "relations": [
                    relation("first_relation", "repo", "has_start_command", "pnpm", alias_1),
                    relation("second_relation", "repo", "has_start_command", "pnpm", alias_2),
                ],
                "action": {
                    "type": "create_only",
                    "scope": SCOPE,
                    "relation_type": "has_start_command",
                    "resolve_action": None,
                },
                "expected": {"review_count": 0},
            }
        )

    for index in range(40):
        old_alias = f"excluded_old_{index:03d}"
        new_alias = f"excluded_new_{index:03d}"
        if index % 2 == 0:
            conflict_case(
                cases,
                category="inactive_or_low_confidence_no_review",
                name=f"inactive_or_low_confidence_no_review_{index:03d}",
                token=f"REVIEW_EXCLUDED_{index:03d}",
                old_alias=old_alias,
                new_alias=new_alias,
                relation_type="has_start_command",
                old_target="npm run dev",
                new_target="pnpm dev",
                resolve_action=None,
                old_status="stale",
                action_type="create_only",
                expected={"review_count": 0},
            )
        else:
            conflict_case(
                cases,
                category="inactive_or_low_confidence_no_review",
                name=f"inactive_or_low_confidence_no_review_{index:03d}",
                token=f"REVIEW_EXCLUDED_{index:03d}",
                old_alias=old_alias,
                new_alias=new_alias,
                relation_type="has_start_command",
                old_target="npm run dev",
                new_target="pnpm dev",
                resolve_action=None,
                new_relation_confidence="inferred",
                action_type="create_only",
                expected={"review_count": 0},
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
