from __future__ import annotations

import json
from pathlib import Path
from typing import Any


OUTPUT = Path(__file__).with_name("task_boundary.jsonl")
SCOPE = "repo:C:/workspace/task-boundary"


def _event(content: str, *, event_type: str = "user_message") -> dict[str, Any]:
    return {
        "event_type": event_type,
        "content": content,
        "source": "conversation",
        "scope": SCOPE,
        "metadata": {},
    }


def _case(
    *,
    name: str,
    category: str,
    current_title: str,
    events: list[str],
    expected_action: str,
    recent_events: list[tuple[str, str]] | None = None,
    next_task_title: str | None = None,
    acceptable_actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "mode": "task_boundary",
        "name": name,
        "category": category,
        "current_task_state": {
            "task_id": f"task_{name}",
            "title": current_title,
            "status": "active",
        },
        "recent_events": [
            _event(content, event_type=event_type)
            for event_type, content in (recent_events or [])
        ],
        "events": [_event(content) for content in events],
        "expected": {
            "action": expected_action,
            "acceptable_actions": acceptable_actions or [expected_action],
            "next_task_title": next_task_title,
        },
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    same_task_cn = [
        ("cn_same_test", "完善 recent_events 只读规则", "那你现在测试一下"),
        ("cn_same_verify", "优化短期记忆分流", "再验证一遍刚刚这个规则"),
        ("cn_same_example", "解释任务边界判断", "给我举个具体例子"),
        ("cn_same_explain", "设计短期记忆生命周期", "详细解释一下这个流程"),
        ("cn_same_docs", "同步项目说明文档", "顺便把说明文档同步一下"),
        ("cn_same_fix", "修复 route 门禁误判", "把刚刚这个误判修一下"),
        ("cn_same_rerun", "远程 route 小样本测试", "再跑一批看看"),
        ("cn_same_continue", "任务边界专项测试", "继续完善这个测试集"),
    ]
    for name, title, event in same_task_cn:
        cases.append(
            _case(
                name=name,
                category="cn_same_task_substep",
                current_title=title,
                events=[event],
                expected_action="same_task",
                acceptable_actions=["same_task", "no_change"],
            )
        )

    same_task_en = [
        ("en_same_tests", "Improve recent_events readonly policy", "Please run the tests now."),
        ("en_same_verify", "Tune session route rules", "Verify that same rule again."),
        ("en_same_example", "Explain task boundary judgment", "Give me a concrete example."),
        ("en_same_docs", "Sync project documentation", "Update the docs for this change."),
        ("en_same_fix", "Fix route gate false positive", "Please fix this false positive."),
        ("en_same_continue", "Task boundary fixture design", "Continue expanding this fixture."),
    ]
    for name, title, event in same_task_en:
        cases.append(
            _case(
                name=name,
                category="en_same_task_substep",
                current_title=title,
                events=[event],
                expected_action="same_task",
                acceptable_actions=["same_task", "no_change"],
            )
        )

    switch_cn = [
        ("cn_switch_next", "完善 recent_events 只读规则", "这部分可以了，接下来做短期记忆生命周期管理。", "短期记忆生命周期管理"),
        ("cn_switch_enter", "远程 route 评估", "可以，现在进入任务边界专项测试。", "任务边界专项测试"),
        ("cn_switch_change", "写入门禁优化", "先别做门禁了，换成召回评估。", "召回评估"),
        ("cn_switch_next_step", "同步项目文档", "下一步做真实远程小样本测试。", "真实远程小样本测试"),
        ("cn_switch_after_done", "修复短期记忆注入", "这个先这样，我们转到任务状态机。", "任务状态机"),
        ("cn_switch_new_module", "任务边界测试", "接下来开始做短期记忆过期策略。", "短期记忆过期策略"),
    ]
    for name, title, event, next_title in switch_cn:
        cases.append(
            _case(
                name=name,
                category="cn_switch_task",
                current_title=title,
                events=[event],
                expected_action="switch_task",
                next_task_title=next_title,
                acceptable_actions=["switch_task", "new_task"],
            )
        )

    switch_en = [
        ("en_switch_next", "Improve recent_events readonly policy", "This part is done; next, work on session memory lifecycle.", "session memory lifecycle"),
        ("en_switch_move_on", "Remote route smoke test", "Move on to task boundary fixtures now.", "task boundary fixtures"),
        ("en_switch_change", "Write gate tuning", "Stop the gate work for now and switch to retrieval evaluation.", "retrieval evaluation"),
        ("en_switch_start", "Documentation sync", "Now start the remote smoke benchmark.", "remote smoke benchmark"),
        ("en_switch_after_done", "Session context injection", "That is enough; let's work on the task state machine.", "task state machine"),
        ("en_switch_new_module", "Task boundary testing", "Next, implement session expiration policy.", "session expiration policy"),
    ]
    for name, title, event, next_title in switch_en:
        cases.append(
            _case(
                name=name,
                category="en_switch_task",
                current_title=title,
                events=[event],
                expected_action="switch_task",
                next_task_title=next_title,
                acceptable_actions=["switch_task", "new_task"],
            )
        )

    done_cases = [
        ("cn_done_complete", "任务边界专项测试", "这部分完成了，先停在这里。"),
        ("cn_done_enough", "同步说明文档", "这个已经可以了，暂时不用继续。"),
        ("cn_done_stop", "远程评估复测", "这一步结束，别再扩展了。"),
        ("en_done_complete", "Task boundary fixtures", "This part is complete; stop here."),
        ("en_done_enough", "Documentation sync", "This is good enough for now."),
        ("en_done_stop", "Remote evaluation retest", "End this step and do not expand it further."),
    ]
    for name, title, event in done_cases:
        cases.append(
            _case(
                name=name,
                category="task_done",
                current_title=title,
                events=[event],
                expected_action="task_done",
            )
        )

    cancel_cases = [
        ("cn_cancel_drop", "短期记忆生命周期", "这个先不做了，取消这一步。"),
        ("cn_cancel_ignore", "远程批量 judge", "先别管这个并发优化了。"),
        ("cn_cancel_stop", "任务状态机实现", "停，不继续做任务状态机。"),
        ("en_cancel_drop", "Session memory lifecycle", "Cancel this step for now."),
        ("en_cancel_ignore", "Remote batch judge", "Do not work on this concurrency change anymore."),
        ("en_cancel_stop", "Task state machine", "Stop; we are not continuing the task state machine."),
    ]
    for name, title, event in cancel_cases:
        cases.append(
            _case(
                name=name,
                category="task_cancelled",
                current_title=title,
                events=[event],
                expected_action="task_cancelled",
            )
        )

    unclear_cases = [
        ("cn_unclear_ok", "任务边界专项测试", "可以"),
        ("cn_unclear_continue", "短期记忆生命周期", "继续"),
        ("cn_unclear_good", "远程评估复测", "好的"),
        ("en_unclear_ok", "Task boundary fixtures", "ok"),
        ("en_unclear_continue", "Session memory lifecycle", "continue"),
        ("en_unclear_sure", "Remote evaluation retest", "sure"),
    ]
    for name, title, event in unclear_cases:
        cases.append(
            _case(
                name=name,
                category="unclear_ack",
                current_title=title,
                events=[event],
                expected_action="unclear",
                acceptable_actions=["unclear", "same_task", "no_change"],
            )
        )

    accepted_next = [
        (
            "cn_accept_next",
            "短期记忆接入上下文",
            "可以，那就进入生命周期这一步。",
            [("assistant_message", "下一步建议做短期记忆生命周期管理。")],
            "短期记忆生命周期管理",
        ),
        (
            "en_accept_next",
            "Session context injection",
            "Yes, let's do that next.",
            [("assistant_message", "Next I suggest working on session memory lifecycle management.")],
            "session memory lifecycle management",
        ),
    ]
    for name, title, event, recent, next_title in accepted_next:
        cases.append(
            _case(
                name=name,
                category="accept_proposed_next_task",
                current_title=title,
                events=[event],
                recent_events=recent,
                expected_action="switch_task",
                next_task_title=next_title,
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
