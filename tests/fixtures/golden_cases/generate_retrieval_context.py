from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "retrieval_context.jsonl"
REPO_ALPHA = "repo:C:/workspace/alpha"
REPO_BETA = "repo:C:/workspace/beta"


def memory(
    alias: str,
    content: str,
    *,
    memory_type: str = "project_fact",
    scope: str = REPO_ALPHA,
    subject: str = "general",
    confidence: str = "confirmed",
    tags: list[str] | None = None,
    status: str = "active",
) -> dict[str, Any]:
    return {
        "alias": alias,
        "content": content,
        "memory_type": memory_type,
        "scope": scope,
        "subject": subject,
        "confidence": confidence,
        "source_event_ids": [f"evt_{alias}"],
        "tags": tags or [],
        "status": status,
    }


def search(
    query: str,
    *,
    scopes: list[str] | None = None,
    memory_types: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    return {
        "query": query,
        "scopes": scopes or [],
        "memory_types": memory_types or [],
        "limit": limit,
    }


def add_case(
    cases: list[dict[str, Any]],
    *,
    mode: str,
    category: str,
    name: str,
    memories: list[dict[str, Any]],
    expected: dict[str, Any],
    search_input: dict[str, Any] | None = None,
    context_input: dict[str, Any] | None = None,
) -> None:
    case: dict[str, Any] = {
        "mode": mode,
        "category": category,
        "name": name,
        "memories": memories,
        "expected": expected,
    }
    if search_input is not None:
        case["search"] = search_input
    if context_input is not None:
        case["context"] = context_input
    cases.append(case)


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    for index in range(60):
        token = f"RET_SCOPE_{index:03d}"
        add_case(
            cases,
            mode="retrieval",
            category="retrieval_current_scope_priority",
            name=f"retrieval_current_scope_priority_{index:03d}",
            memories=[
                memory(
                    f"scope_repo_{index:03d}",
                    f"{token} start command for alpha repo is pnpm dev.",
                    scope=REPO_ALPHA,
                    subject=f"start command {index:03d}",
                ),
                memory(
                    f"scope_global_{index:03d}",
                    f"{token} default start command guidance is npm run dev.",
                    scope="global",
                    subject=f"start command {index:03d}",
                ),
                memory(
                    f"scope_other_{index:03d}",
                    f"{token} start command for beta repo is yarn dev.",
                    scope=REPO_BETA,
                    subject=f"start command {index:03d}",
                ),
            ],
            search_input=search(
                token,
                scopes=[REPO_ALPHA, "global"],
                memory_types=["project_fact"],
                limit=2,
            ),
            expected={
                "ordered_prefix": [f"scope_repo_{index:03d}", f"scope_global_{index:03d}"],
                "absent_aliases": [f"scope_other_{index:03d}"],
            },
        )

    for index in range(50):
        token = f"RET_TYPE_{index:03d}"
        add_case(
            cases,
            mode="retrieval",
            category="retrieval_type_filter",
            name=f"retrieval_type_filter_{index:03d}",
            memories=[
                memory(
                    f"type_project_{index:03d}",
                    f"{token} package manager is uv for this project.",
                    memory_type="project_fact",
                    scope=REPO_ALPHA,
                    subject=f"package manager {index:03d}",
                ),
                memory(
                    f"type_pref_{index:03d}",
                    f"{token} user prefers concise answers.",
                    memory_type="user_preference",
                    scope=REPO_ALPHA,
                    subject=f"answer style {index:03d}",
                ),
            ],
            search_input=search(
                token,
                scopes=[REPO_ALPHA],
                memory_types=["project_fact"],
                limit=5,
            ),
            expected={"exact_aliases": [f"type_project_{index:03d}"]},
        )

    for index in range(40):
        token = f"RET_GLOBAL_{index:03d}"
        add_case(
            cases,
            mode="retrieval",
            category="retrieval_global_fallback",
            name=f"retrieval_global_fallback_{index:03d}",
            memories=[
                memory(
                    f"global_pref_{index:03d}",
                    f"{token} user default response language is Chinese.",
                    memory_type="user_preference",
                    scope="global",
                    subject=f"response language {index:03d}",
                    tags=["future_responses"],
                ),
                memory(
                    f"repo_unrelated_{index:03d}",
                    f"UNRELATED_{index:03d} alpha repo uses local test data.",
                    scope=REPO_ALPHA,
                    subject=f"unrelated {index:03d}",
                ),
            ],
            search_input=search(
                token,
                scopes=[REPO_ALPHA, "global"],
                memory_types=["user_preference"],
                limit=3,
            ),
            expected={"exact_aliases": [f"global_pref_{index:03d}"]},
        )

    for index in range(40):
        token = f"RET_INACTIVE_{index:03d}"
        add_case(
            cases,
            mode="retrieval",
            category="retrieval_excludes_inactive",
            name=f"retrieval_excludes_inactive_{index:03d}",
            memories=[
                memory(
                    f"inactive_active_{index:03d}",
                    f"{token} active project fact should be returned.",
                    scope=REPO_ALPHA,
                    subject=f"active fact {index:03d}",
                ),
                memory(
                    f"inactive_archived_{index:03d}",
                    f"{token} archived project fact must not be returned.",
                    scope=REPO_ALPHA,
                    subject=f"archived fact {index:03d}",
                    status="archived",
                ),
            ],
            search_input=search(token, scopes=[REPO_ALPHA], limit=5),
            expected={
                "exact_aliases": [f"inactive_active_{index:03d}"],
                "absent_aliases": [f"inactive_archived_{index:03d}"],
            },
        )

    for index in range(40):
        token = f"RET_CONF_{index:03d}"
        add_case(
            cases,
            mode="retrieval",
            category="retrieval_confidence_ranking",
            name=f"retrieval_confidence_ranking_{index:03d}",
            memories=[
                memory(
                    f"confidence_likely_{index:03d}",
                    f"{token} likely fact about build command.",
                    scope=REPO_ALPHA,
                    subject=f"build command {index:03d}",
                    confidence="likely",
                ),
                memory(
                    f"confidence_confirmed_{index:03d}",
                    f"{token} confirmed fact about build command.",
                    scope=REPO_ALPHA,
                    subject=f"build command {index:03d}",
                    confidence="confirmed",
                ),
            ],
            search_input=search(token, scopes=[REPO_ALPHA], limit=5),
            expected={
                "ordered_prefix": [
                    f"confidence_confirmed_{index:03d}",
                    f"confidence_likely_{index:03d}",
                ]
            },
        )

    for index in range(30):
        token = f"RET_LIMIT_{index:03d}"
        memories = [
            memory(
                f"limit_item_{index:03d}_{slot}",
                f"{token} candidate memory {slot} for result limit testing.",
                scope=REPO_ALPHA,
                subject=f"limit item {slot}",
            )
            for slot in range(5)
        ]
        add_case(
            cases,
            mode="retrieval",
            category="retrieval_limit",
            name=f"retrieval_limit_{index:03d}",
            memories=memories,
            search_input=search(token, scopes=[REPO_ALPHA], limit=2),
            expected={"result_count": 2},
        )

    for index in range(50):
        add_case(
            cases,
            mode="context",
            category="context_includes_confirmed",
            name=f"context_includes_confirmed_{index:03d}",
            memories=[
                memory(
                    f"context_pref_{index:03d}",
                    f"CONTEXT_CONF_{index:03d} user prefers Chinese technical docs.",
                    memory_type="user_preference",
                    scope="global",
                    subject=f"doc language {index:03d}",
                    tags=["future_responses"],
                ),
                memory(
                    f"context_project_{index:03d}",
                    f"CONTEXT_CONF_{index:03d} alpha repo test command is python -m pytest.",
                    scope=REPO_ALPHA,
                    subject=f"test command {index:03d}",
                    tags=["verification"],
                ),
            ],
            context_input={
                "task": f"CONTEXT_CONF_{index:03d} write project docs",
                "input_aliases": [f"context_pref_{index:03d}", f"context_project_{index:03d}"],
                "token_budget": 1000,
            },
            expected={
                "included_aliases": [f"context_pref_{index:03d}", f"context_project_{index:03d}"],
                "content_contains": ["Relevant memory for task", f"CONTEXT_CONF_{index:03d}"],
            },
        )

    for index in range(30):
        add_case(
            cases,
            mode="context",
            category="context_skips_inactive",
            name=f"context_skips_inactive_{index:03d}",
            memories=[
                memory(
                    f"context_active_{index:03d}",
                    f"CONTEXT_SKIP_{index:03d} active memory remains usable.",
                    scope=REPO_ALPHA,
                    subject=f"active context {index:03d}",
                ),
                memory(
                    f"context_archived_{index:03d}",
                    f"CONTEXT_SKIP_{index:03d} archived memory must stay out of context.",
                    scope=REPO_ALPHA,
                    subject=f"archived context {index:03d}",
                    status="archived",
                ),
            ],
            context_input={
                "task": f"CONTEXT_SKIP_{index:03d} compose",
                "input_aliases": [f"context_active_{index:03d}", f"context_archived_{index:03d}"],
                "token_budget": 1000,
            },
            expected={
                "included_aliases": [f"context_active_{index:03d}"],
                "excluded_aliases": [f"context_archived_{index:03d}"],
                "warning_contains": ["status=archived"],
            },
        )

    for index in range(30):
        add_case(
            cases,
            mode="context",
            category="context_budget",
            name=f"context_budget_{index:03d}",
            memories=[
                memory(
                    f"context_short_{index:03d}",
                    f"CONTEXT_BUDGET_{index:03d} short memory.",
                    memory_type="user_preference",
                    scope="global",
                    subject=f"short context {index:03d}",
                ),
                memory(
                    f"context_long_{index:03d}",
                    f"CONTEXT_BUDGET_{index:03d} " + ("very long memory content " * 40),
                    scope=REPO_ALPHA,
                    subject=f"long context {index:03d}",
                ),
            ],
            context_input={
                "task": f"CONTEXT_BUDGET_{index:03d} assemble context",
                "input_aliases": [f"context_short_{index:03d}", f"context_long_{index:03d}"],
                "token_budget": 260,
            },
            expected={
                "included_aliases": [f"context_short_{index:03d}"],
                "excluded_aliases": [f"context_long_{index:03d}"],
                "warning_contains": ["token_budget exhausted"],
            },
        )

    for index in range(30):
        add_case(
            cases,
            mode="context",
            category="context_low_confidence_warnings",
            name=f"context_low_confidence_warnings_{index:03d}",
            memories=[
                memory(
                    f"context_likely_{index:03d}",
                    f"CONTEXT_WARN_{index:03d} likely memory should carry warnings.",
                    memory_type="project_fact",
                    scope=REPO_ALPHA,
                    subject=f"likely context {index:03d}",
                    confidence="likely",
                )
            ],
            context_input={
                "task": f"CONTEXT_WARN_{index:03d} compose",
                "input_aliases": [f"context_likely_{index:03d}"],
                "token_budget": 1000,
            },
            expected={
                "included_aliases": [f"context_likely_{index:03d}"],
                "warning_contains": ["confidence=likely", "missing last_verified_at"],
            },
        )

    assert len(cases) == 400
    assert len({case["name"] for case in cases}) == 400
    return cases


def main() -> None:
    cases = build_cases()
    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
