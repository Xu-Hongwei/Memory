from __future__ import annotations

import json
import re
from itertools import product
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "write_policy.jsonl"
REPO_SCOPE = "repo:C:/workspace/demo"

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
    event: dict[str, Any],
    expected_candidates: list[dict[str, Any]],
    *,
    existing_memories: list[dict[str, Any]] | None = None,
) -> None:
    case: dict[str, Any] = {
        "name": name,
        "category": category,
        "event": event,
        "expected": {"candidates": expected_candidates},
    }
    if existing_memories:
        case["existing_memories"] = existing_memories
    cases.append(case)


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


def grid(*groups: Iterable[str], limit: int) -> list[tuple[str, ...]]:
    values = list(product(*groups))
    if len(values) < limit:
        raise RuntimeError(f"not enough combinations: need {limit}, got {len(values)}")
    return values[:limit]


def normalize_template_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", TEMPLATE_NOISE_PATTERN.sub("<N>", value)).strip()


def assert_diverse_write_policy_cases(cases: list[dict[str, Any]]) -> None:
    event_texts = [case["event"]["content"] for case in cases]
    normalized_event_texts = [normalize_template_text(text) for text in event_texts]
    if len(set(event_texts)) != len(event_texts):
        raise RuntimeError("write_policy event texts must be exact-unique")
    if len(set(normalized_event_texts)) != len(normalized_event_texts):
        raise RuntimeError("write_policy event texts must be template-unique")

    existing_contents: list[str] = []
    for case in cases:
        for memory in case.get("existing_memories", []):
            existing_contents.append(memory["content"])
    if len(set(existing_contents)) != len(existing_contents):
        raise RuntimeError("write_policy existing memory contents must be exact-unique")
    normalized_existing = [normalize_template_text(text) for text in existing_contents]
    if len(set(normalized_existing)) != len(normalized_existing):
        raise RuntimeError("write_policy existing memory contents must be template-unique")


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    preference_topics = [
        "debugging explanations",
        "API design discussions",
        "release planning",
        "schema migration reviews",
        "frontend polish notes",
        "test strategy writeups",
        "documentation updates",
        "architecture comparisons",
        "memory-system decisions",
        "daily task planning",
    ]
    preference_styles = [
        "start with the concrete next action",
        "separate confirmed facts from inference",
        "use compact tables for option tradeoffs",
        "write in Chinese unless I switch languages",
        "name the verification command explicitly",
        "keep the answer concise but preserve risks",
        "give one specific example before abstraction",
        "avoid saving temporary state as a preference",
        "summarize assumptions before recommending code",
        "put the most likely failure mode first",
    ]
    preference_contexts = [
        "when the task touches existing code",
        "when the result depends on environment state",
        "when several implementation paths are possible",
    ]
    preference_cues = [
        "I prefer",
        "Please remember",
        "Always",
        "By default",
        "My preference is",
    ]
    for index, (topic, style, context) in enumerate(
        grid(preference_topics, preference_styles, preference_contexts, limit=300)
    ):
        cue = preference_cues[index % len(preference_cues)]
        content = f"{cue} that for {topic}, you {style}, especially {context}."
        add_case(
            cases,
            "positive_user_preference",
            f"positive_user_preference_{index:03d}",
            event("user_message", content),
            [expected("user_preference", "direct_user_statement", "write", commit=True)],
        )

    casual_objects = [
        "this jazz intro",
        "the smell of fresh rain",
        "this midnight snack",
        "the blue notebook cover",
        "that tiny coffee shop",
        "this puzzle clue",
        "the movie ending",
        "this desk lamp",
        "the rhythm of the sentence",
        "that quiet street photo",
        "this tea cup",
        "the guitar riff",
        "that weekend market",
        "this sketch composition",
    ]
    casual_contexts = [
        "as a passing reaction",
        "just for this conversation",
        "while looking at the current example",
        "without turning it into a stored note",
        "only because the current mood fits it",
        "as a casual aside",
        "while comparing today's options",
        "for this one draft",
        "because it feels pleasant right now",
        "with no need to keep it later",
    ]
    for index, (item, context) in enumerate(
        grid(casual_objects, casual_contexts, limit=140)
    ):
        content = f"I like {item}, {context}."
        add_case(
            cases,
            "negative_casual_like",
            f"negative_casual_like_{index:03d}",
            event("user_message", content),
            [],
        )

    temporary_tasks = [
        "run the dev server",
        "inspect the exported JSON",
        "draft the migration note",
        "compare two candidate prompts",
        "open the temporary preview",
        "rename the scratch branch",
        "check one flaky assertion",
        "mock the remote embedding call",
        "skip the long benchmark",
        "keep the console output short",
    ]
    temporary_choices = [
        "port blue-harbor",
        "folder amber-scratch",
        "profile quiet-lab",
        "endpoint sandbox-gate",
        "label dusk-review",
        "cache key cedar-pass",
        "fixture slate-pocket",
        "browser tab north-window",
        "sample set violet-note",
        "timeout quick-river",
        "theme silver-marker",
        "workspace pine-bridge",
        "draft name lunar-card",
        "log bucket clear-shelf",
        "shell alias soft-run",
        "review mode calm-pass",
        "temporary token placeholder",
    ]
    for index, (task, choice) in enumerate(
        grid(temporary_tasks, temporary_choices, limit=170)
    ):
        content = (
            f"Temporarily use {choice} while we {task}; "
            "do not keep this as a long-term memory."
        )
        add_case(
            cases,
            "negative_temporary_state",
            f"negative_temporary_state_{index:03d}",
            event("user_message", content, scope=REPO_SCOPE),
            [],
        )

    project_sources = [
        ("package.json", "file_observation"),
        ("pyproject.toml", "file_observation"),
        ("README.md", "file_observation"),
        ("docs/09-verification-and-testing.md", "file_observation"),
        ("src/memory_system/api.py", "file_observation"),
        ("src/memory_system/memory_store.py", "file_observation"),
        ("tests/test_cli.py", "file_observation"),
        ("tests/test_remote_adapters.py", "file_observation"),
        ("shell", "tool_result"),
        ("pytest", "tool_result"),
        ("ruff", "tool_result"),
        ("sqlite", "tool_result"),
    ]
    project_facts = [
        ("dev command", "the development command is memoryctl serve"),
        ("test command", "the test command is python -m pytest"),
        ("format command", "the lint command is python -m ruff check ."),
        ("api factory", "the API factory is memory_system.api:create_app"),
        ("database backend", "the local storage backend is SQLite"),
        ("fixture folder", "golden fixtures live under tests/fixtures/golden_cases"),
        ("remote adapter", "remote embedding evaluation uses evaluate-retrieval"),
        ("context composer", "context assembly enforces token budgets"),
        ("graph recall", "graph recall uses memory relation edges"),
        ("candidate policy", "candidate review separates write, merge, reject, and ask_user"),
        ("documentation rule", "verification docs describe the golden case workflow"),
        ("CLI namespace", "remote commands are grouped under memoryctl remote"),
        ("schema table", "memory_items stores content, type, scope, subject, and status"),
        ("audit command", "fixture audit reports exact and template duplicates"),
        ("remote model", "retrieval comparison can use the configured embedding model"),
    ]
    for index, ((source, event_type), (subject, fact)) in enumerate(
        grid(project_sources, project_facts, limit=180)
    ):
        content = f"已确认 {subject}: {fact}; source is {source}."
        add_case(
            cases,
            "positive_project_fact",
            f"positive_project_fact_{index:03d}",
            event(
                event_type,
                content,
                source=source,
                scope=REPO_SCOPE,
                metadata={"subject": f"{subject} from {source}"},
            ),
            [
                expected(
                    "project_fact",
                    event_type,
                    "write",
                    commit=True,
                )
            ],
        )

    tool_rule_actions = [
        "adding a dependency",
        "changing the API surface",
        "refreshing documentation",
        "editing a generated fixture",
        "testing remote adapters",
        "reviewing sensitive content",
        "building a release candidate",
        "debugging Windows encoding",
        "starting a local server",
        "summarizing benchmark results",
    ]
    tool_rule_requirements = [
        "record the verification command beside the result",
        "avoid writing secrets into fixtures or docs",
        "regenerate JSONL from the script instead of hand-editing rows",
        "run the focused pytest file before broad regression",
        "state whether a result is measured or inferred",
        "keep temporary session choices out of long-term memory",
        "check exact source files before updating docs",
        "preserve UTF-8 fixture encoding",
        "include category-level statistics when comparing retrieval",
        "prefer low-churn edits over broad rewrites",
        "treat no-match retrieval cases as first-class tests",
        "keep explicit Memory MCP rules separate from user preferences",
        "verify generated data with the audit script",
        "document fixture intent in the dataset README",
    ]
    for index, (action, requirement) in enumerate(
        grid(tool_rule_actions, tool_rule_requirements, limit=140)
    ):
        claim = f"已确认 tool rule for {action}: {requirement}."
        add_case(
            cases,
            "positive_tool_rule",
            f"positive_tool_rule_{index:03d}",
            event(
                "user_confirmation",
                claim,
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "tool_rule",
                    f"{action} rule",
                    claim,
                    reuse_cases=["verification", "repo_workflow"],
                ),
            ),
            [expected("tool_rule", "direct_user_statement", "write", commit=True)],
        )

    troubleshooting_problems = [
        "remote embedding call times out",
        "PowerShell preview shows mojibake",
        "fixture regeneration changes row order",
        "SQLite test keeps a file handle open",
        "FastAPI TestClient fails to import",
        "keyword retrieval misses paraphrased queries",
        "guarded hybrid returns ambiguous candidates",
        "CLI command cannot find the package",
        "docs drift after behavior changes",
        "semantic no-match cases return noise",
    ]
    troubleshooting_experiences = [
        "checking the exact command output identified the failing layer",
        "reading the file with UTF-8 proved the stored text was valid",
        "comparing generated names caught a script-level issue",
        "closing the connection removed the Windows lock",
        "installing the missing dependency restored the import path",
        "embedding recall reduced false negatives compared with keyword",
        "intent rerank helped only when candidate intent was clear",
        "setting PYTHONPATH to src made the module importable",
        "auditing implementation first located the stale paragraph",
        "raising the guard threshold reduced unexpected aliases",
        "category summaries exposed the weak case family",
        "a focused fixture isolated the regression faster than full tests",
        "checking active ports prevented testing the wrong server",
        "redaction happened before memory proposal",
        "the duplicate audit separated exact repeats from template repeats",
    ]
    troubleshooting_solutions = [
        "reran the request with a smaller batch and verification passed",
        "used Python encoding='utf-8' to inspect the source and verification passed",
        "updated the generator and regenerated the fixture successfully",
        "closed the store before cleanup and pytest passed",
        "installed the dependency and the targeted test passed",
        "enabled semantic retrieval and the golden case passed",
        "kept ambiguous results empty and the guard test passed",
        "set PYTHONPATH before invoking the CLI and the command passed",
        "patched the documentation and ruff still passed",
        "added a no-match guard and the retrieval evaluation passed",
    ]
    for index, (problem, experience, solution) in enumerate(
        grid(
            troubleshooting_problems,
            troubleshooting_experiences,
            troubleshooting_solutions,
            limit=150,
        )
    ):
        content = f"问题：{problem}。经验：{experience}。解决方式：{solution}。验证通过。"
        add_case(
            cases,
            "positive_troubleshooting",
            f"positive_troubleshooting_{index:03d}",
            event(
                "tool_result",
                content,
                source="shell",
                scope=REPO_SCOPE,
                metadata={"subject": f"{problem} / {solution}"},
            ),
            [expected("troubleshooting", "tool_result", "write", commit=True)],
        )

    sensitive_contexts = [
        "deployment log",
        "browser cookie dump",
        "email transcript",
        "billing webhook trace",
        "database connection note",
        "temporary support ticket",
        "OAuth callback sample",
        "mobile crash report",
        "cloud console screenshot",
        "debug request header",
        "customer CSV preview",
        "local env file",
    ]
    sensitive_markers = [
        "api_key=[REDACTED]",
        "token=[REDACTED]",
        "secret=[REDACTED]",
        "password=[REDACTED]",
        "cookie=[REDACTED]",
        "Bearer [REDACTED]",
        "email=[REDACTED_EMAIL]",
        "phone=[REDACTED_PHONE]",
        "id=[REDACTED_ID]",
        "session=[REDACTED]",
    ]
    for index, (context, marker) in enumerate(
        grid(sensitive_contexts, sensitive_markers, limit=120)
    ):
        content = f"The {context} contains {marker}; do not create memory from it."
        add_case(
            cases,
            "negative_sensitive",
            f"negative_sensitive_{index:03d}",
            event("user_message", content),
            [],
        )

    low_evidence_contexts = [
        "long answers",
        "short answers",
        "diagram-heavy explanations",
        "English comments",
        "minimal code comments",
        "table-first summaries",
        "voice and tone",
        "test-first workflow",
        "daily planning",
        "remote-model decisions",
        "browser validation",
        "fixture naming",
    ]
    low_evidence_phrases = [
        "maybe I like",
        "I might prefer",
        "perhaps I want",
        "it is possible I favor",
        "I am not sure, but I may want",
        "there is a chance I prefer",
        "I could imagine wanting",
        "maybe future me prefers",
        "this is only a guess, but I might like",
        "I have not confirmed it, but I may prefer",
    ]
    for index, (context, phrase) in enumerate(
        grid(low_evidence_contexts, low_evidence_phrases, limit=120)
    ):
        content = f"{phrase} {context}; please ask before treating this as stable."
        add_case(
            cases,
            "review_low_evidence",
            f"review_low_evidence_{index:03d}",
            event(
                "user_message",
                content,
                metadata={
                    "memory_type": "user_preference",
                    "subject": f"low evidence preference about {context}",
                    "claim": content,
                    "confidence": "inferred",
                    "risk": "low",
                },
            ),
            [expected("user_preference", "unknown", "ask_user")],
        )

    duplicate_artifacts = [
        "package.json",
        "pyproject.toml",
        "README.md",
        "memory_store.py",
        "api.py",
        "cli.py",
        "remote.py",
        "remote_evaluation.py",
        "context_composer.py",
        "graph_recall.py",
    ]
    duplicate_facts = [
        ("dev command", "已确认 package.json 的 dev command is memoryctl serve."),
        ("test command", "已确认 pyproject.toml 的 test command is python -m pytest."),
        ("lint command", "已确认 pyproject.toml 的 lint command is python -m ruff check ."),
        ("API factory", "已确认 api.py exposes memory_system.api:create_app."),
        ("database", "已确认 memory_store.py uses SQLite for local storage."),
        ("fixture path", "已确认 golden fixtures are stored under tests/fixtures/golden_cases."),
        ("remote CLI", "已确认 cli.py provides memoryctl remote commands."),
        ("redaction", "已确认 event_log.py redacts sensitive values before proposal."),
        ("context budget", "已确认 context_composer.py enforces token budgets."),
        ("graph recall", "已确认 graph_recall.py expands related memories."),
        ("audit script", "已确认 audit_golden_cases.py reports template duplicates."),
    ]
    for index, (artifact, (fact_key, content)) in enumerate(
        grid(duplicate_artifacts, duplicate_facts, limit=110)
    ):
        subject = f"{artifact} {fact_key} duplicate"
        scoped_content = f"已确认 {artifact} stores {fact_key}: {content}"
        existing = {
            "content": scoped_content,
            "memory_type": "project_fact",
            "scope": REPO_SCOPE,
            "subject": subject,
            "confidence": "confirmed",
            "source_event_ids": [f"evt_existing_duplicate_{index:03d}"],
        }
        add_case(
            cases,
            "merge_duplicate",
            f"merge_duplicate_{index:03d}",
            event(
                "file_observation",
                scoped_content,
                source=artifact,
                scope=REPO_SCOPE,
                metadata={"subject": subject},
            ),
            [expected("project_fact", "file_observation", "merge", commit=True)],
            existing_memories=[existing],
        )

    conflict_subjects = [
        "startup command",
        "database backend",
        "default language",
        "test runner",
        "embedding provider",
        "API port",
        "fixture location",
        "documentation owner",
        "browser validation path",
        "release gate",
    ]
    conflict_pairs = [
        ("old value says npm run dev", "已确认 the startup command is pnpm dev."),
        ("old value says Redis", "已确认 the database backend is SQLite."),
        ("old value says English", "已确认 the default language is Chinese."),
        ("old value says unittest", "已确认 the test runner is pytest."),
        ("old value says local-only embeddings", "已确认 the embedding provider can be remote."),
        ("old value says port copper", "已确认 the API port is configured by environment."),
        ("old value says fixtures live in docs", "已确认 fixtures live under tests/fixtures."),
        ("old value says README owns all docs", "已确认 docs/ owns detailed verification notes."),
        ("old value says use shell screenshots", "已确认 browser validation uses the in-app browser."),
        ("old value says build-only release", "已确认 release gates include ruff and pytest."),
        ("old value says no graph layer", "已确认 graph relations are part of recall testing."),
    ]
    for index, (subject_area, (old_value, new_content)) in enumerate(
        grid(conflict_subjects, conflict_pairs, limit=110)
    ):
        subject = f"{subject_area} conflict fact"
        old_content = f"Previously confirmed {subject_area}: {old_value}."
        scoped_new_content = f"已确认 {subject_area}: {new_content}"
        existing = {
            "content": old_content,
            "memory_type": "project_fact",
            "scope": REPO_SCOPE,
            "subject": subject,
            "confidence": "confirmed",
            "source_event_ids": [f"evt_existing_conflict_{index:03d}"],
        }
        add_case(
            cases,
            "ask_conflict",
            f"ask_conflict_{index:03d}",
            event(
                "file_observation",
                scoped_new_content,
                source="README.md",
                scope=REPO_SCOPE,
                metadata={"subject": subject},
            ),
            [expected("project_fact", "file_observation", "ask_user")],
            existing_memories=[existing],
        )

    ordinary_topics = [
        "the paragraph wording",
        "the current branch name",
        "a possible UI layout",
        "today's reading order",
        "a draft title",
        "one console snippet",
        "a rough project idea",
        "the next question",
        "a meeting note",
        "a temporary comparison",
        "a screenshot impression",
        "an unfinished hypothesis",
        "a vague dependency thought",
        "a local scratch file",
        "a single error line",
        "a proposed section name",
    ]
    ordinary_modifiers = [
        "just needs a quick look",
        "is not confirmed yet",
        "can wait until later",
        "should not become a project fact",
        "is only useful for this reply",
        "might change after inspection",
        "does not contain a stable user rule",
        "is merely context for the next response",
        "should stay out of long-term memory",
        "is a one-off observation",
    ]
    for index, (topic, modifier) in enumerate(
        grid(ordinary_topics, ordinary_modifiers, limit=160)
    ):
        content = f"Please look at {topic}; it {modifier}."
        add_case(
            cases,
            "negative_ordinary_or_unverified",
            f"negative_ordinary_or_unverified_{index:03d}",
            event("user_message", content, scope=REPO_SCOPE),
            [],
        )

    question_topics = [
        "this function",
        "the failing assertion",
        "the API response",
        "the schema field",
        "the CLI flag",
        "the generated fixture",
        "the remote warning",
        "the graph relation",
        "the context budget",
        "the ambiguous retrieval case",
    ]
    question_angles = [
        "what does it mean",
        "why did it fail",
        "which file should I inspect first",
        "how risky is it",
        "what changed recently",
        "can you compare the options",
        "is there a smaller test",
        "what should happen next",
    ]
    for index, (topic, angle) in enumerate(grid(question_topics, question_angles, limit=80)):
        content = f"For {topic}, {angle}?"
        add_case(
            cases,
            "negative_question_only",
            f"negative_question_only_{index:03d}",
            event("user_message", content, scope=REPO_SCOPE),
            [],
        )

    emotional_contexts = [
        "this debugging session",
        "the failed test output",
        "the long fixture review",
        "the unclear design choice",
        "the remote-model comparison",
        "the documentation drift",
        "the noisy console output",
        "the repeated data issue",
        "the slow verification run",
        "the next implementation step",
    ]
    emotional_states = [
        "feels tiring right now",
        "is a bit confusing",
        "makes me want to slow down",
        "feels surprisingly messy",
        "is easier if we take it step by step",
        "is making me second-guess the plan",
        "needs a calmer pass",
        "is annoying but manageable",
    ]
    for index, (context, state) in enumerate(
        grid(emotional_contexts, emotional_states, limit=80)
    ):
        content = f"{context} {state}; this is just how I feel in the moment."
        add_case(
            cases,
            "negative_emotional_or_social",
            f"negative_emotional_or_social_{index:03d}",
            event("user_message", content),
            [],
        )

    workflow_names = [
        "documentation sync",
        "remote retrieval comparison",
        "fixture regeneration",
        "API behavior change",
        "graph memory update",
        "release validation",
        "encoding investigation",
        "no-match retrieval review",
        "candidate policy tuning",
        "context budget audit",
    ]
    workflow_steps = [
        "audit the source behavior before editing docs",
        "run v1 and v2 fixtures before interpreting quality",
        "regenerate JSONL from scripts and then audit duplicates",
        "update tests and docs in the same change",
        "verify relation recall before changing graph rules",
        "run ruff, focused pytest, and then broad pytest",
        "read files as UTF-8 before assuming content is corrupted",
        "separate ambiguous results from true no-match decisions",
        "check false negatives before optimizing noise",
    ]
    for index, (name, step) in enumerate(grid(workflow_names, workflow_steps, limit=70)):
        claim = f"已确认 workflow for {name}: {step}."
        add_case(
            cases,
            "positive_workflow_explicit",
            f"positive_workflow_explicit_{index:03d}",
            event(
                "user_confirmation",
                claim,
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "workflow",
                    f"{name} workflow",
                    claim,
                    reuse_cases=["repo_workflow", "future_tasks"],
                ),
            ),
            [expected("workflow", "direct_user_statement", "write", commit=True)],
        )

    environment_areas = [
        "shell",
        "operating system",
        "workspace",
        "Python invocation",
        "database file",
        "fixture encoding",
        "remote base URL",
        "test runner",
        "lint runner",
        "local API",
    ]
    environment_facts = [
        "the active shell is PowerShell",
        "the development machine is Windows",
        "the project path is C:/Users/Administrator/Desktop/memory",
        "tests are run through python -m pytest",
        "the default database path is data/memory.sqlite",
        "golden JSONL files are UTF-8",
        "remote credentials are read from environment variables",
        "the test suite includes golden fixture regression",
        "ruff is available as python -m ruff check",
        "FastAPI exposes a create_app factory",
    ]
    for index, (area, fact) in enumerate(
        grid(environment_areas, environment_facts, limit=70)
    ):
        claim = f"已确认 environment fact for {area}: {fact}."
        add_case(
            cases,
            "positive_environment_fact_explicit",
            f"positive_environment_fact_explicit_{index:03d}",
            event(
                "tool_result",
                claim,
                source="shell",
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "environment_fact",
                    f"{area} environment",
                    claim,
                    evidence_type="tool_result",
                    reuse_cases=["setup", "verification"],
                ),
            ),
            [expected("environment_fact", "tool_result", "write", commit=True)],
        )

    assert len(cases) == 2000
    assert len({case["name"] for case in cases}) == 2000
    assert {case["category"] for case in cases} == {
        "ask_conflict",
        "merge_duplicate",
        "negative_casual_like",
        "negative_emotional_or_social",
        "negative_ordinary_or_unverified",
        "negative_question_only",
        "negative_sensitive",
        "negative_temporary_state",
        "positive_environment_fact_explicit",
        "positive_project_fact",
        "positive_tool_rule",
        "positive_troubleshooting",
        "positive_user_preference",
        "positive_workflow_explicit",
        "review_low_evidence",
    }
    assert_diverse_write_policy_cases(cases)
    return cases


def main() -> None:
    cases = build_cases()
    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
