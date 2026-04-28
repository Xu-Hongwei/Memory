from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "task_recall.jsonl"
REPO = "repo:C:/workspace/task-recall"
OTHER_REPO = "repo:C:/workspace/other-task"


def memory(
    alias: str,
    content: str,
    *,
    memory_type: str = "project_fact",
    scope: str = REPO,
    subject: str = "task recall",
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
        "tags": tags or [],
    }


def add_case(
    cases: list[dict[str, Any]],
    *,
    category: str,
    name: str,
    task: str,
    memories: list[dict[str, Any]],
    included_aliases: list[str],
    excluded_aliases: list[str] | None = None,
    intent: str | None = None,
    scope: str = REPO,
) -> None:
    expected: dict[str, Any] = {
        "included_aliases": included_aliases,
        "excluded_aliases": excluded_aliases or [],
    }
    if intent:
        expected["intent"] = intent
    cases.append(
        {
            "name": name,
            "category": category,
            "synthetic": True,
            "task": task,
            "scope": scope,
            "memories": memories,
            "expected": expected,
        }
    )


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    for index in range(60):
        token = f"TASK_STARTUP_DOCS_{index:03d}"
        add_case(
            cases,
            category="startup_docs_recall",
            name=f"startup_docs_recall_{index:03d}",
            task=f"{token} 帮我写这个项目的启动说明 README",
            memories=[
                memory(
                    f"startup_doc_style_{index:03d}",
                    f"{token} documentation style uses Chinese and conclusion-first structure.",
                    memory_type="user_preference",
                    scope="global",
                    subject=f"documentation style {index:03d}",
                    tags=["docs"],
                ),
                memory(
                    f"startup_command_{index:03d}",
                    f"{token} start command is pnpm dev.",
                    subject=f"start command {index:03d}",
                    tags=["startup"],
                ),
                memory(
                    f"startup_verify_{index:03d}",
                    f"{token} verify docs examples with python -m pytest.",
                    memory_type="tool_rule",
                    subject=f"verification {index:03d}",
                    tags=["verification"],
                ),
                memory(
                    f"startup_other_repo_{index:03d}",
                    f"{token} start command for another repo is yarn dev.",
                    scope=OTHER_REPO,
                    subject=f"other start command {index:03d}",
                ),
            ],
            included_aliases=[
                f"startup_doc_style_{index:03d}",
                f"startup_command_{index:03d}",
                f"startup_verify_{index:03d}",
            ],
            excluded_aliases=[f"startup_other_repo_{index:03d}"],
            intent="documentation",
        )

    for index in range(50):
        token = f"TASK_DEBUG_{index:03d}"
        add_case(
            cases,
            category="debug_recall",
            name=f"debug_recall_{index:03d}",
            task=f"{token} 这个项目报错 error，帮我排查失败原因",
            memories=[
                memory(
                    f"debug_experience_{index:03d}",
                    f"{token} troubleshooting: missing API_BASE_URL caused error; setting it fixed the failure.",
                    memory_type="troubleshooting",
                    subject=f"API_BASE_URL error {index:03d}",
                    tags=["debug"],
                ),
                memory(
                    f"debug_env_{index:03d}",
                    f"{token} environment fact: local shell is PowerShell.",
                    memory_type="environment_fact",
                    subject=f"shell environment {index:03d}",
                    tags=["environment"],
                ),
                memory(
                    f"debug_other_repo_{index:03d}",
                    f"{token} troubleshooting for another repo uses Docker reset.",
                    memory_type="troubleshooting",
                    scope=OTHER_REPO,
                    subject=f"other debug {index:03d}",
                ),
            ],
            included_aliases=[f"debug_experience_{index:03d}", f"debug_env_{index:03d}"],
            excluded_aliases=[f"debug_other_repo_{index:03d}"],
            intent="troubleshooting",
        )

    for index in range(50):
        token = f"TASK_VERIFY_{index:03d}"
        add_case(
            cases,
            category="verification_recall",
            name=f"verification_recall_{index:03d}",
            task=f"{token} 运行测试并验证 pytest 和 ruff",
            memories=[
                memory(
                    f"verify_pytest_{index:03d}",
                    f"{token} test command is python -m pytest.",
                    memory_type="tool_rule",
                    subject=f"pytest command {index:03d}",
                    tags=["test"],
                ),
                memory(
                    f"verify_ruff_{index:03d}",
                    f"{token} verification command is python -m ruff check .",
                    memory_type="tool_rule",
                    subject=f"ruff command {index:03d}",
                    tags=["verify"],
                ),
                memory(
                    f"verify_timeout_{index:03d}",
                    f"{token} troubleshooting: close SQLite connections when tests hang on Windows.",
                    memory_type="troubleshooting",
                    subject=f"test timeout {index:03d}",
                    tags=["test"],
                ),
            ],
            included_aliases=[
                f"verify_pytest_{index:03d}",
                f"verify_ruff_{index:03d}",
                f"verify_timeout_{index:03d}",
            ],
            intent="verification",
        )

    for index in range(40):
        token = f"TASK_STRUCTURE_{index:03d}"
        add_case(
            cases,
            category="project_structure_recall",
            name=f"project_structure_recall_{index:03d}",
            task=f"{token} 解释项目结构 architecture 和模块目录",
            memories=[
                memory(
                    f"structure_modules_{index:03d}",
                    f"{token} project structure: src/memory_system contains schemas, store, api, and recall modules.",
                    subject=f"project structure {index:03d}",
                    tags=["structure"],
                ),
                memory(
                    f"structure_docs_{index:03d}",
                    f"{token} workflow: update PROJECT_STRUCTURE style docs after module changes.",
                    memory_type="workflow",
                    subject=f"structure docs {index:03d}",
                    tags=["docs"],
                ),
            ],
            included_aliases=[f"structure_modules_{index:03d}", f"structure_docs_{index:03d}"],
            intent="project_structure",
        )

    for index in range(40):
        token = f"TASK_PREF_{index:03d}"
        add_case(
            cases,
            category="preference_recall",
            name=f"preference_recall_{index:03d}",
            task=f"{token} 按我的偏好和默认风格回复",
            memories=[
                memory(
                    f"pref_style_{index:03d}",
                    f"{token} preference: answer in Chinese with clear facts and assumptions.",
                    memory_type="user_preference",
                    scope="global",
                    subject=f"answer style {index:03d}",
                    tags=["style"],
                ),
                memory(
                    f"pref_other_repo_{index:03d}",
                    f"{token} project fact in another repo should not be recalled.",
                    scope=OTHER_REPO,
                    subject=f"other pref {index:03d}",
                ),
            ],
            included_aliases=[f"pref_style_{index:03d}"],
            excluded_aliases=[f"pref_other_repo_{index:03d}"],
            intent="preference",
        )

    for index in range(40):
        token = f"TASK_INACTIVE_{index:03d}"
        add_case(
            cases,
            category="inactive_exclusion_recall",
            name=f"inactive_exclusion_recall_{index:03d}",
            task=f"{token} 写启动说明",
            memories=[
                memory(
                    f"inactive_active_start_{index:03d}",
                    f"{token} start command is pnpm dev.",
                    subject=f"active start {index:03d}",
                ),
                memory(
                    f"inactive_stale_start_{index:03d}",
                    f"{token} start command used to be npm run dev.",
                    subject=f"stale start {index:03d}",
                    status="stale",
                ),
                memory(
                    f"inactive_archived_note_{index:03d}",
                    f"{token} archived note says use old debug folder.",
                    memory_type="workflow",
                    subject=f"archived note {index:03d}",
                    status="archived",
                ),
            ],
            included_aliases=[f"inactive_active_start_{index:03d}"],
            excluded_aliases=[
                f"inactive_stale_start_{index:03d}",
                f"inactive_archived_note_{index:03d}",
            ],
            intent="documentation",
        )

    for index in range(20):
        token = f"TASK_SCOPE_{index:03d}"
        add_case(
            cases,
            category="cross_scope_exclusion_recall",
            name=f"cross_scope_exclusion_recall_{index:03d}",
            task=f"{token} 启动这个项目并写说明",
            memories=[
                memory(
                    f"scope_current_start_{index:03d}",
                    f"{token} start command is uvicorn memory_system.api:create_app.",
                    subject=f"current start {index:03d}",
                ),
                memory(
                    f"scope_global_style_{index:03d}",
                    f"{token} docs preference: keep setup instructions concise.",
                    memory_type="user_preference",
                    scope="global",
                    subject=f"global docs style {index:03d}",
                ),
                memory(
                    f"scope_other_start_{index:03d}",
                    f"{token} other repo start command is yarn dev.",
                    scope=OTHER_REPO,
                    subject=f"other start {index:03d}",
                ),
            ],
            included_aliases=[f"scope_current_start_{index:03d}", f"scope_global_style_{index:03d}"],
            excluded_aliases=[f"scope_other_start_{index:03d}"],
            intent="documentation",
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
