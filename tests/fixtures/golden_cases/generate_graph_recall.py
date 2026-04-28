from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "graph_recall.jsonl"
SCOPE = "repo:C:/workspace/graph"
OTHER_SCOPE = "repo:C:/workspace/graph-other"


def memory(
    alias: str,
    content: str,
    *,
    memory_type: str = "project_fact",
    scope: str = SCOPE,
    subject: str = "graph fact",
    status: str = "active",
) -> dict[str, Any]:
    return {
        "alias": alias,
        "content": content,
        "memory_type": memory_type,
        "scope": scope,
        "subject": subject,
        "confidence": "confirmed",
        "source_event_ids": [f"evt_{alias}"],
        "tags": ["graph"],
        "status": status,
    }


def entity(
    alias: str,
    name: str,
    *,
    entity_type: str = "concept",
    scope: str = SCOPE,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "alias": alias,
        "name": name,
        "entity_type": entity_type,
        "scope": scope,
        "aliases": aliases or [],
    }


def relation(
    alias: str,
    from_alias: str,
    relation_type: str,
    to_alias: str,
    *,
    source_memory_aliases: list[str] | None = None,
    confidence: str = "confirmed",
) -> dict[str, Any]:
    return {
        "alias": alias,
        "from_alias": from_alias,
        "relation_type": relation_type,
        "to_alias": to_alias,
        "source_memory_aliases": source_memory_aliases or [],
        "confidence": confidence,
    }


def add_case(
    cases: list[dict[str, Any]],
    *,
    category: str,
    name: str,
    task: str,
    memories: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    included_aliases: list[str],
    excluded_aliases: list[str] | None = None,
    scope: str = SCOPE,
    max_depth: int = 2,
) -> None:
    cases.append(
        {
            "category": category,
            "name": name,
            "synthetic": True,
            "task": task,
            "scope": scope,
            "max_depth": max_depth,
            "memories": memories,
            "entities": entities,
            "relations": relations,
            "expected": {
                "included_aliases": included_aliases,
                "excluded_aliases": excluded_aliases or [],
            },
        }
    )


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    for index in range(60):
        token = f"GRAPH_REPO_{index:03d}"
        mem = f"repo_memory_{index:03d}"
        add_case(
            cases,
            category="repo_entity_recall",
            name=f"repo_entity_recall_{index:03d}",
            task=f"{token} 这个项目启动失败，帮我排查",
            memories=[memory(mem, f"{token} start command is pnpm dev.")],
            entities=[
                entity("repo", SCOPE, entity_type="repo", aliases=[token]),
                entity("command", "pnpm dev", entity_type="command"),
            ],
            relations=[relation("repo_command", "repo", "has_start_command", "command", source_memory_aliases=[mem])],
            included_aliases=[mem],
        )

    for index in range(50):
        token = f"GRAPH_FILE_{index:03d}"
        mem = f"file_memory_{index:03d}"
        add_case(
            cases,
            category="file_entity_recall",
            name=f"file_entity_recall_{index:03d}",
            task=f"{token} package.json 里的 dev 脚本怎么看",
            memories=[memory(mem, f"{token} package.json dev script is pnpm dev.")],
            entities=[
                entity("file", "package.json", entity_type="file", aliases=[token]),
                entity("command", "pnpm dev", entity_type="command"),
            ],
            relations=[relation("file_command", "file", "defines_command", "command", source_memory_aliases=[mem])],
            included_aliases=[mem],
        )

    for index in range(50):
        token = f"GRAPH_TOOL_{index:03d}"
        mem = f"tool_memory_{index:03d}"
        add_case(
            cases,
            category="tool_entity_recall",
            name=f"tool_entity_recall_{index:03d}",
            task=f"{token} pnpm 怎么启动这个项目",
            memories=[memory(mem, f"{token} pnpm runs the project with pnpm dev.")],
            entities=[
                entity("tool", "pnpm", entity_type="tool", aliases=[token]),
                entity("command", "pnpm dev", entity_type="command"),
            ],
            relations=[relation("tool_command", "tool", "runs_command", "command", source_memory_aliases=[mem])],
            included_aliases=[mem],
        )

    for index in range(50):
        token = f"GRAPH_ERROR_{index:03d}"
        mem = f"error_memory_{index:03d}"
        add_case(
            cases,
            category="error_solution_recall",
            name=f"error_solution_recall_{index:03d}",
            task=f"{token} host binding error 又出现了",
            memories=[
                memory(
                    mem,
                    f"{token} host binding error is solved by adding --host 0.0.0.0.",
                    memory_type="troubleshooting",
                    subject="host binding error",
                )
            ],
            entities=[
                entity("error", "host binding error", entity_type="error", aliases=[token]),
                entity("solution", "--host 0.0.0.0", entity_type="solution"),
            ],
            relations=[relation("error_solution", "error", "solved_by", "solution", source_memory_aliases=[mem])],
            included_aliases=[mem],
        )

    for index in range(40):
        token = f"GRAPH_SCOPE_{index:03d}"
        mem = f"other_scope_memory_{index:03d}"
        add_case(
            cases,
            category="cross_scope_exclusion",
            name=f"cross_scope_exclusion_{index:03d}",
            task=f"{token} 这个项目启动失败",
            memories=[memory(mem, f"{token} other repo command is npm run dev.", scope=OTHER_SCOPE)],
            entities=[
                entity("current_repo", SCOPE, entity_type="repo", aliases=[token]),
                entity("other_repo", OTHER_SCOPE, entity_type="repo", scope=OTHER_SCOPE, aliases=[token]),
                entity("other_command", "npm run dev", entity_type="command", scope=OTHER_SCOPE),
            ],
            relations=[
                relation(
                    "other_repo_command",
                    "other_repo",
                    "has_start_command",
                    "other_command",
                    source_memory_aliases=[mem],
                )
            ],
            included_aliases=[],
            excluded_aliases=[mem],
        )

    for index in range(30):
        token = f"GRAPH_OLD_{index:03d}"
        mem = f"old_memory_{index:03d}"
        add_case(
            cases,
            category="old_memory_exclusion",
            name=f"old_memory_exclusion_{index:03d}",
            task=f"{token} 这个项目启动失败",
            memories=[memory(mem, f"{token} old command is npm run dev.", status="superseded")],
            entities=[
                entity("repo", SCOPE, entity_type="repo", aliases=[token]),
                entity("old_command", "npm run dev", entity_type="command"),
            ],
            relations=[
                relation("old_repo_command", "repo", "has_start_command", "old_command", source_memory_aliases=[mem])
            ],
            included_aliases=[],
            excluded_aliases=[mem],
        )

    for index in range(20):
        token = f"GRAPH_LOWCONF_{index:03d}"
        mem = f"low_conf_memory_{index:03d}"
        add_case(
            cases,
            category="low_confidence_relation_exclusion",
            name=f"low_confidence_relation_exclusion_{index:03d}",
            task=f"{token} 这个项目启动失败",
            memories=[memory(mem, f"{token} guessed start command might be npm run dev.")],
            entities=[
                entity("repo", SCOPE, entity_type="repo", aliases=[token]),
                entity("guess", "npm run dev", entity_type="command"),
            ],
            relations=[
                relation(
                    "low_conf_repo_command",
                    "repo",
                    "maybe_has_start_command",
                    "guess",
                    source_memory_aliases=[mem],
                    confidence="inferred",
                )
            ],
            included_aliases=[],
            excluded_aliases=[mem],
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
