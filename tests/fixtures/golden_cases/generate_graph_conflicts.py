from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "graph_conflicts.jsonl"
SCOPE = "repo:C:/workspace/graph-conflicts"
OTHER_SCOPE = "repo:C:/workspace/graph-conflicts-other"


def memory(
    alias: str,
    content: str,
    *,
    scope: str = SCOPE,
    status: str = "active",
) -> dict[str, Any]:
    return {
        "alias": alias,
        "content": content,
        "memory_type": "project_fact",
        "scope": scope,
        "subject": "graph conflict",
        "confidence": "confirmed",
        "source_event_ids": [f"evt_{alias}"],
        "tags": ["graph-conflict"],
        "status": status,
    }


def entity(
    alias: str,
    name: str,
    *,
    entity_type: str = "concept",
    scope: str = SCOPE,
) -> dict[str, Any]:
    return {
        "alias": alias,
        "name": name,
        "entity_type": entity_type,
        "scope": scope,
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


def add_case(
    cases: list[dict[str, Any]],
    *,
    category: str,
    name: str,
    memories: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    action: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    cases.append(
        {
            "category": category,
            "name": name,
            "synthetic": True,
            "memories": memories,
            "entities": entities,
            "relations": relations,
            "action": action,
            "expected": expected,
        }
    )


def conflict_expected(
    *,
    from_alias: str,
    relation_type: str,
    target_aliases: list[str],
    memory_aliases: list[str],
) -> dict[str, Any]:
    return {
        "conflict_count": 1,
        "conflicts": [
            {
                "from_alias": from_alias,
                "relation_type": relation_type,
                "target_aliases": target_aliases,
                "memory_aliases": memory_aliases,
            }
        ],
    }


def no_conflict_expected() -> dict[str, Any]:
    return {"conflict_count": 0, "conflicts": []}


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    for index in range(80):
        token = f"GRAPH_CONFLICT_START_{index:03d}"
        old_memory = f"start_old_{index:03d}"
        new_memory = f"start_new_{index:03d}"
        add_case(
            cases,
            category="start_command_conflict",
            name=f"start_command_conflict_{index:03d}",
            memories=[
                memory(old_memory, f"{token} start command is npm run dev."),
                memory(new_memory, f"{token} start command is pnpm dev."),
            ],
            entities=[
                entity("repo", SCOPE, entity_type="repo"),
                entity("npm", "npm run dev", entity_type="command"),
                entity("pnpm", "pnpm dev", entity_type="command"),
            ],
            relations=[
                relation("repo_npm", "repo", "has_start_command", "npm", old_memory),
                relation("repo_pnpm", "repo", "has_start_command", "pnpm", new_memory),
            ],
            action={"scope": SCOPE, "relation_type": "has_start_command"},
            expected=conflict_expected(
                from_alias="repo",
                relation_type="has_start_command",
                target_aliases=["npm", "pnpm"],
                memory_aliases=[old_memory, new_memory],
            ),
        )

    for index in range(60):
        token = f"GRAPH_CONFLICT_DB_{index:03d}"
        sqlite_memory = f"db_sqlite_{index:03d}"
        redis_memory = f"db_redis_{index:03d}"
        add_case(
            cases,
            category="database_conflict",
            name=f"database_conflict_{index:03d}",
            memories=[
                memory(sqlite_memory, f"{token} memory store uses SQLite."),
                memory(redis_memory, f"{token} memory store uses Redis."),
            ],
            entities=[
                entity("repo", SCOPE, entity_type="repo"),
                entity("sqlite", "SQLite", entity_type="tool"),
                entity("redis", "Redis", entity_type="tool"),
            ],
            relations=[
                relation("repo_sqlite", "repo", "uses_database", "sqlite", sqlite_memory),
                relation("repo_redis", "repo", "uses_database", "redis", redis_memory),
            ],
            action={"scope": SCOPE, "relation_type": "uses_database"},
            expected=conflict_expected(
                from_alias="repo",
                relation_type="uses_database",
                target_aliases=["sqlite", "redis"],
                memory_aliases=[sqlite_memory, redis_memory],
            ),
        )

    for index in range(50):
        token = f"GRAPH_CONFLICT_LANG_{index:03d}"
        zh_memory = f"lang_zh_{index:03d}"
        en_memory = f"lang_en_{index:03d}"
        add_case(
            cases,
            category="language_conflict",
            name=f"language_conflict_{index:03d}",
            memories=[
                memory(zh_memory, f"{token} documentation language is Chinese."),
                memory(en_memory, f"{token} documentation language is English."),
            ],
            entities=[
                entity("repo", SCOPE, entity_type="repo"),
                entity("zh", "Chinese", entity_type="concept"),
                entity("en", "English", entity_type="concept"),
            ],
            relations=[
                relation("repo_zh", "repo", "default_language", "zh", zh_memory),
                relation("repo_en", "repo", "default_language", "en", en_memory),
            ],
            action={"scope": SCOPE, "relation_type": "default_language"},
            expected=conflict_expected(
                from_alias="repo",
                relation_type="default_language",
                target_aliases=["zh", "en"],
                memory_aliases=[zh_memory, en_memory],
            ),
        )

    for index in range(40):
        token = f"GRAPH_NO_CONFLICT_TARGET_{index:03d}"
        first = f"same_target_first_{index:03d}"
        second = f"same_target_second_{index:03d}"
        add_case(
            cases,
            category="same_target_no_conflict",
            name=f"same_target_no_conflict_{index:03d}",
            memories=[
                memory(first, f"{token} package manager is pnpm."),
                memory(second, f"{token} README also says package manager is pnpm."),
            ],
            entities=[
                entity("repo", SCOPE, entity_type="repo"),
                entity("pnpm", "pnpm", entity_type="tool"),
            ],
            relations=[
                relation("repo_pnpm_first", "repo", "uses_package_manager", "pnpm", first),
                relation("repo_pnpm_second", "repo", "uses_package_manager", "pnpm", second),
            ],
            action={"scope": SCOPE, "relation_type": "uses_package_manager"},
            expected=no_conflict_expected(),
        )

    for index in range(30):
        token = f"GRAPH_CONFLICT_SCOPE_{index:03d}"
        old_memory = f"other_start_old_{index:03d}"
        new_memory = f"other_start_new_{index:03d}"
        add_case(
            cases,
            category="cross_scope_exclusion",
            name=f"cross_scope_exclusion_{index:03d}",
            memories=[
                memory(old_memory, f"{token} other repo start command is npm.", scope=OTHER_SCOPE),
                memory(new_memory, f"{token} other repo start command is pnpm.", scope=OTHER_SCOPE),
            ],
            entities=[
                entity("current_repo", SCOPE, entity_type="repo", scope=SCOPE),
                entity("other_repo", OTHER_SCOPE, entity_type="repo", scope=OTHER_SCOPE),
                entity("npm", "npm run dev", entity_type="command", scope=OTHER_SCOPE),
                entity("pnpm", "pnpm dev", entity_type="command", scope=OTHER_SCOPE),
            ],
            relations=[
                relation("other_npm", "other_repo", "has_start_command", "npm", old_memory),
                relation("other_pnpm", "other_repo", "has_start_command", "pnpm", new_memory),
            ],
            action={"scope": SCOPE, "relation_type": "has_start_command"},
            expected=no_conflict_expected(),
        )

    for index in range(20):
        token = f"GRAPH_CONFLICT_INACTIVE_{index:03d}"
        active = f"inactive_active_{index:03d}"
        stale = f"inactive_stale_{index:03d}"
        add_case(
            cases,
            category="inactive_source_exclusion",
            name=f"inactive_source_exclusion_{index:03d}",
            memories=[
                memory(active, f"{token} active command is pnpm dev."),
                memory(stale, f"{token} stale command is npm run dev.", status="stale"),
            ],
            entities=[
                entity("repo", SCOPE, entity_type="repo"),
                entity("pnpm", "pnpm dev", entity_type="command"),
                entity("npm", "npm run dev", entity_type="command"),
            ],
            relations=[
                relation("repo_pnpm", "repo", "has_start_command", "pnpm", active),
                relation("repo_npm", "repo", "has_start_command", "npm", stale),
            ],
            action={"scope": SCOPE, "relation_type": "has_start_command"},
            expected=no_conflict_expected(),
        )

    for index in range(20):
        token = f"GRAPH_CONFLICT_LOWCONF_{index:03d}"
        confirmed = f"lowconf_confirmed_{index:03d}"
        inferred = f"lowconf_inferred_{index:03d}"
        add_case(
            cases,
            category="low_confidence_relation_exclusion",
            name=f"low_confidence_relation_exclusion_{index:03d}",
            memories=[
                memory(confirmed, f"{token} confirmed command is pnpm dev."),
                memory(inferred, f"{token} guessed command is npm run dev."),
            ],
            entities=[
                entity("repo", SCOPE, entity_type="repo"),
                entity("pnpm", "pnpm dev", entity_type="command"),
                entity("npm", "npm run dev", entity_type="command"),
            ],
            relations=[
                relation("repo_pnpm", "repo", "has_start_command", "pnpm", confirmed),
                relation(
                    "repo_npm",
                    "repo",
                    "has_start_command",
                    "npm",
                    inferred,
                    confidence="inferred",
                ),
            ],
            action={"scope": SCOPE, "relation_type": "has_start_command"},
            expected=no_conflict_expected(),
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
