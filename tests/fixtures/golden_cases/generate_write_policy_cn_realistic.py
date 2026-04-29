from __future__ import annotations

import hashlib
import json
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "write_policy_cn_realistic.jsonl"
REPO_SCOPE = "repo:C:/workspace/cn-realistic"


def expected(
    memory_type: str,
    evidence_type: str,
    decision: str,
    *,
    commit: bool = False,
) -> dict[str, Any]:
    return {
        "memory_type": memory_type,
        "evidence_type": evidence_type,
        "decision": decision,
        "commit": commit,
    }


def event(
    event_type: str,
    content: str,
    *,
    source: str = "conversation",
    scope: str = "global",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_type": event_type,
        "content": content,
        "source": source,
        "scope": scope,
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


def explicit_metadata(
    memory_type: str,
    subject: str,
    claim: str,
    *,
    evidence_type: str = "direct_user_statement",
    confidence: str = "confirmed",
    risk: str = "low",
    time_validity: str = "until_changed",
    reuse_cases: list[str] | None = None,
    scores: dict[str, float] | None = None,
) -> dict[str, Any]:
    return {
        "memory_type": memory_type,
        "subject": subject,
        "claim": claim,
        "evidence_type": evidence_type,
        "time_validity": time_validity,
        "reuse_cases": reuse_cases or ["future_tasks"],
        "confidence": confidence,
        "risk": risk,
        "scores": scores
        or {
            "long_term": 0.9,
            "evidence": 1.0,
            "reuse": 0.8,
            "risk": 0.1,
            "specificity": 0.8,
        },
    }


def add_case(
    cases: list[dict[str, Any]],
    category: str,
    name: str,
    event_payload: dict[str, Any],
    expected_candidates: list[dict[str, Any]],
    *,
    scenario: str,
    utterance_style: str,
    source_family: str = "manual_design",
    existing_memories: list[dict[str, Any]] | None = None,
) -> None:
    case: dict[str, Any] = {
        "name": name,
        "category": category,
        "scenario": scenario,
        "utterance_style": utterance_style,
        "source_family": source_family,
        "event": event_payload,
        "expected": {"candidates": expected_candidates},
    }
    if existing_memories:
        case["existing_memories"] = existing_memories
    cases.append(case)


def grid(*groups: Iterable[Any], limit: int) -> list[tuple[Any, ...]]:
    values = list(product(*groups))
    if len(values) < limit:
        raise RuntimeError(f"not enough combinations: need {limit}, got {len(values)}")
    return values[:limit]


def stable_suffix(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def memory(
    content: str,
    *,
    memory_type: str,
    subject: str,
    scope: str = REPO_SCOPE,
) -> dict[str, Any]:
    return {
        "content": content,
        "memory_type": memory_type,
        "scope": scope,
        "subject": subject,
        "confidence": "confirmed",
        "source_event_ids": [f"evt_existing_{stable_suffix(content)}"],
        "status": "active",
        "tags": [],
    }


def varied(items: Sequence[Any], index: int) -> Any:
    return items[index % len(items)]


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    direct_scenarios = [
        ("coding_support", "排查 Python 单测失败", "先复现失败，再说修改点"),
        ("frontend_review", "检查前端布局", "先指出重叠和溢出风险"),
        ("docs_sync", "同步项目文档", "先对齐代码事实，再改说明"),
        ("remote_model_eval", "看远程模型统计", "先分清 FN、噪声和 ambiguous"),
        ("memory_design", "讨论记忆机制", "把写入、召回、上下文分层解释"),
        ("dataset_quality", "审查测试数据集", "先说样本是否重复，再说怎么扩充"),
        ("git_workflow", "准备提交代码", "先列变更和验证，再建议提交"),
        ("learning_explain", "解释新概念", "先给一个生活化例子"),
        ("meeting_summary", "整理会议纪要", "把结论、待办和风险分开"),
        ("travel_planning", "规划出行方案", "先给约束和取舍，再给路线"),
        ("shopping_compare", "比较购买选项", "先列硬指标，再给推荐"),
        ("daily_schedule", "拆日程计划", "先确认时间窗口和优先级"),
        ("writing_polish", "润色中文段落", "保留原意，不写得太营销"),
        ("research_reading", "总结论文或资料", "区分作者结论和你的推断"),
        ("life_admin", "整理生活提醒", "只记稳定安排，不记临时情绪"),
    ]
    direct_templates = [
        "以后{task}时，请{guidance}。",
        "默认在{task}的时候，{guidance}。",
        "记住：以后帮我{task}，{guidance}。",
        "我的长期偏好是，{task}时{guidance}。",
    ]
    for index, ((scenario, task, guidance), template) in enumerate(
        grid(direct_scenarios, direct_templates, limit=60)
    ):
        content = template.format(task=task, guidance=guidance)
        add_case(
            cases,
            "cn_positive_preference_direct",
            f"cn_positive_preference_direct_{index:03d}",
            event("user_message", content),
            [expected("user_preference", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="stable_preference",
        )

    uncertain_scenarios = [
        ("answer_style", "回答长问题", "短一点"),
        ("code_review", "给代码建议", "先讲风险"),
        ("test_failure", "解释测试失败", "先给最可能原因"),
        ("commit_message", "写提交说明", "少用抽象词"),
        ("doc_structure", "整理文档结构", "先列目录"),
        ("retrieval_policy", "比较召回策略", "多举 no-match 例子"),
        ("write_policy", "判断是否写入记忆", "先说证据强弱"),
        ("remote_result", "分析远程结果", "先区分少召回和噪声"),
        ("project_status", "描述项目进度", "先说已完成"),
        ("travel_plan", "规划旅行回答", "先给预算边界"),
        ("shopping_advice", "做购买建议", "先列不可接受项"),
        ("daily_plan", "拆日程回答", "先按时间块"),
        ("study_note", "解释学习材料", "先讲直觉"),
        ("meeting_brief", "写会议摘要", "先给行动项"),
        ("writing_feedback", "改中文稿件", "先指出结构问题"),
    ]
    uncertain_templates = [
        "可能我更喜欢你在{task}时{guidance}，但我还没想好。",
        "也许{task}可以{guidance}，先别直接当成长期偏好。",
        "不确定以后{task}是不是都要{guidance}，这条先需要确认。",
    ]
    for index, ((scenario, task, guidance), template) in enumerate(
        grid(uncertain_scenarios, uncertain_templates, limit=45)
    ):
        content = template.format(task=task, guidance=guidance)
        add_case(
            cases,
            "cn_review_preference_uncertain",
            f"cn_review_preference_uncertain_{index:03d}",
            event("user_message", content),
            [expected("user_preference", "direct_user_statement", "ask_user")],
            scenario=scenario,
            utterance_style="uncertain_preference",
        )

    underspecified_contexts = [
        ("docs_sync", "刚才那版 README 说明看着顺"),
        ("travel_planning", "这次旅行清单拆得挺清楚"),
        ("debugging", "这段排错过程我能跟上"),
        ("meeting_summary", "这个会议摘要的颗粒度不错"),
        ("cooking_plan", "刚刚那个晚饭替换建议挺实用"),
        ("shopping_compare", "这份键盘对比看着省心"),
        ("retrieval_policy", "这个 no-match 分析角度可以"),
    ]
    underspecified_phrases = [
        "以后都这样。",
        "以后也这样。",
        "以后按这个来。",
        "下次也这样。",
        "之后都这样。",
    ]
    for index, ((scenario, context), phrase) in enumerate(
        grid(underspecified_contexts, underspecified_phrases, limit=35)
    ):
        add_case(
            cases,
            "cn_review_preference_underspecified",
            f"cn_review_preference_underspecified_{index:03d}",
            event("user_message", f"{context}，{phrase}"),
            [expected("user_preference", "direct_user_statement", "ask_user")],
            scenario=scenario,
            utterance_style="underspecified_generalization",
        )

    temporary_requests = [
        ("debugging", "这次先把日志级别调到 debug", "只是为了看这一轮失败"),
        ("remote_eval", "本轮先跳过远程 LLM 判断", "等额度确认后再说"),
        ("frontend_review", "这个页面先用蓝色按钮", "只是当前截图要对齐"),
        ("docs_sync", "这段说明先不写进 README", "我想再确认措辞"),
        ("git_workflow", "这个分支先叫 memory-demo", "后面可能会改名"),
        ("test_runner", "先只跑这一条 pytest 用例", "全量稍后再跑"),
        ("api_debug", "暂时把端口改成 8011", "只是避开当前占用"),
        ("dataset_quality", "先保留这个临时分类名", "别写进长期记忆"),
        ("writing_polish", "这次标题先夸张一点", "只是给我看效果"),
        ("travel_planning", "这次行程先按周六出发算", "时间还没定"),
        ("shopping_compare", "先把预算写成 500 元以内", "只是临时假设"),
        ("daily_schedule", "今天先把会议挪到下午", "不代表以后都这样"),
        ("study_note", "这次先用英文术语", "只是为了对照原文"),
        ("life_admin", "先提醒我今晚看一下账单", "不用记录成习惯"),
        ("meeting_summary", "这份纪要先不分责任人", "等会我再补"),
    ]
    temporary_templates = [
        "{action}，{reason}。",
        "先说明一下：{action}，{reason}。",
        "{action}；{reason}，不要长期记。",
    ]
    for index, ((scenario, action, reason), template) in enumerate(
        grid(temporary_requests, temporary_templates, limit=45)
    ):
        add_case(
            cases,
            "cn_negative_temporary_request",
            f"cn_negative_temporary_request_{index:03d}",
            event("user_message", template.format(action=action, reason=reason), scope=REPO_SCOPE),
            [],
            scenario=scenario,
            utterance_style="temporary_request",
        )

    casual_likes = [
        ("music_chat", "这首歌的鼓点", "只是现在听着舒服"),
        ("food_chat", "这杯拿铁的味道", "不代表我以后都点它"),
        ("ui_preview", "这个按钮圆角", "不要当成偏好"),
        ("travel_chat", "这张民宿照片里的窗景", "只是随口一说"),
        ("writing_chat", "这句开场白", "不代表长期写作风格"),
        ("design_preview", "这个配色", "别记录成偏好"),
        ("shopping_browse", "这款耳机外观", "当前页面看着还行"),
    ]
    casual_templates = [
        "我喜欢{item}，{reason}。",
        "{item}我还挺喜欢的，{reason}。",
        "这个瞬间我觉得{item}不错，{reason}。",
        "先说一句，我喜欢{item}，但{reason}。",
        "{item}挺合眼缘，{reason}。",
    ]
    for index, ((scenario, item, reason), template) in enumerate(
        grid(casual_likes, casual_templates, limit=35)
    ):
        add_case(
            cases,
            "cn_negative_casual_like",
            f"cn_negative_casual_like_{index:03d}",
            event("user_message", template.format(item=item, reason=reason)),
            [],
            scenario=scenario,
            utterance_style="casual_like",
        )

    questions = [
        ("project_lookup", "这个项目现在怎么启动？", "只是问一下当前情况"),
        ("remote_model", "远程模型现在走的是哪条链路？", "先别记"),
        ("memory_concept", "召回测试和写入测试有什么区别？", "不用写成长期事实"),
        ("dataset_quality", "这个数据集是不是还有重复？", "等确认后再说"),
        ("test_inventory", "现在一共有几个黄金测试集？", "只是想理解流程"),
        ("retrieval_noise", "为什么 no-match 会产生噪声？", "别当成偏好"),
        ("docs_sync", "说明文档哪一段还没同步？", "先帮我查清楚"),
        ("api_debug", "这个接口为什么返回空？", "只是当前排查"),
        ("git_workflow", "现在应该提交还是继续改？", "先不用记录"),
        ("daily_plan", "明天几点提醒我比较合适？", "我还没决定"),
    ]
    question_templates = [
        "{question}{tail}。",
        "先确认一个问题：{question}{tail}。",
        "我想确认一下：{question}{tail}。",
    ]
    for index, ((scenario, question, tail), template) in enumerate(
        grid(questions, question_templates, limit=30)
    ):
        add_case(
            cases,
            "cn_negative_question_only",
            f"cn_negative_question_only_{index:03d}",
            event("user_message", template.format(question=question, tail=tail)),
            [],
            scenario=scenario,
            utterance_style="question_only",
        )

    emotional_lines = [
        ("confusion", "我现在有点乱", "先帮我把层次讲清楚就行"),
        ("overload", "测试文件太多我看着有点懵", "不用记录成偏好"),
        ("uncertainty", "这个结果让我有点没底", "这只是当前感受"),
        ("frustration", "这一步绕得我有点烦", "先别当成长期信息"),
        ("hesitation", "我还不确定要不要继续扩大数据集", "等我确认后再沉淀"),
    ]
    emotional_templates = [
        "{emotion}，{tail}。",
        "说实话，{emotion}，{tail}。",
        "{emotion}；{tail}。",
        "现在的状态是：{emotion}，{tail}。",
        "{tail}，因为{emotion}。",
    ]
    for index, ((scenario, emotion, tail), template) in enumerate(
        grid(emotional_lines, emotional_templates, limit=25)
    ):
        add_case(
            cases,
            "cn_negative_emotional_or_social",
            f"cn_negative_emotional_or_social_{index:03d}",
            event("user_message", template.format(emotion=emotion, tail=tail)),
            [],
            scenario=scenario,
            utterance_style="emotional_or_social",
        )

    project_facts = [
        ("pyproject", "pyproject.toml", "file_observation", "测试配置", "pytest 的测试路径包含 tests 目录"),
        ("api", "src/memory_system/api.py", "file_observation", "API 入口", "API 工厂是 memory_system.api:create_app"),
        ("cli", "src/memory_system/cli.py", "file_observation", "CLI 入口", "命令行入口使用 memory_system.cli"),
        ("store", "src/memory_system/memory_store.py", "file_observation", "写入门禁", "候选写入前会经过 evaluate_candidate"),
        ("orchestrator", "src/memory_system/recall_orchestrator.py", "file_observation", "召回入口", "智能体推荐使用 orchestrate_recall"),
        ("fixtures", "tests/fixtures/golden_cases/README.md", "file_observation", "黄金集目录", "黄金测试集放在 tests/fixtures/golden_cases"),
        ("remote", "shell", "tool_result", "远程健康检查", "remote health 会检查 /models 是否可访问"),
        ("sqlite", "sqlite", "tool_result", "本地数据库", "示例数据库默认使用 data/memory.sqlite"),
        ("pytest", "pytest", "tool_result", "全量测试", "全量测试使用 python -m pytest -q"),
    ]
    project_templates = [
        "已确认：{source} 里的{subject}规则是：{fact}。",
        "验证通过：{subject}来自 {source}，当前事实是：{fact}。",
        "文件观察结论：{source} 表明{subject}为：{fact}。",
        "工具输出已确认 {subject}：{fact}，来源是 {source}。",
        "当前项目事实：{subject}，{fact}。",
    ]
    for index, ((scenario, source, event_type, subject, fact), template) in enumerate(
        grid(project_facts, project_templates, limit=45)
    ):
        content = template.format(source=source, subject=subject, fact=fact)
        add_case(
            cases,
            "cn_positive_project_fact_observed",
            f"cn_positive_project_fact_observed_{index:03d}",
            event(
                event_type,
                content,
                source=source,
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "project_fact",
                    f"{source} {subject}",
                    content,
                    evidence_type=event_type,
                    reuse_cases=["project_lookup", "setup", "debugging"],
                ),
            ),
            [expected("project_fact", event_type, "write", commit=True)],
            scenario=scenario,
            utterance_style="observed_project_fact",
        )

    troubleshooting = [
        ("remote_timeout", "远程 embedding 批量请求超时", "先缩小 batch 定位", "把 batch 调小后重跑验证通过"),
        ("encoding", "PowerShell 预览中文显示乱码", "先确认真实文件编码", "用 Python 按 UTF-8 读取后验证通过"),
        ("no_match_noise", "语义 no-match 场景误召回", "同时看 FN、unexpected 和 ambiguous", "加入具体事实风险判断后验证通过"),
        ("fixture_repeat", "fixture 生成后出现模板重复", "优先改生成脚本，不手写 JSONL", "更新生成脚本并重新 audit 后验证通过"),
        ("pythonpath", "API 测试找不到本地包", "先确认 PYTHONPATH 是否包含 src", "设置 PYTHONPATH=src 后验证通过"),
        ("sqlite_lock", "SQLite 文件在 Windows 上被占用", "先确认是否有旧进程占用", "停止旧进程后验证通过"),
        ("sensitive_candidate", "远程 LLM 把敏感内容提成候选", "敏感 preflight 要先于远程调用", "加入本地过滤后验证通过"),
        ("doc_drift", "文档说明和代码行为不一致", "以代码行为为准做漂移审计", "同步 README 和测试说明后验证通过"),
    ]
    troubleshooting_templates = [
        "问题：{problem}。经验：{experience}。解决方式：{solution}。验证通过。",
        "问题：{problem}；经验：{experience}；解决方式：{solution}。",
        "排错记录：问题是{problem}，经验是{experience}，解决方式是{solution}。",
        "已验证排错经验：问题：{problem}。经验：{experience}。解决方式：{solution}。",
        "问题：{problem}。经验：{experience}。解决方式：{solution}。已验证。",
    ]
    for index, ((scenario, problem, experience, solution), template) in enumerate(
        grid(troubleshooting, troubleshooting_templates, limit=40)
    ):
        content = template.format(problem=problem, experience=experience, solution=solution)
        add_case(
            cases,
            "cn_positive_troubleshooting_verified",
            f"cn_positive_troubleshooting_verified_{index:03d}",
            event(
                "tool_result",
                content,
                source="shell",
                scope=REPO_SCOPE,
                metadata={"subject": problem},
            ),
            [expected("troubleshooting", "tool_result", "write", commit=True)],
            scenario=scenario,
            utterance_style="verified_troubleshooting",
        )

    tool_rules = [
        ("golden_fixture", "改黄金测试集", "先跑对应生成脚本，再跑 audit"),
        ("secret_handling", "处理配置和日志", "不要把真实密钥写进 fixture"),
        ("remote_quality", "接远程模型统计", "先做小样本统计，再扩大规模"),
        ("answer_grounding", "解释测试结果", "必须把 confirmed 和 inferred 分开说"),
        ("docs_sync", "同步说明文档", "先读当前代码，再改 README"),
        ("windows_shell", "在 PowerShell 里查文件", "优先用 rg 和 Get-Content"),
        ("dataset_review", "审查数据集质量", "先看重复和模板化，再看语义场景"),
        ("memory_write", "判断写入长期记忆", "敏感内容默认不提候选"),
        ("retrieval_eval", "评估召回", "同时观察 FN、unexpected 和 top1"),
    ]
    tool_templates = [
        "已确认工具规则：关于{action}，{rule}。",
        "固定工具规则：在{action}时，{rule}。",
        "以后执行{action}，规则是{rule}。",
    ]
    for index, ((scenario, action, rule), template) in enumerate(
        grid(tool_rules, tool_templates, limit=25)
    ):
        claim = template.format(action=action, rule=rule)
        add_case(
            cases,
            "cn_positive_tool_rule_explicit",
            f"cn_positive_tool_rule_explicit_{index:03d}",
            event(
                "user_confirmation",
                claim,
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "tool_rule",
                    f"{action}工具规则",
                    claim,
                    reuse_cases=["repo_workflow", "verification"],
                ),
            ),
            [expected("tool_rule", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="explicit_tool_rule",
        )

    workflows = [
        ("release", "发布前检查", "先跑 ruff，再跑 pytest，最后做关键路径冒烟"),
        ("fixture_update", "修改测试集", "先改生成脚本，再生成 JSONL，然后跑 audit"),
        ("remote_eval", "接入远程评测", "先跑 50 条小样本，再看是否扩大"),
        ("docs_sync", "同步文档", "先对齐代码行为，再更新说明文件"),
        ("retrieval_quality", "排查召回质量", "先看分类统计，再看失败样本"),
        ("commit", "提交代码", "先确认 git diff，再跑相关测试"),
        ("api_change", "修改 API", "先补单元测试，再跑接口测试"),
        ("data_download", "下载公开数据集", "原始数据放外部目录，不进 fixture"),
        ("maintenance", "维护记忆", "先生成 review，再人工确认动作"),
    ]
    workflow_templates = [
        "已确认固定流程：{name}是{step}。",
        "固定流程：{name}时，{step}。",
        "以后做{name}，流程固定为{step}。",
    ]
    for index, ((scenario, name, step), template) in enumerate(
        grid(workflows, workflow_templates, limit=25)
    ):
        claim = template.format(name=name, step=step)
        add_case(
            cases,
            "cn_positive_workflow_explicit",
            f"cn_positive_workflow_explicit_{index:03d}",
            event(
                "user_confirmation",
                claim,
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "workflow",
                    f"{name}流程",
                    claim,
                    reuse_cases=["repo_workflow", "future_tasks"],
                ),
            ),
            [expected("workflow", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="explicit_workflow",
        )

    environment_facts = [
        ("shell", "shell", "当前 shell 是 PowerShell"),
        ("os", "操作系统", "当前机器是 Windows 环境"),
        ("repo_path", "项目路径", "项目路径是 C:/Users/Administrator/Desktop/memory"),
        ("test_command", "测试命令", "全量测试通过 python -m pytest -q 运行"),
        ("data_path", "外部数据路径", "公开数据集下载到 E:/Xu/data"),
        ("remote_llm", "远程 LLM", "远程模型名是 qwen3.6-flash"),
        ("remote_embedding", "远程 embedding", "embedding 模型名是 tongyi-embedding-vision-flash-2026-03-06"),
    ]
    env_templates = [
        "已确认环境状态：{area}，{fact}。",
        "工具输出确认：{area} 当前状态为{fact}。",
        "环境事实已验证：{area}，{fact}。",
    ]
    for index, ((scenario, area, fact), template) in enumerate(
        grid(environment_facts, env_templates, limit=20)
    ):
        claim = template.format(area=area, fact=fact)
        add_case(
            cases,
            "cn_positive_environment_fact_explicit",
            f"cn_positive_environment_fact_explicit_{index:03d}",
            event(
                "tool_result",
                claim,
                source="shell",
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "environment_fact",
                    f"{area}环境状态",
                    claim,
                    evidence_type="tool_result",
                    reuse_cases=["setup", "verification"],
                ),
            ),
            [expected("environment_fact", "tool_result", "write", commit=True)],
            scenario=scenario,
            utterance_style="explicit_environment_fact",
        )

    sensitive_items = [
        ("logs", "日志里出现了 token=[REDACTED]"),
        ("headers", "请求头里有 Authorization: Bearer [REDACTED]"),
        ("env_file", "本地 env 文件里有 api_key=[REDACTED]"),
        ("ticket", "客户工单里包含 email=[REDACTED_EMAIL]"),
        ("config", "配置截图里有 password=[REDACTED]"),
    ]
    sensitive_templates = [
        "{item}，不要记录成长期记忆。",
        "{item}，只需要提醒我脱敏。",
        "{item}，这类内容默认不提候选。",
        "我贴一下：{item}，别保存。",
        "{item}，后面用占位符就行。",
    ]
    for index, ((scenario, item), template) in enumerate(
        grid(sensitive_items, sensitive_templates, limit=25)
    ):
        add_case(
            cases,
            "cn_negative_sensitive",
            f"cn_negative_sensitive_{index:03d}",
            event("user_message", template.format(item=item)),
            [],
            scenario=scenario,
            utterance_style="sensitive_negative",
        )

    merge_facts = [
        ("auth_module", "认证模块", "固定测试命令是 python -m pytest tests/test_auth.py"),
        ("recall_module", "召回模块", "固定测试命令是 python -m pytest tests/test_recall_orchestrator.py"),
        ("api_module", "API 模块", "固定测试命令是 python -m pytest tests/test_api.py"),
        ("graph_module", "图谱模块", "固定测试命令是 python -m pytest tests/test_memory_graph.py"),
        ("remote_module", "远程模块", "固定测试命令是 python -m pytest tests/test_remote_adapters.py"),
        ("cli_module", "CLI 模块", "固定测试命令是 python -m pytest tests/test_cli.py"),
        ("context_module", "上下文模块", "固定测试命令是 python -m pytest tests/test_review_and_context.py"),
        ("lifecycle_module", "生命周期模块", "固定测试命令是 python -m pytest tests/test_lifecycle.py"),
        ("store_module", "存储模块", "固定测试命令是 python -m pytest tests/test_memory_store.py"),
        ("policy_module", "写入门禁模块", "固定测试命令是 python -m pytest tests/test_golden_write_policy.py"),
        ("dataset_module", "数据集模块", "固定审计命令是 python tests/fixtures/golden_cases/audit_golden_cases.py --strict"),
        ("public_data", "公开数据集脚本", "下载命令写入 tools/download_public_memory_datasets.py"),
        ("docs_module", "文档模块", "说明文件以 PROJECT_OVERVIEW.md 作为当前状态摘要"),
        ("quality_module", "质量统计模块", "远程候选质量 fixture 是 remote_candidate_quality_50.jsonl"),
        ("semantic_module", "语义召回模块", "中文召回 fixture 是 semantic_retrieval_cn.jsonl"),
    ]
    for index, (scenario, subject, fact) in enumerate(merge_facts):
        content = f"已确认：{subject}的{fact}。"
        add_case(
            cases,
            "cn_merge_duplicate",
            f"cn_merge_duplicate_{index:03d}",
            event(
                "file_observation",
                content,
                source=f"{scenario}.md",
                scope=REPO_SCOPE,
                metadata={"subject": subject},
            ),
            [expected("project_fact", "file_observation", "merge", commit=True)],
            scenario=scenario,
            utterance_style="duplicate_fact",
            existing_memories=[memory(content, memory_type="project_fact", subject=subject)],
        )

    conflicts = [
        ("web_console", "Web 控制台默认端口", "已确认：Web 控制台默认端口是 8010。", "已确认：Web 控制台默认端口是 9010。"),
        ("api_server", "API 服务启动命令", "已确认：API 服务启动命令是 uvicorn app:app。", "已确认：API 服务启动命令是 python -m uvicorn memory_system.api:create_app --factory。"),
        ("embedding_batch", "embedding 批量大小", "已确认：embedding 批量大小默认是 8。", "已确认：embedding 批量大小默认是 32。"),
        ("db_path", "本地数据库路径", "已确认：本地数据库路径是 data/old_memory.sqlite。", "已确认：本地数据库路径是 data/memory.sqlite。"),
        ("docs_source", "项目说明源文件", "已确认：项目说明以 README.md 为唯一来源。", "已确认：项目说明以 PROJECT_OVERVIEW.md 为当前状态摘要。"),
        ("remote_model", "远程模型名称", "已确认：远程模型名是 qwen-old-flash。", "已确认：远程模型名是 qwen3.6-flash。"),
        ("fixture_count", "黄金测试集总量", "已确认：黄金测试集总量是 4950 条。", "已确认：黄金测试集总量是 5435 条。"),
        ("data_download", "公开数据集目录", "已确认：公开数据集目录是 D:/tmp/memory_data。", "已确认：公开数据集目录是 E:/Xu/data。"),
        ("quality_gate", "写入门禁默认动作", "已确认：低证据偏好默认 write。", "已确认：低证据偏好默认 ask_user。"),
        ("browser_rule", "本地页面验证方式", "已确认：本地页面默认用系统浏览器打开。", "已确认：本地页面默认用 in-app browser 验证。"),
        ("python_env", "Python 运行方式", "已确认：测试默认直接运行 pytest。", "已确认：测试默认运行 python -m pytest。"),
        ("semantic_guard", "语义召回 guard 策略", "已确认：guard 只看相似度阈值。", "已确认：guard 同时看低分、歧义和具体事实风险。"),
        ("memory_scope", "用户偏好 scope", "已确认：用户偏好默认写入 repo scope。", "已确认：用户偏好默认写入 global scope。"),
        ("review_owner", "冲突复核动作", "已确认：冲突默认 accept_new。", "已确认：冲突默认 ask_user 或人工复核。"),
        ("encoding_rule", "中文 fixture 编码", "已确认：中文 fixture 使用 GBK。", "已确认：中文 fixture 使用 UTF-8。"),
    ]
    for index, (scenario, subject, old_content, new_content) in enumerate(conflicts):
        add_case(
            cases,
            "cn_ask_conflict",
            f"cn_ask_conflict_{index:03d}",
            event(
                "file_observation",
                new_content,
                source=f"{scenario}.yaml",
                scope=REPO_SCOPE,
                metadata={"subject": subject},
            ),
            [expected("project_fact", "file_observation", "ask_user")],
            scenario=scenario,
            utterance_style="conflicting_fact",
            existing_memories=[memory(old_content, memory_type="project_fact", subject=subject)],
        )

    reference_direct = [
        ("naturalconv_sports", "聊运动赛事新闻", "先说明你掌握的信息边界，再给判断"),
        ("naturalconv_health", "回答健康生活建议", "先提醒这不是医疗诊断"),
        ("naturalconv_entertainment", "讨论电影和综艺", "不要把随口喜欢当成长期偏好"),
        ("naturalconv_education", "解释课程和考试安排", "先区分确定信息和推测"),
        ("naturalconv_game", "聊游戏攻略", "先给可执行步骤，再说取舍"),
        ("naturalconv_tech", "解释科技新闻", "先讲背景，再讲影响"),
        ("personal_interest_music", "聊音乐兴趣", "只记录稳定偏好，不记录当下心情"),
        ("personal_interest_travel", "聊旅行兴趣", "优先记长期约束，比如预算和交通偏好"),
        ("personal_location", "涉及地区和城市", "不要把来源语料里的地点当成真实用户地址"),
        ("personal_identity", "涉及身份或职业", "需要用户明确确认后再写入"),
    ]
    reference_direct_templates = [
        "以后{task}时，{guidance}。",
        "默认帮我{task}的时候，{guidance}。",
        "记住这个长期规则：{task}时{guidance}。",
        "以后如果我们{task}，请按这个规则处理：{guidance}。",
    ]
    for offset, ((scenario, task, guidance), template) in enumerate(
        grid(reference_direct, reference_direct_templates, limit=40),
        start=60,
    ):
        content = template.format(task=task, guidance=guidance)
        add_case(
            cases,
            "cn_positive_preference_direct",
            f"cn_positive_preference_direct_{offset:03d}",
            event("user_message", content),
            [expected("user_preference", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="reference_stable_preference",
            source_family="naturalconv_personal_dialog",
        )

    reference_uncertain = [
        ("naturalconv_topic_shift", "话题从电影转到旅行时", "先确认我是不是真的想换话题"),
        ("naturalconv_health_chat", "回答养生建议时", "先提醒信息可能不完整"),
        ("naturalconv_game_chat", "聊游戏选择时", "先给入门版，不要写得太硬核"),
        ("personal_tag_interest", "根据兴趣标签给建议时", "大概先问我是否仍然喜欢"),
        ("personal_location_hint", "根据地区做推荐时", "先问我这个城市是否还适用"),
    ]
    reference_uncertain_templates = [
        "可能我更希望{task}，{guidance}，但这条先别直接写死。",
        "也许{task}要{guidance}，先放到确认里。",
        "不确定以后{task}是不是都要{guidance}，先放到确认里。",
        "我还没想好：{task}，是否要{guidance}。",
        "大概{task}可以{guidance}，但证据还不够。",
    ]
    for offset, ((scenario, task, guidance), template) in enumerate(
        grid(reference_uncertain, reference_uncertain_templates, limit=25),
        start=45,
    ):
        content = template.format(task=task, guidance=guidance)
        add_case(
            cases,
            "cn_review_preference_uncertain",
            f"cn_review_preference_uncertain_{offset:03d}",
            event("user_message", content),
            [expected("user_preference", "direct_user_statement", "ask_user")],
            scenario=scenario,
            utterance_style="reference_uncertain_preference",
            source_family="naturalconv_personal_dialog",
        )

    reference_underspecified = [
        ("naturalconv_topic_transition", "刚才你从体育聊到健康的过渡挺自然"),
        ("naturalconv_background", "这个背景补充的节奏还可以"),
        ("personal_dialog_casual", "这种闲聊里的回应不尴尬"),
        ("locomo_daily_event", "刚才那个日常事件总结我看懂了"),
        ("longmem_abstention", "刚才不知道就说不知道这点不错"),
    ]
    for offset, ((scenario, context), phrase) in enumerate(
        grid(reference_underspecified, underspecified_phrases, limit=25),
        start=35,
    ):
        add_case(
            cases,
            "cn_review_preference_underspecified",
            f"cn_review_preference_underspecified_{offset:03d}",
            event("user_message", f"{context}，{phrase}"),
            [expected("user_preference", "direct_user_statement", "ask_user")],
            scenario=scenario,
            utterance_style="reference_underspecified_generalization",
            source_family="long_dialogue_benchmarks",
        )

    reference_temporary = [
        ("naturalconv_sampling", "这次先抽 30 条 NaturalConv 看话题转移", "不要把这些原句写进 fixture"),
        ("personal_dialog_sampling", "今天先只看 PersonalDialog 的 dev_random", "训练集太大先不全量处理"),
        ("realmem_sampling", "本轮先看 RealMem 的项目状态样例", "后面再决定是否扩到冲突集"),
        ("longmem_sampling", "先用 LongMemEval 的 question_type 做分类参考", "不要照搬答案文本"),
        ("locomo_sampling", "这次先看 LoCoMo 的多会话问法", "只是为了设计场景"),
    ]
    reference_temporary_templates = [
        "{action}，{reason}。",
        "先说明一下：{action}，{reason}。",
        "{action}；{reason}，不用长期记录。",
        "今天先这样：{action}，{reason}。",
        "本轮{action}，{reason}。",
    ]
    for offset, ((scenario, action, reason), template) in enumerate(
        grid(reference_temporary, reference_temporary_templates, limit=25),
        start=45,
    ):
        add_case(
            cases,
            "cn_negative_temporary_request",
            f"cn_negative_temporary_request_{offset:03d}",
            event("user_message", template.format(action=action, reason=reason), scope=REPO_SCOPE),
            [],
            scenario=scenario,
            utterance_style="reference_temporary_request",
            source_family="reference_mining",
        )

    reference_casual_likes = [
        ("naturalconv_sports_chat", "刚才那个运动员故事", "只是这段聊天里有意思"),
        ("naturalconv_entertainment_chat", "这部电影的设定", "不代表我长期喜欢这个类型"),
        ("naturalconv_game_chat", "这个游戏角色", "别记录成偏好"),
        ("personal_dialog_music_chat", "这句歌词", "只是当前情绪对上了"),
        ("personal_dialog_travel_chat", "那个海边城市", "不要当成我的旅行偏好"),
        ("personal_dialog_food_chat", "这家店名", "只是顺口提到"),
        ("personal_dialog_social_chat", "这个朋友的玩笑", "不要写成事实"),
    ]
    reference_casual_templates = [
        "我喜欢{item}，{reason}。",
        "{item}我听着还挺喜欢，{reason}。",
        "刚刚说到的{item}不错，{reason}。",
        "先随口说一句，我喜欢{item}，但{reason}。",
        "{item}挺吸引我，{reason}。",
    ]
    for offset, ((scenario, item, reason), template) in enumerate(
        grid(reference_casual_likes, reference_casual_templates, limit=35),
        start=35,
    ):
        add_case(
            cases,
            "cn_negative_casual_like",
            f"cn_negative_casual_like_{offset:03d}",
            event("user_message", template.format(item=item, reason=reason)),
            [],
            scenario=scenario,
            utterance_style="reference_casual_like",
            source_family="naturalconv_personal_dialog",
        )

    reference_questions = [
        ("longmem_abstention", "如果公开数据里没有答案，测试应该怎么写？", "只是问原则"),
        ("locomo_temporal", "跨 session 的时间顺序要怎么构造？", "先别记"),
        ("realmem_project", "项目状态更新应该写成 decision 还是 project_fact？", "等我们确认"),
        ("naturalconv_topics", "NaturalConv 的六个主题都要覆盖吗？", "只是设计问题"),
        ("personal_dialog_profile", "PersonalDialog 的兴趣标签能不能直接写进样本？", "不要直接复制"),
        ("dataset_license", "这些外部语料的原文能不能进 fixture？", "先按不能处理"),
    ]
    reference_question_templates = [
        "{question}{tail}。",
        "我想确认：{question}{tail}。",
        "这个先当问题看：{question}{tail}。",
        "先问一下，{question}{tail}。",
        "关于数据集：{question}{tail}。",
    ]
    for offset, ((scenario, question, tail), template) in enumerate(
        grid(reference_questions, reference_question_templates, limit=30),
        start=30,
    ):
        add_case(
            cases,
            "cn_negative_question_only",
            f"cn_negative_question_only_{offset:03d}",
            event("user_message", template.format(question=question, tail=tail)),
            [],
            scenario=scenario,
            utterance_style="reference_question_only",
            source_family="reference_mining",
        )

    reference_emotions = [
        ("dataset_overload", "外部语料一下子太多了", "先给我归类就行"),
        ("license_concern", "我有点担心版权和隐私边界", "这只是当前顾虑"),
        ("quality_confusion", "我还是分不清哪些适合写入", "不用记录成偏好"),
        ("sampling_anxiety", "PersonalDialog 太大我有点没底", "先别当成长期信息"),
        ("benchmark_fatigue", "这些 benchmark 名字看着有点乱", "先帮我整理"),
    ]
    reference_emotional_templates = [
        "{emotion}，{tail}。",
        "说实话，{emotion}，{tail}。",
        "{tail}，因为{emotion}。",
        "现在我的状态是：{emotion}，{tail}。",
        "{emotion}；{tail}。",
    ]
    for offset, ((scenario, emotion, tail), template) in enumerate(
        grid(reference_emotions, reference_emotional_templates, limit=25),
        start=25,
    ):
        add_case(
            cases,
            "cn_negative_emotional_or_social",
            f"cn_negative_emotional_or_social_{offset:03d}",
            event("user_message", template.format(emotion=emotion, tail=tail)),
            [],
            scenario=scenario,
            utterance_style="reference_emotional_or_social",
            source_family="reference_mining",
        )

    reference_project_facts = [
        ("naturalconv_inventory", "NaturalConv 规模", "NaturalConv 有 19,919 段对话和 400,562 条 utterance。"),
        ("naturalconv_topics", "NaturalConv 主题", "NaturalConv 主题包括体育、健康、娱乐、教育、游戏和科技。"),
        ("personal_dialog_inventory", "PersonalDialog 规模", "PersonalDialog train split 有 5,438,165 行。"),
        ("personal_dialog_profiles", "PersonalDialog 字段", "PersonalDialog 包含 dialog、profile 和 uid 字段。"),
        ("longmemeval_inventory", "LongMemEval 规模", "LongMemEval 本地镜像包含 500 条 QA 行。"),
        ("locomo_inventory", "LoCoMo 规模", "LoCoMo 本地 dialogue 文件有 35 行。"),
        ("realmem_inventory", "RealMemBench 规模", "RealMemBench 本地有 10 个 256k dialogue 文件。"),
    ]
    reference_project_templates = [
        "已确认：{subject}，{fact}",
        "本地盘点确认：{subject}，{fact}",
        "参考语料事实：{subject}。{fact}",
        "工具输出确认：{subject}，{fact}",
        "已验证外部语料盘点：{subject}，{fact}",
    ]
    for offset, ((scenario, subject, fact), template) in enumerate(
        grid(reference_project_facts, reference_project_templates, limit=35),
        start=45,
    ):
        content = template.format(subject=subject, fact=fact)
        add_case(
            cases,
            "cn_positive_project_fact_observed",
            f"cn_positive_project_fact_observed_{offset:03d}",
            event(
                "tool_result",
                content,
                source="reference_corpus_inventory",
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "project_fact",
                    subject,
                    content,
                    evidence_type="tool_result",
                    reuse_cases=["dataset_design", "fixture_generation"],
                ),
            ),
            [expected("project_fact", "tool_result", "write", commit=True)],
            scenario=scenario,
            utterance_style="reference_project_fact",
            source_family="reference_inventory",
        )

    reference_troubleshooting = [
        ("hf_xet_tls", "Hugging Face Xet 下载出现 TLS handshake eof", "先不要判断为数据不存在", "设置 HF_HUB_DISABLE_XET=1 后重试验证通过"),
        ("naturalconv_partial", "NaturalConv 首次下载目录缺少 dialog_release.json", "exists 状态不等于完整", "使用 --force 刷新后验证通过"),
        ("large_personal_dialog", "PersonalDialog 训练集很大", "先用 dev/test 和抽样统计设计样本", "生成 inventory 后验证通过"),
        ("windows_invalid_path", "RealMemBench zip 里有 Windows 非法文件名", "解压时需要跳过末尾空格文件", "manifest 记录 skipped_windows_invalid_paths 后验证通过"),
        ("external_raw_boundary", "外部原文不应进入仓库 fixture", "只抽取结构和场景画像", "改写为合成样本后验证通过"),
    ]
    reference_troubleshooting_templates = [
        "问题：{problem}。经验：{experience}。解决方式：{solution}。验证通过。",
        "排错记录：问题：{problem}。经验：{experience}。解决方式：{solution}。",
        "已验证排错经验：问题：{problem}。经验：{experience}。解决方式：{solution}。",
        "问题：{problem}；经验：{experience}；解决方式：{solution}。验证通过。",
    ]
    for offset, ((scenario, problem, experience, solution), template) in enumerate(
        grid(reference_troubleshooting, reference_troubleshooting_templates, limit=20),
        start=40,
    ):
        content = template.format(problem=problem, experience=experience, solution=solution)
        add_case(
            cases,
            "cn_positive_troubleshooting_verified",
            f"cn_positive_troubleshooting_verified_{offset:03d}",
            event(
                "tool_result",
                content,
                source="download_public_memory_datasets",
                scope=REPO_SCOPE,
                metadata={"subject": problem},
            ),
            [expected("troubleshooting", "tool_result", "write", commit=True)],
            scenario=scenario,
            utterance_style="reference_troubleshooting",
            source_family="reference_download",
        )

    reference_tool_rules = [
        ("external_raw", "改写外部语料", "只能参考结构和表达分布，不复制原文"),
        ("download_retry", "下载 Hugging Face 语料", "遇到 Xet TLS 错误时先尝试 HF_HUB_DISABLE_XET=1"),
        ("inventory", "扩展公开语料", "先更新下载脚本，再生成 inventory"),
        ("fixture_source", "生成 fixture", "每条样本要标注 source_family"),
        ("quality_check", "扩大中文写入门禁集", "必须检查 scenario 和 utterance_style 分散度"),
        ("naturalconv_license", "使用 NaturalConv", "只能参考话题和对话结构，不复制原句"),
        ("personal_profile_boundary", "使用 PersonalDialog 画像", "只抽象兴趣和身份类型，不搬真实标签"),
        ("longmem_abstention", "设计拒答样本", "没有证据时 expected.candidates 保持空或 ask_user"),
        ("locomo_temporal", "设计时间线样本", "保留时间变化，不混成当前事实"),
        ("realmem_project_state", "设计项目记忆样本", "区分目标、进度、决策和约束"),
        ("derived_inventory", "读取 derived inventory", "优先使用统计和结构，不使用原文"),
        ("scenario_labels", "扩充 scenario", "每组样本至少跨多个来源族"),
        ("utterance_styles", "扩充表达风格", "每个类别不能只换名词"),
        ("sensitive_profile", "处理画像字段", "疑似个人信息默认不写入"),
        ("test_gate", "完成扩充后", "必须跑新增 fixture、audit 和全量 pytest"),
    ]
    for offset, (scenario, action, rule) in enumerate(reference_tool_rules, start=25):
        claim = f"已确认工具规则：关于{action}，{rule}。"
        add_case(
            cases,
            "cn_positive_tool_rule_explicit",
            f"cn_positive_tool_rule_explicit_{offset:03d}",
            event(
                "user_confirmation",
                claim,
                scope=REPO_SCOPE,
                metadata=explicit_metadata("tool_rule", f"{action}工具规则", claim),
            ),
            [expected("tool_rule", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="reference_tool_rule",
            source_family="reference_mining",
        )

    reference_workflows = [
        ("corpus_adaptation", "公开语料改写", "先下载到 E:/Xu/data，再生成 inventory，最后改写成合成 fixture"),
        ("quality_gate_v2", "写入门禁 v2 扩展", "先扩大场景来源，再跑 audit 和全量 pytest"),
        ("dataset_refresh", "刷新外部数据", "先跑下载脚本 --force，再检查 manifest 和核心文件"),
        ("source_boundary", "外部数据使用", "先确认不复制原文，再沉淀场景画像"),
        ("fixture_review", "fixture 人工审查", "先看模板化重复，再抽样看语义覆盖"),
        ("naturalconv_adaptation", "NaturalConv 改写", "先抽象话题转移，再生成闲聊反例和含糊偏好"),
        ("personal_dialog_adaptation", "PersonalDialog 改写", "先抽象画像字段，再生成兴趣和身份边界样本"),
        ("longmem_adaptation", "LongMemEval 改写", "先看 question_type，再生成拒答和更新样本"),
        ("locomo_adaptation", "LoCoMo 改写", "先提取多会话事件形态，再设计召回和写入边界"),
        ("realmem_adaptation", "RealMemBench 改写", "先拆目标、进度、决策和约束，再映射 memory_type"),
        ("inventory_refresh", "语料盘点刷新", "先跑 summarize 脚本，再看 derived 报告"),
        ("raw_data_boundary", "原始语料边界", "外部原文只留在 E 盘，仓库只留合成样本"),
        ("scenario_review", "场景审查", "先看 source_family 分布，再抽查中文自然度"),
        ("negative_review", "反例审查", "先确认不会触发候选，再跑 write policy 测试"),
        ("doc_sync_public", "公开数据文档同步", "先更新下载脚本，再更新 docs/12"),
    ]
    for offset, (scenario, name, step) in enumerate(reference_workflows, start=25):
        claim = f"已确认固定流程：{name}是{step}。"
        add_case(
            cases,
            "cn_positive_workflow_explicit",
            f"cn_positive_workflow_explicit_{offset:03d}",
            event(
                "user_confirmation",
                claim,
                scope=REPO_SCOPE,
                metadata=explicit_metadata("workflow", f"{name}流程", claim),
            ),
            [expected("workflow", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="reference_workflow",
            source_family="reference_mining",
        )

    reference_env = [
        ("reference_root", "公开参考语料根目录", "公开参考语料根目录是 E:/Xu/data/memory_benchmarks"),
        ("derived_inventory", "公开语料盘点报告", "盘点报告位于 E:/Xu/data/memory_benchmarks/derived"),
        ("naturalconv_file", "NaturalConv 核心文件", "NaturalConv 核心文件是 dialog_release.json"),
        ("personal_dialog_file", "PersonalDialog 训练文件", "PersonalDialog 训练文件是 dialogues_train.jsonl.gz"),
        ("manifest_file", "公开语料 manifest", "manifest 文件是 E:/Xu/data/memory_benchmarks/manifest.json"),
    ]
    reference_env_templates = [
        "已确认环境状态：{area}，{fact}。",
        "工具输出确认：{area}，{fact}。",
    ]
    for offset, ((scenario, area, fact), template) in enumerate(
        grid(reference_env, reference_env_templates, limit=10),
        start=20,
    ):
        claim = template.format(area=area, fact=fact)
        add_case(
            cases,
            "cn_positive_environment_fact_explicit",
            f"cn_positive_environment_fact_explicit_{offset:03d}",
            event(
                "tool_result",
                claim,
                source="reference_corpus_inventory",
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "environment_fact",
                    f"{area}环境状态",
                    claim,
                    evidence_type="tool_result",
                ),
            ),
            [expected("environment_fact", "tool_result", "write", commit=True)],
            scenario=scenario,
            utterance_style="reference_environment_fact",
            source_family="reference_inventory",
        )

    reference_sensitive = [
        ("raw_utterance", "外部语料原句里可能包含个人昵称或地点", "不要复制进 fixture"),
        ("profile_tags", "PersonalDialog 画像标签可能包含敏感身份暗示", "只参考类型，不搬原值"),
        ("document_url", "NaturalConv document_url_release.json 里有原始 URL", "不要当成用户事实"),
        ("token_log", "下载日志里如果出现 token=[REDACTED]", "默认不提候选"),
        ("email_profile", "样本里如果出现 email=[REDACTED_EMAIL]", "只保留脱敏占位符"),
    ]
    reference_sensitive_templates = [
        "{item}，{rule}。",
        "注意：{item}，{rule}。",
        "{item}；{rule}，不要记录成长期记忆。",
    ]
    for offset, ((scenario, item, rule), template) in enumerate(
        grid(reference_sensitive, reference_sensitive_templates, limit=15),
        start=25,
    ):
        add_case(
            cases,
            "cn_negative_sensitive",
            f"cn_negative_sensitive_{offset:03d}",
            event("user_message", template.format(item=item, rule=rule)),
            [],
            scenario=scenario,
            utterance_style="reference_sensitive_negative",
            source_family="reference_mining",
        )

    assert len(cases) == 800
    assert len({case["name"] for case in cases}) == len(cases)
    assert len({case["event"]["content"] for case in cases}) == len(cases)
    assert len({case["scenario"] for case in cases}) >= 150
    assert len({case["utterance_style"] for case in cases}) >= 25
    assert len({case["source_family"] for case in cases}) >= 6
    return cases


def main() -> None:
    cases = build_cases()
    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
