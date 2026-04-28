from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
ALLOWED_MEMORY_CONTENT_DUPLICATES = {
    "semantic_retrieval.jsonl",
    "semantic_retrieval_cn.jsonl",
    "semantic_retrieval_public.jsonl",
    "semantic_retrieval_v2.jsonl",
}
ALLOWED_TEXT_DUPLICATE_CATEGORIES = {
    ("write_policy.jsonl", "merge_duplicate"),
}
ALLOWED_MEMORY_DUPLICATE_CATEGORIES = {
    ("write_policy.jsonl", "ask_conflict"),
    ("write_policy.jsonl", "merge_duplicate"),
}
TEMPLATE_NOISE_PATTERN = re.compile(
    r"第\s*\d+\s*个"
    r"|样本\s*\d+"
    r"|编号\s*\d+"
    r"|冲突\s*\d+"
    r"|低证据样本\s*\d+"
    r"|临时样本\s*\d+"
    r"|提问样本\s*\d+"
    r"|普通样本\s*\d+"
    r"|情绪闲聊样本\s*\d+"
    r"|场景编号\s*\d+"
    r"|\b\d+\b"
)
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class FixtureStats:
    path: Path
    rows: int
    categories: int
    duplicate_names: int
    text_values: int
    duplicate_text_values: int
    unexpected_duplicate_text_values: int
    template_duplicate_text_values: int
    memory_contents: int
    duplicate_memory_contents: int
    unexpected_duplicate_memory_contents: int
    template_duplicate_memory_contents: int

    @property
    def has_unexpected_duplicates(self) -> bool:
        return (
            self.duplicate_names > 0
            or self.unexpected_duplicate_text_values > 0
            or self.unexpected_duplicate_memory_contents > 0
        )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected object")
        rows.append(value)
    return rows


def extract_case_texts(case: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in ("input", "event", "context", "search", "query"):
        value = case.get(key)
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict):
            for nested_key in ("message", "text", "task", "query", "content"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, str):
                    texts.append(nested_value)
    return texts


def extract_memory_contents(case: dict[str, Any]) -> list[str]:
    contents: list[str] = []
    for key in ("memories", "existing_memories"):
        memories = case.get(key)
        if not isinstance(memories, list):
            continue
        for memory in memories:
            if isinstance(memory, dict) and isinstance(memory.get("content"), str):
                contents.append(memory["content"])
    return contents


def duplicate_count(values: list[str]) -> int:
    counts = Counter(values)
    return sum(count - 1 for count in counts.values() if count > 1)


def normalize_template_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", TEMPLATE_NOISE_PATTERN.sub("<N>", value)).strip()


def template_duplicate_count(values: list[str]) -> int:
    return duplicate_count([normalize_template_text(value) for value in values])


def unexpected_text_duplicate_count(path: Path, rows: list[dict[str, Any]]) -> int:
    grouped: dict[str, list[str]] = {}
    for row in rows:
        category = str(row.get("category", ""))
        for text in extract_case_texts(row):
            grouped.setdefault(text, []).append(category)
    unexpected = 0
    for categories in grouped.values():
        if len(categories) < 2:
            continue
        if all(
            (path.name, category) in ALLOWED_TEXT_DUPLICATE_CATEGORIES
            for category in categories
        ):
            continue
        unexpected += len(categories) - 1
    return unexpected


def unexpected_memory_duplicate_count(path: Path, rows: list[dict[str, Any]]) -> int:
    if path.name in ALLOWED_MEMORY_CONTENT_DUPLICATES:
        return 0
    grouped: dict[str, list[str]] = {}
    for row in rows:
        category = str(row.get("category", ""))
        for content in extract_memory_contents(row):
            grouped.setdefault(content, []).append(category)
    unexpected = 0
    for categories in grouped.values():
        if len(categories) < 2:
            continue
        if all(
            (path.name, category) in ALLOWED_MEMORY_DUPLICATE_CATEGORIES
            for category in categories
        ):
            continue
        unexpected += len(categories) - 1
    return unexpected


def template_duplicate_examples(
    path: Path,
    *,
    field: str,
    limit: int,
) -> list[str]:
    rows = load_jsonl(path)
    grouped: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        if field == "text":
            values = extract_case_texts(row)
        elif field == "memory":
            values = extract_memory_contents(row)
        else:
            raise ValueError(field)
        for value in values:
            grouped.setdefault(normalize_template_text(value), []).append(
                (str(row.get("name", "")), str(row.get("category", "")))
            )
    repeated = [
        (normalized, occurrences)
        for normalized, occurrences in grouped.items()
        if len(occurrences) > 1
    ]
    repeated.sort(key=lambda item: len(item[1]), reverse=True)
    examples: list[str] = []
    for normalized, occurrences in repeated[:limit]:
        sample = ", ".join(f"{name}/{category}" for name, category in occurrences[:3])
        examples.append(f"{field} x{len(occurrences)}: {normalized} [{sample}]")
    return examples


def summarize_fixture(path: Path) -> FixtureStats:
    rows = load_jsonl(path)
    names = [str(row.get("name", "")) for row in rows if row.get("name") is not None]
    texts: list[str] = []
    memory_contents: list[str] = []
    categories = {str(row.get("category")) for row in rows if row.get("category") is not None}
    for row in rows:
        texts.extend(extract_case_texts(row))
        memory_contents.extend(extract_memory_contents(row))
    return FixtureStats(
        path=path,
        rows=len(rows),
        categories=len(categories),
        duplicate_names=duplicate_count(names),
        text_values=len(texts),
        duplicate_text_values=duplicate_count(texts),
        unexpected_duplicate_text_values=unexpected_text_duplicate_count(path, rows),
        template_duplicate_text_values=template_duplicate_count(texts),
        memory_contents=len(memory_contents),
        duplicate_memory_contents=duplicate_count(memory_contents),
        unexpected_duplicate_memory_contents=unexpected_memory_duplicate_count(path, rows),
        template_duplicate_memory_contents=template_duplicate_count(memory_contents),
    )


def format_stats(stats: FixtureStats) -> str:
    marker = "!" if stats.has_unexpected_duplicates else " "
    return (
        f"{marker} {stats.path.name:<34} "
        f"rows={stats.rows:<4} "
        f"categories={stats.categories:<3} "
        f"dup_names={stats.duplicate_names:<3} "
        f"texts={stats.text_values:<4} "
        f"dup_texts={stats.duplicate_text_values:<3} "
        f"unexpected_dup_texts={stats.unexpected_duplicate_text_values:<3} "
        f"template_dup_texts={stats.template_duplicate_text_values:<4} "
        f"memory_contents={stats.memory_contents:<4} "
        f"dup_memory_contents={stats.duplicate_memory_contents:<4} "
        f"unexpected_dup_memory={stats.unexpected_duplicate_memory_contents:<4} "
        f"template_dup_memory={stats.template_duplicate_memory_contents:<4}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit golden JSONL fixtures for duplicate names and repeated text."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 1 when unexpected duplicates are found.",
    )
    parser.add_argument(
        "--show-template-groups",
        type=int,
        default=0,
        metavar="N",
        help="Show the top N normalized template duplicate groups per fixture.",
    )
    args = parser.parse_args()

    stats = [summarize_fixture(path) for path in sorted(ROOT.glob("*.jsonl"))]
    for item in stats:
        print(format_stats(item))
        if args.show_template_groups > 0:
            examples = [
                *template_duplicate_examples(
                    item.path,
                    field="text",
                    limit=args.show_template_groups,
                ),
                *template_duplicate_examples(
                    item.path,
                    field="memory",
                    limit=args.show_template_groups,
                ),
            ]
            for example in examples:
                print(f"    {example}")

    if args.strict and any(item.has_unexpected_duplicates for item in stats):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
