from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import requests
from huggingface_hub import snapshot_download


DEFAULT_OUTPUT_ROOT = Path(r"E:\Xu\data\memory_benchmarks")

HF_DATASETS = [
    {
        "name": "longmemeval",
        "repo_id": "MemoryAsModality/LongMemEval",
        "description": "Small Hugging Face mirror for LongMemEval-style long-term chat memory QA.",
    },
    {
        "name": "locomo_dialogues",
        "repo_id": "Aman279/Locomo",
        "description": "LoCoMo long multi-session dialogue data.",
    },
    {
        "name": "locomo_benchmark_queries",
        "repo_id": "Nithish2410/benchmark-locomo",
        "description": "LoCoMo-style query/target benchmark rows for retrieval evaluation.",
    },
    {
        "name": "naturalconv_zh",
        "repo_id": "xywang1/NaturalConv",
        "description": "Chinese multi-turn topic-driven conversation corpus for natural expression reference.",
    },
    {
        "name": "personal_dialog_zh",
        "repo_id": "silver/personal_dialog",
        "description": "Large Chinese multi-turn dialogue corpus with speaker profile traits for persona/preference reference.",
    },
]

GIT_REPOSITORIES: list[dict[str, Any]] = []

GITHUB_ARCHIVES = [
    {
        "name": "RealMemBench",
        "archive_urls": [
            "https://github.com/AvatarMemory/RealMemBench/archive/refs/heads/main.zip",
            "https://github.com/AvatarMemory/RealMemBench/archive/refs/heads/master.zip",
        ],
        "description": "RealMem project-oriented long-term memory benchmark and generation code.",
        "source": "https://github.com/AvatarMemory/RealMemBench",
    },
]


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def git_command(target: Path, *args: str) -> list[str]:
    return ["git", "-c", f"safe.directory={target}", "-C", str(target), *args]


def apply_sparse_excludes(target: Path, excludes: list[str]) -> None:
    if not excludes:
        return
    info_dir = target / ".git" / "info"
    info_dir.mkdir(parents=True, exist_ok=True)
    patterns = ["/*", *[f"!/{pattern}" for pattern in excludes]]
    (info_dir / "sparse-checkout").write_text(
        "\n".join(patterns) + "\n",
        encoding="utf-8",
    )
    run(git_command(target, "config", "core.sparseCheckout", "true"))
    run(git_command(target, "config", "core.sparseCheckoutCone", "false"))
    run(git_command(target, "checkout", "-f", "HEAD"))


def download_hf_dataset(entry: dict[str, str], output_root: Path, *, force: bool) -> dict[str, Any]:
    target = output_root / entry["name"]
    if target.exists() and any(target.iterdir()) and not force:
        return {
            **entry,
            "target": str(target),
            "status": "exists",
        }
    target.mkdir(parents=True, exist_ok=True)
    path = snapshot_download(
        repo_id=entry["repo_id"],
        repo_type="dataset",
        local_dir=target,
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    return {
        **entry,
        "target": str(Path(path)),
        "status": "downloaded",
    }


def clone_or_update_repo(entry: dict[str, str], output_root: Path, *, force: bool) -> dict[str, Any]:
    target = output_root / entry["name"]
    sparse_exclude = list(entry.get("sparse_exclude", []))
    if target.exists() and (target / ".git").exists():
        apply_sparse_excludes(target, sparse_exclude)
        if force:
            run(git_command(target, "fetch", "--all", "--prune"))
            run(git_command(target, "pull", "--ff-only"))
            apply_sparse_excludes(target, sparse_exclude)
            status = "updated"
        else:
            status = "exists"
        return {
            **entry,
            "target": str(target),
            "status": status,
        }
    if target.exists() and any(target.iterdir()):
        raise RuntimeError(f"target exists but is not a git repo: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    clone_command = ["git", "clone"]
    if sparse_exclude:
        clone_command.append("--no-checkout")
    run([*clone_command, entry["url"], str(target)])
    apply_sparse_excludes(target, sparse_exclude)
    return {
        **entry,
        "target": str(target),
        "status": "cloned",
    }


def remove_tree(path: Path) -> None:
    def handle_error(function: Any, file_path: str, _exc_info: Any) -> None:
        os.chmod(file_path, 0o700)
        function(file_path)

    shutil.rmtree(path, onerror=handle_error)


def is_windows_invalid_path(relative_path: str) -> bool:
    return any(part.endswith((" ", ".")) for part in Path(relative_path).parts)


def download_github_archive(entry: dict[str, Any], output_root: Path, *, force: bool) -> dict[str, Any]:
    target = output_root / entry["name"]
    if target.exists() and any(target.iterdir()):
        if not force:
            return {
                **entry,
                "target": str(target),
                "status": "exists",
            }
        remove_tree(target)
    target.mkdir(parents=True, exist_ok=True)

    last_error: str | None = None
    for url in entry["archive_urls"]:
        response = requests.get(url, timeout=120)
        if response.status_code != 200:
            last_error = f"{url}: HTTP {response.status_code}"
            continue
        archive_path = output_root / f"{entry['name']}.zip"
        archive_path.write_bytes(response.content)
        skipped: list[str] = []
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                parts = Path(member.filename).parts
                if len(parts) < 2:
                    continue
                relative = Path(*parts[1:])
                relative_text = str(relative)
                if is_windows_invalid_path(relative_text):
                    skipped.append(relative_text)
                    continue
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
        return {
            **entry,
            "target": str(target),
            "status": "downloaded_archive",
            "archive_url": url,
            "skipped_windows_invalid_paths": skipped,
        }
    raise RuntimeError(last_error or f"failed to download {entry['name']}")


def write_manifest(output_root: Path, records: list[dict[str, Any]]) -> None:
    manifest = {
        "output_root": str(output_root),
        "datasets": records,
        "notes": [
            "These are external public datasets for local inspection and adaptation.",
            "Do not commit downloaded dataset files into the project repository.",
            "Use project fixtures for deterministic CI; use these datasets for reference mining.",
        ],
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download public memory benchmark datasets for local reference."
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help=f"External dataset root. Default: {DEFAULT_OUTPUT_ROOT}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh existing git repos and re-run Hugging Face downloads.",
    )
    args = parser.parse_args()

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for entry in HF_DATASETS:
        records.append(download_hf_dataset(entry, output_root, force=args.force))
    for entry in GIT_REPOSITORIES:
        records.append(clone_or_update_repo(entry, output_root, force=args.force))
    for entry in GITHUB_ARCHIVES:
        records.append(download_github_archive(entry, output_root, force=args.force))
    write_manifest(output_root, records)

    for record in records:
        print(f"{record['status']}: {record['name']} -> {record['target']}")
    print(f"manifest: {output_root / 'manifest.json'}")


if __name__ == "__main__":
    main()
