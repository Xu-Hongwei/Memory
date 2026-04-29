from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(r"E:\Xu\data\memory_benchmarks")


def size_mb(path: Path) -> float:
    return round(path.stat().st_size / (1024 * 1024), 3)


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction)))
    return ordered[index]


def summarize_json_dialog_lengths(path: Path) -> dict[str, Any]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    lengths = [len(row.get("content", [])) for row in rows if isinstance(row, dict)]
    return {
        "rows": len(rows),
        "utterances": sum(lengths),
        "turns_min": min(lengths) if lengths else None,
        "turns_avg": round(statistics.mean(lengths), 2) if lengths else None,
        "turns_p50": percentile(lengths, 0.5),
        "turns_p90": percentile(lengths, 0.9),
        "turns_max": max(lengths) if lengths else None,
    }


def summarize_naturalconv(root: Path) -> dict[str, Any]:
    target = root / "naturalconv_zh"
    dialog_path = target / "dialog_release.json"
    document_path = target / "document_url_release.json"
    documents = json.loads(document_path.read_text(encoding="utf-8"))
    topics = sorted({str(item.get("topic", "")) for item in documents if isinstance(item, dict)})
    splits = {}
    for split in ("train", "dev", "test"):
        split_path = target / f"{split}.txt"
        splits[split] = len(
            [line for line in split_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        )
    return {
        "path": str(target),
        "files": {item.name: size_mb(item) for item in target.iterdir() if item.is_file()},
        "dialogue_stats": summarize_json_dialog_lengths(dialog_path),
        "document_rows": len(documents),
        "topic_count": len(topics),
        "topics_preview": topics[:20],
        "splits": splits,
        "recommended_use": [
            "learn natural Chinese multi-turn transitions",
            "add casual topic-switching negatives",
            "add vague preference phrasing without copying utterances",
        ],
    }


def summarize_personal_dialog(root: Path, *, sample_limit: int) -> dict[str, Any]:
    target = root / "personal_dialog_zh"
    info = json.loads((target / "dataset_infos.json").read_text(encoding="utf-8"))
    split_info = info["default"]["splits"]
    samples: dict[str, Any] = {}
    for name, filename in (
        ("train", "dialogues_train.jsonl.gz"),
        ("dev_random", "dev_random.jsonl.gz"),
        ("dev_biased", "dev_biased.jsonl.gz"),
        ("test_random", "test_random.jsonl.gz"),
        ("test_biased", "test_biased.jsonl.gz"),
    ):
        path = target / filename
        dialog_lengths: list[int] = []
        profile_counts: list[int] = []
        non_empty_tag_counts: list[int] = []
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index >= sample_limit:
                    break
                row = json.loads(line)
                dialog = row.get("dialog") or []
                profiles = row.get("profile") or []
                tags = [
                    tag
                    for profile in profiles
                    if isinstance(profile, dict)
                    for tag in profile.get("tag", [])
                    if str(tag).strip()
                ]
                dialog_lengths.append(len(dialog))
                profile_counts.append(len(profiles))
                non_empty_tag_counts.append(len(tags))
        samples[name] = {
            "file_size_mb": size_mb(path),
            "sampled_rows": len(dialog_lengths),
            "dialog_turns_avg": round(statistics.mean(dialog_lengths), 2)
            if dialog_lengths
            else None,
            "dialog_turns_p50": percentile(dialog_lengths, 0.5),
            "dialog_turns_p90": percentile(dialog_lengths, 0.9),
            "profiles_avg": round(statistics.mean(profile_counts), 2)
            if profile_counts
            else None,
            "non_empty_profile_tags_avg": round(statistics.mean(non_empty_tag_counts), 2)
            if non_empty_tag_counts
            else None,
        }
    return {
        "path": str(target),
        "download_size_mb": round(info["default"]["download_size"] / (1024 * 1024), 3),
        "splits": {
            name: {
                "num_examples": value["num_examples"],
                "num_bytes_mb": round(value["num_bytes"] / (1024 * 1024), 3),
            }
            for name, value in split_info.items()
        },
        "sample_summary": samples,
        "recommended_use": [
            "learn Chinese persona/profile surface forms",
            "add identity/location/interest facts",
            "add non-memory casual chat and noisy social-media phrasing",
        ],
    }


def summarize_realmem(root: Path) -> dict[str, Any]:
    target = root / "RealMemBench"
    dataset_dir = target / "dataset"
    dialogue_files = sorted(dataset_dir.glob("*_dialogues_256k.json"))
    stats = []
    for path in dialogue_files:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, list):
            rows = len(value)
            keys = sorted(value[0].keys()) if value and isinstance(value[0], dict) else []
        elif isinstance(value, dict):
            rows = len(value)
            keys = sorted(value.keys())
        else:
            rows = None
            keys = []
        stats.append({"file": path.name, "size_mb": size_mb(path), "top_level_rows": rows, "keys": keys})
    return {
        "path": str(target),
        "dialogue_file_count": len(dialogue_files),
        "dialogue_files": stats,
        "recommended_use": [
            "project goals and evolving project state",
            "conflicting updates and schedule changes",
            "work-oriented long-term memory cases",
        ],
    }


def summarize_locomo(root: Path) -> dict[str, Any]:
    target = root / "locomo_dialogues"
    csv_path = target / "locomo.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = 0
        fieldnames = reader.fieldnames or []
        for _row in reader:
            rows += 1
    query_target = root / "locomo_benchmark_queries"
    query_files = {
        item.name: size_mb(item)
        for item in query_target.glob("*")
        if item.is_file()
    }
    return {
        "dialogues_path": str(target),
        "dialogue_rows": rows,
        "dialogue_columns": fieldnames,
        "benchmark_query_path": str(query_target),
        "benchmark_query_files": query_files,
        "recommended_use": [
            "daily long-context memory",
            "persona and event recall",
            "temporal or multi-hop retrieval",
        ],
    }


def summarize_longmemeval(root: Path) -> dict[str, Any]:
    target = root / "longmemeval"
    parquet_files = sorted((target / "data").glob("*.parquet"))
    result: dict[str, Any] = {
        "path": str(target),
        "parquet_files": {item.name: size_mb(item) for item in parquet_files},
        "recommended_use": [
            "information extraction",
            "multi-session reasoning",
            "knowledge updates",
            "abstention/no-answer cases",
        ],
    }
    try:
        import pyarrow.parquet as pq  # type: ignore[import-not-found]

        result["schemas"] = {}
        for item in parquet_files:
            metadata = pq.read_metadata(item)
            result["schemas"][item.name] = {
                "rows": metadata.num_rows,
                "columns": metadata.schema.names,
            }
    except Exception as exc:  # pragma: no cover - diagnostic only
        result["schema_error"] = str(exc)
    return result


def build_summary(root: Path, *, sample_limit: int) -> dict[str, Any]:
    return {
        "root": str(root),
        "datasets": {
            "longmemeval": summarize_longmemeval(root),
            "locomo": summarize_locomo(root),
            "realmem": summarize_realmem(root),
            "naturalconv_zh": summarize_naturalconv(root),
            "personal_dialog_zh": summarize_personal_dialog(root, sample_limit=sample_limit),
        },
        "fixture_adaptation_plan": [
            "Keep external raw data outside repo fixtures.",
            "Use RealMemBench for project state, goal, decision, schedule, and conflict patterns.",
            "Use LongMemEval and LoCoMo for temporal recall, knowledge update, multi-hop, and no-answer structure.",
            "Use NaturalConv for Chinese multi-turn transitions and everyday topic changes.",
            "Use PersonalDialog for persona, location, interest tags, short casual messages, and profile-like facts.",
            "Rewrite all final fixture rows as project-owned synthetic Chinese cases; do not copy raw utterances.",
        ],
    }


def write_markdown(summary: dict[str, Any], path: Path) -> None:
    datasets = summary["datasets"]
    lines = [
        "# Public Memory Dataset Inventory",
        "",
        f"Root: `{summary['root']}`",
        "",
        "## Downloaded Datasets",
        "",
        "| Dataset | Key size/count | Recommended use |",
        "| --- | --- | --- |",
    ]
    natural = datasets["naturalconv_zh"]["dialogue_stats"]
    personal = datasets["personal_dialog_zh"]
    realmem = datasets["realmem"]
    locomo = datasets["locomo"]
    longmem = datasets["longmemeval"]
    rows = [
        (
            "LongMemEval",
            ", ".join(
                f"{name}: {value.get('rows', '?')} rows"
                for name, value in longmem.get("schemas", {}).items()
            )
            or "parquet files downloaded",
            "; ".join(longmem["recommended_use"]),
        ),
        (
            "LoCoMo",
            f"{locomo['dialogue_rows']} dialogue rows",
            "; ".join(locomo["recommended_use"]),
        ),
        (
            "RealMemBench",
            f"{realmem['dialogue_file_count']} 256k dialogue files",
            "; ".join(realmem["recommended_use"]),
        ),
        (
            "NaturalConv",
            f"{natural['rows']} dialogues, {natural['utterances']} utterances",
            "; ".join(datasets["naturalconv_zh"]["recommended_use"]),
        ),
        (
            "PersonalDialog",
            f"{personal['splits']['train']['num_examples']} train rows, {personal['download_size_mb']} MB compressed",
            "; ".join(personal["recommended_use"]),
        ),
    ]
    for name, size, use in rows:
        lines.append(f"| {name} | {size} | {use} |")
    lines.extend(["", "## Fixture Adaptation Plan", ""])
    lines.extend(f"- {item}" for item in summary["fixture_adaptation_plan"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize downloaded public memory datasets.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--sample-limit", type=int, default=5000)
    args = parser.parse_args()

    root = Path(args.root)
    output_dir = root / "derived"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = build_summary(root, sample_limit=args.sample_limit)
    json_path = output_dir / "reference_corpus_inventory.json"
    md_path = output_dir / "reference_corpus_inventory.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(summary, md_path)
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


if __name__ == "__main__":
    main()
