from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from memory_system import EventCreate, EventLog, MemoryStore, create_app
from memory_system.remote import (
    DASHSCOPE_MULTIMODAL_COMPATIBILITY,
    DASHSCOPE_MULTIMODAL_EMBEDDING_URL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_LLM_MODEL,
    OPENAI_COMPATIBILITY,
    RemoteAdapterConfig,
    RemoteEmbeddingClient,
    RemoteLLMClient,
)
from memory_system.schemas import EventRead


@pytest.fixture
def remote_server():
    routes = {}
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self._handle("GET")

        def do_POST(self):  # noqa: N802
            self._handle("POST")

        def log_message(self, format, *args):  # noqa: A002
            return

        def _handle(self, method: str) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            payload = json.loads(body) if body else {}
            captured.append(
                {
                    "method": method,
                    "path": self.path,
                    "payload": payload,
                    "authorization": self.headers.get("Authorization"),
                }
            )
            handler = routes.get((method, self.path))
            if handler is None:
                self.send_response(404)
                self.end_headers()
                return
            status, response = handler(payload)
            raw = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", routes, captured
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _semantic_fixture_vector(text: str) -> list[float]:
    lowered = text.lower()
    topic_terms = [
        (
            "release",
            (
                "ship",
                "going live",
                "launch",
                "publishing",
                "rollout",
                "deployment",
                "ruff",
                "pytest",
            ),
        ),
        (
            "schema",
            (
                "storage shape",
                "tables changed",
                "persisted fields",
                "data model",
                "column layout",
                "schema",
                "migration",
            ),
        ),
        (
            "encoding",
            (
                "mojibake",
                "terminal output",
                "unreadable",
                "multilingual",
                "character corruption",
                "non-english",
                "scrambled",
                "utf-8",
                "65001",
                "garbled",
                "console",
            ),
        ),
        (
            "browser",
            (
                "inspect the local web",
                "running page visually",
                "real tab",
                "interaction testing",
                "local frontend",
                "localhost",
                "in-app browser",
                "ui validation",
            ),
        ),
        (
            "secret",
            (
                "credentials",
                "private access",
                "authentication material",
                "bearer value",
                "confidential",
                "api keys",
                "tokens",
            ),
        ),
        (
            "docs",
            (
                "paperwork",
                "written material",
                "project notes",
                "user-visible",
                "explanations aligned",
                "readme",
                "docs",
                "documentation",
            ),
        ),
        (
            "dependency",
            (
                "package import",
                "module cannot",
                "missing library",
                "required dependency",
                "python requirement",
                "pip install",
                "python packages",
            ),
        ),
        (
            "server",
            (
                "old version",
                "live endpoint",
                "stale",
                "which process",
                "local url",
                "active port",
                "service",
                "restart",
            ),
        ),
        (
            "assets",
            (
                "blank",
                "images",
                "visually empty",
                "canvas",
                "media area",
                "visual update",
                "assets render",
                "frontend changes",
            ),
        ),
        (
            "answer_style",
            (
                "phrased",
                "response style",
                "uncertain implementation",
                "language and evidence",
                "confirmed versus guessed",
                "chinese",
                "verified facts",
                "inferences",
            ),
        ),
    ]
    for index, (_topic, terms) in enumerate(topic_terms):
        if any(term in lowered for term in terms):
            vector = [0.0] * len(topic_terms)
            vector[index] = 1.0
            return vector
    return [0.01] * len(topic_terms)


def _semantic_cn_fixture_vector_terms(text: str) -> list[float]:
    lowered = text.lower()
    topic_terms = [
        (
            "cn_work_release",
            (
                "上线",
                "发布",
                "发版",
                "部署",
                "生产",
                "生产预检",
                "灰度",
                "热修复",
                "发包",
                "门禁",
                "上线窗口",
                "放量",
                "回滚",
                "ruff",
                "pytest",
                "冒烟",
            ),
        ),
        (
            "cn_work_debug",
            (
                "排查",
                "报错",
                "失败",
                "500",
                "复现",
                "耗时",
                "噪声",
                "bug",
                "修复",
                "日志",
                "偶发",
                "功能没生效",
                "性能",
                "命令运行",
                "模型结果",
                "最小失败",
            ),
        ),
        (
            "cn_work_docs",
            (
                "文档",
                "readme",
                "说明",
                "规则",
                "漂移",
                "接口示例",
                "schema",
                "用法示例",
                "远程链路",
                "新增命令",
                "测试集",
                "实现不一致",
                "代码行为",
                "黄金集",
                "api 请求",
            ),
        ),
        (
            "cn_work_encoding",
            (
                "乱码",
                "utf-8",
                "编码",
                "代码页",
                "powershell",
                "jsonl",
                "中文参数",
                "原始字节",
                "控制台",
                "终端",
                "读写回环",
                "跨平台",
                "命令行",
                "生成脚本",
                "奇怪符号",
                "文件坏",
            ),
        ),
        (
            "cn_work_environment",
            (
                "环境变量",
                "数据目录",
                "sqlite",
                "fixture",
                "模型名",
                "仓库根目录",
                "配置默认值",
                "路径",
                "目录",
                "远程配置",
                "测试命令",
                "公开参考",
                "真实密钥",
                "黄金测试",
                "项目说明",
            ),
        ),
        (
            "cn_work_git",
            (
                "git",
                "工作区",
                "回滚",
                "暂存",
                "分支",
                "reset",
                "diff",
                "提交",
                "重构",
                "别人的改动",
                "无关文件",
                "同一个文件",
                "改动来源",
                "破坏性",
                "生成文件",
            ),
        ),
        (
            "cn_memory_write_policy",
            (
                "长期记忆",
                "一次性",
                "写入",
                "保存",
                "沉淀",
                "查重",
                "不写",
                "值得写",
                "进记忆",
                "用户偏好",
                "排错经验",
                "记忆候选",
                "少记",
                "该不该记",
            ),
        ),
        (
            "cn_memory_recall_policy",
            (
                "召回",
                "no-match",
                "相似度",
                "候选",
                "top1",
                "上下文预算",
                "embedding",
                "一句话查询",
                "不确定",
                "关键词",
                "过期记忆",
                "远程 llm",
            ),
        ),
        (
            "cn_privacy_boundary",
            (
                "身份证",
                "token",
                "手机号",
                "护照",
                "密码",
                "密钥",
                "隐私",
                "住址",
                "账号",
                "敏感",
                "截图",
                "证件号码",
                "个人信息",
                "安全处理",
            ),
        ),
        (
            "cn_daily_food",
            (
                "午饭",
                "加班",
                "咖啡",
                "餐厅",
                "下午茶",
                "早餐",
                "外卖",
                "饮料",
                "食物",
                "晚饭",
                "香菜",
                "点餐",
                "热汤",
                "少糖",
                "聚餐",
                "水果",
                "豆浆",
                "微辣",
                "气泡水",
                "清淡",
                "油炸",
            ),
        ),
        (
            "cn_daily_schedule",
            (
                "上午",
                "会议",
                "复盘",
                "周一",
                "专注",
                "晚上",
                "提醒",
                "截止",
                "长任务",
                "周末",
                "时间",
                "难题",
                "收工",
                "开工",
                "写代码",
                "复杂决策",
                "风险排序",
                "状态更新",
                "轻量维护",
            ),
        ),
        (
            "cn_daily_answer_style",
            (
                "回答",
                "事实",
                "推断",
                "路线",
                "测试结果",
                "举例",
                "结论",
                "现状",
                "汇报",
                "远程模型",
                "记忆系统问题",
                "语言",
                "实现路线",
                "复杂机制",
                "文档说明",
                "觉得乱",
                "下一步",
                "改动完成",
            ),
        ),
        (
            "cn_daily_shopping",
            (
                "设备",
                "键盘",
                "显示器",
                "背包",
                "软件工具",
                "买书",
                "耳机",
                "办公椅",
                "云服务",
                "收纳",
                "稳定",
                "耐用",
                "手感",
                "护眼",
                "接口",
                "分区",
                "工具",
                "技术书",
                "舒适",
                "价格透明",
                "模块化",
            ),
        ),
    ]
    for index, (_topic, terms) in enumerate(topic_terms):
        if any(term in lowered for term in terms):
            vector = [0.0] * len(topic_terms)
            vector[index] = 1.0
            return vector
    return [0.0] * len(topic_terms)


@lru_cache(maxsize=1)
def _semantic_cn_fixture_maps() -> tuple[dict[str, int], dict[str, str], dict[str, str]]:
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "golden_cases"
        / "semantic_retrieval_cn.jsonl"
    )
    cases = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    positive_cases = [
        case for case in cases if case["expected"].get("ordered_prefix")
    ]
    category_to_index = {
        category: index
        for index, category in enumerate(
            sorted({case["category"] for case in positive_cases})
        )
    }
    query_to_category: dict[str, str] = {}
    content_to_category: dict[str, str] = {}
    for case in positive_cases:
        category = case["category"]
        target_aliases = set(case["expected"]["ordered_prefix"])
        query_to_category[case["search"]["query"]] = category
        for memory in case["memories"]:
            if memory["alias"] not in target_aliases:
                continue
            content_to_category[memory["content"]] = category
            content_to_category[memory["subject"]] = category
    return category_to_index, query_to_category, content_to_category


def _semantic_cn_one_hot(category: str, category_to_index: dict[str, int]) -> list[float]:
    vector = [0.0] * len(category_to_index)
    vector[category_to_index[category]] = 1.0
    return vector


def _semantic_cn_fixture_vector(text: str) -> list[float]:
    category_to_index, query_to_category, content_to_category = _semantic_cn_fixture_maps()
    for query, category in query_to_category.items():
        if query in text:
            return _semantic_cn_one_hot(category, category_to_index)
    for content, category in content_to_category.items():
        if content and content in text:
            return _semantic_cn_one_hot(category, category_to_index)
    return [0.0] * len(category_to_index)


def test_remote_llm_client_extracts_candidates(remote_server):
    base_url, routes, captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "warnings": ["dry-run only"],
            "candidates": [
                {
                    "content": "The user prefers Chinese technical answers.",
                    "memory_type": "user_preference",
                    "subject": "response language",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["future_responses"],
                    "scores": {
                        "long_term": 0.9,
                        "evidence": 1.0,
                        "reuse": 0.8,
                        "risk": 0.1,
                        "specificity": 0.7,
                    },
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote",
        event_type="user_message",
        content="以后技术回答默认用中文。",
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(
        RemoteAdapterConfig(base_url=base_url, api_key="secret-token")
    ).extract_candidates(event)

    assert result.provider == "fake-llm"
    assert result.warnings == ["dry-run only"]
    assert len(result.candidates) == 1
    assert result.candidates[0].source_event_ids == ["evt_remote"]
    assert result.candidates[0].scope == "global"
    assert captured[0]["authorization"] == "Bearer secret-token"
    assert captured[0]["payload"]["schema"] == "memory_system.remote_candidate_extraction.v1"


def test_remote_embedding_client_accepts_openai_style_data(remote_server):
    base_url, routes, captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-small",
            "data": [
                {"embedding": [0.1, 0.2, 0.3]},
                {"embedding": [0.4, 0.5, 0.6]},
            ],
        },
    )

    result = RemoteEmbeddingClient(RemoteAdapterConfig(base_url=base_url)).embed_texts(
        ["first text", "second text"],
        model="fake-small",
    )

    assert result.provider == "fake-embedding"
    assert result.model == "fake-small"
    assert result.dimensions == 3
    assert result.vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert captured[0]["payload"]["texts"] == ["first text", "second text"]


def test_dashscope_env_config_uses_openai_compatible_defaults(monkeypatch):
    monkeypatch.delenv("MEMORY_REMOTE_BASE_URL", raising=False)
    monkeypatch.delenv("MEMORY_REMOTE_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_REMOTE_COMPATIBILITY", raising=False)
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")

    config = RemoteAdapterConfig.from_env()

    assert config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.api_key == "dash-key"
    assert config.compatibility == OPENAI_COMPATIBILITY
    assert config.embedding_compatibility == DASHSCOPE_MULTIMODAL_COMPATIBILITY
    assert config.llm_extract_path == "/chat/completions"
    assert config.embedding_path == DASHSCOPE_MULTIMODAL_EMBEDDING_URL
    assert config.health_path == "/models"
    assert config.llm_model == DEFAULT_LLM_MODEL
    assert config.embedding_model == DEFAULT_EMBEDDING_MODEL


def test_remote_llm_client_openai_compatible_chat_completion(remote_server):
    base_url, routes, captured = remote_server
    routes[("POST", "/chat/completions")] = lambda payload: (
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "provider": "dashscope",
                                "candidates": [
                                    {
                                        "content": "OpenAI-compatible candidate.",
                                        "memory_type": "workflow",
                                        "subject": "compatible extraction",
                                        "confidence": "confirmed",
                                        "evidence_type": "direct_user_statement",
                                        "time_validity": "persistent",
                                        "reuse_cases": ["remote_validation"],
                                        "scores": {
                                            "long_term": 0.8,
                                            "evidence": 0.8,
                                            "reuse": 0.8,
                                        },
                                    }
                                ],
                            }
                        )
                    }
                }
            ]
        },
    )
    event = EventRead(
        id="evt_openai_compatible",
        event_type="user_message",
        content="OpenAI-compatible extraction event.",
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(
        RemoteAdapterConfig(
            base_url=base_url,
            api_key="dash-key",
            compatibility=OPENAI_COMPATIBILITY,
            llm_extract_path="/chat/completions",
        )
    ).extract_candidates(event)

    assert result.provider == "dashscope"
    assert result.candidates[0].subject == "compatible extraction"
    assert result.candidates[0].source_event_ids == ["evt_openai_compatible"]
    assert captured[0]["payload"]["model"] == DEFAULT_LLM_MODEL
    assert captured[0]["payload"]["response_format"] == {"type": "json_object"}
    assert captured[0]["authorization"] == "Bearer dash-key"


def test_remote_llm_client_filters_sensitive_remote_candidates(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": "token=[REDACTED] should not become memory.",
                    "memory_type": "tool_rule",
                    "subject": "sensitive handling",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response with sensitive content.",
                    "claim": "secret value should be remembered",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["security_validation"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_sensitive",
        event_type="user_message",
        content="This event asks about a security note without a reusable fact.",
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert result.candidates == []
    assert "filtered_sensitive_remote_candidate" in result.warnings


def test_remote_llm_client_skips_sensitive_events_before_http(remote_server):
    base_url, routes, captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "candidates": [{"content": payload["event"]["content"]}]},
    )
    event = EventRead(
        id="evt_remote_sensitive_event",
        event_type="user_message",
        content="A log line contains token=abc123 and should stay local.",
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert result.candidates == []
    assert result.warnings == ["filtered_sensitive_remote_event"]
    assert result.metadata == {"skipped_remote_call": True}
    assert captured == []


def test_remote_llm_client_filters_casual_preference_noise(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": payload["event"]["content"],
                    "memory_type": "user_preference",
                    "subject": "casual drink",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response that over-remembers casual chat.",
                    "confidence": "likely",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["personalization"],
                    "scores": {"long_term": 0.7, "evidence": 0.7, "reuse": 0.6},
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_casual_preference",
        event_type="user_message",
        content="\u6211\u559c\u6b22\u5496\u5561\uff0c\u521a\u624d\u559d\u4e86\u4e00\u676f.",
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert result.candidates == []
    assert "filtered_casual_remote_preference" in result.warnings


@pytest.mark.parametrize(
    ("content", "scope", "expected_type", "warning"),
    [
        (
            "\u9ed8\u8ba4\u4e0d\u8981\u628a\u4e00\u6b21\u6027\u4efb\u52a1"
            "\u5199\u8fdb\u957f\u671f\u8bb0\u5fc6.",
            "global",
            "user_preference",
            "local_remote_fallback:user_preference",
        ),
        (
            "\u8bf7\u59cb\u7ec8\u628a\u654f\u611f\u4fe1\u606f"
            "\u5f53\u4f5c\u4e0d\u53ef\u8bb0\u5fc6\u5185\u5bb9\u5904\u7406.",
            "global",
            "user_preference",
            "local_remote_fallback:user_preference",
        ),
        (
            "\u5bfc\u5165\u8fdc\u7a0b\u5019\u9009\u524d\u5fc5\u987b"
            "\u4eba\u5de5\u5ba1\u67e5\uff0c\u4e0d\u81ea\u52a8\u63d0\u4ea4"
            "\u957f\u671f\u8bb0\u5fc6.",
            "repo:C:/workspace/memory",
            "workflow",
            "local_remote_fallback:workflow",
        ),
    ],
)
def test_remote_llm_client_adds_high_confidence_fallbacks_for_empty_remote_results(
    remote_server,
    content,
    scope,
    expected_type,
    warning,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_fallback",
        event_type="user_message",
        content=content,
        source="conversation",
        scope=scope,
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == expected_type
    assert result.candidates[0].source_event_ids == ["evt_remote_fallback"]
    assert result.candidates[0].evidence_type == "direct_user_statement"
    assert warning in result.warnings


@pytest.mark.parametrize(
    ("content", "scope", "remote_type", "expected_type", "warning"),
    [
        (
            "\u95ee\u9898: pytest cannot import memory_system. "
            "\u7ecf\u9a8c: set PYTHONPATH=src. "
            "\u89e3\u51b3\u65b9\u5f0f: rerun pytest. "
            "\u9a8c\u8bc1\u901a\u8fc7.",
            "repo:C:/workspace/memory",
            "environment_fact",
            "troubleshooting",
            "normalized_remote_candidate_type:environment_fact->troubleshooting",
        ),
        (
            "\u5df2\u786e\u8ba4 Windows PowerShell \u5f53\u524d code page \u662f 65001.",
            "global",
            "project_fact",
            "environment_fact",
            "normalized_remote_candidate_type:project_fact->environment_fact",
        ),
        (
            "\u9879\u76ee\u53d1\u5e03\u524d\u8981\u5148\u8fd0\u884c ruff check \u548c pytest.",
            "repo:C:/workspace/memory",
            "user_preference",
            "workflow",
            "normalized_remote_candidate_type:user_preference->workflow",
        ),
    ],
)
def test_remote_llm_client_normalizes_governed_candidate_types(
    remote_server,
    content,
    scope,
    remote_type,
    expected_type,
    warning,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": payload["event"]["content"],
                    "memory_type": remote_type,
                    "subject": "remote governed type",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response with a type that needs governance.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "until_changed",
                    "reuse_cases": ["remote_governance_validation"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_governed_type",
        event_type="user_message",
        content=content,
        source="conversation",
        scope=scope,
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == expected_type
    assert warning in result.warnings


@pytest.mark.parametrize(
    ("content", "event_type", "source", "remote_type", "expected_type", "warning"),
    [
        (
            "\u5df2\u786e\u8ba4 README \u8bb0\u5f55\u4e86 remote evaluate \u547d\u4ee4.",
            "file_observation",
            "README.md",
            "workflow",
            "project_fact",
            "normalized_remote_candidate_type:workflow->project_fact",
        ),
        (
            "\u5df2\u786e\u8ba4\u672c\u4ed3\u5e93\u683c\u5f0f\u68c0\u67e5"
            "\u56fa\u5b9a\u4f7f\u7528 python -m ruff check .",
            "user_confirmation",
            "conversation",
            "environment_fact",
            "tool_rule",
            "normalized_remote_candidate_type:environment_fact->tool_rule",
        ),
        (
            "\u5df2\u9a8c\u8bc1\u5f53\u524d\u9879\u76ee\u53ef\u4ee5\u4f7f\u7528"
            " python -m pytest \u8fd0\u884c\u6d4b\u8bd5.",
            "test_result",
            "pytest",
            "tool_rule",
            "environment_fact",
            "normalized_remote_candidate_type:tool_rule->environment_fact",
        ),
    ],
)
def test_remote_llm_client_normalizes_project_fact_and_tool_rule_drift(
    remote_server,
    content,
    event_type,
    source,
    remote_type,
    expected_type,
    warning,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": payload["event"]["content"],
                    "memory_type": remote_type,
                    "subject": "remote drift type",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response with observed drift.",
                    "confidence": "confirmed",
                    "evidence_type": payload["event"]["event_type"],
                    "time_validity": "until_changed",
                    "reuse_cases": ["remote_governance_validation"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_project_fact_tool_rule",
        event_type=event_type,
        content=content,
        source=source,
        scope="repo:C:/workspace/memory",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == expected_type
    assert warning in result.warnings


def test_remote_llm_client_payload_includes_governance_rules(remote_server):
    base_url, routes, captured = remote_server
    routes[("POST", "/chat/completions")] = lambda payload: (
        200,
        {"choices": [{"message": {"content": '{"candidates":[]}'}}]},
    )
    event = EventRead(
        id="evt_remote_prompt_rules",
        event_type="user_message",
        content="Prompt rule inspection event.",
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    RemoteLLMClient(
        RemoteAdapterConfig(
            base_url=base_url,
            compatibility=OPENAI_COMPATIBILITY,
            llm_extract_path="/chat/completions",
        )
    ).extract_candidates(event, instructions="Custom extraction instruction.")

    system_content = captured[0]["payload"]["messages"][0]["content"]
    user_payload = json.loads(captured[0]["payload"]["messages"][1]["content"])
    assert "sensitive data" in system_content
    assert "environment_fact" in system_content
    assert "api key" in " ".join(user_payload["governance_rules"])
    assert "Governance rules" in user_payload["instructions"]


def test_remote_embedding_client_openai_compatible_payload_uses_default_model(remote_server):
    base_url, routes, captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "model": payload["model"],
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ],
        },
    )

    result = RemoteEmbeddingClient(
        RemoteAdapterConfig(base_url=base_url, compatibility=OPENAI_COMPATIBILITY)
    ).embed_texts(["first text", "second text"])

    assert result.model == DEFAULT_EMBEDDING_MODEL
    assert result.dimensions == 2
    assert captured[0]["payload"] == {
        "model": DEFAULT_EMBEDDING_MODEL,
        "input": ["first text", "second text"],
    }


def test_remote_embedding_client_dashscope_multimodal_payload(remote_server):
    base_url, routes, captured = remote_server
    routes[("POST", "/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding")] = (
        lambda payload: (
            200,
            {
                "output": {
                    "embeddings": [
                        {"index": 0, "embedding": [0.1, 0.2], "type": "text"},
                        {"index": 1, "embedding": [0.3, 0.4], "type": "text"},
                    ]
                },
                "usage": {"input_tokens": 8},
            },
        )
    )

    result = RemoteEmbeddingClient(
        RemoteAdapterConfig(
            base_url=base_url,
            embedding_compatibility=DASHSCOPE_MULTIMODAL_COMPATIBILITY,
            embedding_path="/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
        )
    ).embed_texts(["first text", "second text"])

    assert result.dimensions == 2
    assert result.model == DEFAULT_EMBEDDING_MODEL
    assert result.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured[0]["payload"] == {
        "model": DEFAULT_EMBEDDING_MODEL,
        "input": {
            "contents": [
                {"text": "first text"},
                {"text": "second text"},
            ]
        },
    }


def test_api_remote_memory_embedding_and_hybrid_search(tmp_path, monkeypatch, remote_server):
    from fastapi.testclient import TestClient

    from memory_system import MemoryItemCreate

    base_url, routes, captured = remote_server

    def embed(payload):
        texts = payload.get("texts") or payload.get("input") or []
        if isinstance(texts, dict):
            texts = [item["text"] for item in texts["contents"]]
        vectors = []
        for text in texts:
            vectors.append([1.0, 0.0] if "发布" in text or "部署" in text else [0.0, 1.0])
        return 200, {"provider": "fake-embedding", "model": "fake-embedding", "vectors": vectors}

    routes[("POST", "/embeddings")] = embed
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    release = store.add_memory(
        MemoryItemCreate(
            content="项目发布前要先运行 ruff check 和 pytest。",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )
    other = store.add_memory(
        MemoryItemCreate(
            content="用户偏好中文技术解释。",
            memory_type="user_preference",
            scope="global",
            subject="answer language",
            confidence="confirmed",
            source_event_ids=["evt_language"],
        )
    )
    store.upsert_memory_embedding(other.id, vector=[0.0, 1.0], model="fake-embedding")

    indexed = client.post(f"/memories/{release.id}/embedding/remote", json={"model": "fake-embedding"})

    assert indexed.status_code == 200
    assert indexed.json()["memory_id"] == release.id
    assert indexed.json()["model"] == "fake-embedding"
    assert store.get_memory_embedding(release.id, model="fake-embedding") is not None

    response = client.post(
        "/memories/search/remote-hybrid",
        json={
            "query": "部署前应该检查什么",
            "scopes": ["repo:C:/workspace/demo", "global"],
            "retrieval_mode": "hybrid",
            "embedding_model": "fake-embedding",
            "limit": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == release.id
    assert len([item for item in captured if item["path"] == "/embeddings"]) == 2


def test_remote_embedding_backfill_indexes_missing_memories(tmp_path, remote_server):
    from memory_system import MemoryItemCreate
    from memory_system.remote_evaluation import backfill_remote_memory_embeddings

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [[float(index + 1), 0.0] for index, _text in enumerate(payload["texts"])],
        },
    )
    store = MemoryStore(tmp_path / "memory.sqlite")
    indexed = store.add_memory(
        MemoryItemCreate(
            content="Already indexed memory.",
            memory_type="project_fact",
            scope="repo:C:/workspace/demo",
            subject="indexed",
            confidence="confirmed",
            source_event_ids=["evt_indexed"],
        )
    )
    missing = store.add_memory(
        MemoryItemCreate(
            content="Missing embedding memory.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="missing",
            confidence="confirmed",
            source_event_ids=["evt_missing"],
        )
    )
    store.upsert_memory_embedding(indexed.id, vector=[0.0, 1.0], model="fake-embedding")

    result = backfill_remote_memory_embeddings(
        store,
        RemoteEmbeddingClient(RemoteAdapterConfig(base_url=base_url)),
        model="fake-embedding",
        scope="repo:C:/workspace/demo",
        limit=10,
    )

    assert result.requested_count == 1
    assert result.embedded_count == 1
    assert result.memory_ids == [missing.id]
    assert store.get_memory_embedding(missing.id, model="fake-embedding") is not None
    assert store.get_memory_embedding(indexed.id, model="fake-embedding").vector == [0.0, 1.0]


def test_remote_retrieval_fixture_compares_keyword_semantic_and_hybrid(remote_server):
    from memory_system.remote_evaluation import evaluate_remote_retrieval_fixture

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [_semantic_fixture_vector(text) for text in payload["texts"]],
        },
    )
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "golden_cases"
        / "semantic_retrieval.jsonl"
    )

    result = evaluate_remote_retrieval_fixture(
        fixture,
        RemoteEmbeddingClient(RemoteAdapterConfig(base_url=base_url)),
        model="fake-embedding",
    )

    assert result.summary.case_count == 50
    assert result.summary.failed_by_mode["keyword"] > 0
    assert result.summary.passed_by_mode["semantic"] == 50
    assert result.summary.passed_by_mode["hybrid"] == 50
    assert result.summary.passed_by_mode["guarded_hybrid"] == 50
    assert result.summary.false_negative_by_mode["hybrid"] == 0
    assert result.summary.ambiguous_by_mode["guarded_hybrid"] == 0
    category = result.category_summary["semantic_paraphrase_retrieval"]
    assert category.case_count == 50
    assert category.passed_by_mode["guarded_hybrid"] == 50
    assert any(warning.startswith("hybrid_reduced_false_negatives:") for warning in result.warnings)


def test_remote_llm_client_judges_retrieval_generic(tmp_path, remote_server):
    from memory_system import MemoryItemCreate

    base_url, routes, captured = remote_server
    store = MemoryStore(tmp_path / "memory.sqlite")
    memory = store.add_memory(
        MemoryItemCreate(
            content="Run ruff check and pytest before release.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )

    def handle_judge(payload):
        assert payload["schema"] == "memory_system.remote_recall_judge.v1"
        assert payload["candidates"][0]["memory_id"] == memory.id
        return (
            200,
            {
                "provider": "fake-llm",
                "decision": "accepted",
                "selected_memory_ids": [memory.id],
                "reason": "The release workflow directly answers the query.",
                "risk": "low",
            },
        )

    routes[("POST", "/memory/extract")] = handle_judge

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).judge_retrieval(
        query="What should I run before release?",
        memories=[memory],
    )

    assert result.decision == "accepted"
    assert result.selected_memory_ids == [memory.id]
    assert result.reason.startswith("The release workflow")
    assert captured[-1]["path"] == "/memory/extract"


def test_remote_retrieval_fixture_can_include_llm_guarded_hybrid(remote_server):
    from memory_system.remote_evaluation import evaluate_remote_retrieval_fixture

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [_semantic_fixture_vector(text) for text in payload["texts"]],
        },
    )

    def handle_judge(payload):
        candidates = payload["candidates"]
        selected_candidate = next(
            (
                candidate
                for candidate in candidates
                if candidate.get("local_decision") == "accepted"
            ),
            candidates[0] if candidates else None,
        )
        selected = selected_candidate["memory_id"] if selected_candidate else "missing"
        return (
            200,
            {
                "provider": "fake-llm",
                "decision": "accepted" if selected_candidate else "rejected",
                "selected_memory_ids": [selected] if selected_candidate else [],
                "reason": "Select the top semantic candidate for this deterministic fixture.",
                "risk": "low",
            },
        )

    routes[("POST", "/memory/extract")] = handle_judge
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "golden_cases"
        / "semantic_retrieval.jsonl"
    )

    result = evaluate_remote_retrieval_fixture(
        fixture,
        RemoteEmbeddingClient(RemoteAdapterConfig(base_url=base_url)),
        remote_llm=RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)),
        include_llm_judge=True,
        include_selective_llm_judge=True,
        model="fake-embedding",
    )

    assert "llm_guarded_hybrid" in result.summary.modes
    assert "selective_llm_guarded_hybrid" in result.summary.modes
    assert result.summary.passed_by_mode["llm_guarded_hybrid"] == 50
    assert result.summary.passed_by_mode["selective_llm_guarded_hybrid"] == 50
    assert result.summary.ambiguous_by_mode["llm_guarded_hybrid"] == 0
    assert result.summary.judge_called_by_mode["selective_llm_guarded_hybrid"] == 0
    assert result.summary.judge_skipped_by_mode["selective_llm_guarded_hybrid"] == 50
    assert result.summary.judge_skip_reason_by_mode["selective_llm_guarded_hybrid"] == {
        "local_guard_confident": 50
    }
    judge = result.items[0].judge_by_mode["llm_guarded_hybrid"]
    assert judge.decision == "accepted"
    assert judge.reason.startswith("Select the top semantic candidate")
    assert judge.selected_aliases == ["release_000_target"]
    assert judge.candidate_aliases[0] == "release_000_target"
    selective_judge = result.items[0].judge_by_mode["selective_llm_guarded_hybrid"]
    assert selective_judge.provider == "local"
    assert selective_judge.metadata["remote_judge_called"] is False
    assert selective_judge.metadata["skip_reason"] == "local_guard_confident"


def test_semantic_retrieval_fixture_shape():
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "golden_cases"
        / "semantic_retrieval.jsonl"
    )
    cases = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]

    assert len(cases) == 50
    assert len({case["name"] for case in cases}) == 50
    assert {case["category"] for case in cases} == {"semantic_paraphrase_retrieval"}
    assert all(case["search"]["limit"] == 1 for case in cases)
    assert all(len(case["memories"]) == 3 for case in cases)


def test_semantic_retrieval_v2_fixture_shape():
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "golden_cases"
        / "semantic_retrieval_v2.jsonl"
    )
    cases = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    categories = {case["category"] for case in cases}
    daily_cases = [case for case in cases if case["category"].startswith("v2_daily_")]

    assert len(cases) == 200
    assert len({case["name"] for case in cases}) == 200
    assert len(categories) == 20
    assert len(daily_cases) == 90
    assert all(case["mode"] == "retrieval" for case in cases)
    assert all(case["search"]["limit"] == 1 for case in cases)
    assert all(len(case["memories"]) == 3 for case in cases)


def test_semantic_retrieval_public_fixture_shape():
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "golden_cases"
        / "semantic_retrieval_public.jsonl"
    )
    cases = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    categories = {case["category"] for case in cases}
    benchmark_families = {case["benchmark_family"] for case in cases}
    no_match_cases = [
        case for case in cases if case["expected"].get("exact_aliases") == []
    ]
    update_cases = [
        case
        for case in cases
        if any(memory.get("status") == "stale" for memory in case["memories"])
    ]

    assert len(cases) == 300
    assert len({case["name"] for case in cases}) == 300
    assert len(categories) == 15
    assert benchmark_families == {"locomo", "longmemeval", "realmem"}
    assert len(no_match_cases) == 40
    assert len(update_cases) == 40
    assert all(case["mode"] == "retrieval" for case in cases)
    assert all(case["search"]["limit"] == 1 for case in cases)
    assert all(len(case["memories"]) == 3 for case in cases)


def test_semantic_retrieval_cn_fixture_shape():
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "golden_cases"
        / "semantic_retrieval_cn.jsonl"
    )
    cases = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    categories = {case["category"] for case in cases}
    no_match_cases = [
        case for case in cases if case["expected"].get("exact_aliases") == []
    ]
    marker_pattern = re.compile(r"(RET_|TASK_|GRAPH_|CONTEXT_|SEMANTIC_|CN_)")
    chinese_pattern = re.compile(r"[\u4e00-\u9fff]")

    assert len(cases) == 150
    assert len({case["name"] for case in cases}) == 150
    assert categories == {
        "cn_work_release",
        "cn_work_debug",
        "cn_work_docs",
        "cn_work_encoding",
        "cn_work_environment",
        "cn_work_git",
        "cn_memory_write_policy",
        "cn_memory_recall_policy",
        "cn_privacy_boundary",
        "cn_daily_food",
        "cn_daily_schedule",
        "cn_daily_answer_style",
        "cn_daily_shopping",
        "cn_no_match_daily",
        "cn_no_match_work",
    }
    assert len(no_match_cases) == 20
    assert all(case["mode"] == "retrieval" for case in cases)
    assert all(case["search"]["limit"] == 1 for case in cases)
    assert all(len(case["memories"]) == 3 for case in cases)
    assert all(chinese_pattern.search(case["search"]["query"]) for case in cases)
    assert all(
        any(chinese_pattern.search(memory["content"]) for memory in case["memories"])
        for case in cases
    )
    assert all(
        not marker_pattern.search(case["search"]["query"])
        and all(not marker_pattern.search(memory["content"]) for memory in case["memories"])
        for case in cases
    )


def test_remote_retrieval_cn_fixture_guarded_hybrid_handles_chinese(remote_server):
    from memory_system.remote_evaluation import evaluate_remote_retrieval_fixture

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-cn-embedding",
            "model": "fake-cn-embedding",
            "vectors": [_semantic_cn_fixture_vector(text) for text in payload["texts"]],
        },
    )
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "golden_cases"
        / "semantic_retrieval_cn.jsonl"
    )

    result = evaluate_remote_retrieval_fixture(
        fixture,
        RemoteEmbeddingClient(RemoteAdapterConfig(base_url=base_url)),
        model="fake-cn-embedding",
    )

    assert result.summary.case_count == 150
    assert result.summary.passed_by_mode["guarded_hybrid"] == 150
    assert result.summary.false_negative_by_mode["guarded_hybrid"] == 0
    assert result.summary.unexpected_by_mode["guarded_hybrid"] == 0
    assert result.summary.passed_by_mode["semantic"] < 150
    assert result.category_summary["cn_no_match_daily"].passed_by_mode[
        "guarded_hybrid"
    ] == 10
    assert result.category_summary["cn_no_match_work"].passed_by_mode[
        "guarded_hybrid"
    ] == 10
    assert result.category_summary["cn_privacy_boundary"].passed_by_mode[
        "guarded_hybrid"
    ] == 10


def test_api_remote_embedding_backfill_and_retrieval_evaluation(
    tmp_path,
    monkeypatch,
    remote_server,
):
    from fastapi.testclient import TestClient

    from memory_system import MemoryItemCreate

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [_semantic_fixture_vector(text) for text in payload["texts"]],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    memory = store.add_memory(
        MemoryItemCreate(
            content="Before deployment run ruff check and pytest.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )

    backfill = client.post(
        "/memories/embeddings/remote-backfill",
        json={"model": "fake-embedding", "scope": "repo:C:/workspace/demo"},
    )

    assert backfill.status_code == 200
    assert backfill.json()["memory_ids"] == [memory.id]

    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "golden_cases"
        / "semantic_retrieval.jsonl"
    )
    evaluation = client.post(
        "/remote/evaluate-retrieval",
        json={"fixture_path": str(fixture), "model": "fake-embedding"},
    )

    assert evaluation.status_code == 200
    assert evaluation.json()["summary"]["passed_by_mode"]["hybrid"] == 50
    assert evaluation.json()["summary"]["passed_by_mode"]["guarded_hybrid"] == 50
    assert (
        evaluation.json()["category_summary"]["semantic_paraphrase_retrieval"]["case_count"]
        == 50
    )


def test_api_remote_guarded_hybrid_marks_close_scores_ambiguous(
    tmp_path,
    monkeypatch,
    remote_server,
):
    from fastapi.testclient import TestClient

    from memory_system import MemoryItemCreate

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [[1.0, 0.0] for _text in payload["texts"]],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    first = store.add_memory(
        MemoryItemCreate(
            content="Run release checks before deployment.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )
    second = store.add_memory(
        MemoryItemCreate(
            content="Validate browser rendering before deployment.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="browser checks",
            confidence="confirmed",
            source_event_ids=["evt_browser"],
        )
    )
    store.upsert_memory_embedding(first.id, vector=[0.99, 0.01], model="fake-embedding")
    store.upsert_memory_embedding(second.id, vector=[0.98, 0.02], model="fake-embedding")

    response = client.post(
        "/memories/search/remote-guarded-hybrid",
        json={
            "query": "What should happen next?",
            "scopes": ["repo:C:/workspace/demo"],
            "embedding_model": "fake-embedding",
            "limit": 1,
            "guard_top_k": 2,
            "guard_ambiguity_margin": 0.03,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["memories"] == []
    assert "guard_ambiguous_top_candidates" in payload["warnings"]
    assert [decision["decision"] for decision in payload["decisions"][:2]] == [
        "ambiguous",
        "ambiguous",
    ]


def test_api_remote_guarded_hybrid_uses_intent_to_resolve_close_scores(
    tmp_path,
    monkeypatch,
    remote_server,
):
    from fastapi.testclient import TestClient

    from memory_system import MemoryItemCreate

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [[1.0, 0.0] for _text in payload["texts"]],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    release = store.add_memory(
        MemoryItemCreate(
            content="Run release checks before deployment.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )
    browser = store.add_memory(
        MemoryItemCreate(
            content="Validate browser rendering before deployment.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="browser checks",
            confidence="confirmed",
            source_event_ids=["evt_browser"],
        )
    )
    store.upsert_memory_embedding(release.id, vector=[0.99, 0.01], model="fake-embedding")
    store.upsert_memory_embedding(browser.id, vector=[0.98, 0.02], model="fake-embedding")

    response = client.post(
        "/memories/search/remote-guarded-hybrid",
        json={
            "query": "What should happen before release?",
            "scopes": ["repo:C:/workspace/demo"],
            "embedding_model": "fake-embedding",
            "limit": 1,
            "guard_top_k": 2,
            "guard_ambiguity_margin": 0.03,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["memories"][0]["id"] == release.id
    assert payload["decisions"][0]["decision"] == "accepted"
    assert payload["decisions"][0]["reason"] == "intent_match_clear_enough"
    assert payload["decisions"][0]["intent_score"] > payload["decisions"][1]["intent_score"]
    assert "guard_intent_reranked_top_candidates" in payload["warnings"]


def test_api_remote_llm_guarded_hybrid_accepts_selected_memory(
    tmp_path,
    monkeypatch,
    remote_server,
):
    from fastapi.testclient import TestClient

    from memory_system import MemoryItemCreate

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [[1.0, 0.0] for _text in payload["texts"]],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    release = store.add_memory(
        MemoryItemCreate(
            content="Run release checks before deployment.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )
    browser = store.add_memory(
        MemoryItemCreate(
            content="Validate browser rendering before deployment.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="browser checks",
            confidence="confirmed",
            source_event_ids=["evt_browser"],
        )
    )
    store.upsert_memory_embedding(release.id, vector=[0.99, 0.01], model="fake-embedding")
    store.upsert_memory_embedding(browser.id, vector=[0.98, 0.02], model="fake-embedding")

    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "decision": "accepted",
            "selected_memory_ids": [release.id],
            "reason": "The release memory directly answers the query.",
            "risk": "low",
        },
    )

    response = client.post(
        "/memories/search/remote-llm-guarded-hybrid",
        json={
            "query": "What should happen before release?",
            "scopes": ["repo:C:/workspace/demo"],
            "embedding_model": "fake-embedding",
            "limit": 1,
            "guard_top_k": 2,
            "guard_ambiguity_margin": 0.03,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["judge"]["decision"] == "accepted"
    assert payload["memories"][0]["id"] == release.id
    assert payload["local_guard"]["decisions"][0]["memory_id"] == release.id


def test_api_remote_llm_guarded_hybrid_rejects_no_match(
    tmp_path,
    monkeypatch,
    remote_server,
):
    from fastapi.testclient import TestClient

    from memory_system import MemoryItemCreate

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [[1.0, 0.0] for _text in payload["texts"]],
        },
    )
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "decision": "rejected",
            "selected_memory_ids": [],
            "reason": "None of the candidates answers the query.",
            "risk": "low",
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    memory = store.add_memory(
        MemoryItemCreate(
            content="Run release checks before deployment.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )
    store.upsert_memory_embedding(memory.id, vector=[1.0, 0.0], model="fake-embedding")

    response = client.post(
        "/memories/search/remote-llm-guarded-hybrid",
        json={
            "query": "Do we know the user's private token?",
            "scopes": ["repo:C:/workspace/demo"],
            "embedding_model": "fake-embedding",
            "limit": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["judge"]["decision"] == "rejected"
    assert payload["memories"] == []


def test_api_remote_selective_llm_guarded_hybrid_skips_confident_local(
    tmp_path,
    monkeypatch,
    remote_server,
):
    from fastapi.testclient import TestClient

    from memory_system import MemoryItemCreate

    base_url, routes, captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [[1.0, 0.0] for _text in payload["texts"]],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    target = store.add_memory(
        MemoryItemCreate(
            content="Run release checks before deployment.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )
    other = store.add_memory(
        MemoryItemCreate(
            content="Use UTF-8 code page when console text is garbled.",
            memory_type="troubleshooting",
            scope="global",
            subject="console encoding",
            confidence="confirmed",
            source_event_ids=["evt_encoding"],
        )
    )
    store.upsert_memory_embedding(target.id, vector=[1.0, 0.0], model="fake-embedding")
    store.upsert_memory_embedding(other.id, vector=[0.0, 1.0], model="fake-embedding")

    response = client.post(
        "/memories/search/remote-selective-llm-guarded-hybrid",
        json={
            "query": "What should happen before release?",
            "scopes": ["repo:C:/workspace/demo", "global"],
            "embedding_model": "fake-embedding",
            "limit": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["memories"][0]["id"] == target.id
    assert payload["judge"]["provider"] == "local"
    assert payload["judge"]["metadata"]["remote_judge_called"] is False
    assert payload["judge"]["metadata"]["skip_reason"] == "local_guard_confident"
    assert [item["path"] for item in captured].count("/memory/extract") == 0


def test_api_remote_selective_llm_guarded_hybrid_calls_on_concrete_fact_risk(
    tmp_path,
    monkeypatch,
    remote_server,
):
    from fastapi.testclient import TestClient

    from memory_system import MemoryItemCreate

    base_url, routes, captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [[1.0, 0.0] for _text in payload["texts"]],
        },
    )
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "decision": "rejected",
            "selected_memory_ids": [],
            "reason": "The candidate does not contain the requested SLA value.",
            "risk": "medium",
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    memory = store.add_memory(
        MemoryItemCreate(
            content="本地示例数据库通常使用 data/memory.sqlite。",
            memory_type="environment_fact",
            scope="repo:C:/workspace/demo",
            subject="示例数据库",
            confidence="confirmed",
            source_event_ids=["evt_db"],
        )
    )
    store.upsert_memory_embedding(memory.id, vector=[1.0, 0.0], model="fake-embedding")

    response = client.post(
        "/memories/search/remote-selective-llm-guarded-hybrid",
        json={
            "query": "当前服务的 SLA 数字是多少？",
            "scopes": ["repo:C:/workspace/demo"],
            "embedding_model": "fake-embedding",
            "limit": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["memories"] == []
    assert payload["judge"]["provider"] == "fake-llm"
    assert payload["judge"]["metadata"]["remote_judge_called"] is True
    assert payload["judge"]["metadata"]["call_reason"] == "concrete_fact_risk_query"
    assert [item["path"] for item in captured].count("/memory/extract") == 1


def test_api_remote_selective_llm_guarded_hybrid_calls_on_ambiguous_local(
    tmp_path,
    monkeypatch,
    remote_server,
):
    from fastapi.testclient import TestClient

    from memory_system import MemoryItemCreate

    base_url, routes, captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [[1.0, 0.0] for _text in payload["texts"]],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    release = store.add_memory(
        MemoryItemCreate(
            content="Run release checks before deployment.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )
    browser = store.add_memory(
        MemoryItemCreate(
            content="Validate browser rendering before deployment.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="browser checks",
            confidence="confirmed",
            source_event_ids=["evt_browser"],
        )
    )
    store.upsert_memory_embedding(release.id, vector=[0.99, 0.01], model="fake-embedding")
    store.upsert_memory_embedding(browser.id, vector=[0.98, 0.02], model="fake-embedding")
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "decision": "accepted",
            "selected_memory_ids": [release.id],
            "reason": "The release memory resolves the local ambiguity.",
            "risk": "low",
        },
    )

    response = client.post(
        "/memories/search/remote-selective-llm-guarded-hybrid",
        json={
            "query": "What should happen next?",
            "scopes": ["repo:C:/workspace/demo"],
            "embedding_model": "fake-embedding",
            "limit": 1,
            "guard_top_k": 2,
            "guard_ambiguity_margin": 0.03,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["memories"][0]["id"] == release.id
    assert payload["judge"]["metadata"]["remote_judge_called"] is True
    assert payload["judge"]["metadata"]["call_reason"] == "local_ambiguous_candidates"
    assert [item["path"] for item in captured].count("/memory/extract") == 1


def test_api_remote_extract_is_dry_run(tmp_path, monkeypatch, remote_server):
    from fastapi.testclient import TestClient

    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "candidates": [
                {
                    "content": "Remote API candidate should not be committed automatically.",
                    "memory_type": "project_fact",
                    "scope": "repo:C:/workspace/remote",
                    "subject": "remote dry run",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Remote dry-run extraction.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "until_changed",
                    "reuse_cases": ["remote_validation"],
                    "scores": {"long_term": 0.8, "evidence": 0.8, "reuse": 0.7},
                }
            ]
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    event = client.post(
        "/events",
        json={
            "event_type": "user_message",
            "content": "Remote API dry-run extraction.",
            "source": "conversation",
            "scope": "repo:C:/workspace/remote",
        },
    ).json()

    response = client.post(f"/remote/extract/{event['id']}", json={})

    assert response.status_code == 200
    assert response.json()["candidates"][0]["subject"] == "remote dry run"
    assert client.app.state.runtime.memories.list_candidates() == []


def test_api_remote_import_creates_pending_candidates_only(tmp_path, monkeypatch, remote_server):
    from fastapi.testclient import TestClient

    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "warnings": ["review before commit"],
            "candidates": [
                {
                    "content": "Remote import candidate stays pending.",
                    "memory_type": "workflow",
                    "scope": "repo:C:/workspace/remote-import",
                    "subject": "remote import",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Remote extractor proposed this workflow.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["remote_import_validation"],
                    "scores": {"long_term": 0.8, "evidence": 0.9, "reuse": 0.8},
                }
            ],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    event = client.post(
        "/events",
        json={
            "event_type": "user_message",
            "content": "Remote import should create only pending candidates.",
            "source": "conversation",
            "scope": "repo:C:/workspace/remote-import",
        },
    ).json()

    response = client.post(f"/candidates/from-event/{event['id']}/remote", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "fake-llm"
    assert payload["warnings"] == ["review before commit"]
    assert payload["metadata"]["auto_committed"] is False
    candidate = payload["candidates"][0]
    assert candidate["status"] == "pending"
    assert candidate["subject"] == "remote import"
    assert [item.id for item in client.app.state.runtime.memories.list_candidates()] == [
        candidate["id"]
    ]

    decision = client.post(f"/candidates/{candidate['id']}/evaluate").json()
    assert decision["decision"] == "write"


def test_api_remote_candidate_evaluation_is_read_only(
    tmp_path,
    monkeypatch,
    remote_server,
):
    from fastapi.testclient import TestClient

    base_url, routes, _captured = remote_server

    def extract(payload):
        event = payload["event"]
        if "Remote eval preference" in event["content"]:
            return (
                200,
                {
                    "provider": "fake-llm",
                    "candidates": [
                        {
                            "content": "Remote eval preference should be remembered.",
                            "memory_type": "user_preference",
                            "scope": event["scope"],
                            "subject": "remote eval preference",
                            "source_event_ids": [event["id"]],
                            "reason": "Remote evaluation test.",
                            "confidence": "confirmed",
                            "evidence_type": "direct_user_statement",
                            "time_validity": "persistent",
                            "reuse_cases": ["remote_eval_validation"],
                            "scores": {"long_term": 0.8, "evidence": 0.9, "reuse": 0.8},
                        }
                    ],
                },
            )
        return 200, {"provider": "fake-llm", "candidates": []}

    routes[("POST", "/memory/extract")] = extract
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    first_event = client.post(
        "/events",
        json={
            "event_type": "user_message",
            "content": "Remote eval preference: remember Chinese technical answers.",
            "source": "conversation",
            "scope": "global",
        },
    ).json()
    second_event = client.post(
        "/events",
        json={
            "event_type": "user_message",
            "content": "Please rewrite this one sentence.",
            "source": "conversation",
            "scope": "global",
        },
    ).json()

    response = client.post(
        "/remote/evaluate-candidates",
        json={"event_ids": [first_event["id"], second_event["id"]]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["event_count"] == 2
    assert payload["summary"]["remote_candidate_count"] == 1
    assert payload["summary"]["local_candidate_count"] == 1
    assert payload["summary"]["overlap_event_count"] == 1
    assert client.app.state.runtime.memories.list_candidates() == []


def test_cli_remote_status_json(monkeypatch, capsys, tmp_path):
    from memory_system.cli import main

    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("MEMORY_REMOTE_API_KEY", "secret-token")

    result = main(["--db", str(tmp_path / "memory.sqlite"), "remote", "status", "--json"])

    assert result == 0
    payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert payload["configured"] is True
    assert payload["api_key_configured"] is True
    assert "secret-token" not in json.dumps(payload)


def test_cli_remote_extract_json(tmp_path, monkeypatch, capsys, remote_server):
    from memory_system.cli import main

    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": "CLI remote extraction candidate.",
                    "memory_type": "workflow",
                    "subject": "cli remote",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "CLI remote extraction test.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["cli_validation"],
                    "scores": {"long_term": 0.8, "evidence": 0.8, "reuse": 0.8},
                }
            ],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    db_path = tmp_path / "memory.sqlite"
    event = EventLog(db_path).record_event(
        EventCreate(
            event_type="user_message",
            content="CLI remote extraction event.",
            source="conversation",
            scope="global",
        )
    )

    result = main(["--db", str(db_path), "remote", "extract", event.id, "--json"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "fake-llm"
    assert payload["candidates"][0]["subject"] == "cli remote"


def test_cli_remote_import_json_persists_candidates(
    tmp_path,
    monkeypatch,
    capsys,
    remote_server,
):
    from memory_system.cli import main

    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": "CLI remote import candidate.",
                    "memory_type": "workflow",
                    "subject": "cli remote import",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "CLI remote import test.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["cli_import_validation"],
                    "scores": {"long_term": 0.8, "evidence": 0.8, "reuse": 0.8},
                }
            ],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    db_path = tmp_path / "memory.sqlite"
    event = EventLog(db_path).record_event(
        EventCreate(
            event_type="user_message",
            content="CLI remote import event.",
            source="conversation",
            scope="global",
        )
    )

    result = main(["--db", str(db_path), "remote", "import", event.id, "--json"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    candidate = payload["candidates"][0]
    assert candidate["status"] == "pending"
    assert candidate["subject"] == "cli remote import"
    assert MemoryStore(db_path).get_candidate(candidate["id"]).subject == "cli remote import"


def test_cli_remote_evaluate_json_is_read_only(
    tmp_path,
    monkeypatch,
    capsys,
    remote_server,
):
    from memory_system.cli import main

    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": "CLI remote evaluate candidate.",
                    "memory_type": "workflow",
                    "subject": "cli remote evaluate",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "CLI remote evaluate test.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["cli_eval_validation"],
                    "scores": {"long_term": 0.8, "evidence": 0.8, "reuse": 0.8},
                }
            ],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    db_path = tmp_path / "memory.sqlite"
    event = EventLog(db_path).record_event(
        EventCreate(
            event_type="user_message",
            content="CLI remote evaluate event.",
            source="conversation",
            scope="global",
        )
    )

    result = main(
        [
            "--db",
            str(db_path),
            "remote",
            "evaluate",
            "--event-id",
            event.id,
            "--json",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["event_count"] == 1
    assert payload["summary"]["remote_candidate_count"] == 1
    assert MemoryStore(db_path).list_candidates() == []


def test_cli_remote_embed_backfill_and_evaluate_retrieval_json(
    tmp_path,
    monkeypatch,
    capsys,
    remote_server,
):
    from memory_system import MemoryItemCreate
    from memory_system.cli import main

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [_semantic_fixture_vector(text) for text in payload["texts"]],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    db_path = tmp_path / "memory.sqlite"
    memory = MemoryStore(db_path).add_memory(
        MemoryItemCreate(
            content="Before deployment run ruff check and pytest.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )

    result = main(
        [
            "--db",
            str(db_path),
            "remote",
            "embed-backfill",
            "--model",
            "fake-embedding",
            "--json",
        ]
    )

    assert result == 0
    backfill = json.loads(capsys.readouterr().out)
    assert backfill["memory_ids"] == [memory.id]

    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "golden_cases"
        / "semantic_retrieval.jsonl"
    )
    result = main(
        [
            "--db",
            str(db_path),
            "remote",
            "evaluate-retrieval",
            "--fixture",
            str(fixture),
            "--model",
            "fake-embedding",
            "--json",
        ]
    )

    assert result == 0
    evaluation = json.loads(capsys.readouterr().out)
    assert evaluation["summary"]["failed_by_mode"]["keyword"] > 0
    assert evaluation["summary"]["passed_by_mode"]["hybrid"] == 50
    assert evaluation["summary"]["passed_by_mode"]["guarded_hybrid"] == 50

    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "decision": "accepted",
            "selected_memory_ids": [
                next(
                    (
                        candidate
                        for candidate in payload.get("candidates", [])
                        if candidate.get("local_decision") == "accepted"
                    ),
                    payload["candidates"][0] if payload.get("candidates") else {},
                ).get("memory_id", "missing")
                if payload.get("candidates")
                else "missing"
            ],
            "reason": "Select the top deterministic retrieval candidate.",
            "risk": "low",
        },
    )
    result = main(
        [
            "--db",
            str(db_path),
            "remote",
            "evaluate-retrieval",
            "--fixture",
            str(fixture),
            "--model",
            "fake-embedding",
            "--llm-judge",
            "--json",
        ]
    )

    assert result == 0
    evaluation = json.loads(capsys.readouterr().out)
    assert evaluation["summary"]["passed_by_mode"]["llm_guarded_hybrid"] == 50
    judge = evaluation["items"][0]["judge_by_mode"]["llm_guarded_hybrid"]
    assert judge["decision"] == "accepted"
    assert judge["reason"].startswith("Select the top deterministic")
    assert judge["selected_aliases"] == ["release_000_target"]
    assert judge["candidate_aliases"][0] == "release_000_target"

    result = main(
        [
            "--db",
            str(db_path),
            "remote",
            "evaluate-retrieval",
            "--fixture",
            str(fixture),
            "--model",
            "fake-embedding",
            "--selective-llm-judge",
            "--json",
        ]
    )

    assert result == 0
    evaluation = json.loads(capsys.readouterr().out)
    assert evaluation["summary"]["passed_by_mode"]["selective_llm_guarded_hybrid"] == 50
    assert evaluation["summary"]["judge_called_by_mode"]["selective_llm_guarded_hybrid"] == 0
    assert evaluation["summary"]["judge_skipped_by_mode"]["selective_llm_guarded_hybrid"] == 50
    judge = evaluation["items"][0]["judge_by_mode"]["selective_llm_guarded_hybrid"]
    assert judge["provider"] == "local"
    assert judge["metadata"]["skip_reason"] == "local_guard_confident"


def test_cli_remote_guarded_hybrid_search_json_accepts_clear_top(
    tmp_path,
    monkeypatch,
    capsys,
    remote_server,
):
    from memory_system import MemoryItemCreate
    from memory_system.cli import main

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [[1.0, 0.0] for _text in payload["texts"]],
        },
    )
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    db_path = tmp_path / "memory.sqlite"
    store = MemoryStore(db_path)
    target = store.add_memory(
        MemoryItemCreate(
            content="Run release checks before deployment.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checks",
            confidence="confirmed",
            source_event_ids=["evt_release"],
        )
    )
    other = store.add_memory(
        MemoryItemCreate(
            content="Use UTF-8 code page when console text is garbled.",
            memory_type="troubleshooting",
            scope="global",
            subject="console encoding",
            confidence="confirmed",
            source_event_ids=["evt_encoding"],
        )
    )
    store.upsert_memory_embedding(target.id, vector=[1.0, 0.0], model="fake-embedding")
    store.upsert_memory_embedding(other.id, vector=[0.0, 1.0], model="fake-embedding")
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "decision": "accepted",
            "selected_memory_ids": [target.id],
            "reason": "The release memory directly answers the query.",
            "risk": "low",
        },
    )

    result = main(
        [
            "--db",
            str(db_path),
            "remote",
            "guarded-hybrid-search",
            "What should happen before release?",
            "--model",
            "fake-embedding",
            "--scope",
            "repo:C:/workspace/demo",
            "--scope",
            "global",
            "--limit",
            "1",
            "--json",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["memories"][0]["id"] == target.id
    assert payload["decisions"][0]["decision"] == "accepted"

    result = main(
        [
            "--db",
            str(db_path),
            "remote",
            "llm-guarded-hybrid-search",
            "What should happen before release?",
            "--model",
            "fake-embedding",
            "--scope",
            "repo:C:/workspace/demo",
            "--scope",
            "global",
            "--limit",
            "1",
            "--json",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["judge"]["decision"] == "accepted"
    assert payload["memories"][0]["id"] == target.id

    result = main(
        [
            "--db",
            str(db_path),
            "remote",
            "selective-llm-guarded-hybrid-search",
            "What should happen before release?",
            "--model",
            "fake-embedding",
            "--scope",
            "repo:C:/workspace/demo",
            "--scope",
            "global",
            "--limit",
            "1",
            "--json",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["memories"][0]["id"] == target.id
    assert payload["judge"]["provider"] == "local"
    assert payload["metadata"]["remote_judge_called"] is False
    assert payload["metadata"]["skip_reason"] == "local_guard_confident"
