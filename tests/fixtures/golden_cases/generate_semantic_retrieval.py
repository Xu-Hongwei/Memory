from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "semantic_retrieval.jsonl"
REPO_SCOPE = "repo:C:/workspace/demo"


TOPICS: list[dict[str, Any]] = [
    {
        "key": "release",
        "subject": "release checks",
        "content": "Before deployment run ruff check and pytest.",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["ci"],
        "queries": [
            "How do I ship safely?",
            "What should happen before going live?",
            "What is the launch safety routine?",
            "What should I check before publishing a build?",
            "How do we avoid a bad rollout?",
        ],
    },
    {
        "key": "schema",
        "subject": "schema migrations",
        "content": "Run migration scripts after schema edits.",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["database"],
        "queries": [
            "The storage shape shifted, what follows?",
            "Tables changed, what should I do next?",
            "What comes after altering persisted fields?",
            "How do I handle a data model update?",
            "A column layout moved, what is the next step?",
        ],
    },
    {
        "key": "encoding",
        "subject": "console encoding",
        "content": "Use UTF-8 code page 65001 when console text is garbled.",
        "memory_type": "troubleshooting",
        "scope": "global",
        "tags": ["windows"],
        "queries": [
            "Chinese characters are mojibake in PowerShell.",
            "Terminal output is unreadable after printing Chinese.",
            "The shell shows broken multilingual text.",
            "Command output has strange character corruption.",
            "Non-English logs look scrambled in the console.",
        ],
    },
    {
        "key": "browser",
        "subject": "browser validation",
        "content": "Open localhost pages in the in-app browser for UI validation.",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["ui"],
        "queries": [
            "Need to inspect the local web screen.",
            "How should I verify the running page visually?",
            "I want to check the interface in a real tab.",
            "The app view needs manual interaction testing.",
            "Where should I look at the local frontend?",
        ],
    },
    {
        "key": "secret",
        "subject": "secret handling",
        "content": "Do not store API keys or tokens in memory.",
        "memory_type": "tool_rule",
        "scope": "global",
        "tags": ["security"],
        "queries": [
            "How should credentials be handled?",
            "What do we do with private access strings?",
            "Should authentication material become memory?",
            "A bearer value appears in chat, what now?",
            "How are confidential connection values treated?",
        ],
    },
    {
        "key": "docs",
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
            "How do we keep explanations aligned with the implementation?",
        ],
    },
    {
        "key": "dependency",
        "subject": "dependency installation",
        "content": "Install missing Python packages with python -m pip install.",
        "memory_type": "tool_rule",
        "scope": "global",
        "tags": ["python"],
        "queries": [
            "A package import is unavailable.",
            "The module cannot be found at runtime.",
            "How should I add a missing library?",
            "The environment lacks a required dependency.",
            "A Python requirement is absent, what command shape is preferred?",
        ],
    },
    {
        "key": "server",
        "subject": "active server verification",
        "content": "When a local service seems stale, verify the active port and process.",
        "memory_type": "troubleshooting",
        "scope": REPO_SCOPE,
        "tags": ["runtime"],
        "queries": [
            "The running app still behaves like the old version.",
            "Changes are not visible on the live endpoint.",
            "The service looks stale after a restart.",
            "Which process is actually serving the page?",
            "The local URL is not reflecting the patch.",
        ],
    },
    {
        "key": "assets",
        "subject": "visual asset validation",
        "content": "For frontend changes, verify referenced assets render correctly.",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["frontend"],
        "queries": [
            "The screen looks blank after a UI change.",
            "Images may not be loading in the interface.",
            "How do I confirm the page is not visually empty?",
            "The canvas or media area needs a rendering check.",
            "A visual update needs asset verification.",
        ],
    },
    {
        "key": "answer_style",
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
            "How should the assistant present confirmed versus guessed details?",
        ],
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
    for topic_index, topic in enumerate(TOPICS):
        distractor_a = TOPICS[(topic_index + 3) % len(TOPICS)]
        distractor_b = TOPICS[(topic_index + 7) % len(TOPICS)]
        for query_index, query in enumerate(topic["queries"]):
            suffix = f"{topic['key']}_{query_index:03d}"
            target_alias = f"{suffix}_target"
            distractor_a_alias = f"{suffix}_distractor_a"
            distractor_b_alias = f"{suffix}_distractor_b"
            cases.append(
                {
                    "category": "semantic_paraphrase_retrieval",
                    "mode": "retrieval",
                    "name": f"semantic_{suffix}",
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
    return cases


def main() -> None:
    cases = build_cases()
    if len(cases) != 50:
        raise RuntimeError(f"expected 50 cases, got {len(cases)}")
    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, separators=(",", ":")) for case in cases)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
