from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "session_closeout.jsonl"
SCOPE = "repo:C:/workspace/session-closeout"


def _boundary(action: str, *, next_task_title: str | None = None) -> dict[str, Any]:
    previous_status = {
        "task_done": "done",
        "task_cancelled": "cancelled",
        "switch_task": "done",
        "new_task": "done",
    }.get(action, "active")
    return {
        "action": action,
        "confidence": "high",
        "current_task_id": "task_session_closeout",
        "current_task_title": "Session memory closeout",
        "next_task_title": next_task_title,
        "previous_task_status": previous_status,
        "reason": f"Fixture boundary for {action}.",
    }


def _event(content: str, *, event_type: str = "user_message") -> dict[str, Any]:
    return {
        "event_type": event_type,
        "content": content,
        "source": "conversation",
        "scope": SCOPE,
        "metadata": {},
    }


def _memory(
    alias: str,
    *,
    content: str,
    memory_type: str,
    subject: str,
    source_event_id: str,
    reason: str,
    expires_when: str = "task_end",
    scope: str = SCOPE,
) -> dict[str, Any]:
    return {
        "alias": alias,
        "content": content,
        "memory_type": memory_type,
        "scope": scope,
        "subject": subject,
        "source_event_ids": [source_event_id],
        "reason": reason,
        "metadata": {"expires_when": expires_when},
    }


def _expected_item(
    action: str,
    *,
    acceptable_actions: list[str] | None = None,
    candidate_memory_types: list[str] | None = None,
    forbid_promote: bool | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "action": action,
        "acceptable_actions": acceptable_actions or [action],
    }
    if candidate_memory_types is not None:
        item["candidate_memory_types"] = candidate_memory_types
    if forbid_promote is not None:
        item["forbid_promote"] = forbid_promote
    return item


def _case(
    *,
    category: str,
    index: int,
    task_boundary: dict[str, Any],
    current_task_state: dict[str, Any],
    recent_events: list[dict[str, Any]],
    session_memories: list[dict[str, Any]],
    expected_items: dict[str, dict[str, Any]],
    scenario: str,
    utterance_style: str,
    source_family: str = "manual_design",
) -> dict[str, Any]:
    return {
        "name": f"{category}_{index:03d}",
        "mode": "session_closeout",
        "category": category,
        "session_id": f"s_{category}_{index:03d}",
        "task_boundary": task_boundary,
        "current_task_state": current_task_state,
        "recent_events": recent_events,
        "session_memories": session_memories,
        "expected": {"items": expected_items},
        "scenario": scenario,
        "utterance_style": utterance_style,
        "source_family": source_family,
    }


def _done_state(title: str) -> dict[str, Any]:
    return {"task_id": "task_session_closeout", "title": title, "status": "done"}


def _active_state(title: str) -> dict[str, Any]:
    return {"task_id": "task_session_closeout", "title": title, "status": "active"}


def _snippet(text: str, *, limit: int = 28) -> str:
    return text if len(text) <= limit else f"{text[:limit]}..."


def _add_done_promote_project_fact(cases: list[dict[str, Any]], *, cn: bool) -> None:
    category = "cn_done_promote_project_fact" if cn else "en_done_promote_project_fact"
    rows = [
        ("pytest command", "发布检查固定使用 python -m pytest -q。")
        if cn
        else ("pytest command", "The project validation command is python -m pytest -q."),
        ("report path", "会话收尾报告固定写入 data/session_closeout_eval.json。")
        if cn
        else ("report path", "Session closeout reports are saved to data/session_closeout_eval.json."),
        ("fixture owner", "短期记忆收尾样本由 golden_cases 目录统一维护。")
        if cn
        else ("fixture owner", "Session closeout fixtures live under the golden_cases directory."),
        ("api endpoint", "会话收尾接口是 POST /session/closeout。")
        if cn
        else ("api endpoint", "The session closeout endpoint is POST /session/closeout."),
        ("storage rule", "dismissed 的短期记忆默认不会进入 session search。")
        if cn
        else ("storage rule", "Dismissed session memories are hidden from session search by default."),
        ("closeout action", "promote_candidate 会先变成长记忆候选，再交给本地门禁。")
        if cn
        else ("closeout action", "promote_candidate creates a long-term candidate for local policy gate."),
        ("scope rule", "短期记忆收尾样本使用 repo:C:/workspace/session-closeout scope。")
        if cn
        else ("scope rule", "Closeout fixtures use repo:C:/workspace/session-closeout scope."),
        ("summary rule", "summarize 动作会 dismiss 原始短期记忆。")
        if cn
        else ("summary rule", "The summarize action dismisses the original session memory."),
        ("remote route", "远程收尾模型使用 memory_system.session_closeout.v1 schema。")
        if cn
        else ("remote route", "The remote closeout model uses memory_system.session_closeout.v1."),
        ("safety rule", "敏感短期记忆在远程收尾前必须过滤。")
        if cn
        else ("safety rule", "Sensitive session memories must be filtered before remote closeout."),
    ]
    for index, (subject, content) in enumerate(rows):
        event_id = f"evt_{category}_{index:03d}"
        scratch_id = f"evt_{category}_{index:03d}_scratch"
        cases.append(
            _case(
                category=category,
                index=index,
                task_boundary=_boundary("task_done"),
                current_task_state=_done_state("Verify session closeout"),
                recent_events=[_event(content, event_type="tool_result")],
                session_memories=[
                    _memory(
                        "target",
                        content=content,
                        memory_type="working_fact",
                        subject=subject,
                        source_event_id=event_id,
                        reason="Verified during the completed task.",
                    ),
                    _memory(
                        "scratch",
                        content=(
                            f"临时草稿：围绕“{subject}”的最终回复占位，收尾后不再需要。"
                            if cn
                            else (
                                f"Temporary scratch note for {subject}; discard after final reply."
                            )
                        ),
                        memory_type="scratch_note",
                        subject="temporary scratch note",
                        source_event_id=scratch_id,
                        reason="Only useful while composing the current answer.",
                    ),
                ],
                expected_items={
                    "target": _expected_item(
                        "promote_candidate",
                        candidate_memory_types=["project_fact", "workflow", "tool_rule"],
                    ),
                    "scratch": _expected_item("discard", forbid_promote=True),
                },
                scenario="completed_task_verified_fact",
                utterance_style="cn_verified_fact" if cn else "en_verified_fact",
            )
        )


def _add_done_promote_workflow(cases: list[dict[str, Any]], *, cn: bool) -> None:
    category = "cn_done_promote_workflow" if cn else "en_done_promote_workflow"
    workflows = [
        "发布前先跑 ruff，再跑 pytest，最后做关键路径冒烟。"
        if cn
        else "Before release, run ruff, then pytest, then a key-path smoke check.",
        "修改远程模型配置后，先 health，再跑 12 条 smoke，再扩大样本。"
        if cn
        else "After changing remote model config, run health, then 12 smoke cases, then scale.",
        "扩充 golden 数据时，先改生成脚本，再重生 JSONL，最后跑 audit。"
        if cn
        else "When expanding golden data, update the generator, regenerate JSONL, then run audit.",
        "召回评估固定用 case_concurrency=4 作为第一轮速度基线。"
        if cn
        else "Retrieval evaluation uses case_concurrency=4 as the first speed baseline.",
        "写入门禁调参先看 FN，再看敏感误写，最后看低价值噪声。"
        if cn
        else "For write-gate tuning, review FN, then sensitive writes, then low-value noise.",
        "短期记忆先判断任务边界，再做 closeout，不直接清空。"
        if cn
        else "For session memory, judge task boundary before closeout instead of clearing all.",
        "远程评估保存 report-path，避免只看终端摘要。"
        if cn
        else "Remote evaluation saves report-path instead of relying only on terminal summaries.",
        "真实远程测试先小样本分层抽样，再考虑全量。"
        if cn
        else "Real remote tests start with stratified small samples before full runs.",
        "文档同步先做漂移审查，再改具体过时段落。"
        if cn
        else "Documentation sync starts with drift audit before patching stale sections.",
        "敏感样本只用占位符，不写入真实访问凭据。"
        if cn
        else "Sensitive samples use placeholders and never include real credentials.",
    ]
    for index, content in enumerate(workflows):
        cases.append(
            _case(
                category=category,
                index=index,
                task_boundary=_boundary("task_done"),
                current_task_state=_done_state("Document reusable workflow"),
                recent_events=[_event(content)],
                session_memories=[
                    _memory(
                        "workflow",
                        content=content,
                        memory_type="working_fact",
                        subject="reusable closeout workflow",
                        source_event_id=f"evt_{category}_{index:03d}",
                        reason="The completed task confirmed a reusable procedure.",
                    ),
                    _memory(
                        "emotion",
                        content=(
                            f"刚才梳理“{_snippet(content)}”时有点乱，现在已经理顺了。"
                            if cn
                            else f"I was confused by {_snippet(content)} earlier, but it is clear now."
                        ),
                        memory_type="emotional_state",
                        subject="resolved confusion",
                        source_event_id=f"evt_{category}_{index:03d}_emotion",
                        reason="Emotional context is no longer needed after closeout.",
                    ),
                ],
                expected_items={
                    "workflow": _expected_item(
                        "promote_candidate",
                        candidate_memory_types=["workflow", "project_fact"],
                    ),
                    "emotion": _expected_item("discard", forbid_promote=True),
                },
                scenario="completed_task_reusable_workflow",
                utterance_style="cn_workflow" if cn else "en_workflow",
            )
        )


def _add_done_discard_temporary(cases: list[dict[str, Any]], *, cn: bool) -> None:
    category = "cn_done_discard_temporary" if cn else "en_done_discard_temporary"
    temporary_rules = [
        "这次先不要提交代码，等我看完 diff。",
        "本轮只跑 session closeout 的两个测试文件。",
        "当前例子里先不要调用真实远程模型。",
        "今天先用中文解释，不需要写英文说明。",
        "这次先别动 README，只改 fixture。",
        "本轮先不扩大到 500 条样本。",
        "当前任务先不要写入 Memory MCP。",
        "这次先跳过全量 pytest。",
        "本轮先不要做 GitHub 推送。",
        "当前例子只看 closeout，不讨论召回。",
    ] if cn else [
        "For this task, do not commit code until I review the diff.",
        "For this run, execute only the two session closeout tests.",
        "Current example should not call the real remote model yet.",
        "Today only, explain in Chinese and skip the English note.",
        "This time, do not touch README; only change the fixture.",
        "For this round, do not scale the sample set to 500 cases.",
        "Current task should not write new Memory MCP entries.",
        "For this run, skip the full pytest suite.",
        "This round should not push anything to GitHub.",
        "Current example only covers closeout, not retrieval.",
    ]
    for index, content in enumerate(temporary_rules):
        cases.append(
            _case(
                category=category,
                index=index,
                task_boundary=_boundary("task_done"),
                current_task_state=_done_state("Finish temporary constraint"),
                recent_events=[_event("Task completed; temporary constraint no longer applies.")],
                session_memories=[
                    _memory(
                        "temporary_rule",
                        content=content,
                        memory_type="temporary_rule",
                        subject="current task constraint",
                        source_event_id=f"evt_{category}_{index:03d}",
                        reason="Scoped to the just-finished task.",
                    ),
                    _memory(
                        "task_state",
                        content=(
                            f"当前任务已完成，临时限制“{_snippet(content)}”可以进入收尾。"
                            if cn
                            else (
                                f"The task for {_snippet(content)} is complete and ready for closeout."
                            )
                        ),
                        memory_type="task_state",
                        subject="completed task state",
                        source_event_id=f"evt_{category}_{index:03d}_state",
                        reason="Useful only as a short task recap.",
                    ),
                ],
                expected_items={
                    "temporary_rule": _expected_item("discard", forbid_promote=True),
                    "task_state": _expected_item(
                        "summarize",
                        acceptable_actions=["summarize", "discard"],
                        forbid_promote=True,
                    ),
                },
                scenario="completed_task_temporary_rule",
                utterance_style="cn_temporary_rule" if cn else "en_temporary_rule",
            )
        )


def _add_done_summarize_state(cases: list[dict[str, Any]], *, cn: bool) -> None:
    category = "cn_done_summarize_state" if cn else "en_done_summarize_state"
    states = [
        "已经完成短期记忆路线说明，剩下只需要在最终回答里总结。",
        "刚跑完 50 条小样本，主要结论是分类大体可用但细分类型还需观察。",
        "文档已同步到第一层 README，最终回复只需要说明改了什么。",
        "远程 smoke 已跑完，报告路径在 data/session_closeout_smoke.json。",
        "用户已经决定暂时不做本地硬规则，只保留 LLM closeout。",
        "我们已确认任务边界用于辅助 closeout，而不是直接删除短期记忆。",
        "测试集结构已经固定，下一步只需看远程准确率。",
        "API 接口已接上 apply 参数，需要在最终回答提醒默认行为。",
        "当前设计倾向轻本地规则，远程负责整体判断。",
        "短期记忆生命周期已经闭环，最终回答要交代下一步是评估。",
    ] if cn else [
        "Session route explanation is complete; only final summary is still needed.",
        "The 50-case smoke run is done; categories are mostly right but types need review.",
        "Docs were synced to top-level README; final answer only needs a change summary.",
        "Remote smoke finished and the report path is data/session_closeout_smoke.json.",
        "The user decided to avoid hard local rules and keep LLM closeout.",
        "Task boundary is confirmed as closeout context, not a direct delete signal.",
        "The fixture shape is fixed; next step is checking remote accuracy.",
        "The API endpoint is wired with apply; final answer should mention the default.",
        "The design favors light local rules while remote judges the full context.",
        "Session memory lifecycle is closed; final answer should propose evaluation.",
    ]
    for index, content in enumerate(states):
        cases.append(
            _case(
                category=category,
                index=index,
                task_boundary=_boundary("task_done"),
                current_task_state=_done_state("Summarize completed task"),
                recent_events=[_event(content)],
                session_memories=[
                    _memory(
                        "state",
                        content=content,
                        memory_type="task_state",
                        subject="completed task recap",
                        source_event_id=f"evt_{category}_{index:03d}",
                        reason="Useful for final recap, not long-term memory.",
                    ),
                    _memory(
                        "scratch",
                        content=(
                            f"临时备注：围绕“{_snippet(content)}”的最终回复控制在三段以内。"
                            if cn
                            else (
                                f"Scratch note for {_snippet(content)}: keep the final answer concise."
                            )
                        ),
                        memory_type="scratch_note",
                        subject="final response note",
                        source_event_id=f"evt_{category}_{index:03d}_scratch",
                        reason="Only useful while composing the response.",
                    ),
                ],
                expected_items={
                    "state": _expected_item(
                        "summarize",
                        acceptable_actions=["summarize", "discard"],
                        forbid_promote=True,
                    ),
                    "scratch": _expected_item("discard", forbid_promote=True),
                },
                scenario="completed_task_recap",
                utterance_style="cn_task_state" if cn else "en_task_state",
            )
        )


def _add_keep_pending(cases: list[dict[str, Any]], *, cn: bool) -> None:
    category = "cn_keep_pending_decision" if cn else "en_keep_pending_decision"
    decisions = [
        "还没决定 session closeout 是先全量跑还是先分层抽样。",
        "等用户确认是否把 summarize 的内容写进任务报告。",
        "还需要确认 promoted candidate 是否自动进入本地 gate。",
        "用户尚未决定是否保留 closeout 的 apply=false 默认值。",
        "等确认后再决定是否把情绪状态纳入短期召回。",
        "还没确认 task_done 时 pending_decision 是否继续保留。",
        "需要用户选择是否扩大到 500 条 closeout 样本。",
        "等用户确认是否把远程失败视为 keep。",
        "还没决定 sensitive filtered 项显示 missing 还是 discard。",
        "等待确认 closeout 报告是否按 category 输出。",
    ] if cn else [
        "Need confirmation whether closeout should run full or stratified samples first.",
        "Waiting for the user to confirm whether summarize text enters the task report.",
        "Need confirmation before promoted candidates automatically enter local gate.",
        "The user has not decided whether apply=false should remain the default.",
        "Waiting to confirm whether emotional state joins session recall.",
        "Need confirmation whether pending_decision stays active after task_done.",
        "The user needs to choose whether to expand closeout samples to 500.",
        "Waiting to confirm whether remote failures should be treated as keep.",
        "Need to decide whether sensitive filtered items show missing or discard.",
        "Waiting for confirmation on category-level closeout reporting.",
    ]
    for index, content in enumerate(decisions):
        cases.append(
            _case(
                category=category,
                index=index,
                task_boundary=_boundary("same_task"),
                current_task_state=_active_state("Wait for user decision"),
                recent_events=[_event(content)],
                session_memories=[
                    _memory(
                        "pending",
                        content=content,
                        memory_type="pending_decision",
                        subject="open closeout decision",
                        source_event_id=f"evt_{category}_{index:03d}",
                        reason="Decision is still unresolved and should guide next turn.",
                        expires_when="task_resolution",
                    ),
                    _memory(
                        "scratch",
                        content=(
                            f"临时草稿：等待用户确认“{_snippet(content)}”后再继续。"
                            if cn
                            else (
                                f"Temporary scratch for {_snippet(content)}; continue after user reply."
                            )
                        ),
                        memory_type="scratch_note",
                        subject="waiting scratch note",
                        source_event_id=f"evt_{category}_{index:03d}_scratch",
                        reason="Low-value scratch note.",
                    ),
                ],
                expected_items={
                    "pending": _expected_item("keep"),
                    "scratch": _expected_item(
                        "discard",
                        acceptable_actions=["discard", "keep"],
                        forbid_promote=True,
                    ),
                },
                scenario="unresolved_decision",
                utterance_style="cn_pending_decision" if cn else "en_pending_decision",
            )
        )


def _add_cancel_discard(cases: list[dict[str, Any]], *, cn: bool) -> None:
    category = "cn_cancel_discard" if cn else "en_cancel_discard"
    notes = [
        "取消这个方向，不继续写旧版 closeout prompt。",
        "先别管刚才的统计表，用户已经放弃那条路线。",
        "停止生成这份临时报告，后续不再使用。",
        "取消远程 batch=8 的尝试，因为速度不可接受。",
        "放弃把短期记忆全部强制注入上下文的想法。",
        "取消手工枚举任务关键词的实现方向。",
        "停止跟进旧的 retrieval_context 语义判断。",
        "取消把所有非长期信息都保存为 session 的方案。",
        "放弃单纯编号扩充样本的做法。",
        "停止当前实验，不继续保存临时结论。",
    ] if cn else [
        "Cancel this direction and do not continue the old closeout prompt.",
        "Ignore the previous stats table because the user abandoned that path.",
        "Stop generating this temporary report; it will not be used later.",
        "Cancel the remote batch=8 attempt because latency is unacceptable.",
        "Abandon forcing every session memory into context.",
        "Cancel the implementation based on enumerated task keywords.",
        "Stop following the old retrieval_context semantic judgment path.",
        "Cancel the plan to store every non-long-term item as session memory.",
        "Abandon expanding samples by changing only numeric identifiers.",
        "Stop the current experiment and do not preserve temporary conclusions.",
    ]
    for index, content in enumerate(notes):
        cases.append(
            _case(
                category=category,
                index=index,
                task_boundary=_boundary("task_cancelled"),
                current_task_state={"task_id": "task_session_closeout", "title": "Cancelled task", "status": "cancelled"},
                recent_events=[_event("The user cancelled this direction.")],
                session_memories=[
                    _memory(
                        "cancelled_state",
                        content=content,
                        memory_type="task_state",
                        subject="cancelled task state",
                        source_event_id=f"evt_{category}_{index:03d}",
                        reason="The task was cancelled.",
                    ),
                    _memory(
                        "temporary_rule",
                        content=(
                            f"取消前的临时限制：围绕“{_snippet(content)}”这轮不要扩大范围。"
                            if cn
                            else (
                                f"Temporary rule before cancelling {_snippet(content)}: do not expand."
                            )
                        ),
                        memory_type="temporary_rule",
                        subject="cancelled temporary rule",
                        source_event_id=f"evt_{category}_{index:03d}_rule",
                        reason="Rule died with the cancelled task.",
                    ),
                ],
                expected_items={
                    "cancelled_state": _expected_item("discard", forbid_promote=True),
                    "temporary_rule": _expected_item("discard", forbid_promote=True),
                },
                scenario="cancelled_task",
                utterance_style="cn_cancelled" if cn else "en_cancelled",
            )
        )


def _add_switch_task(cases: list[dict[str, Any]], *, cn: bool) -> None:
    category = "cn_switch_task_mixed" if cn else "en_switch_task_mixed"
    reusable = [
        "session closeout 评估脚本需要按 action 和 strict 分开统计。",
        "closeout 中的 promote_candidate 必须带 MemoryCandidateCreate。",
        "missing 决策在敏感过滤场景中是允许结果。",
        "短期记忆 search 默认只返回 active 状态。",
        "会话结束时 temporary_rule 通常应 discard。",
        "pending_decision 在 same_task 边界下应 keep。",
        "任务切换时可复用的已验证事实应考虑 promote。",
        "敏感内容被过滤后不应传给远程模型。",
        "closeout 的 report 需要保存 failures 便于回看。",
        "多条 session memory 应由同一次 closeout 统一判断。",
    ] if cn else [
        "Session closeout evaluation should report action and strict metrics separately.",
        "closeout promote_candidate must include a MemoryCandidateCreate object.",
        "A missing decision is acceptable for sensitive filtered items.",
        "Session memory search returns only active items by default.",
        "temporary_rule usually becomes discard at session closeout.",
        "pending_decision should stay keep under a same_task boundary.",
        "Reusable verified facts should be considered for promote on task switch.",
        "Sensitive content must be filtered before reaching the remote model.",
        "Closeout reports should save failures for later review.",
        "Multiple session memories should be judged in one closeout call.",
    ]
    for index, content in enumerate(reusable):
        cases.append(
            _case(
                category=category,
                index=index,
                task_boundary=_boundary("switch_task", next_task_title="Retrieval quality audit"),
                current_task_state=_done_state("Switch from closeout to retrieval"),
                recent_events=[_event("Next, switch to retrieval quality audit.")],
                session_memories=[
                    _memory(
                        "reusable_fact",
                        content=content,
                        memory_type="working_fact",
                        subject="reusable closeout fact",
                        source_event_id=f"evt_{category}_{index:03d}",
                        reason="Verified fact remains useful after the task switch.",
                    ),
                    _memory(
                        "old_task_state",
                        content=(
                            f"旧任务“{_snippet(content)}”已结束，下一步改做召回质量检查。"
                            if cn
                            else (
                                f"The old task around {_snippet(content)} is done; next is retrieval audit."
                            )
                        ),
                        memory_type="task_state",
                        subject="old task transition",
                        source_event_id=f"evt_{category}_{index:03d}_state",
                        reason="Only useful as a transition recap.",
                    ),
                ],
                expected_items={
                    "reusable_fact": _expected_item(
                        "promote_candidate",
                        candidate_memory_types=["project_fact", "workflow", "decision"],
                    ),
                    "old_task_state": _expected_item(
                        "summarize",
                        acceptable_actions=["summarize", "discard"],
                        forbid_promote=True,
                    ),
                },
                scenario="task_switch_with_reusable_fact",
                utterance_style="cn_switch" if cn else "en_switch",
            )
        )


def _add_sensitive_filtered(cases: list[dict[str, Any]], *, cn: bool) -> None:
    category = "cn_sensitive_filtered" if cn else "en_sensitive_filtered"
    safe_notes = [
        "敏感项已被占位符替换，真实密钥没有进入 fixture。",
        "远程 closeout 只应看到安全的会话记忆。",
        "包含访问凭据的短期记忆不应发给远程模型。",
        "真实访问密钥不允许出现在 golden case。",
        "敏感短期记忆即使当前任务完成，也不能升级为长期记忆。",
        "过滤后的密钥项可以在评估里表现为 missing。",
        "敏感过滤 warning 应该保留在 closeout 报告中。",
        "安全说明可以升级，真实凭据不能升级。",
        "候选长期记忆不能包含访问凭据文本。",
        "敏感预检应发生在远程模型调用之前。",
    ] if cn else [
        "The credential placeholder was removed before remote closeout.",
        "Remote closeout should only see safe session memories.",
        "The evaluator should forbid promotion of filtered credentials.",
        "Sensitive preflight should report a warning instead of model content.",
        "The closeout path should keep credentials out of MemoryCandidateCreate.",
        "A filtered credential may appear as missing in the closeout evaluation.",
        "Safe filtering notes may promote, but credentials must not.",
        "Long-term candidates must not contain credential text.",
        "Sensitive preflight should happen before the remote model call.",
        "The report should preserve warnings for filtered session memories.",
    ]
    for index, safe_note in enumerate(safe_notes):
        secret = (
            f"请临时使用 [REDACTED] token 处理“{_snippet(safe_note)}”，任务结束后不要保留。"
            if cn
            else (
                f"Temporarily use the [REDACTED] token for {_snippet(safe_note)}; do not keep it."
            )
        )
        cases.append(
            _case(
                category=category,
                index=index,
                task_boundary=_boundary("task_done"),
                current_task_state=_done_state("Filter sensitive closeout"),
                recent_events=[_event(safe_note)],
                session_memories=[
                    _memory(
                        "secret",
                        content=secret,
                        memory_type="temporary_rule",
                        subject="redacted secret",
                        source_event_id=f"evt_{category}_{index:03d}_secret",
                        reason="Sensitive placeholder should be filtered.",
                    ),
                    _memory(
                        "safe_note",
                        content=safe_note,
                        memory_type="working_fact",
                        subject="safe filtering note",
                        source_event_id=f"evt_{category}_{index:03d}_safe",
                        reason="Safe note about filtering behavior.",
                    ),
                ],
                expected_items={
                    "secret": _expected_item(
                        "missing",
                        acceptable_actions=["missing", "keep", "discard"],
                        forbid_promote=True,
                    ),
                    "safe_note": _expected_item(
                        "promote_candidate",
                        acceptable_actions=["promote_candidate", "discard", "summarize", "keep"],
                        candidate_memory_types=["project_fact", "workflow"],
                    ),
                },
                scenario="sensitive_preflight",
                utterance_style="cn_sensitive" if cn else "en_sensitive",
            )
        )


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for language_is_cn in (True, False):
        _add_done_promote_project_fact(cases, cn=language_is_cn)
        _add_done_promote_workflow(cases, cn=language_is_cn)
        _add_done_discard_temporary(cases, cn=language_is_cn)
        _add_done_summarize_state(cases, cn=language_is_cn)
        _add_keep_pending(cases, cn=language_is_cn)
        _add_cancel_discard(cases, cn=language_is_cn)
        _add_switch_task(cases, cn=language_is_cn)
        _add_sensitive_filtered(cases, cn=language_is_cn)
    return cases


def main() -> None:
    cases = build_cases()
    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases)
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(cases)} cases to {OUTPUT}")


if __name__ == "__main__":
    main()
