from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent
OUTPUT = ROOT / "session_route_splitting.jsonl"
SCOPE = "repo:C:/workspace/session-route"


def event(
    alias: str,
    content: str,
    *,
    event_type: str = "user_message",
    source: str = "conversation",
    scope: str = SCOPE,
) -> dict[str, Any]:
    return {
        "alias": alias,
        "event_type": event_type,
        "content": content,
        "source": source,
        "scope": scope,
        "metadata": {},
    }


def expected(
    label: str,
    route: str,
    *,
    source_event_aliases: list[str],
    memory_type: str | None = None,
    session_memory_type: str | None = None,
    context_role: str = "excluded",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "label": label,
        "route": route,
        "source_event_aliases": source_event_aliases,
        "context_role": context_role,
    }
    if memory_type is not None:
        payload["memory_type"] = memory_type
    if session_memory_type is not None:
        payload["session_memory_type"] = session_memory_type
    return payload


def case(
    name: str,
    category: str,
    events: list[dict[str, Any]],
    expected_items: list[dict[str, Any]],
    *,
    scenario: str,
    utterance_style: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "mode": "session_route_splitting",
        "category": category,
        "scenario": scenario,
        "utterance_style": utterance_style,
        "source_family": "manual_design",
        "events": events,
        "expected": {"items": expected_items},
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    single_cn = [
        (
            "以后技术文档默认中文；这次先不要提交；刚刚 pytest 已经通过。",
            [
                expected(
                    "stable_language",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="user_preference",
                ),
                expected(
                    "temporary_commit_rule",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="temporary_rule",
                    context_role="critical",
                ),
                expected(
                    "pytest_result",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="working_fact",
                    context_role="critical",
                ),
            ],
        ),
        (
            "发布前固定流程是先跑 ruff 再跑 pytest；当前先只跑 50 条样本。",
            [
                expected(
                    "release_workflow",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="workflow",
                ),
                expected(
                    "current_sample_size",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="task_state",
                    context_role="critical",
                ),
            ],
        ),
        (
            "我现在有点乱，需要你放慢解释；以后技术解释先给结论。",
            [
                expected(
                    "current_confusion",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="emotional_state",
                    context_role="critical",
                ),
                expected(
                    "answer_order",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="user_preference",
                ),
            ],
        ),
        (
            "待确认事项：短期记忆是否落盘？以后项目文档要同步 README 和 docs。",
            [
                expected(
                    "storage_decision",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="pending_decision",
                    context_role="critical",
                ),
                expected(
                    "doc_sync_workflow",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="workflow",
                ),
            ],
        ),
        (
            "这次如果要删除 legacy 入口，先问我，没确认不要动；这次先不要提交；长期偏好是技术解释要区分事实和推断。",
            [
                expected("legacy_confirmation", "ask_user", source_event_aliases=["mixed"]),
                expected(
                    "temporary_no_commit",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="temporary_rule",
                    context_role="critical",
                ),
                expected(
                    "fact_inference_preference",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="user_preference",
                ),
            ],
        ),
        (
            "以后远程评估报告先写 serious failure；这次只看 session_route_splitting 结果；如果遇到隐私材料，先留在本地处理。",
            [
                expected(
                    "serious_first_report",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="user_preference",
                ),
                expected(
                    "current_focus",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="task_state",
                    context_role="critical",
                ),
            ],
        ),
    ]
    for index, (content, expected_items) in enumerate(single_cn):
        cases.append(
            case(
                f"split_single_cn_{index:03d}",
                "single_event_multi_info_cn",
                [event("mixed", content)],
                expected_items,
                scenario="single_event_atomic_split",
                utterance_style="compound_cn",
            )
        )

    single_en = [
        (
            "Going forward, summarize risks first; for this run, keep generated reports in data/.",
            [
                expected(
                    "risk_first_preference",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="user_preference",
                ),
                expected(
                    "report_location_rule",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="temporary_rule",
                    context_role="critical",
                ),
            ],
        ),
        (
            "Validation order is ruff, targeted pytest, full suite; today only run the targeted pytest.",
            [
                expected(
                    "validation_workflow",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="workflow",
                ),
                expected(
                    "targeted_only_today",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="temporary_rule",
                    context_role="critical",
                ),
            ],
        ),
        (
            "I am confused about the memory flow right now; by default, explain with concrete examples.",
            [
                expected(
                    "current_confusion",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="emotional_state",
                    context_role="critical",
                ),
                expected(
                    "example_preference",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="user_preference",
                ),
            ],
        ),
        (
            "Pending confirmation: should session memory expire by task or by page refresh? Also remember that docs must cite test commands.",
            [
                expected(
                    "expiry_decision",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="pending_decision",
                    context_role="critical",
                ),
                expected(
                    "doc_test_command_rule",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="workflow",
                ),
            ],
        ),
        (
            "Before deleting old fixtures in this task, ask me and do not proceed until I confirm; for this run do not commit; keep future memory reports concise.",
            [
                expected("delete_confirmation", "ask_user", source_event_aliases=["mixed"]),
                expected(
                    "temporary_no_commit",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="temporary_rule",
                    context_role="critical",
                ),
                expected(
                    "concise_reports",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="user_preference",
                ),
            ],
        ),
        (
            "Future split reports should include item accuracy; for this pass, compare only route accuracy; private material should stay local.",
            [
                expected(
                    "item_accuracy_report",
                    "long_term",
                    source_event_aliases=["mixed"],
                    memory_type="user_preference",
                ),
                expected(
                    "route_accuracy_focus",
                    "session",
                    source_event_aliases=["mixed"],
                    session_memory_type="task_state",
                    context_role="critical",
                ),
            ],
        ),
    ]
    for index, (content, expected_items) in enumerate(single_en):
        cases.append(
            case(
                f"split_single_en_{index:03d}",
                "single_event_multi_info_en",
                [event("mixed", content)],
                expected_items,
                scenario="single_event_atomic_split",
                utterance_style="compound_en",
            )
        )

    multi_cn = [
        (
            [
                event("pref", "以后写项目说明默认中文，并且先说结论。"),
                event("rule", "这次先不要提交，只保存评估报告。"),
                event("ack", "好的。"),
            ],
            [
                expected(
                    "project_intro_preference",
                    "long_term",
                    source_event_aliases=["pref"],
                    memory_type="user_preference",
                ),
                expected(
                    "no_commit_rule",
                    "session",
                    source_event_aliases=["rule"],
                    session_memory_type="temporary_rule",
                    context_role="critical",
                ),
            ],
        ),
        (
            [
                event("workflow", "固定验证流程是先 ruff，再 pytest，最后远程烟测。"),
                event("state", "当前任务先只跑 session_route_splitting。"),
                event("emotion", "我现在有点乱，解释慢一点。"),
            ],
            [
                expected(
                    "validation_workflow",
                    "long_term",
                    source_event_aliases=["workflow"],
                    memory_type="workflow",
                ),
                expected(
                    "current_fixture_focus",
                    "session",
                    source_event_aliases=["state"],
                    session_memory_type="task_state",
                    context_role="critical",
                ),
                expected(
                    "slow_down",
                    "session",
                    source_event_aliases=["emotion"],
                    session_memory_type="emotional_state",
                    context_role="critical",
                ),
            ],
        ),
        (
            [
                event("pending", "待确认事项：下一批是跑 50 条还是 100 条？"),
                event("pref", "长期偏好是分析测试结果时先说误判类型。"),
            ],
            [
                expected(
                    "sample_size_decision",
                    "session",
                    source_event_aliases=["pending"],
                    session_memory_type="pending_decision",
                    context_role="critical",
                ),
                expected(
                    "failure_type_preference",
                    "long_term",
                    source_event_aliases=["pref"],
                    memory_type="user_preference",
                ),
            ],
        ),
        (
            [
                event("secret", "这里出现 [REDACTED] / token / secret 相关内容，默认不提候选。"),
                event("state", "这轮只验证 preflight 和 session 是否能同时存在。"),
                event("pref", "以后分流报告默认先写 serious failure。"),
            ],
            [
                expected("secret_preflight", "reject", source_event_aliases=["secret"]),
                expected(
                    "preflight_focus",
                    "session",
                    source_event_aliases=["state"],
                    session_memory_type="task_state",
                    context_role="critical",
                ),
                expected(
                    "serious_first_report",
                    "long_term",
                    source_event_aliases=["pref"],
                    memory_type="user_preference",
                ),
            ],
        ),
        (
            [
                event("ask", "如果这次要删除旧数据集，先问我，没确认不要动。"),
                event("state", "这次先不要提交数据集修改。"),
                event("workflow", "数据集说明文档要写生成方式和使用方式。"),
            ],
            [
                expected("delete_dataset_confirmation", "ask_user", source_event_aliases=["ask"]),
                expected(
                    "temporary_no_commit",
                    "session",
                    source_event_aliases=["state"],
                    session_memory_type="temporary_rule",
                    context_role="critical",
                ),
                expected(
                    "dataset_readme_workflow",
                    "long_term",
                    source_event_aliases=["workflow"],
                    memory_type="workflow",
                ),
            ],
        ),
        (
            [
                event("fact", "刚刚定向 30 条 route 测试通过，没有 serious failure。"),
                event("pref", "之后汇报远程测试时默认给出 route 和 strict 两个指标。"),
            ],
            [
                expected(
                    "targeted_test_result",
                    "session",
                    source_event_aliases=["fact"],
                    session_memory_type="working_fact",
                    context_role="critical",
                ),
                expected(
                    "metrics_preference",
                    "long_term",
                    source_event_aliases=["pref"],
                    memory_type="user_preference",
                ),
            ],
        ),
    ]
    for index, (events, expected_items) in enumerate(multi_cn):
        cases.append(
            case(
                f"split_batch_cn_{index:03d}",
                "multi_event_batch_cn",
                events,
                expected_items,
                scenario="multi_event_atomic_split",
                utterance_style="batch_cn",
            )
        )

    multi_en = [
        (
            [
                event(
                    "pref",
                    "Going forward, keep memory benchmark summaries short and evidence-first.",
                ),
                event("rule", "For this run, do not commit generated reports."),
                event("ack", "Thanks."),
            ],
            [
                expected(
                    "benchmark_summary_preference",
                    "long_term",
                    source_event_aliases=["pref"],
                    memory_type="user_preference",
                ),
                expected(
                    "no_commit_rule",
                    "session",
                    source_event_aliases=["rule"],
                    session_memory_type="temporary_rule",
                    context_role="critical",
                ),
            ],
        ),
        (
            [
                event(
                    "workflow",
                    "Release validation order is ruff, pytest, then a remote smoke test.",
                ),
                event("state", "Current task is only the multi-event route split test."),
                event("emotion", "I am a bit lost, so slow down the explanation."),
            ],
            [
                expected(
                    "release_validation_workflow",
                    "long_term",
                    source_event_aliases=["workflow"],
                    memory_type="workflow",
                ),
                expected(
                    "route_split_focus",
                    "session",
                    source_event_aliases=["state"],
                    session_memory_type="task_state",
                    context_role="critical",
                ),
                expected(
                    "slow_down",
                    "session",
                    source_event_aliases=["emotion"],
                    session_memory_type="emotional_state",
                    context_role="critical",
                ),
            ],
        ),
        (
            [
                event(
                    "pending",
                    "Pending confirmation: should the next batch use 50 cases or 100 cases?",
                ),
                event(
                    "pref", "When analyzing test output, default to listing false negatives first."
                ),
            ],
            [
                expected(
                    "batch_size_decision",
                    "session",
                    source_event_aliases=["pending"],
                    session_memory_type="pending_decision",
                    context_role="critical",
                ),
                expected(
                    "fn_first_preference",
                    "long_term",
                    source_event_aliases=["pref"],
                    memory_type="user_preference",
                ),
            ],
        ),
        (
            [
                event(
                    "secret",
                    "If [REDACTED] token-like material appears, reject it before extraction.",
                ),
                event("state", "This pass only checks whether reject and session can coexist."),
                event("pref", "Future split reports should mention serious failures first."),
            ],
            [
                expected("secret_preflight", "reject", source_event_aliases=["secret"]),
                expected(
                    "reject_session_focus",
                    "session",
                    source_event_aliases=["state"],
                    session_memory_type="task_state",
                    context_role="critical",
                ),
                expected(
                    "serious_first_report",
                    "long_term",
                    source_event_aliases=["pref"],
                    memory_type="user_preference",
                ),
            ],
        ),
        (
            [
                event(
                    "ask",
                    "Before deleting the old fixture file in this task, ask me and do not proceed until I confirm.",
                ),
                event("state", "For this pass, do not commit fixture changes yet."),
                event(
                    "workflow",
                    "Fixture README should document generation commands and evaluation commands.",
                ),
            ],
            [
                expected("delete_fixture_confirmation", "ask_user", source_event_aliases=["ask"]),
                expected(
                    "temporary_no_commit",
                    "session",
                    source_event_aliases=["state"],
                    session_memory_type="temporary_rule",
                    context_role="critical",
                ),
                expected(
                    "fixture_readme_workflow",
                    "long_term",
                    source_event_aliases=["workflow"],
                    memory_type="workflow",
                ),
            ],
        ),
        (
            [
                event(
                    "fact",
                    "The targeted 30-case route test just passed with zero serious failures.",
                ),
                event(
                    "pref",
                    "Future remote-test reports should include route accuracy and strict accuracy.",
                ),
            ],
            [
                expected(
                    "targeted_test_result",
                    "session",
                    source_event_aliases=["fact"],
                    session_memory_type="working_fact",
                    context_role="critical",
                ),
                expected(
                    "metrics_preference",
                    "long_term",
                    source_event_aliases=["pref"],
                    memory_type="user_preference",
                ),
            ],
        ),
    ]
    for index, (events, expected_items) in enumerate(multi_en):
        cases.append(
            case(
                f"split_batch_en_{index:03d}",
                "multi_event_batch_en",
                events,
                expected_items,
                scenario="multi_event_atomic_split",
                utterance_style="batch_en",
            )
        )
    return cases


def main() -> None:
    cases = build_cases()
    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(cases)} cases to {OUTPUT}")


if __name__ == "__main__":
    main()
