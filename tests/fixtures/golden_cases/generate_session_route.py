from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "session_route.jsonl"
SCOPE = "repo:C:/workspace/session-route"


def _event(content: str, *, event_type: str = "user_message", source: str = "conversation") -> dict[str, Any]:
    return {
        "event_type": event_type,
        "content": content,
        "source": source,
        "scope": SCOPE,
        "metadata": {},
    }


def _case(
    *,
    category: str,
    index: int,
    content: str,
    route: str,
    scenario: str,
    utterance_style: str,
    source_family: str,
    session_memory_type: str | None = None,
    memory_type: str | None = None,
    event_type: str = "user_message",
    source: str = "conversation",
    context_role: str = "excluded",
    local_fallback_supported: bool = False,
    remote_preflight_reject: bool = False,
) -> dict[str, Any]:
    expected: dict[str, Any] = {
        "route": route,
        "context_role": context_role,
        "should_store_session": route == "session",
        "should_create_long_term_candidate": route == "long_term",
        "local_fallback_supported": local_fallback_supported,
        "remote_preflight_reject": remote_preflight_reject,
    }
    if session_memory_type is not None:
        expected["session_memory_type"] = session_memory_type
    if memory_type is not None:
        expected["memory_type"] = memory_type
    return {
        "name": f"{category}_{index:03d}",
        "mode": "session_route",
        "category": category,
        "event": _event(content, event_type=event_type, source=source),
        "expected": expected,
        "scenario": scenario,
        "utterance_style": utterance_style,
        "source_family": source_family,
    }


def _add_many(
    cases: list[dict[str, Any]],
    *,
    category: str,
    contents: list[str],
    route: str,
    scenario: str,
    utterance_style: str,
    source_family: str,
    session_memory_type: str | None = None,
    memory_type: str | None = None,
    event_type: str = "user_message",
    source: str = "conversation",
    context_role: str = "excluded",
    local_fallback_supported: bool = False,
    remote_preflight_reject: bool = False,
) -> None:
    for index, content in enumerate(contents):
        cases.append(
            _case(
                category=category,
                index=index,
                content=content,
                route=route,
                scenario=scenario,
                utterance_style=utterance_style,
                source_family=source_family,
                session_memory_type=session_memory_type,
                memory_type=memory_type,
                event_type=event_type,
                source=source,
                context_role=context_role,
                local_fallback_supported=local_fallback_supported,
                remote_preflight_reject=remote_preflight_reject,
            )
        )


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    _add_many(
        cases,
        category="cn_session_temporary_rule",
        route="session",
        session_memory_type="temporary_rule",
        context_role="critical",
        local_fallback_supported=True,
        scenario="current_task_constraint",
        utterance_style="explicit_temporary_rule_cn",
        source_family="manual_design",
        contents=[
            "这次先不要提交代码，只把变更点和风险说清楚。",
            "当前任务先不提交，等我看完测试结果再决定。",
            "本轮不要扩大范围，只处理短期记忆测试集。",
            "今天先不要写入数据库，先保留在会话里验证。",
            "当前例子不要扩大到业务逻辑修改，只解释判断过程。",
            "这次先不要扩大到全量测试，只跑短期记忆相关测试。",
            "本轮先不提交 PR，先把 fixture 质量检查完。",
            "当前任务不要扩大到自动归档旧记忆，先列出候选。",
            "今天先不要提交远程推送，只在本地看测试结果。",
            "这次不要扩大到长期记忆优化，专注短期分流。",
        ],
    )
    _add_many(
        cases,
        category="en_session_temporary_rule",
        route="session",
        session_memory_type="temporary_rule",
        context_role="critical",
        local_fallback_supported=True,
        scenario="current_task_constraint",
        utterance_style="explicit_temporary_rule_en",
        source_family="manual_design",
        contents=[
            "For this task, do not commit anything; just explain the changes.",
            "For now, don't commit or push the branch until I review the test output.",
            "This task only: do not expand the dataset beyond session routing.",
            "Today only, do not write session memory into SQLite yet.",
            "Current example: do not expand into business logic, just show the route.",
            "For this task, skip the full suite and run only session-memory tests.",
            "Just for now, don't commit a pull request after generating fixtures.",
            "This time only, do not expand into archiving old memories automatically.",
            "For now, don't write new Memory MCP entries from this experiment.",
            "Current example: do not expand into long-term retrieval tuning.",
        ],
    )

    _add_many(
        cases,
        category="cn_session_task_state",
        route="session",
        session_memory_type="task_state",
        context_role="critical",
        local_fallback_supported=True,
        scenario="current_task_state",
        utterance_style="task_progress_cn",
        source_family="manual_design",
        contents=[
            "当前任务是在设计短期记忆如何参与回答上下文。",
            "本轮我们正在先确认 session route 的测试边界。",
            "这次讨论的目标是让短期记忆不要污染长期库。",
            "当前任务先围绕 temporary_rule 和 pending_decision 做验证。",
            "本轮重点是判断短期记忆是否需要召回排序。",
            "这次先把 session memory 的分类标准讲清楚。",
            "当前例子正在比较短期强制注入和长期语义召回。",
            "本轮任务是生成可复用的短期记忆 fixture。",
            "当前任务先检查中文场景是否覆盖足够多。",
            "这次讨论还停留在设计阶段，暂时不接生产接口。",
        ],
    )
    _add_many(
        cases,
        category="en_session_task_state",
        route="session",
        session_memory_type="task_state",
        context_role="critical",
        local_fallback_supported=True,
        scenario="current_task_state",
        utterance_style="task_progress_en",
        source_family="manual_design",
        contents=[
            "For this task, we are designing how session memory enters context.",
            "This task only covers the route boundary for short-term memory.",
            "For now, the goal is to keep session facts out of long-term storage.",
            "Current example focuses on temporary rules and pending decisions.",
            "For this task, we are comparing forced session injection with recall.",
            "This time only, we are drafting the fixture before tuning prompts.",
            "For now, we are checking whether emotional state should be session memory.",
            "Current example is about session-memory categories, not vector search.",
            "For this task, the dataset shape matters more than model speed.",
            "This task only needs a stable fixture before remote evaluation.",
        ],
    )

    _add_many(
        cases,
        category="cn_session_working_fact",
        route="session",
        session_memory_type="working_fact",
        context_role="relevant",
        local_fallback_supported=True,
        event_type="test_result",
        source="pytest",
        scenario="fresh_tool_or_test_result",
        utterance_style="verified_current_result_cn",
        source_family="manual_design",
        contents=[
            "刚才运行 tests/test_session_memory.py，结果是全部通过。",
            "已经跑完短期记忆形状检查，通过了本地断言。",
            "工具结果是 session_route.jsonl 成功生成。",
            "测试结果显示本地 fallback 对 temporary_rule 通过。",
            "刚才运行 ruff 检查，结果是没有格式错误。",
            "已经跑完 fixture 唯一性检查，没有重复 case name。",
            "工具结果是敏感样本没有真实密钥，只有占位符。",
            "测试结果是 pending_decision 的确认线索已通过识别。",
            "刚才运行 JSONL 读取检查，所有行都能解析。",
            "已经跑完 session route 覆盖统计，结果是类别数量符合预期。",
        ],
    )
    _add_many(
        cases,
        category="en_session_working_fact",
        route="session",
        session_memory_type="working_fact",
        context_role="relevant",
        local_fallback_supported=True,
        event_type="test_result",
        source="pytest",
        scenario="fresh_tool_or_test_result",
        utterance_style="verified_current_result_en",
        source_family="manual_design",
        contents=[
            "Just ran tests/test_session_memory.py; the result passed locally.",
            "The JSONL validation result is passed for the session route fixture.",
            "Tool result: session_route.jsonl was generated successfully.",
            "The temporary_rule fallback check passed in the current run.",
            "Just ran ruff on the session files; the result passed.",
            "The fixture uniqueness check passed without duplicate case names.",
            "Tool result: sensitive examples use placeholders, not real private values.",
            "The pending_decision cue check passed for the current fixture.",
            "Just ran the JSONL parser; every line loaded successfully.",
            "The category coverage result passed for this session route batch.",
        ],
    )

    _add_many(
        cases,
        category="cn_session_pending_decision",
        route="session",
        session_memory_type="pending_decision",
        context_role="critical",
        local_fallback_supported=True,
        scenario="pending_choice_tracking",
        utterance_style="pending_decision_cn",
        source_family="manual_design",
        contents=[
            "待确认事项：短期记忆要不要写入 SQLite？",
            "待确认事项：session 召回是先做关键词还是直接注入？",
            "待确认事项：legacy import 入口是删除还是只标记 deprecated？",
            "待确认事项：短期情绪状态要不要强制注入？",
            "待确认事项：当前任务是保留内存态还是落盘？",
            "待确认事项：working_fact 是否需要过期时间？",
            "待确认事项：短期记忆是否需要 embedding？",
            "待确认事项：这批 fixture 是否扩到五百条？",
            "待确认事项：session memory 是否跨页面恢复？",
            "待确认事项：先只测中文样本还是中英文一起测？",
        ],
    )
    _add_many(
        cases,
        category="en_session_pending_decision",
        route="session",
        session_memory_type="pending_decision",
        context_role="critical",
        local_fallback_supported=True,
        scenario="pending_choice_tracking",
        utterance_style="pending_decision_en",
        source_family="manual_design",
        contents=[
            "Pending confirmation: should session memory be persisted to SQLite or kept in process?",
            "Pending confirmation: should we inject temporary rules before long-term memories?",
            "Pending confirmation: should legacy import be deleted or only marked deprecated?",
            "Pending confirmation: should emotional state be forced into context or ranked normally?",
            "Pending confirmation: should working facts expire at task end or session end?",
            "Pending confirmation: should session memory use embeddings or simple scoring?",
            "Pending confirmation: should this fixture grow to five hundred cases or stay small?",
            "Pending confirmation: should session memory survive page refreshes or only one runtime?",
            "Pending confirmation: should the first evaluation use Chinese only or bilingual cases?",
            "Pending confirmation: should scratch notes be injected by default or only when relevant?",
        ],
    )

    _add_many(
        cases,
        category="cn_session_emotional_state",
        route="session",
        session_memory_type="emotional_state",
        context_role="critical",
        scenario="current_user_state",
        utterance_style="emotional_or_comprehension_cn",
        source_family="manual_design",
        contents=[
            "我现在有点乱，先用最简单的图解方式说。",
            "这个链路我还不太理解，你先慢一点讲。",
            "我有点担心短期记忆会污染长期库，先解释边界。",
            "我现在注意力不太集中，回答尽量短一点。",
            "我对 route 和 recall 的区别还是迷糊，先别跳步骤。",
            "我有点焦虑测试集不够准，先帮我确认覆盖面。",
            "这块我还没想明白，先用一个真实例子讲。",
            "我现在脑子有点乱，先不要堆术语。",
            "我担心模型会乱记情绪，先说安全策略。",
            "我有点不确定这个方案，先给我稳定结论。",
        ],
    )
    _add_many(
        cases,
        category="en_session_emotional_state",
        route="session",
        session_memory_type="emotional_state",
        context_role="critical",
        scenario="current_user_state",
        utterance_style="emotional_or_comprehension_en",
        source_family="manual_design",
        contents=[
            "I'm a bit confused right now, so explain the route slowly.",
            "I don't fully understand the memory flow yet; use a concrete example.",
            "I'm worried short-term memory might pollute long-term memory; clarify the boundary.",
            "I'm losing focus, so keep the next answer compact.",
            "I'm still mixing up route and recall; don't skip steps.",
            "I'm anxious that the fixture may be too narrow; check the coverage first.",
            "This part is not clear to me yet; walk through one real case.",
            "I'm a little overwhelmed, so avoid piling up terminology.",
            "I'm worried the model may store emotions incorrectly; explain the safety rule.",
            "I'm unsure about the plan; give me the stable conclusion first.",
        ],
    )

    _add_many(
        cases,
        category="cn_session_scratch_note",
        route="session",
        session_memory_type="scratch_note",
        context_role="relevant",
        scenario="temporary_reference_note",
        utterance_style="scratch_note_cn",
        source_family="manual_design",
        contents=[
            "先把“短期便签”这个比喻留着，后面解释时可能用。",
            "刚刚那个三层并发的例子可以暂时当作类比。",
            "把 session_route 这个名字先记在当前讨论里。",
            "这个小节先叫“当前回答不断片”，后面可能改标题。",
            "把强制注入和按需召回先作为两个临时小标题。",
            "先把“不是长期垃圾桶”这句话留作提醒。",
            "刚才提到的上下文顺序可以作为临时草稿。",
            "把短期记忆测试先按中英文各半来想。",
            "先记一下：scratch_note 不应该默认强制注入。",
            "把这个例子暂时归到 session route，不进入长期库。",
        ],
    )
    _add_many(
        cases,
        category="en_session_scratch_note",
        route="session",
        session_memory_type="scratch_note",
        context_role="relevant",
        scenario="temporary_reference_note",
        utterance_style="scratch_note_en",
        source_family="manual_design",
        contents=[
            "Keep the phrase 'session sticky note' as a temporary explanation handle.",
            "Use the earlier concurrency example as a temporary analogy for routing.",
            "Keep the name session_route in the current discussion for now.",
            "Call this section 'avoid losing the current thread' for the draft.",
            "Keep forced injection and on-demand recall as temporary subsection names.",
            "Remember the temporary warning: session is not a long-term trash bin.",
            "Use the previous context-order sketch as a temporary draft.",
            "Keep the first fixture bilingual for the current planning pass.",
            "Note for now that scratch_note should not be force-injected by default.",
            "Treat this example as a session route note, not long-term memory.",
        ],
    )

    _add_many(
        cases,
        category="cn_ignore_low_info",
        route="ignore",
        scenario="low_information_reply",
        utterance_style="acknowledgement_cn",
        source_family="manual_design",
        contents=[
            "可以。",
            "好的。",
            "嗯嗯。",
            "继续。",
            "明白。",
            "先这样。",
            "行。",
            "收到。",
            "OK。",
            "没问题。",
        ],
    )
    _add_many(
        cases,
        category="en_ignore_low_info",
        route="ignore",
        scenario="low_information_reply",
        utterance_style="acknowledgement_en",
        source_family="manual_design",
        contents=[
            "Ok.",
            "Sounds good.",
            "Got it.",
            "Continue.",
            "Sure.",
            "That works.",
            "Understood.",
            "Fine by me.",
            "Proceed.",
            "No problem.",
        ],
    )
    _add_many(
        cases,
        category="cn_ignore_casual_social",
        route="ignore",
        scenario="casual_social_chatter",
        utterance_style="low_value_chat_cn",
        source_family="manual_design",
        contents=[
            "哈哈这个说法还挺有意思。",
            "今天咖啡有点苦，不过问题不大。",
            "这个名字听起来有点像临时小工具。",
            "刚刚那句话有点绕，算了继续。",
            "我笑了一下，先不用管这个。",
            "这段对话有点长，但还行。",
            "这个例子有点好玩，不用记。",
            "我随口吐槽一下，继续正题。",
            "这句话只是感叹，不需要处理。",
            "嗯这个比喻有点可爱，跳过吧。",
        ],
    )
    _add_many(
        cases,
        category="en_ignore_casual_social",
        route="ignore",
        scenario="casual_social_chatter",
        utterance_style="low_value_chat_en",
        source_family="manual_design",
        contents=[
            "That wording is kind of funny.",
            "My coffee is a little bitter today, but never mind.",
            "That name sounds like a tiny helper tool.",
            "The last sentence was a bit twisty; let's move on.",
            "I laughed at that, but it does not matter.",
            "This chat is getting long, but it is fine.",
            "That example is amusing; no need to remember it.",
            "Just a random complaint, back to the point.",
            "That was only a reaction, not something to process.",
            "That analogy is cute; skip it.",
        ],
    )

    _add_many(
        cases,
        category="cn_long_term_preference",
        route="long_term",
        memory_type="user_preference",
        context_role="excluded",
        scenario="durable_user_preference",
        utterance_style="explicit_future_preference_cn",
        source_family="manual_design",
        contents=[
            "以后解释技术方案默认先给结论，再展开细节。",
            "以后类似项目文档默认用中文写。",
            "记住，我更喜欢你把事实和推断分开说。",
            "以后代码评审先列风险，再说总结。",
            "默认回答里少用营销式表达，直接讲工程取舍。",
            "以后涉及测试结果时，请明确说跑了哪些命令。",
            "记住，敏感信息相关内容默认不要展开候选。",
            "以后讲复杂链路时先画文字流程图。",
            "默认不要把一次性状态写成长期记忆。",
            "以后如果不确定是否该记，先保守不写。",
        ],
    )
    _add_many(
        cases,
        category="en_long_term_preference",
        route="long_term",
        memory_type="user_preference",
        context_role="excluded",
        scenario="durable_user_preference",
        utterance_style="explicit_future_preference_en",
        source_family="manual_design",
        contents=[
            "Going forward, start technical explanations with the conclusion.",
            "For future project docs, use Chinese by default.",
            "Remember that I prefer facts and inferences to be separated.",
            "In future code reviews, list risks before the summary.",
            "By default, avoid marketing language and explain engineering tradeoffs.",
            "When reporting tests later, say exactly which commands were run.",
            "Remember: do not expand sensitive content into memory candidates.",
            "For complex flows in the future, show a text diagram first.",
            "By default, do not turn one-off state into long-term memory.",
            "If it is unclear whether to remember something, be conservative.",
        ],
    )

    _add_many(
        cases,
        category="cn_long_term_project_rule",
        route="long_term",
        memory_type="workflow",
        context_role="excluded",
        scenario="durable_project_workflow",
        utterance_style="confirmed_workflow_cn",
        source_family="manual_design",
        contents=[
            "已确认固定流程：发布前先跑 ruff，再跑 pytest，最后做冒烟验证。",
            "项目规则已确认：远程召回评估要带 embedding cache 和 report path。",
            "固定流程是先审计 fixture 重复，再扩大样本量。",
            "已确认：写入长期记忆前必须先经过本地 evaluate_candidate。",
            "项目流程规定：真实远程测试默认显式开启，不放进普通单测。",
            "已确认工作流：先更新生成脚本，再重新生成 JSONL。",
            "固定规则是文档变更要和当前代码入口保持一致。",
            "项目流程：远程模型切换后先跑小样本，再扩大统计。",
            "已确认：敏感事件在远程请求前就要 preflight 拦截。",
            "固定验证顺序：先跑 ruff，再跑相关 pytest，最后跑全量。",
        ],
    )
    _add_many(
        cases,
        category="en_long_term_project_rule",
        route="long_term",
        memory_type="workflow",
        context_role="excluded",
        scenario="durable_project_workflow",
        utterance_style="confirmed_workflow_en",
        source_family="manual_design",
        contents=[
            "Confirmed workflow: run ruff, then pytest, then a smoke check before release.",
            "Confirmed project rule: remote retrieval evaluations use embedding cache and report path.",
            "Fixed process: audit fixture duplicates before increasing sample size.",
            "Confirmed: long-term memory writes must pass local evaluate_candidate first.",
            "Project workflow: live remote tests are opt-in and not part of ordinary unit tests.",
            "Confirmed workflow: update the generator before regenerating JSONL.",
            "Fixed rule: documentation must match the current code entry points.",
            "Project process: after switching models, run a small sample before large stats.",
            "Confirmed: sensitive events must be preflight-filtered before remote calls.",
            "Validation order: run ruff, then targeted pytest, then the full suite.",
        ],
    )

    _add_many(
        cases,
        category="cn_reject_sensitive",
        route="reject",
        context_role="excluded",
        remote_preflight_reject=True,
        scenario="sensitive_secret",
        utterance_style="redacted_secret_cn",
        source_family="manual_design",
        contents=[
            "这次请求里有 [REDACTED] token，别发给远程模型。",
            "临时使用的 api key 是 [REDACTED]，不要进入记忆。",
            "这里包含 bearer [REDACTED]，需要直接拒绝保存。",
            "cookie 字段是 [REDACTED]，不要提取候选。",
            "authorization header 为 [REDACTED]，不要进入远程 route。",
            "password 已经打码为 [REDACTED]，仍然不要写入。",
            "secret 值是 [REDACTED]，这条只应被过滤。",
            "这个 token 占位符 [REDACTED] 不能出现在记忆里。",
            "这里有私钥片段 [REDACTED]，必须拒绝。",
            "访问凭据 [REDACTED] 只用于说明敏感过滤。",
        ],
    )
    _add_many(
        cases,
        category="en_reject_sensitive",
        route="reject",
        context_role="excluded",
        remote_preflight_reject=True,
        scenario="sensitive_secret",
        utterance_style="redacted_secret_en",
        source_family="manual_design",
        contents=[
            "This request contains a [REDACTED] token; do not send it remotely.",
            "The temporary api key is [REDACTED], so it must not become memory.",
            "This includes bearer [REDACTED]; reject it instead of routing.",
            "The cookie value is [REDACTED], so do not extract candidates.",
            "The authorization header is [REDACTED]; keep it out of remote route.",
            "The password is masked as [REDACTED], but it still must not be stored.",
            "The secret value is [REDACTED]; this line should only be filtered.",
            "This token placeholder [REDACTED] must not appear in memory.",
            "There is a private key fragment [REDACTED], so reject the item.",
            "Credential placeholder [REDACTED] is only here to test filtering.",
        ],
    )

    _add_many(
        cases,
        category="cn_ask_user_blocking_decision",
        route="ask_user",
        context_role="review",
        scenario="immediate_user_confirmation",
        utterance_style="blocking_confirmation_cn",
        source_family="manual_design",
        contents=[
            "现在先停一下，问我是否要把短期记忆写进数据库，确认前不要继续。",
            "删除 legacy 入口前先问我，没确认不要动代码。",
            "如果要把 session memory 接进回答链路，先问我是否同意再实施。",
            "这两个方案你不要替我选，先问我要保守版还是激进版。",
            "在扩大到五百条之前先让我确认，不要直接生成。",
            "是否接真实远程模型这一步先问我，确认前不要跑。",
            "短期情绪状态是否强制注入，先问我再改策略。",
            "现在先问我要不要持久化 session，别直接决定。",
            "是否把 scratch_note 默认注入上下文，先向我确认。",
            "继续实现前先问我是不是接受这个分类方案。",
        ],
    )
    _add_many(
        cases,
        category="en_ask_user_blocking_decision",
        route="ask_user",
        context_role="review",
        scenario="immediate_user_confirmation",
        utterance_style="blocking_confirmation_en",
        source_family="manual_design",
        contents=[
            "Pause here and ask me whether session memory should be stored before continuing.",
            "Ask me before deleting the legacy entry point; do not change code yet.",
            "Before wiring session memory into answers, ask for my confirmation.",
            "Do not choose between the conservative and aggressive plan; ask me first.",
            "Before expanding this to five hundred cases, let me confirm the size.",
            "Ask me before connecting the live remote model; do not run it yet.",
            "Before forcing emotional state into context, ask whether I agree.",
            "Ask whether session memory should be persisted instead of deciding directly.",
            "Before injecting scratch_note by default, ask me to confirm.",
            "Before continuing implementation, ask whether I accept this classification plan.",
        ],
    )

    return cases


def main() -> None:
    cases = build_cases()
    names = [case["name"] for case in cases]
    contents = [case["event"]["content"] for case in cases]
    if len(names) != len(set(names)):
        raise ValueError("duplicate case names")
    if len(contents) != len(set(contents)):
        raise ValueError("duplicate event contents")
    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases)
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(cases)} cases to {OUTPUT}")


if __name__ == "__main__":
    main()
