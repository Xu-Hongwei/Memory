from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import Any

import pytest

from memory_system import EventCreate, EventLog, MemoryStore, create_app
from memory_system.remote import (
    DEFAULT_DEEPSEEK_BASE_URL,
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
    monkeypatch.delenv("MEMORY_REMOTE_LLM_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
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


def test_deepseek_env_config_uses_openai_compatible_defaults(monkeypatch):
    monkeypatch.delenv("MEMORY_REMOTE_BASE_URL", raising=False)
    monkeypatch.delenv("MEMORY_REMOTE_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_REMOTE_COMPATIBILITY", raising=False)
    monkeypatch.delenv("MEMORY_REMOTE_LLM_MODEL", raising=False)
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    config = RemoteAdapterConfig.from_env()

    assert config.base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert config.api_key == "deepseek-key"
    assert config.compatibility == OPENAI_COMPATIBILITY
    assert config.llm_extract_path == "/chat/completions"
    assert config.health_path == "/models"
    assert config.llm_model == "deepseek-v4-flash"
    assert config.embedding_model == DEFAULT_EMBEDDING_MODEL


def test_split_remote_env_uses_deepseek_for_llm_and_dashscope_for_embedding(monkeypatch):
    for key in (
        "MEMORY_REMOTE_BASE_URL",
        "MEMORY_REMOTE_API_KEY",
        "MEMORY_REMOTE_COMPATIBILITY",
        "MEMORY_REMOTE_LLM_MODEL",
        "LLM_REMOTE_BASE_URL",
        "LLM_REMOTE_API_KEY",
        "LLM_REMOTE_MODEL",
        "LLM_REMOTE_LLM_MODEL",
        "EMBEDDING_REMOTE_BASE_URL",
        "EMBEDDING_REMOTE_API_KEY",
        "EMBEDDING_REMOTE_MODEL",
        "EMBEDDING_REMOTE_EMBEDDING_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")

    llm_config = RemoteAdapterConfig.llm_from_env()
    embedding_config = RemoteAdapterConfig.embedding_from_env()

    assert llm_config.base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert llm_config.api_key == "deepseek-key"
    assert llm_config.llm_model == "deepseek-v4-flash"
    assert embedding_config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert embedding_config.api_key == "dash-key"
    assert embedding_config.embedding_compatibility == DASHSCOPE_MULTIMODAL_COMPATIBILITY
    assert embedding_config.embedding_path == DASHSCOPE_MULTIMODAL_EMBEDDING_URL
    assert embedding_config.embedding_model == DEFAULT_EMBEDDING_MODEL


def test_explicit_embedding_remote_env_overrides_dashscope(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")
    monkeypatch.setenv("EMBEDDING_REMOTE_BASE_URL", "https://embedding.example.test/v1")
    monkeypatch.setenv("EMBEDDING_REMOTE_API_KEY", "embedding-key")
    monkeypatch.setenv("EMBEDDING_REMOTE_MODEL", "embedding-small")
    monkeypatch.setenv("EMBEDDING_REMOTE_COMPATIBILITY", "openai")

    config = RemoteAdapterConfig.embedding_from_env()

    assert config.base_url == "https://embedding.example.test/v1"
    assert config.api_key == "embedding-key"
    assert config.embedding_model == "embedding-small"
    assert config.embedding_compatibility == OPENAI_COMPATIBILITY
    assert config.embedding_path == "/embeddings"


def test_llm_remote_model_alias_overrides_model(monkeypatch):
    monkeypatch.setenv("LLM_REMOTE_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("LLM_REMOTE_API_KEY", "llm-key")
    monkeypatch.setenv("LLM_REMOTE_MODEL", "llm-alias-model")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    config = RemoteAdapterConfig.llm_from_env()

    assert config.base_url == "https://llm.example.test/v1"
    assert config.api_key == "llm-key"
    assert config.llm_model == "llm-alias-model"


def test_memory_remote_env_overrides_deepseek_env(monkeypatch):
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("MEMORY_REMOTE_API_KEY", "memory-key")
    monkeypatch.setenv("MEMORY_REMOTE_LLM_MODEL", "memory-model")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    config = RemoteAdapterConfig.from_env()

    assert config.base_url == "https://example.test/v1"
    assert config.api_key == "memory-key"
    assert config.llm_model == "memory-model"


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


def test_remote_llm_client_openai_compatible_recall_planner(remote_server):
    base_url, routes, captured = remote_server
    routes[("POST", "/chat/completions")] = lambda payload: (
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "intent": "verification",
                                "facets": ["memory_system", "remote"],
                                "identifiers": ["DeepSeek", "judge"],
                                "query_terms": ["DeepSeek judge recall"],
                                "memory_types": ["workflow", "project_fact"],
                                "scopes": ["repo:C:/workspace/demo", "global"],
                                "strategy_hint": "guarded_hybrid",
                                "include_graph": False,
                                "include_session": True,
                                "needs_llm_judge": True,
                                "confidence": 0.88,
                                "reasons": ["remote planner understood the task"],
                            }
                        )
                    }
                }
            ]
        },
    )

    result = RemoteLLMClient(
        RemoteAdapterConfig(
            base_url=base_url,
            api_key="dash-key",
            compatibility=OPENAI_COMPATIBILITY,
            llm_extract_path="/chat/completions",
        )
    ).plan_recall(
        task="继续中文远程召回测试，看 DeepSeek judge",
        scope="repo:C:/workspace/demo",
        limit_per_query=4,
    )

    assert result.planner_source == "remote"
    assert result.intent == "verification"
    assert result.query_terms == ["DeepSeek judge recall"]
    assert result.memory_types == ["workflow", "project_fact"]
    assert result.strategy_hint == "guarded_hybrid"
    assert result.include_session is True
    assert result.needs_llm_judge is True
    assert result.confidence == 0.88
    assert captured[0]["payload"]["response_format"] == {"type": "json_object"}
    user_payload = json.loads(captured[0]["payload"]["messages"][1]["content"])
    assert user_payload["schema"] == "memory_system.remote_recall_planner.v1"
    assert user_payload["limit_per_query"] == 4


def test_remote_llm_client_recall_planner_coerces_string_booleans(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/chat/completions")] = lambda payload: (
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "intent": "general",
                                "query_terms": ["release checklist"],
                                "memory_types": ["workflow"],
                                "scopes": ["repo:C:/workspace/demo"],
                                "strategy_hint": "keyword",
                                "include_graph": "false",
                                "include_session": "false",
                                "needs_llm_judge": "false",
                            }
                        )
                    }
                }
            ]
        },
    )

    result = RemoteLLMClient(
        RemoteAdapterConfig(
            base_url=base_url,
            api_key="dash-key",
            compatibility=OPENAI_COMPATIBILITY,
            llm_extract_path="/chat/completions",
        )
    ).plan_recall(
        task="发布前检查什么？",
        scope="repo:C:/workspace/demo",
    )

    assert result.include_graph is False
    assert result.include_session is False
    assert result.needs_llm_judge is False


def test_remote_llm_client_repairs_markdown_fenced_json(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/chat/completions")] = lambda payload: (
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            "```json\n"
                            + json.dumps(
                                {
                                    "provider": "deepseek",
                                    "candidates": [
                                        {
                                            "content": "Fenced JSON candidate.",
                                            "memory_type": "workflow",
                                            "subject": "json repair",
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
                            + "\n```"
                        )
                    }
                }
            ]
        },
    )
    event = EventRead(
        id="evt_openai_fenced_json",
        event_type="user_message",
        content="OpenAI-compatible fenced JSON extraction event.",
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(
        RemoteAdapterConfig(
            base_url=base_url,
            compatibility=OPENAI_COMPATIBILITY,
            llm_extract_path="/chat/completions",
        )
    ).extract_candidates(event)

    assert result.provider == "deepseek"
    assert result.candidates[0].subject == "json repair"


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


def test_remote_llm_client_adds_low_evidence_preference_fallback_for_empty_results(
    remote_server,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_low_evidence_fallback",
        event_type="user_message",
        content=(
            "\u53ef\u80fd\u6211\u66f4\u559c\u6b22\u4f60\u5728\u56de\u7b54"
            "\u957f\u95ee\u9898\u65f6\u77ed\u4e00\u70b9\uff0c\u4f46\u6211"
            "\u8fd8\u6ca1\u60f3\u597d\u3002"
        ),
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == "user_preference"
    assert result.candidates[0].confidence == "inferred"
    assert result.candidates[0].scores.evidence == 0.4
    assert "local_remote_fallback:low_evidence_user_preference" in result.warnings


def test_remote_llm_client_prioritizes_uncertain_preference_over_stable_fallback(
    remote_server,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_uncertain_preference_fallback",
        event_type="user_message",
        content=(
            "\u4e0d\u786e\u5b9a\u4ee5\u540e\u56de\u7b54\u957f\u95ee"
            "\u9898\u662f\u4e0d\u662f\u90fd\u8981\u77ed\u4e00\u70b9"
            "\uff0c\u8fd9\u6761\u5148\u9700\u8981\u786e\u8ba4\u3002"
        ),
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].confidence == "inferred"
    assert result.candidates[0].scores.evidence == 0.4
    assert "local_remote_fallback:low_evidence_user_preference" in result.warnings
    assert "local_remote_fallback:stable_user_preference" not in result.warnings


def test_remote_llm_client_adds_english_low_evidence_preference_fallback(
    remote_server,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_low_evidence_english_fallback",
        event_type="user_message",
        content="Perhaps I want minimal code comments; please ask before treating this as stable.",
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == "user_preference"
    assert result.candidates[0].confidence == "inferred"
    assert result.candidates[0].scores.evidence == 0.4
    assert "local_remote_fallback:low_evidence_user_preference" in result.warnings


def test_remote_llm_client_adds_low_evidence_fixture_naming_fallback(
    remote_server,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_low_evidence_fixture_naming",
        event_type="user_message",
        content=(
            "there is a chance I prefer fixture naming; "
            "please ask before treating this as stable."
        ),
        source="conversation",
        scope="global",
        metadata={
            "claim": (
                "there is a chance I prefer fixture naming; "
                "please ask before treating this as stable."
            ),
            "memory_type": "user_preference",
            "subject": "low evidence preference about fixture naming",
        },
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == "user_preference"
    assert result.candidates[0].evidence_type == "unknown"
    assert result.candidates[0].confidence == "inferred"
    assert "local_remote_fallback:low_evidence_user_preference" in result.warnings


def test_remote_llm_client_adds_stable_preference_fallback_for_empty_results(
    remote_server,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_stable_preference_fallback",
        event_type="user_message",
        content=(
            "Always that for test strategy writeups, you name the verification "
            "command explicitly, especially when the task touches existing code."
        ),
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == "user_preference"
    assert result.candidates[0].confidence == "confirmed"
    assert result.candidates[0].evidence_type == "direct_user_statement"
    assert "local_remote_fallback:stable_user_preference" in result.warnings


def test_remote_llm_client_adds_tool_rule_fallback_for_empty_results(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_tool_rule_fallback",
        event_type="user_message",
        content=(
            "已确认 tool rule for refreshing documentation: "
            "run the focused pytest file before broad regression."
        ),
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == "tool_rule"
    assert result.candidates[0].time_validity == "until_changed"
    assert "local_remote_fallback:tool_rule" in result.warnings


def test_remote_llm_client_adds_project_fact_fallback_for_file_observation(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_project_fact_fallback",
        event_type="file_observation",
        content=(
            "Confirmed dev command: the development command is memoryctl serve; "
            "source is pyproject.toml."
        ),
        source="pyproject.toml",
        scope="repo:C:/workspace/memory",
        metadata={"subject": "dev command from pyproject.toml"},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == "project_fact"
    assert result.candidates[0].subject == "dev command from pyproject.toml"
    assert "local_remote_fallback:project_fact" in result.warnings


def test_remote_llm_client_uses_metadata_type_fallback_before_command_cues(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_metadata_environment_fallback",
        event_type="tool_result",
        content="Confirmed environment fact for Python invocation: tests are run through python -m pytest.",
        source="shell",
        scope="repo:C:/workspace/memory",
        metadata={
            "memory_type": "environment_fact",
            "subject": "Python invocation environment",
            "evidence_type": "tool_result",
            "time_validity": "until_changed",
        },
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == "environment_fact"
    assert result.candidates[0].subject == "Python invocation environment"
    assert "local_remote_fallback:metadata_environment_fact" in result.warnings


def test_remote_llm_client_does_not_fallback_rejected_preference_for_empty_results(
    remote_server,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_rejected_preference_fallback",
        event_type="user_message",
        content="I like that seaside photo; do not treat it as my travel preference.",
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert result.candidates == []
    assert "local_remote_fallback:stable_user_preference" not in result.warnings


def test_remote_llm_client_adds_troubleshooting_fallback_for_empty_results(
    remote_server,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_troubleshooting_fallback",
        event_type="tool_result",
        content=(
            "Verified troubleshooting note: Problem: NaturalConv directory existed "
            "but lacked dialog_release.json. Lesson: exists does not mean complete. "
            "Solution: refreshing with --force passed validation."
        ),
        source="download_public_memory_datasets",
        scope="repo:C:/workspace/en-realistic",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == "troubleshooting"
    assert result.candidates[0].evidence_type == "tool_result"
    assert "local_remote_fallback:troubleshooting" in result.warnings


def test_remote_llm_client_does_not_fallback_temporary_branch_name(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {"provider": "fake-llm", "warnings": ["remote returned empty"], "candidates": []},
    )
    event = EventRead(
        id="evt_remote_temporary_branch_name",
        event_type="user_message",
        content="\u8fd9\u4e2a\u5206\u652f\u5148\u53eb memory-demo\uff0c\u540e\u9762\u53ef\u80fd\u4f1a\u6539\u540d\u3002",
        source="conversation",
        scope="repo:C:/workspace/memory",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert result.candidates == []
    assert "local_remote_fallback:low_evidence_user_preference" not in result.warnings


def test_remote_llm_client_downgrades_overconfident_low_evidence_preference(
    remote_server,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": payload["event"]["content"],
                    "memory_type": "user_preference",
                    "subject": "answer style",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response that over-commits an underspecified preference.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["style_guidance", "future_responses"],
                    "scores": {
                        "long_term": 0.9,
                        "evidence": 0.9,
                        "reuse": 0.8,
                        "risk": 0.1,
                        "specificity": 0.8,
                    },
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_low_evidence_downgrade",
        event_type="user_message",
        content=(
            "\u521a\u624d\u90a3\u7248 README \u8bf4\u660e\u770b\u7740\u987a"
            "\uff0c\u4ee5\u540e\u90fd\u8fd9\u6837\u3002"
        ),
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].confidence == "inferred"
    assert result.candidates[0].scores.evidence == 0.4
    assert result.candidates[0].scores.specificity == 0.3
    assert result.candidates[0].time_validity == "unknown"
    assert "downgraded_remote_low_evidence_preference" in result.warnings


def test_remote_llm_client_downgrades_underspecified_positive_feedback(
    remote_server,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": payload["event"]["content"],
                    "memory_type": "user_preference",
                    "subject": "no-match analysis approach",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response that over-commits vague positive feedback.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["analysis_style"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_underspecified_positive_feedback",
        event_type="user_message",
        content="That no-match analysis angle worked; keep doing it this way.",
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].confidence == "inferred"
    assert result.candidates[0].time_validity == "unknown"
    assert result.candidates[0].scores.evidence == 0.4
    assert "downgraded_remote_low_evidence_preference" in result.warnings


def test_remote_llm_client_filters_user_rejected_preference_candidates(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": payload["event"]["content"],
                    "memory_type": "user_preference",
                    "subject": "draft reaction",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response that ignores the user's rejection.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["style_guidance"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_user_rejected_preference",
        event_type="user_message",
        content="Do not treat this as a preference; I liked this draft today.",
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert result.candidates == []
    assert "filtered_remote_preference_rejected_by_user" in result.warnings


def test_remote_llm_client_filters_temporary_user_message_candidates(remote_server):
    base_url, routes, captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": payload["event"]["content"],
                    "memory_type": "user_preference",
                    "subject": "pytest execution behavior",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response that over-stores a temporary instruction.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["testing"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_temporary_instruction",
        event_type="user_message",
        content="For this task, run only this pytest case for now; the full suite can run later.",
        source="conversation",
        scope="repo:C:/workspace/memory",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert result.candidates == []
    assert "filtered_temporary_remote_event" in result.warnings
    assert captured == []


def test_remote_llm_client_filters_pending_question_before_fallback(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "warnings": [
                "Event is a pending question awaiting confirmation; no long-term memory."
            ],
            "candidates": [],
        },
    )
    event = EventRead(
        id="evt_remote_pending_question",
        event_type="user_message",
        content=(
            "\u5173\u4e8e\u6570\u636e\u96c6\uff1a\u9879\u76ee\u72b6\u6001"
            "\u66f4\u65b0\u5e94\u8be5\u5199\u6210 decision \u8fd8\u662f "
            "project_fact\uff1f\u7b49\u6211\u4eec\u786e\u8ba4\u3002"
        ),
        source="conversation",
        scope="repo:C:/workspace/memory",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert result.candidates == []
    assert "filtered_pending_question_remote_event" in result.warnings
    assert "local_remote_fallback:environment_fact" not in result.warnings


def test_remote_llm_client_dedupes_remote_candidates_after_governance(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": "The release workflow is ruff then pytest.",
                    "memory_type": "workflow",
                    "subject": "release workflow",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "First duplicate candidate.",
                    "claim": "Run ruff then pytest before release.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "until_changed",
                    "reuse_cases": ["release_validation"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                },
                {
                    "content": "The release workflow is ruff then pytest.",
                    "memory_type": "workflow",
                    "subject": "release workflow",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Second duplicate candidate.",
                    "claim": "Run ruff then pytest before release.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "until_changed",
                    "reuse_cases": ["release_validation"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                },
            ],
        },
    )
    event = EventRead(
        id="evt_remote_dedupe",
        event_type="user_message",
        content="For this repo, the release workflow is ruff then pytest.",
        source="conversation",
        scope="repo:C:/workspace/memory",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == "workflow"
    assert "deduped_remote_candidate" in result.warnings


def test_remote_llm_client_dedupes_same_subject_content_across_scope_drift(
    remote_server,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": "Remote phrasing before metadata normalization.",
                    "memory_type": "project_fact",
                    "scope": "global",
                    "subject": "api.py audit script duplicate",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "First duplicate candidate with scope drift.",
                    "confidence": "confirmed",
                    "evidence_type": "file_observation",
                    "time_validity": "until_changed",
                    "reuse_cases": ["dataset_audit"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                },
                {
                    "content": "Another remote phrasing before metadata normalization.",
                    "memory_type": "project_fact",
                    "subject": "api.py audit script duplicate",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Second duplicate candidate with default scope.",
                    "confidence": "confirmed",
                    "evidence_type": "file_observation",
                    "time_validity": "until_changed",
                    "reuse_cases": ["dataset_audit"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                },
            ],
        },
    )
    event = EventRead(
        id="evt_remote_scope_drift_dedupe",
        event_type="file_observation",
        content=(
            "\u5df2\u786e\u8ba4 api.py stores audit script: "
            "\u5df2\u786e\u8ba4 audit_golden_cases.py reports template duplicates."
        ),
        source="api.py",
        scope="repo:C:/workspace/memory",
        metadata={"subject": "api.py audit script duplicate"},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].subject == "api.py audit script duplicate"
    assert "deduped_remote_candidate" in result.warnings


def test_remote_llm_client_filters_inferred_troubleshooting_derivatives(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": payload["event"]["content"],
                    "memory_type": "troubleshooting",
                    "subject": "NaturalConv dataset validation",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "The concrete verified troubleshooting record.",
                    "confidence": "confirmed",
                    "evidence_type": "tool_result",
                    "time_validity": "until_changed",
                    "reuse_cases": ["dataset_validation"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                },
                {
                    "content": "Existing directories can still be incomplete.",
                    "memory_type": "reflection",
                    "subject": "data integrity principle",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "An inferred principle derived from the troubleshooting note.",
                    "confidence": "confirmed",
                    "evidence_type": "inferred",
                    "time_validity": "persistent",
                    "reuse_cases": ["dataset_validation"],
                    "scores": {"long_term": 0.7, "evidence": 0.4, "reuse": 0.5},
                },
            ],
        },
    )
    event = EventRead(
        id="evt_remote_troubleshooting_derivative",
        event_type="tool_result",
        content=(
            "Problem: NaturalConv directory existed but lacked dialog_release.json; "
            "lesson: exists does not mean complete; solution: refreshing with --force "
            "passed validation. Validation passed."
        ),
        source="download_public_memory_datasets",
        scope="repo:C:/workspace/memory",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].subject == "NaturalConv dataset validation"
    assert "filtered_inferred_troubleshooting_derivative" in result.warnings


def test_remote_llm_client_anchors_troubleshooting_evidence_to_event(
    remote_server,
):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": payload["event"]["content"],
                    "memory_type": "troubleshooting",
                    "subject": "remote embedding timeout",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response that reports the evidence as the nested test result.",
                    "confidence": "likely",
                    "evidence_type": "test_result",
                    "time_validity": "until_changed",
                    "reuse_cases": ["remote_embedding_debugging"],
                    "scores": {"long_term": 0.9, "evidence": 0.8, "reuse": 0.8},
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_troubleshooting_evidence_anchor",
        event_type="tool_result",
        content=(
            "\u95ee\u9898\uff1aremote embedding call times out\u3002"
            "\u7ecf\u9a8c\uff1aintent rerank helped only when candidate intent was clear\u3002"
            "\u89e3\u51b3\u65b9\u5f0f\uff1ainstalled the dependency and the targeted test passed\u3002"
            "\u9a8c\u8bc1\u901a\u8fc7\u3002"
        ),
        source="shell",
        scope="repo:C:/workspace/memory",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].evidence_type == "tool_result"
    assert "normalized_remote_candidate_evidence_from_event" in result.warnings


def test_remote_llm_client_anchors_candidate_to_event_metadata(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": "Remote summary says the embedding model is configured.",
                    "memory_type": "project_fact",
                    "subject": "remote model config",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response with drift from event metadata.",
                    "confidence": "confirmed",
                    "evidence_type": "unknown",
                    "time_validity": "until_changed",
                    "reuse_cases": ["setup"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_metadata_anchor",
        event_type="tool_result",
        content=(
            "\u5de5\u5177\u8f93\u51fa\u786e\u8ba4\uff1a\u8fdc\u7a0b embedding "
            "\u5f53\u524d\u72b6\u6001\u4e3aembedding \u6a21\u578b\u540d\u662f "
            "tongyi-embedding-vision-flash-2026-03-06\u3002"
        ),
        source="shell",
        scope="repo:C:/workspace/cn-realistic",
        metadata={
            "memory_type": "environment_fact",
            "subject": "\u8fdc\u7a0b embedding\u73af\u5883\u72b6\u6001",
            "claim": "\u8fdc\u7a0b embedding \u6a21\u578b\u540d\u5df2\u786e\u8ba4\u3002",
            "evidence_type": "tool_result",
        },
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.memory_type == "environment_fact"
    assert candidate.subject == "\u8fdc\u7a0b embedding\u73af\u5883\u72b6\u6001"
    assert candidate.claim == "\u8fdc\u7a0b embedding \u6a21\u578b\u540d\u5df2\u786e\u8ba4\u3002"
    assert candidate.evidence_type == "tool_result"
    assert candidate.content == event.content
    assert "normalized_remote_candidate_subject_from_event_metadata" in result.warnings


def test_remote_llm_client_respects_metadata_memory_type_over_command_cues(remote_server):
    base_url, routes, _captured = remote_server
    routes[("POST", "/memory/extract")] = lambda payload: (
        200,
        {
            "provider": "fake-llm",
            "candidates": [
                {
                    "content": payload["event"]["content"],
                    "memory_type": "tool_rule",
                    "subject": "Python invocation environment",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response that treats an environment fact as a tool rule.",
                    "confidence": "confirmed",
                    "evidence_type": "tool_result",
                    "time_validity": "until_changed",
                    "reuse_cases": ["verification"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_metadata_type_priority",
        event_type="tool_result",
        content="Confirmed environment fact for Python invocation: tests are run through python -m pytest.",
        source="shell",
        scope="repo:C:/workspace/memory",
        metadata={
            "memory_type": "environment_fact",
            "subject": "Python invocation environment",
            "evidence_type": "tool_result",
        },
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == "environment_fact"
    assert "normalized_remote_candidate_type:tool_rule->environment_fact" in result.warnings


@pytest.mark.parametrize("remote_type", ["tool_rule", "workflow"])
def test_remote_llm_client_normalizes_global_stable_preference_drift(
    remote_server,
    remote_type,
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
                    "subject": "verification style",
                    "source_event_ids": [payload["event"]["id"]],
                    "reason": "Fake response that treats a personal preference as a repo rule.",
                    "confidence": "confirmed",
                    "evidence_type": "direct_user_statement",
                    "time_validity": "persistent",
                    "reuse_cases": ["style_guidance", "future_responses"],
                    "scores": {"long_term": 0.9, "evidence": 0.9, "reuse": 0.8},
                }
            ],
        },
    )
    event = EventRead(
        id="evt_remote_global_preference_drift",
        event_type="user_message",
        content=(
            "Always that for test strategy writeups, you name the verification "
            "command explicitly, especially when the task touches existing code."
        ),
        source="conversation",
        scope="global",
        metadata={},
        created_at=datetime.now(timezone.utc),
    )

    result = RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)).extract_candidates(event)

    assert len(result.candidates) == 1
    assert result.candidates[0].memory_type == "user_preference"
    assert f"normalized_remote_candidate_type:{remote_type}->user_preference" in result.warnings


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
            "Problem: pytest cannot import memory_system. "
            "Lesson: set PYTHONPATH=src before invoking pytest. "
            "Solution: rerun the targeted suite. Verified passed.",
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
            "Confirmed memory_store.py stores lint command: pyproject.toml lint command is python -m ruff check .",
            "file_observation",
            "memory_store.py",
            "tool_rule",
            "project_fact",
            "normalized_remote_candidate_type:tool_rule->project_fact",
        ),
        (
            "\u5df2\u786e\u8ba4\uff1a\u9879\u76ee\u8bf4\u660e\u4ee5 PROJECT_OVERVIEW.md "
            "\u4e3a\u5f53\u524d\u72b6\u6001\u6458\u8981\u3002",
            "file_observation",
            "docs_source.yaml",
            "environment_fact",
            "project_fact",
            "normalized_remote_candidate_type:environment_fact->project_fact",
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
    assert "atomic claim" in " ".join(user_payload["governance_rules"])
    assert "time_validity" in " ".join(user_payload["governance_rules"])
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


def test_remote_retrieval_fixture_reuses_embedding_cache(tmp_path, remote_server):
    from memory_system.remote_evaluation import evaluate_remote_retrieval_fixture

    base_url, routes, captured = remote_server
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
    cache_path = tmp_path / "embedding-cache.jsonl"

    first = evaluate_remote_retrieval_fixture(
        fixture,
        RemoteEmbeddingClient(RemoteAdapterConfig(base_url=base_url)),
        model="fake-embedding",
        limit=1,
        embedding_cache_path=cache_path,
    )
    captured_after_first = len(captured)
    second = evaluate_remote_retrieval_fixture(
        fixture,
        RemoteEmbeddingClient(RemoteAdapterConfig(base_url=base_url)),
        model="fake-embedding",
        limit=1,
        embedding_cache_path=cache_path,
    )

    assert first.metadata["embedding_cache"]["writes"] == 4
    assert second.metadata["embedding_cache"]["hits"] == 4
    assert len(captured) == captured_after_first
    assert cache_path.exists()


def test_remote_retrieval_fixture_prefetches_embeddings_in_parallel(tmp_path, remote_server):
    from memory_system.remote_evaluation import evaluate_remote_retrieval_fixture

    base_url, routes, _captured = remote_server
    lock = Lock()
    in_flight = 0
    max_in_flight = 0

    def embedding_handler(payload):
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        try:
            time.sleep(0.05)
            return (
                200,
                {
                    "provider": "fake-embedding",
                    "model": "fake-embedding",
                    "vectors": [_semantic_fixture_vector(text) for text in payload["texts"]],
                },
            )
        finally:
            with lock:
                in_flight -= 1

    routes[("POST", "/embeddings")] = embedding_handler
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
        limit=4,
        batch_size=1,
        embedding_cache_path=tmp_path / "parallel-cache.jsonl",
        case_concurrency=4,
    )

    assert result.summary.case_count == 4
    assert result.metadata["case_concurrency"] == 4
    assert result.metadata["prefetch"]["enabled"] is True
    assert result.metadata["prefetch"]["case_concurrency"] == 4
    assert max_in_flight > 1


def test_remote_retrieval_fixture_records_embedding_errors_per_case(remote_server):
    from memory_system.remote_evaluation import evaluate_remote_retrieval_fixture

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (500, {"error": "embedding down"})
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
        limit=1,
    )

    assert result.summary.case_count == 1
    assert result.summary.failed_by_mode["semantic"] == 1
    assert result.summary.ambiguous_by_mode["semantic"] == 1
    assert "remote_embedding_error" in result.warnings
    assert result.items[0].warnings == ["remote_embedding_error"]
    assert "remote returned HTTP 500" in result.items[0].metadata["remote_error"]


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
    assert "behavior guidance" in captured[-1]["payload"]["instructions"]
    assert "user_preference, workflow, and tool_rule" in captured[-1]["payload"]["instructions"]


def test_remote_llm_client_recall_prompt_distinguishes_guidance_memory(
    tmp_path,
    remote_server,
):
    from memory_system import MemoryItemCreate

    base_url, routes, captured = remote_server
    store = MemoryStore(tmp_path / "memory.sqlite")
    memory = store.add_memory(
        MemoryItemCreate(
            content="The user prefers explanations that start with a concrete example.",
            memory_type="user_preference",
            scope="global",
            subject="explanation style",
            confidence="confirmed",
            source_event_ids=["evt_preference"],
        )
    )

    def handle_chat(payload):
        user_payload = json.loads(payload["messages"][1]["content"])
        assert user_payload["schema"] == "memory_system.remote_recall_judge.v1"
        assert user_payload["candidates"][0]["memory_type"] == "user_preference"
        return (
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "provider": "fake-llm",
                                    "decision": "accepted",
                                    "selected_memory_ids": [memory.id],
                                    "reason": "The preference should guide the explanation.",
                                    "risk": "low",
                                }
                            )
                        }
                    }
                ]
            },
        )

    routes[("POST", "/chat/completions")] = handle_chat

    result = RemoteLLMClient(
        RemoteAdapterConfig(
            base_url=base_url,
            compatibility=OPENAI_COMPATIBILITY,
            llm_extract_path="/chat/completions",
        )
    ).judge_retrieval(
        query="How should I frame an unfamiliar API?",
        memories=[memory],
    )

    system_content = captured[-1]["payload"]["messages"][0]["content"]
    user_payload = json.loads(captured[-1]["payload"]["messages"][1]["content"])
    assert result.decision == "accepted"
    assert result.selected_memory_ids == [memory.id]
    assert "For factual memories" in system_content
    assert "user_preference, workflow, and tool_rule" in system_content
    assert "guide how the agent responds or acts" in system_content
    assert "behavior guidance" in user_payload["instructions"]


def test_remote_llm_client_batch_recall_prompt_distinguishes_guidance_memory(
    tmp_path,
    remote_server,
):
    from memory_system import MemoryItemCreate

    base_url, routes, captured = remote_server
    store = MemoryStore(tmp_path / "memory.sqlite")
    memory = store.add_memory(
        MemoryItemCreate(
            content="The release checklist is ruff, pytest, then smoke test.",
            memory_type="workflow",
            scope="repo:C:/workspace/demo",
            subject="release checklist",
            confidence="confirmed",
            source_event_ids=["evt_workflow"],
        )
    )

    def handle_chat(payload):
        user_payload = json.loads(payload["messages"][1]["content"])
        request_id = user_payload["cases"][0]["request_id"]
        assert user_payload["schema"] == "memory_system.remote_recall_judge_batch.v1"
        assert user_payload["cases"][0]["candidates"][0]["memory_type"] == "workflow"
        return (
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "results": [
                                        {
                                            "request_id": request_id,
                                            "provider": "fake-llm",
                                            "decision": "accepted",
                                            "selected_memory_ids": [memory.id],
                                            "reason": "The workflow should guide the action.",
                                            "risk": "low",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    routes[("POST", "/chat/completions")] = handle_chat

    result = RemoteLLMClient(
        RemoteAdapterConfig(
            base_url=base_url,
            compatibility=OPENAI_COMPATIBILITY,
            llm_extract_path="/chat/completions",
        )
    ).judge_retrieval_batch(
        [{"request_id": "case-1", "query": "How should I release?", "memories": [memory]}]
    )

    system_content = captured[-1]["payload"]["messages"][0]["content"]
    user_payload = json.loads(captured[-1]["payload"]["messages"][1]["content"])
    assert result["case-1"].decision == "accepted"
    assert result["case-1"].selected_memory_ids == [memory.id]
    assert "For factual memories" in system_content
    assert "user_preference, workflow, and tool_rule" in system_content
    assert "guide how the agent responds or acts" in system_content
    assert "behavior guidance" in user_payload["instructions"]


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
    assert result.metadata["judge"]["mode"] == "single"
    assert result.metadata["judge"]["group_size"] == 1
    assert result.metadata["judge"]["concurrency"] == 1
    assert result.metadata["judge"]["pending_tasks"] == 51
    assert result.metadata["judge"]["single_calls"] == 51
    assert result.summary.judge_called_by_mode["selective_llm_guarded_hybrid"] == 1
    assert result.summary.judge_skipped_by_mode["selective_llm_guarded_hybrid"] == 49
    assert result.summary.judge_skip_reason_by_mode["selective_llm_guarded_hybrid"] == {
        "local_guard_confident": 49
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


def test_remote_retrieval_fixture_parallelizes_single_llm_judges(tmp_path, remote_server):
    from memory_system.remote_evaluation import evaluate_remote_retrieval_fixture

    base_url, routes, _captured = remote_server
    judge_payloads = []
    active_judges = 0
    max_active_judges = 0
    judge_lock = Lock()
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [_semantic_fixture_vector(text) for text in payload["texts"]],
        },
    )

    def handle_judge(payload):
        nonlocal active_judges, max_active_judges
        assert payload["schema"] == "memory_system.remote_recall_judge.v1"
        with judge_lock:
            active_judges += 1
            max_active_judges = max(max_active_judges, active_judges)
        try:
            time.sleep(0.05)
            judge_payloads.append(payload)
            selected_candidate = next(
                (
                    candidate
                    for candidate in payload["candidates"]
                    if str(candidate.get("subject", "")).startswith("release SLA")
                ),
                payload["candidates"][0],
            )
            selected = selected_candidate["memory_id"]
            return (
                200,
                {
                    "provider": "fake-llm",
                    "decision": "accepted",
                    "selected_memory_ids": [selected],
                    "reason": "The single judge selected the release SLA memory.",
                    "risk": "low",
                },
            )
        finally:
            with judge_lock:
                active_judges -= 1

    routes[("POST", "/memory/extract")] = handle_judge
    fixture = tmp_path / "single_parallel_retrieval.jsonl"
    rows = []
    for index in range(4):
        rows.append(
            {
                "mode": "retrieval",
                "name": f"single_parallel_judge_{index:03d}",
                "category": "single_parallel_judge",
                "search": {
                    "query": f"What is the SLA before release for service {index}?",
                    "scopes": ["global"],
                    "memory_types": ["project_fact"],
                    "limit": 1,
                },
                "expected": {"exact_aliases": [f"single_{index:03d}_target"]},
                "memories": [
                    {
                        "alias": f"single_{index:03d}_target",
                        "content": f"The release SLA for service {index} is 99.{index} percent.",
                        "memory_type": "project_fact",
                        "scope": "global",
                        "subject": f"release SLA {index}",
                        "confidence": "confirmed",
                        "source_event_ids": [f"evt_single_{index:03d}"],
                    },
                    {
                        "alias": f"single_{index:03d}_distractor",
                        "content": "Console encoding uses UTF-8 when text is garbled.",
                        "memory_type": "project_fact",
                        "scope": "global",
                        "subject": "encoding note",
                        "confidence": "confirmed",
                        "source_event_ids": [f"evt_single_other_{index:03d}"],
                    },
                ],
            }
        )
    fixture.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = evaluate_remote_retrieval_fixture(
        fixture,
        RemoteEmbeddingClient(RemoteAdapterConfig(base_url=base_url)),
        remote_llm=RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)),
        include_llm_judge=True,
        model="fake-embedding",
        case_concurrency=1,
        judge_group_size=1,
        judge_concurrency=4,
    )

    assert result.summary.case_count == 4
    assert result.summary.passed_by_mode["llm_guarded_hybrid"] == 4
    assert result.summary.judge_called_by_mode["llm_guarded_hybrid"] == 4
    assert result.metadata["judge"]["mode"] == "single"
    assert result.metadata["judge"]["group_size"] == 1
    assert result.metadata["judge"]["concurrency"] == 4
    assert result.metadata["judge"]["pending_tasks"] == 4
    assert result.metadata["judge"]["single_calls"] == 4
    assert result.metadata["judge"]["batch_calls"] == 0
    assert len(judge_payloads) == 4
    assert max_active_judges > 1
    judge = result.items[0].judge_by_mode["llm_guarded_hybrid"]
    assert judge.metadata["request_mode"] == "single"
    assert judge.metadata["remote_judge_called"] is True


def test_remote_retrieval_fixture_batches_selective_llm_judges(tmp_path, remote_server):
    from memory_system.remote_evaluation import evaluate_remote_retrieval_fixture

    base_url, routes, _captured = remote_server
    batch_payloads = []
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [_semantic_fixture_vector(text) for text in payload["texts"]],
        },
    )

    def handle_batch_judge(payload):
        assert payload["schema"] == "memory_system.remote_recall_judge_batch.v1"
        batch_payloads.append(payload)
        results = []
        for case in payload["cases"]:
            selected_candidate = next(
                (
                    candidate
                    for candidate in case["candidates"]
                    if str(candidate.get("subject", "")).startswith("release SLA")
                ),
                case["candidates"][0],
            )
            selected = selected_candidate["memory_id"]
            results.append(
                {
                    "request_id": case["request_id"],
                    "provider": "fake-llm",
                    "decision": "accepted",
                    "selected_memory_ids": [selected],
                    "reason": "The batched judge selected the release SLA memory.",
                    "risk": "low",
                }
            )
        return 200, {"provider": "fake-llm", "results": results}

    routes[("POST", "/memory/extract")] = handle_batch_judge
    fixture = tmp_path / "batch_retrieval.jsonl"
    rows = []
    for index in range(4):
        rows.append(
            {
                "mode": "retrieval",
                "name": f"batch_judge_{index:03d}",
                "category": "batch_judge",
                "search": {
                    "query": f"What is the SLA before release for service {index}?",
                    "scopes": ["global"],
                    "memory_types": ["project_fact"],
                    "limit": 1,
                },
                "expected": {"exact_aliases": [f"batch_{index:03d}_target"]},
                "memories": [
                    {
                        "alias": f"batch_{index:03d}_target",
                        "content": f"The release SLA for service {index} is 99.{index} percent.",
                        "memory_type": "project_fact",
                        "scope": "global",
                        "subject": f"release SLA {index}",
                        "confidence": "confirmed",
                        "source_event_ids": [f"evt_batch_{index:03d}"],
                    },
                    {
                        "alias": f"batch_{index:03d}_distractor",
                        "content": "Console encoding uses UTF-8 when text is garbled.",
                        "memory_type": "project_fact",
                        "scope": "global",
                        "subject": "encoding note",
                        "confidence": "confirmed",
                        "source_event_ids": [f"evt_batch_other_{index:03d}"],
                    },
                ],
            }
        )
    fixture.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = evaluate_remote_retrieval_fixture(
        fixture,
        RemoteEmbeddingClient(RemoteAdapterConfig(base_url=base_url)),
        remote_llm=RemoteLLMClient(RemoteAdapterConfig(base_url=base_url)),
        include_selective_llm_judge=True,
        model="fake-embedding",
        embedding_cache_path=tmp_path / "batch-cache.jsonl",
        case_concurrency=2,
        judge_group_size=2,
        judge_concurrency=2,
    )

    assert result.summary.case_count == 4
    assert result.summary.passed_by_mode["selective_llm_guarded_hybrid"] == 4
    assert result.summary.judge_called_by_mode["selective_llm_guarded_hybrid"] == 4
    assert result.metadata["judge"]["mode"] == "batch"
    assert result.metadata["judge"]["group_size"] == 2
    assert result.metadata["judge"]["concurrency"] == 2
    assert result.metadata["judge"]["pending_tasks"] == 4
    assert result.metadata["judge"]["batch_count"] == 2
    assert result.metadata["judge"]["batch_calls"] == 2
    assert result.metadata["judge"]["fallback_single_calls"] == 0
    assert len(batch_payloads) == 2
    assert {len(payload["cases"]) for payload in batch_payloads} == {2}
    judge = result.items[0].judge_by_mode["selective_llm_guarded_hybrid"]
    assert judge.metadata["request_mode"] == "batch"
    assert judge.metadata["remote_judge_called"] is True


def test_benchmark_remote_retrieval_script_writes_summary(tmp_path, remote_server):
    from tools.benchmark_remote_retrieval import parse_args, run_benchmark

    base_url, routes, _captured = remote_server
    routes[("POST", "/embeddings")] = lambda payload: (
        200,
        {
            "provider": "fake-embedding",
            "model": "fake-embedding",
            "vectors": [_semantic_fixture_vector(text) for text in payload["texts"]],
        },
    )
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
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "golden_cases"
        / "semantic_retrieval.jsonl"
    )
    args = parse_args(
        [
            "--fixture",
            str(fixture),
            "--limit",
            "1",
            "--embedding-cache",
            str(tmp_path / "bench-cache.jsonl"),
            "--output-dir",
            str(tmp_path / "bench"),
            "--case-concurrency",
            "1",
            "--config",
            "baseline",
            "--config",
            "single_seq",
        ]
    )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    try:
        summary = run_benchmark(args)
    finally:
        monkeypatch.undo()

    assert [row["name"] for row in summary["rows"]] == ["baseline", "single_seq"]
    assert (tmp_path / "bench" / "baseline.json").exists()
    assert (tmp_path / "bench" / "single_seq.json").exists()
    assert (tmp_path / "bench" / "summary.json").exists()
    assert summary["rows"][0]["target_mode"] == "guarded_hybrid"
    assert summary["rows"][1]["target_mode"] == "selective_llm_guarded_hybrid"
    assert "failures" in summary


def test_benchmark_remote_retrieval_script_samples_seeded_cases(tmp_path, remote_server):
    from tools.benchmark_remote_retrieval import parse_args, run_benchmark

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
    base_args = [
        "--fixture",
        str(fixture),
        "--sample-size",
        "3",
        "--sample-seed",
        "17",
        "--embedding-cache",
        str(tmp_path / "sample-cache.jsonl"),
        "--case-concurrency",
        "1",
        "--config",
        "baseline",
    ]

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    try:
        first = run_benchmark(
            parse_args([*base_args, "--output-dir", str(tmp_path / "sample-a")])
        )
        run_benchmark(parse_args([*base_args, "--output-dir", str(tmp_path / "sample-b")]))
    finally:
        monkeypatch.undo()

    first_report = json.loads(
        (tmp_path / "sample-a" / "baseline.json").read_text(encoding="utf-8")
    )
    second_report = json.loads(
        (tmp_path / "sample-b" / "baseline.json").read_text(encoding="utf-8")
    )
    first_names = first_report["metadata"]["selection"]["case_names"]
    second_names = second_report["metadata"]["selection"]["case_names"]
    assert first["limit"] is None
    assert first["sample_size"] == 3
    assert first["sample_seed"] == 17
    assert first["rows"][0]["passed"] + first["rows"][0]["failed"] == 3
    assert first_names == second_names
    assert len(first_names) == 3
    assert first_names != [
        "semantic_release_000",
        "semantic_release_001",
        "semantic_release_002",
    ]


def test_remote_retrieval_fixture_marks_judge_errors_ambiguous(remote_server):
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
    routes[("POST", "/memory/extract")] = lambda payload: (200, [])
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
        model="fake-embedding",
        limit=1,
    )

    assert result.summary.case_count == 1
    assert result.summary.ambiguous_by_mode["llm_guarded_hybrid"] == 3
    judge = result.items[0].judge_by_mode["llm_guarded_hybrid"]
    assert judge.decision == "ambiguous"
    assert "remote_recall_judge_error" in judge.warnings


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


def test_api_remote_selective_llm_guarded_hybrid_calls_on_private_fact_query(
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

    def handle_judge(payload):
        assert "exact requested safe fact" in payload["instructions"]
        return (
            200,
            {
                "provider": "fake-llm",
                "decision": "rejected",
                "selected_memory_ids": [],
                "reason": "The candidate is about a passport location, not a passport number.",
                "risk": "medium",
            },
        )

    routes[("POST", "/memory/extract")] = handle_judge
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    store = client.app.state.runtime.memories
    memory = store.add_memory(
        MemoryItemCreate(
            content="The user said Maya keeps her passport in the blue folder.",
            memory_type="project_fact",
            scope="global",
            subject="passport location",
            confidence="confirmed",
            source_event_ids=["evt_passport"],
        )
    )
    store.upsert_memory_embedding(memory.id, vector=[1.0, 0.0], model="fake-embedding")

    response = client.post(
        "/memories/search/remote-selective-llm-guarded-hybrid",
        json={
            "query": "What is the user's passport number?",
            "scopes": ["global"],
            "embedding_model": "fake-embedding",
            "limit": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["memories"] == []
    assert payload["judge"]["provider"] == "fake-llm"
    assert payload["judge"]["metadata"]["remote_judge_called"] is True
    assert payload["judge"]["metadata"]["call_reason"] == "private_fact_query"
    assert [item["path"] for item in captured].count("/memory/extract") == 1


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


def test_api_remote_route_splits_long_term_and_session(tmp_path, monkeypatch, remote_server):
    from fastapi.testclient import TestClient

    base_url, routes, _captured = remote_server

    def route(payload):
        event_ids = [event["id"] for event in payload["events"]]
        return (
            200,
            {
                "provider": "fake-route",
                "items": [
                    {
                        "route": "long_term",
                        "content": "API route prefers concise answers.",
                        "memory_type": "user_preference",
                        "subject": "api route preference",
                        "source_event_ids": [event_ids[0]],
                        "reason": "Stable future response preference.",
                        "confidence": "confirmed",
                        "evidence_type": "direct_user_statement",
                        "time_validity": "persistent",
                        "reuse_cases": ["future_responses"],
                        "scores": {"long_term": 0.8, "evidence": 1.0, "reuse": 0.8},
                    },
                    {
                        "route": "session",
                        "content": "For this API task, do not commit yet.",
                        "session_memory_type": "temporary_rule",
                        "subject": "current API commit rule",
                        "source_event_ids": [event_ids[1]],
                        "reason": "Temporary current-task constraint.",
                        "time_validity": "session",
                    },
                    {
                        "route": "ignore",
                        "content": "ok",
                        "source_event_ids": [event_ids[2]],
                        "reason": "Common confirmation.",
                    },
                ],
            },
        )

    routes[("POST", "/memory/extract")] = route
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    client = TestClient(create_app(tmp_path / "memory.sqlite"))
    events = [
        client.post(
            "/events",
            json={
                "event_type": "user_message",
                "content": "For future API answers, be concise.",
                "source": "conversation",
                "scope": "global",
            },
        ).json(),
        client.post(
            "/events",
            json={
                "event_type": "user_message",
                "content": "For this API task, do not commit yet.",
                "source": "conversation",
                "scope": "global",
            },
        ).json(),
        client.post(
            "/events",
            json={
                "event_type": "user_message",
                "content": "ok",
                "source": "conversation",
                "scope": "global",
            },
        ).json(),
    ]

    response = client.post(
        "/remote/route",
        json={"event_ids": [event["id"] for event in events], "session_id": "api-session"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "fake-route"
    assert len(payload["long_term"]) == 1
    assert len(payload["session"]) == 1
    assert len(payload["ignored"]) == 1
    assert payload["long_term"][0]["decision"]["decision"] == "write"
    candidate = payload["long_term"][0]["candidate"]
    assert candidate["status"] == "pending"
    assert client.app.state.runtime.memories.get_candidate(candidate["id"]).subject == (
        "api route preference"
    )
    assert payload["session"][0]["session_id"] == "api-session"
    assert payload["session"][0]["memory_type"] == "temporary_rule"
    assert payload["metadata"]["auto_committed"] is False
    assert payload["metadata"]["session_persisted"] is True

    context_response = client.post(
        "/context/compose",
        json={
            "task": "Prepare the API task summary",
            "session_id": "api-session",
            "session_limit": 3,
            "token_budget": 1000,
        },
    )
    assert context_response.status_code == 200
    assert "For this API task, do not commit yet." in context_response.json()["content"]


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


def test_cli_remote_route_json_splits_and_evaluates_memory_routes(
    tmp_path,
    monkeypatch,
    capsys,
    remote_server,
):
    from memory_system.cli import main

    base_url, routes, _captured = remote_server

    def route(payload):
        event_ids = [event["id"] for event in payload["events"]]
        return (
            200,
            {
                "provider": "fake-route",
                "items": [
                    {
                        "route": "long_term",
                        "content": "CLI route prefers concise technical answers.",
                        "memory_type": "user_preference",
                        "subject": "cli route preference",
                        "source_event_ids": [event_ids[0]],
                        "reason": "Stable future response preference.",
                        "confidence": "confirmed",
                        "evidence_type": "direct_user_statement",
                        "time_validity": "persistent",
                        "reuse_cases": ["future_responses"],
                        "scores": {"long_term": 0.8, "evidence": 1.0, "reuse": 0.8},
                    },
                    {
                        "route": "session",
                        "content": "For this task, do not commit yet.",
                        "session_memory_type": "temporary_rule",
                        "subject": "current commit rule",
                        "source_event_ids": [event_ids[1]],
                        "reason": "Temporary current-task constraint.",
                        "time_validity": "session",
                    },
                    {
                        "route": "ignore",
                        "content": "ok",
                        "source_event_ids": [event_ids[2]],
                        "reason": "Common confirmation.",
                    },
                    {
                        "route": "reject",
                        "content": "Unsafe item omitted.",
                        "source_event_ids": [event_ids[3]],
                        "reason": "Rejected by route judge.",
                    },
                ],
            },
        )

    routes[("POST", "/memory/extract")] = route
    monkeypatch.setenv("MEMORY_REMOTE_BASE_URL", base_url)
    db_path = tmp_path / "memory.sqlite"
    event_log = EventLog(db_path)
    events = [
        event_log.record_event(
            EventCreate(
                event_type="user_message",
                content="For future technical answers, be concise.",
                source="conversation",
                scope="global",
            )
        ),
        event_log.record_event(
            EventCreate(
                event_type="user_message",
                content="For this task, do not commit yet.",
                source="conversation",
                scope="global",
            )
        ),
        event_log.record_event(
            EventCreate(
                event_type="user_message",
                content="ok",
                source="conversation",
                scope="global",
            )
        ),
        event_log.record_event(
            EventCreate(
                event_type="user_message",
                content="reject this sample",
                source="conversation",
                scope="global",
            )
        ),
    ]

    result = main(
        [
            "--db",
            str(db_path),
            "remote",
            "route",
            "--event-id",
            events[0].id,
            "--event-id",
            events[1].id,
            "--event-id",
            events[2].id,
            "--event-id",
            events[3].id,
            "--json",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "fake-route"
    assert len(payload["long_term"]) == 1
    assert len(payload["session"]) == 1
    assert len(payload["ignored"]) == 1
    assert len(payload["rejected"]) == 1
    assert payload["long_term"][0]["decision"]["decision"] == "write"
    candidate = payload["long_term"][0]["candidate"]
    assert candidate["status"] == "pending"
    assert MemoryStore(db_path).get_candidate(candidate["id"]).subject == "cli route preference"
    assert payload["session"][0]["memory_type"] == "temporary_rule"
    assert payload["metadata"]["auto_committed"] is False
    assert payload["metadata"]["session_persisted"] is False


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
            "--embedding-cache",
            str(tmp_path / "retrieval-embedding-cache.jsonl"),
            "--report-path",
            str(tmp_path / "retrieval-report.json"),
            "--case-concurrency",
            "2",
            "--json",
        ]
    )

    assert result == 0
    evaluation = json.loads(capsys.readouterr().out)
    assert evaluation["summary"]["failed_by_mode"]["keyword"] > 0
    assert evaluation["summary"]["passed_by_mode"]["hybrid"] == 50
    assert evaluation["summary"]["passed_by_mode"]["guarded_hybrid"] == 50
    assert evaluation["metadata"]["embedding_cache"]["enabled"] is True
    assert evaluation["metadata"]["embedding_cache"]["writes"] > 0
    assert evaluation["metadata"]["case_concurrency"] == 2
    report_payload = json.loads((tmp_path / "retrieval-report.json").read_text(encoding="utf-8"))
    assert report_payload["summary"]["case_count"] == 50
    assert report_payload["metadata"]["embedding_cache"]["enabled"] is True

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
    assert evaluation["summary"]["judge_called_by_mode"]["selective_llm_guarded_hybrid"] == 1
    assert evaluation["summary"]["judge_skipped_by_mode"]["selective_llm_guarded_hybrid"] == 49
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
