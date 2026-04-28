from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "semantic_retrieval_v2.jsonl"
REPO_SCOPE = "repo:C:/workspace/demo"


TOPICS: list[dict[str, Any]] = [
    {
        "key": "release",
        "category": "v2_work_release",
        "subject": "release checks",
        "content": "Before deployment run ruff check and pytest.",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["ci", "release"],
        "queries": [
            "How do I ship safely?",
            "What should happen before going live?",
            "What is the launch safety routine?",
            "What should I check before publishing a build?",
            "上线前需要先确认什么？",
            "release 前要跑哪些检查？",
            "How do we avoid a bad rollout?",
            "Before I cut a build, what gates matter?",
            "What is the preflight before production?",
            "发布之前有哪些固定动作？",
        ],
    },
    {
        "key": "schema",
        "category": "v2_work_schema",
        "subject": "schema migrations",
        "content": "Run migration scripts after schema edits.",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["database", "migration"],
        "queries": [
            "The storage shape shifted, what follows?",
            "Tables changed, what should I do next?",
            "What comes after altering persisted fields?",
            "How do I handle a data model update?",
            "数据库字段变了下一步是什么？",
            "A column layout moved, what is the next step?",
            "After changing SQLite tables, what should run?",
            "Schema edits are done; what is the follow-up?",
            "数据表结构调整后别忘了什么？",
            "The persistence model changed; what should I execute?",
        ],
    },
    {
        "key": "docs",
        "category": "v2_work_docs",
        "subject": "documentation sync",
        "content": "After code behavior changes, sync README and docs.",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["documentation"],
        "queries": [
            "Implementation moved, what paperwork follows?",
            "The behavior changed, what written material needs attention?",
            "After a patch, what project notes should be updated?",
            "What should accompany a user-visible code change?",
            "改完实现以后文档要不要同步？",
            "How do we keep explanations aligned with the implementation?",
            "The public behavior shifted; what docs drift might exist?",
            "代码逻辑变了，说明文件也要处理吗？",
            "What should be checked after changing a documented command?",
            "When feature behavior changes, which notes need a refresh?",
        ],
    },
    {
        "key": "dependency",
        "category": "v2_work_dependency",
        "subject": "dependency installation",
        "content": "Install missing Python packages with python -m pip install.",
        "memory_type": "tool_rule",
        "scope": "global",
        "tags": ["python", "pip"],
        "queries": [
            "A package import is unavailable.",
            "The module cannot be found at runtime.",
            "How should I add a missing library?",
            "The environment lacks a required dependency.",
            "缺 Python 包时用什么安装方式？",
            "A Python requirement is absent, what command shape is preferred?",
            "ImportError points to a missing package; what next?",
            "模块找不到应该怎么补依赖？",
            "What is the preferred way to install a library here?",
            "A dependency is not installed in this environment.",
        ],
    },
    {
        "key": "browser",
        "category": "v2_work_browser",
        "subject": "browser validation",
        "content": "Open localhost pages in the in-app browser for UI validation.",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["ui", "browser"],
        "queries": [
            "Need to inspect the local web screen.",
            "How should I verify the running page visually?",
            "I want to check the interface in a real tab.",
            "The app view needs manual interaction testing.",
            "本地页面要怎么实际看一眼？",
            "Where should I look at the local frontend?",
            "A UI change needs a browser pass.",
            "How do I validate localhost visually?",
            "前端页面改了要在哪里检查？",
            "The screen needs real browser inspection.",
        ],
    },
    {
        "key": "encoding",
        "category": "v2_work_encoding",
        "subject": "console encoding",
        "content": "Use UTF-8 code page 65001 when console text is garbled.",
        "memory_type": "troubleshooting",
        "scope": "global",
        "tags": ["windows", "encoding"],
        "queries": [
            "Chinese characters are mojibake in PowerShell.",
            "Terminal output is unreadable after printing Chinese.",
            "The shell shows broken multilingual text.",
            "Command output has strange character corruption.",
            "PowerShell 里中文乱码怎么办？",
            "Non-English logs look scrambled in the console.",
            "The terminal is showing weird symbols.",
            "Windows 命令行输出变成乱码了。",
            "Text encoding is broken in the shell.",
            "Console Chinese output is corrupted.",
        ],
    },
    {
        "key": "server",
        "category": "v2_work_server",
        "subject": "active server verification",
        "content": "When a local service seems stale, verify the active port and process.",
        "memory_type": "troubleshooting",
        "scope": REPO_SCOPE,
        "tags": ["runtime", "server"],
        "queries": [
            "The running app still behaves like the old version.",
            "Changes are not visible on the live endpoint.",
            "The service looks stale after a restart.",
            "Which process is actually serving the page?",
            "本地服务好像没吃到新代码。",
            "The local URL is not reflecting the patch.",
            "How do I know which port is active?",
            "页面还是旧版本，应该查什么？",
            "A restart happened but the endpoint did not change.",
            "The server process may not be the one I expected.",
        ],
    },
    {
        "key": "assets",
        "category": "v2_work_assets",
        "subject": "visual asset validation",
        "content": "For frontend changes, verify referenced assets render correctly.",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["frontend", "assets"],
        "queries": [
            "The screen looks blank after a UI change.",
            "Images may not be loading in the interface.",
            "How do I confirm the page is not visually empty?",
            "The canvas or media area needs a rendering check.",
            "前端资源是不是没加载出来？",
            "A visual update needs asset verification.",
            "The page changed but the media is missing.",
            "如何确认图片和画布真的渲染了？",
            "The UI shell is there but visual content is gone.",
            "Static assets might be broken after the patch.",
        ],
    },
    {
        "key": "secret",
        "category": "v2_governance_secret",
        "subject": "secret handling",
        "content": "Do not store API keys or tokens in memory.",
        "memory_type": "tool_rule",
        "scope": "global",
        "tags": ["security", "privacy"],
        "queries": [
            "How should credentials be handled?",
            "What do we do with private access strings?",
            "Should authentication material become memory?",
            "A bearer value appears in chat, what now?",
            "密钥信息能不能进入长期记忆？",
            "How are confidential connection values treated?",
            "The message includes an access token; should it be remembered?",
            "遇到 API key 默认怎么处理？",
            "Can a password-like value be saved?",
            "What is the memory rule for secrets?",
        ],
    },
    {
        "key": "answer_style",
        "category": "v2_daily_answer_style",
        "subject": "answer style",
        "content": "Default to Chinese for technical memory-system discussions and separate verified facts from inferences.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["communication"],
        "queries": [
            "How should technical memory answers be phrased?",
            "What response style fits this project conversation?",
            "How do I explain uncertain implementation behavior?",
            "What language and evidence framing should be used?",
            "这种记忆系统问题默认怎么回答？",
            "How should the assistant present confirmed versus guessed details?",
            "回答时要不要区分事实和推断？",
            "What tone should be used for this technical discussion?",
            "技术记忆话题默认用中文吗？",
            "How should uncertainty be surfaced in the answer?",
        ],
    },
    {
        "key": "food",
        "category": "v2_daily_food",
        "subject": "lunch preference",
        "content": "The user prefers vegetarian lunch options and dislikes cilantro.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["daily", "food"],
        "queries": [
            "What should I order them for lunch?",
            "有什么午餐选择比较适合用户？",
            "Which meal option should avoid herbs they dislike?",
            "If we grab takeout, what food preference matters?",
            "What should I remember when choosing a salad?",
            "他们吃饭有什么忌口吗？",
            "Which lunch option is safer for the user?",
            "What kind of meal should I suggest for a casual lunch?",
            "点外卖时有什么偏好要注意？",
            "What food detail matters in daily planning?",
        ],
    },
    {
        "key": "drink",
        "category": "v2_daily_drink",
        "subject": "drink preference",
        "content": "The user prefers unsweetened iced tea over sugary drinks.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["daily", "drink"],
        "queries": [
            "What beverage should I pick up?",
            "用户更适合什么饮料？",
            "If ordering a drink, should it be sweet?",
            "What should I avoid buying at the cafe?",
            "Which refreshment fits their usual taste?",
            "奶茶和无糖茶哪个更贴近偏好？",
            "What drink choice is safest for them?",
            "They asked for something cold; what should it be?",
            "饮料口味有什么长期偏好？",
            "What should I remember at a coffee shop?",
        ],
    },
    {
        "key": "schedule",
        "category": "v2_daily_schedule",
        "subject": "schedule preference",
        "content": "The user prefers deep work in the morning and meetings after lunch.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["daily", "calendar"],
        "queries": [
            "When should I put focus time on the calendar?",
            "上午适合安排什么类型的工作？",
            "Is a morning meeting ideal for this user?",
            "Where should calls land in the day?",
            "How should I arrange deep work and meetings?",
            "会议最好放在午饭前还是之后？",
            "What daily schedule layout does the user prefer?",
            "If planning tomorrow, when should heads-down work happen?",
            "他们的日程安排有什么稳定习惯？",
            "What time block should stay interruption-free?",
        ],
    },
    {
        "key": "learning",
        "category": "v2_daily_learning",
        "subject": "learning style",
        "content": "The user learns best from concrete examples before abstractions.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["daily", "learning"],
        "queries": [
            "How should I explain a new concept?",
            "讲新东西时先讲理论还是例子？",
            "What teaching style works for the user?",
            "Should I start with definitions or a concrete case?",
            "How do they prefer to understand abstractions?",
            "解释复杂机制时先给什么？",
            "What makes an explanation easier for them?",
            "If teaching an API, what should come first?",
            "用户学习新知识时更吃哪种方式？",
            "How should I introduce a technical idea?",
        ],
    },
    {
        "key": "planning",
        "category": "v2_daily_planning",
        "subject": "planning habit",
        "content": "The user likes end-of-day checklists for tomorrow.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["daily", "planning"],
        "queries": [
            "How should I help wrap up the day?",
            "晚上收尾时适合整理什么？",
            "What planning habit helps them prepare for tomorrow?",
            "Should I make a next-day checklist?",
            "How do they prefer to close a work session?",
            "明天的事情要不要列清单？",
            "What should I offer at the end of a long task?",
            "If we finish late, what planning aid is useful?",
            "用户日常计划更喜欢什么形式？",
            "How should I transition from today to tomorrow?",
        ],
    },
    {
        "key": "notification",
        "category": "v2_daily_notification",
        "subject": "reminder tone",
        "content": "The user prefers gentle reminders without alarmist wording.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["daily", "reminder"],
        "queries": [
            "How should I nudge them about a deadline?",
            "提醒用户时语气要不要很急？",
            "What style of reminder is preferred?",
            "Should the reminder sound alarming?",
            "How do they like time-sensitive prompts?",
            "催办事项时应该怎么措辞？",
            "What tone fits a gentle follow-up?",
            "If a task is overdue, how should I phrase it?",
            "日常提醒有什么语气偏好？",
            "How should I avoid stressing them in a reminder?",
        ],
    },
    {
        "key": "travel",
        "category": "v2_daily_travel",
        "subject": "travel lodging preference",
        "content": "The user prefers quiet hotels near public transit.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["daily", "travel"],
        "queries": [
            "What kind of hotel should I choose?",
            "订住宿时要优先考虑什么？",
            "Where should lodging be located for them?",
            "Do they prefer nightlife or a calm place to stay?",
            "What matters for travel accommodation?",
            "出差订酒店有什么偏好？",
            "Should I pick a place near transit?",
            "What hotel environment fits them best?",
            "旅行住宿要避开什么？",
            "Which lodging option is safer for their preferences?",
        ],
    },
    {
        "key": "shopping",
        "category": "v2_daily_shopping",
        "subject": "shopping preference",
        "content": "The user prefers durable items over the cheapest option.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["daily", "shopping"],
        "queries": [
            "How should I choose between two products?",
            "买东西时便宜优先吗？",
            "What matters more than the lowest price?",
            "If comparing gear, what preference should guide me?",
            "Should I pick the budget item or the sturdy one?",
            "购物建议里要强调耐用吗？",
            "What product tradeoff does the user prefer?",
            "When recommending accessories, what should matter?",
            "他们买东西更看重什么？",
            "How should I filter options in a purchase decision?",
        ],
    },
]


NO_MATCH_GROUPS: list[dict[str, Any]] = [
    {
        "category": "v2_no_match_daily",
        "queries": [
            "What birthday gift did Alex want?",
            "用户上周末看了哪部电影？",
            "Which gym class did they book?",
            "What is their favorite childhood song?",
            "Did they prefer the red mug or the blue mug?",
            "他们今天早饭吃了什么？",
            "Which friend is visiting tomorrow?",
            "What size shoes do they wear?",
            "Did they want window seats on this specific flight?",
            "用户最近一次理发是什么时候？",
        ],
        "distractors": ["food", "drink", "travel"],
    },
    {
        "category": "v2_no_match_work",
        "queries": [
            "Which cloud region hosts production?",
            "生产数据库密码在哪里？",
            "What is the current Kubernetes namespace?",
            "Which vendor owns billing webhooks?",
            "What exact version shipped last Friday?",
            "线上缓存 TTL 现在是多少？",
            "Which teammate owns the mobile release?",
            "What is the S3 bucket name?",
            "Which CI runner label is used in production?",
            "线上报警阈值具体是多少？",
        ],
        "distractors": ["release", "schema", "server"],
    },
]


def memory(alias: str, topic: dict[str, Any]) -> dict[str, Any]:
    return {
        "alias": alias,
        "content": topic["content"],
        "memory_type": topic["memory_type"],
        "scope": topic["scope"],
        "subject": topic["subject"],
        "confidence": "confirmed",
        "source_event_ids": [f"evt_{alias}"],
        "tags": list(topic["tags"]),
        "status": "active",
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    topics_by_key = {topic["key"]: topic for topic in TOPICS}
    for topic_index, topic in enumerate(TOPICS):
        distractor_a = TOPICS[(topic_index + 5) % len(TOPICS)]
        distractor_b = TOPICS[(topic_index + 11) % len(TOPICS)]
        for query_index, query in enumerate(topic["queries"]):
            suffix = f"{topic['key']}_{query_index:03d}"
            target_alias = f"{suffix}_target"
            distractor_a_alias = f"{suffix}_distractor_a"
            distractor_b_alias = f"{suffix}_distractor_b"
            cases.append(
                {
                    "category": topic["category"],
                    "mode": "retrieval",
                    "name": f"semantic_v2_{suffix}",
                    "search": {
                        "query": query,
                        "scopes": [REPO_SCOPE, "global"],
                        "limit": 1,
                    },
                    "expected": {
                        "ordered_prefix": [target_alias],
                        "absent_aliases": [distractor_a_alias, distractor_b_alias],
                    },
                    "memories": [
                        memory(target_alias, topic),
                        memory(distractor_a_alias, distractor_a),
                        memory(distractor_b_alias, distractor_b),
                    ],
                }
            )

    for group_index, group in enumerate(NO_MATCH_GROUPS):
        distractors = [topics_by_key[key] for key in group["distractors"]]
        for query_index, query in enumerate(group["queries"]):
            aliases = [
                f"no_match_{group_index}_{query_index:03d}_distractor_{idx}"
                for idx in range(len(distractors))
            ]
            cases.append(
                {
                    "category": group["category"],
                    "mode": "retrieval",
                    "name": f"semantic_v2_no_match_{group_index}_{query_index:03d}",
                    "search": {
                        "query": query,
                        "scopes": [REPO_SCOPE, "global"],
                        "limit": 1,
                    },
                    "expected": {
                        "exact_aliases": [],
                        "absent_aliases": aliases,
                    },
                    "memories": [
                        memory(alias, topic)
                        for alias, topic in zip(aliases, distractors)
                    ],
                }
            )
    return cases


def main() -> None:
    cases = build_cases()
    if len(cases) != 200:
        raise RuntimeError(f"expected 200 cases, got {len(cases)}")
    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, separators=(",", ":")) for case in cases)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
