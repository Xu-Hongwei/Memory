from __future__ import annotations

import hashlib
import json
from itertools import product
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "write_policy_en_realistic.jsonl"
REPO_SCOPE = "repo:C:/workspace/en-realistic"


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


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    direct_scenarios = [
        ("coding_support", "debugging Python unit test failures", "reproduce the failure before proposing edits"),
        ("frontend_review", "reviewing frontend layout", "call out overlap and overflow risks first"),
        ("docs_sync", "syncing project docs", "align with code facts before changing wording"),
        ("remote_model_eval", "reading remote model stats", "separate false negatives from noise and ambiguity"),
        ("memory_design", "explaining the memory system", "split write, recall, and context assembly into layers"),
        ("dataset_quality", "reviewing test datasets", "start with duplication, then discuss coverage"),
        ("git_workflow", "preparing a code commit", "list changes and verification before suggesting a commit"),
        ("learning_explain", "explaining a new concept", "give one concrete example early"),
        ("meeting_summary", "writing meeting notes", "separate decisions, action items, and risks"),
        ("travel_planning", "planning travel options", "state constraints and tradeoffs before the route"),
        ("shopping_compare", "comparing purchase options", "show hard requirements before recommendations"),
        ("daily_schedule", "breaking down a schedule", "confirm time windows and priorities first"),
        ("writing_polish", "polishing English prose", "keep the original meaning and avoid sales copy"),
        ("research_reading", "summarizing papers or references", "separate author claims from your inference"),
        ("life_admin", "organizing personal reminders", "remember stable arrangements, not momentary moods"),
    ]
    direct_templates = [
        "Going forward, when {task}, please {guidance}.",
        "By default, when {task}, {guidance}.",
        "Remember this long-term preference: when {task}, {guidance}.",
        "My stable preference is that when {task}, you {guidance}.",
    ]
    for index, ((scenario, task, guidance), template) in enumerate(
        grid(direct_scenarios, direct_templates, limit=60)
    ):
        content = template.format(task=task, guidance=guidance)
        add_case(
            cases,
            "en_positive_preference_direct",
            f"en_positive_preference_direct_{index:03d}",
            event("user_message", content),
            [expected("user_preference", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="stable_preference",
        )

    uncertain_scenarios = [
        ("answer_style", "answering long questions", "be a little shorter"),
        ("code_review", "giving code suggestions", "lead with risk"),
        ("test_failure", "explaining test failures", "start with the most likely cause"),
        ("commit_message", "drafting commit messages", "use fewer abstract words"),
        ("doc_structure", "organizing documentation", "show the outline first"),
        ("retrieval_policy", "comparing recall strategies", "include more no-match examples"),
        ("write_policy", "deciding whether to write memory", "state evidence strength first"),
        ("remote_result", "analyzing remote results", "separate missed recall from noise"),
        ("project_status", "describing project progress", "start with completed work"),
        ("travel_plan", "answering travel planning questions", "give the budget boundary first"),
        ("shopping_advice", "giving buying advice", "list deal-breakers before the recommendation"),
        ("daily_plan", "splitting a daily plan", "use time blocks first"),
        ("study_note", "explaining study material", "start with intuition"),
        ("meeting_brief", "writing a meeting brief", "put action items first"),
        ("writing_feedback", "editing a draft", "point out structure issues first"),
    ]
    uncertain_templates = [
        "Maybe I prefer that when {task}, you {guidance}, but I have not decided.",
        "I might want {task} to {guidance}; do not write it as confirmed yet.",
        "I am not sure whether {task} should always {guidance}; ask me before storing it.",
    ]
    for index, ((scenario, task, guidance), template) in enumerate(
        grid(uncertain_scenarios, uncertain_templates, limit=45)
    ):
        content = template.format(task=task, guidance=guidance)
        add_case(
            cases,
            "en_review_preference_uncertain",
            f"en_review_preference_uncertain_{index:03d}",
            event("user_message", content),
            [expected("user_preference", "direct_user_statement", "ask_user")],
            scenario=scenario,
            utterance_style="uncertain_preference",
        )

    underspecified_contexts = [
        ("docs_sync", "That README explanation felt clear"),
        ("travel_planning", "The travel checklist was easy to follow"),
        ("debugging", "That debugging walkthrough made sense"),
        ("meeting_summary", "The meeting summary had the right level of detail"),
        ("cooking_plan", "That dinner substitution suggestion was practical"),
        ("shopping_compare", "The keyboard comparison was easy to scan"),
        ("retrieval_policy", "That no-match analysis angle worked"),
    ]
    underspecified_phrases = [
        "keep doing it this way.",
        "use this going forward.",
        "do it like this next time.",
        "same next time.",
        "stick with this.",
    ]
    for index, ((scenario, context), phrase) in enumerate(
        grid(underspecified_contexts, underspecified_phrases, limit=35)
    ):
        add_case(
            cases,
            "en_review_preference_underspecified",
            f"en_review_preference_underspecified_{index:03d}",
            event("user_message", f"{context}; {phrase}"),
            [expected("user_preference", "direct_user_statement", "ask_user")],
            scenario=scenario,
            utterance_style="underspecified_generalization",
        )

    temporary_requests = [
        ("debugging", "set the log level to debug this time", "only to inspect this failure"),
        ("remote_eval", "skip the remote LLM judge for this run", "we can revisit it after the quota check"),
        ("frontend_review", "use the blue button for the current screenshot", "only to match this mock"),
        ("docs_sync", "leave this paragraph out of the README for now", "I still want to check the wording"),
        ("git_workflow", "call this branch memory-demo for now", "the branch name may change"),
        ("test_runner", "run only this pytest case for now", "the full suite can run later"),
        ("api_debug", "temporarily move the port to 8011", "only to avoid the current conflict"),
        ("dataset_quality", "keep this temporary category name", "do not write it into memory"),
        ("writing_polish", "make the title louder this time", "just to compare the effect"),
        ("travel_planning", "assume a Saturday departure for this plan", "the date is not final"),
        ("shopping_compare", "set the budget to under 500 for this example", "it is only a working assumption"),
        ("daily_schedule", "move the meeting to the afternoon today only", "it is not a recurring rule"),
        ("study_note", "use English terminology this time", "only to compare with the source text"),
        ("life_admin", "remind me tonight to check the bill", "do not store it as a habit"),
        ("meeting_summary", "omit owners from this note for now", "I will add them later"),
    ]
    temporary_templates = [
        "For this task, {action}; {reason}.",
        "Just for now, {action}, because {reason}.",
        "{action}; {reason}, so treat it as a one-off.",
    ]
    for index, ((scenario, action, reason), template) in enumerate(
        grid(temporary_requests, temporary_templates, limit=45)
    ):
        add_case(
            cases,
            "en_negative_temporary_request",
            f"en_negative_temporary_request_{index:03d}",
            event("user_message", template.format(action=action, reason=reason), scope=REPO_SCOPE),
            [],
            scenario=scenario,
            utterance_style="temporary_request",
        )

    casual_likes = [
        ("music_chat", "the beat in this song", "it just feels good right now"),
        ("food_chat", "the flavor of this latte", "it is not a long-term preference"),
        ("ui_preview", "this button shape", "do not treat this as a preference"),
        ("travel_chat", "the window view in this rental photo", "I am just reacting to the image"),
        ("writing_chat", "this opening sentence", "it is not my long-term writing style"),
        ("design_preview", "this color palette", "do not store it as a preference"),
        ("shopping_browse", "the look of these headphones", "it only works on this page"),
    ]
    casual_templates = [
        "I like {item}; {reason}.",
        "{item} is nice, but {reason}.",
        "In this moment, {item} works for me; {reason}.",
        "Just saying: I like {item}, but {reason}.",
        "{item} caught my eye; {reason}.",
    ]
    for index, ((scenario, item, reason), template) in enumerate(
        grid(casual_likes, casual_templates, limit=35)
    ):
        add_case(
            cases,
            "en_negative_casual_like",
            f"en_negative_casual_like_{index:03d}",
            event("user_message", template.format(item=item, reason=reason)),
            [],
            scenario=scenario,
            utterance_style="casual_like",
        )

    questions = [
        ("project_lookup", "How does this project start?", "I am only asking about the current state"),
        ("remote_model", "Which path does the remote model use now?", "do not store this yet"),
        ("memory_concept", "What is the difference between recall tests and write tests?", "do not turn this into a fact"),
        ("dataset_quality", "Does this dataset still have duplicated patterns?", "wait until we verify it"),
        ("test_inventory", "How many golden fixtures do we have now?", "I am just trying to understand the flow"),
        ("retrieval_noise", "Why does no-match create noise?", "do not treat it as a preference"),
        ("docs_sync", "Which documentation section is still stale?", "please check it first"),
        ("api_debug", "Why did this endpoint return empty?", "this is only the current investigation"),
        ("git_workflow", "Should we commit now or keep editing?", "do not store this"),
        ("daily_plan", "What reminder time would make sense tomorrow?", "I am only comparing options"),
    ]
    question_templates = [
        "{question} {tail}.",
        "Question for now: {question} {tail}.",
        "I want to check one thing: {question} {tail}.",
    ]
    for index, ((scenario, question, tail), template) in enumerate(
        grid(questions, question_templates, limit=30)
    ):
        add_case(
            cases,
            "en_negative_question_only",
            f"en_negative_question_only_{index:03d}",
            event("user_message", template.format(question=question, tail=tail)),
            [],
            scenario=scenario,
            utterance_style="question_only",
        )

    emotional_lines = [
        ("confusion", "I feel a bit lost right now", "just help me separate the layers"),
        ("overload", "there are too many test files and I am overwhelmed", "do not store this as a preference"),
        ("uncertainty", "this result makes me unsure", "it is only my current reaction"),
        ("frustration", "this step feels annoyingly roundabout", "do not treat that as long-term information"),
        ("hesitation", "I am not sure whether to keep expanding the dataset", "wait until I confirm"),
    ]
    emotional_templates = [
        "{emotion}; {tail}.",
        "Honestly, {emotion}; {tail}.",
        "{tail}, because {emotion}.",
        "My current state is: {emotion}; {tail}.",
        "For this moment, {emotion}; {tail}.",
    ]
    for index, ((scenario, emotion, tail), template) in enumerate(
        grid(emotional_lines, emotional_templates, limit=25)
    ):
        add_case(
            cases,
            "en_negative_emotional_or_social",
            f"en_negative_emotional_or_social_{index:03d}",
            event("user_message", template.format(emotion=emotion, tail=tail)),
            [],
            scenario=scenario,
            utterance_style="emotional_or_social",
        )

    project_facts = [
        ("pyproject", "pyproject.toml", "file_observation", "test configuration", "pytest reads tests from the tests directory"),
        ("api", "src/memory_system/api.py", "file_observation", "API entrypoint", "the API factory is memory_system.api:create_app"),
        ("cli", "src/memory_system/cli.py", "file_observation", "CLI entrypoint", "the command line entrypoint uses memory_system.cli"),
        ("store", "src/memory_system/memory_store.py", "file_observation", "write gate", "candidate writes go through evaluate_candidate"),
        ("orchestrator", "src/memory_system/recall_orchestrator.py", "file_observation", "recall entrypoint", "agents should use orchestrate_recall"),
        ("fixtures", "tests/fixtures/golden_cases/README.md", "file_observation", "golden fixture directory", "golden fixtures live under tests/fixtures/golden_cases"),
        ("remote", "shell", "tool_result", "remote health check", "remote health checks whether /models is reachable"),
        ("sqlite", "sqlite", "tool_result", "local database", "the example database defaults to data/memory.sqlite"),
        ("pytest", "pytest", "tool_result", "full test command", "the full test command is python -m pytest -q"),
    ]
    project_templates = [
        "Confirmed from {source}: {subject}: {fact}.",
        "Verified project fact from {source}: {subject} is {fact}.",
        "File observation: {source} shows that {subject} is {fact}.",
        "Tool output confirmed {subject}: {fact}; source is {source}.",
        "Current project fact: {subject}; {fact}.",
    ]
    for index, ((scenario, source, event_type, subject, fact), template) in enumerate(
        grid(project_facts, project_templates, limit=45)
    ):
        content = template.format(source=source, subject=subject, fact=fact)
        add_case(
            cases,
            "en_positive_project_fact_observed",
            f"en_positive_project_fact_observed_{index:03d}",
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
        ("remote_timeout", "remote embedding batch requests timed out", "reduce batch size first", "lowering the batch size and rerunning passed validation"),
        ("encoding", "PowerShell preview showed garbled English-adjacent output", "check the real file encoding first", "reading the file as UTF-8 passed validation"),
        ("no_match_noise", "semantic no-match cases recalled unrelated memories", "track FN, unexpected, and ambiguous together", "adding concrete fact-risk checks passed validation"),
        ("fixture_repeat", "fixture generation produced template-like repetition", "change the generator instead of editing JSONL by hand", "regenerating and auditing passed validation"),
        ("pythonpath", "API tests could not import the local package", "confirm that PYTHONPATH includes src", "setting PYTHONPATH=src passed validation"),
        ("sqlite_lock", "SQLite was locked on Windows", "check for an old process before changing code", "stopping the old process passed validation"),
        ("sensitive_candidate", "the remote LLM proposed a sensitive candidate", "run local sensitive preflight before remote calls", "filtering before remote evaluation passed validation"),
        ("doc_drift", "documentation disagreed with code behavior", "treat code behavior as the source of truth", "syncing README and verification docs passed validation"),
    ]
    troubleshooting_templates = [
        "Problem: {problem}. Lesson: {lesson}. Solution: {solution}. Verified.",
        "Problem: {problem}; lesson: {lesson}; solution: {solution}. Validation passed.",
        "Verified troubleshooting note. Problem: {problem}. Lesson: {lesson}. Solution: {solution}.",
        "Problem: {problem}. Lesson: {lesson}. Solution: {solution}. The fix was verified.",
        "Troubleshooting record: problem: {problem}; lesson: {lesson}; solution: {solution}; verified.",
    ]
    for index, ((scenario, problem, lesson, solution), template) in enumerate(
        grid(troubleshooting, troubleshooting_templates, limit=40)
    ):
        content = template.format(problem=problem, lesson=lesson, solution=solution)
        add_case(
            cases,
            "en_positive_troubleshooting_verified",
            f"en_positive_troubleshooting_verified_{index:03d}",
            event("tool_result", content, source="shell", scope=REPO_SCOPE),
            [expected("troubleshooting", "tool_result", "write", commit=True)],
            scenario=scenario,
            utterance_style="verified_troubleshooting",
        )

    tool_rules = [
        ("golden_fixture", "editing golden fixtures", "run the generator before audit"),
        ("secret_handling", "handling configs and logs", "never put real secrets into fixtures"),
        ("remote_quality", "connecting remote model statistics", "start with a small sample before scaling"),
        ("answer_grounding", "explaining test results", "separate confirmed facts from inference"),
        ("docs_sync", "syncing documentation", "read current code before changing README"),
        ("windows_shell", "searching files in PowerShell", "prefer rg and Get-Content"),
        ("dataset_review", "reviewing dataset quality", "check duplication before semantic coverage"),
        ("memory_write", "deciding long-term memory writes", "sensitive content should not become a candidate"),
        ("retrieval_eval", "evaluating recall", "watch FN, unexpected, and top1 together"),
    ]
    tool_templates = [
        "Confirmed tool rule: for {action}, {rule}.",
        "Fixed tool rule: when {action}, {rule}.",
        "Going forward, the rule for {action} is: {rule}.",
    ]
    for index, ((scenario, action, rule), template) in enumerate(
        grid(tool_rules, tool_templates, limit=25)
    ):
        claim = template.format(action=action, rule=rule)
        add_case(
            cases,
            "en_positive_tool_rule_explicit",
            f"en_positive_tool_rule_explicit_{index:03d}",
            event(
                "user_confirmation",
                claim,
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "tool_rule",
                    f"{action} tool rule",
                    claim,
                    reuse_cases=["repo_workflow", "verification"],
                ),
            ),
            [expected("tool_rule", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="explicit_tool_rule",
        )

    workflows = [
        ("release", "release checks", "run ruff, run pytest, then smoke-test the critical path"),
        ("fixture_update", "updating fixtures", "edit the generator, regenerate JSONL, then run audit"),
        ("remote_eval", "remote evaluation", "run 50 samples first, then decide whether to scale"),
        ("docs_sync", "documentation sync", "align with code behavior before editing docs"),
        ("retrieval_quality", "recall quality debugging", "read category statistics before failed examples"),
        ("commit", "committing code", "inspect git diff before running related tests"),
        ("api_change", "API changes", "add unit coverage before endpoint coverage"),
        ("data_download", "downloading public datasets", "keep raw data outside fixture files"),
        ("maintenance", "memory maintenance", "generate a review item before applying an action"),
    ]
    workflow_templates = [
        "Confirmed workflow: {name} means {step}.",
        "Fixed workflow for {name}: {step}.",
        "Going forward, when doing {name}, the workflow is {step}.",
    ]
    for index, ((scenario, name, step), template) in enumerate(
        grid(workflows, workflow_templates, limit=25)
    ):
        claim = template.format(name=name, step=step)
        add_case(
            cases,
            "en_positive_workflow_explicit",
            f"en_positive_workflow_explicit_{index:03d}",
            event(
                "user_confirmation",
                claim,
                scope=REPO_SCOPE,
                metadata=explicit_metadata("workflow", f"{name} workflow", claim),
            ),
            [expected("workflow", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="explicit_workflow",
        )

    environment_facts = [
        ("shell", "shell", "the current shell is PowerShell"),
        ("workspace", "workspace root", "the workspace root is C:/Users/Administrator/Desktop/memory"),
        ("data_root", "public data root", "public memory benchmark data is stored under E:/Xu/data/memory_benchmarks"),
        ("python", "Python command", "tests run with python -m pytest"),
        ("fixture_encoding", "fixture encoding", "golden fixture JSONL files use UTF-8"),
    ]
    environment_templates = [
        "Confirmed environment state: {area}; {fact}.",
        "Tool output confirmed {area}: {fact}.",
        "Verified environment fact: {area}; {fact}.",
        "Current environment state for {area}: {fact}.",
    ]
    for index, ((scenario, area, fact), template) in enumerate(
        grid(environment_facts, environment_templates, limit=20)
    ):
        claim = template.format(area=area, fact=fact)
        add_case(
            cases,
            "en_positive_environment_fact_explicit",
            f"en_positive_environment_fact_explicit_{index:03d}",
            event(
                "tool_result",
                claim,
                source="shell",
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "environment_fact",
                    f"{area} environment state",
                    claim,
                    evidence_type="tool_result",
                ),
            ),
            [expected("environment_fact", "tool_result", "write", commit=True)],
            scenario=scenario,
            utterance_style="explicit_environment_fact",
        )

    sensitive_items = [
        ("logs", "the log contains token=[REDACTED]", "do not write it into memory"),
        ("api_key", "the pasted config contains api_key=[REDACTED]", "only remind me to rotate it"),
        ("email", "a sample contains email=[REDACTED_EMAIL]", "keep only the redacted placeholder"),
        ("profile", "a public profile field may imply a sensitive identity", "use only the abstract category"),
        ("url", "a dataset URL may contain private tracking parameters", "do not treat it as a user fact"),
    ]
    sensitive_templates = [
        "{item}; {rule}.",
        "Sensitive note: {item}; {rule}.",
        "{item}; {rule}, and keep it out of long-term memory.",
        "For privacy: {item}; {rule}.",
        "Privacy note: {item}; {rule}.",
    ]
    for index, ((scenario, item, rule), template) in enumerate(
        grid(sensitive_items, sensitive_templates, limit=25)
    ):
        add_case(
            cases,
            "en_negative_sensitive",
            f"en_negative_sensitive_{index:03d}",
            event("user_message", template.format(item=item, rule=rule)),
            [],
            scenario=scenario,
            utterance_style="sensitive_negative",
        )

    duplicates = [
        ("auth_module", "authentication module test command", "Confirmed: the authentication module test command is python -m pytest tests/test_auth.py."),
        ("recall_module", "recall module test command", "Confirmed: the recall module test command is python -m pytest tests/test_recall_orchestrator.py."),
        ("api_module", "API module test command", "Confirmed: the API module test command is python -m pytest tests/test_api.py."),
        ("docs_module", "documentation summary", "Confirmed: PROJECT_OVERVIEW.md is the current-state summary for docs."),
        ("quality_module", "remote quality fixture", "Confirmed: the remote candidate quality fixture is remote_candidate_quality_50.jsonl."),
    ]
    duplicate_templates = [
        "{fact}",
        "{fact} Verified again.",
        "File observation repeated this fact: {fact}",
    ]
    for index, ((scenario, subject, fact), template) in enumerate(
        grid(duplicates, duplicate_templates, limit=15)
    ):
        content = template.format(fact=fact)
        add_case(
            cases,
            "en_merge_duplicate",
            f"en_merge_duplicate_{index:03d}",
            event(
                "file_observation",
                content,
                source=f"{scenario}.md",
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "project_fact",
                    subject,
                    content,
                    evidence_type="file_observation",
                ),
            ),
            [expected("project_fact", "file_observation", "merge", commit=True)],
            scenario=scenario,
            utterance_style="duplicate_fact",
            existing_memories=[memory(content, memory_type="project_fact", subject=subject)],
        )

    conflicts = [
        ("web_console", "web console default port", "Confirmed: the web console default port is 9010.", "Confirmed: the web console default port is 9020."),
        ("api_server", "API start command", "Confirmed: the API starts with uvicorn old_app:app.", "Confirmed: the API starts with python -m uvicorn memory_system.api:create_app --factory."),
        ("embedding_batch", "embedding batch size", "Confirmed: embedding batch size defaults to 16.", "Confirmed: embedding batch size defaults to 32."),
        ("browser_rule", "local page verification", "Confirmed: local pages are verified with the system browser.", "Confirmed: local pages are verified with the in-app browser."),
        ("encoding_rule", "fixture encoding", "Confirmed: English fixtures use CP1252.", "Confirmed: English fixtures use UTF-8."),
    ]
    conflict_templates = [
        "{new_fact}",
        "Updated file observation: {new_fact}",
        "Verified replacement fact: {new_fact}",
    ]
    for index, ((scenario, subject, old_fact, new_fact), template) in enumerate(
        grid(conflicts, conflict_templates, limit=15)
    ):
        content = template.format(new_fact=new_fact)
        add_case(
            cases,
            "en_ask_conflict",
            f"en_ask_conflict_{index:03d}",
            event(
                "file_observation",
                content,
                source=f"{scenario}.yaml",
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "project_fact",
                    subject,
                    content,
                    evidence_type="file_observation",
                ),
            ),
            [expected("project_fact", "file_observation", "ask_user")],
            scenario=scenario,
            utterance_style="conflicting_fact",
            existing_memories=[memory(old_fact, memory_type="project_fact", subject=subject)],
        )

    reference_direct = [
        ("public_dialog_sports", "discussing sports news", "state your information boundary before judgment"),
        ("public_dialog_health", "answering health lifestyle questions", "make clear that it is not medical advice"),
        ("public_dialog_entertainment", "discussing movies and shows", "do not store casual likes as stable preference"),
        ("public_dialog_education", "explaining classes or exams", "separate confirmed information from guesses"),
        ("public_dialog_games", "talking through game strategy", "give actionable steps before tradeoffs"),
        ("public_dialog_tech", "explaining technology news", "give background before impact"),
        ("persona_interest_music", "talking about music interests", "store stable preference only after repeated evidence"),
        ("persona_interest_travel", "talking about travel interests", "prioritize stable constraints like budget and transport"),
        ("persona_location", "using location hints", "do not treat source-corpus locations as the real user address"),
        ("persona_identity", "handling identity or job details", "write only after explicit user confirmation"),
    ]
    reference_direct_templates = [
        "Going forward, when {task}, {guidance}.",
        "By default, help me with {task} by doing this: {guidance}.",
        "Remember this long-term rule: when {task}, {guidance}.",
        "When we are {task}, please follow this rule: {guidance}.",
    ]
    for offset, ((scenario, task, guidance), template) in enumerate(
        grid(reference_direct, reference_direct_templates, limit=40),
        start=60,
    ):
        content = template.format(task=task, guidance=guidance)
        add_case(
            cases,
            "en_positive_preference_direct",
            f"en_positive_preference_direct_{offset:03d}",
            event("user_message", content),
            [expected("user_preference", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="reference_stable_preference",
            source_family="public_dialog_persona",
        )

    reference_uncertain = [
        ("topic_shift", "when the topic shifts from movies to travel", "ask whether I really want to switch"),
        ("health_chat", "when answering lifestyle health questions", "warn that the evidence may be incomplete"),
        ("game_chat", "when discussing game choices", "start with a beginner version"),
        ("interest_tag", "when using interest tags for recommendations", "ask whether the interest is still current"),
        ("location_hint", "when using city hints for recommendations", "ask whether that city still applies"),
    ]
    reference_uncertain_templates = [
        "Maybe I would prefer that {task}, you {guidance}, but do not lock it in.",
        "I might want you to {guidance} {task}; ask me before storing it.",
        "I am not sure whether {task} should always mean you {guidance}; put it in confirmation.",
        "I have not decided: {task}, should you {guidance}?",
        "Probably {task} should {guidance}, but the evidence is weak.",
    ]
    for offset, ((scenario, task, guidance), template) in enumerate(
        grid(reference_uncertain, reference_uncertain_templates, limit=25),
        start=45,
    ):
        content = template.format(task=task, guidance=guidance)
        add_case(
            cases,
            "en_review_preference_uncertain",
            f"en_review_preference_uncertain_{offset:03d}",
            event("user_message", content),
            [expected("user_preference", "direct_user_statement", "ask_user")],
            scenario=scenario,
            utterance_style="reference_uncertain_preference",
            source_family="public_dialog_persona",
        )

    reference_underspecified = [
        ("topic_transition", "That transition from sports to health felt natural"),
        ("background_context", "The background context arrived at a good pace"),
        ("casual_dialogue", "That casual response was not awkward"),
        ("daily_event", "The daily event summary was easy to follow"),
        ("abstention", "Saying you did not know was the right move"),
    ]
    for offset, ((scenario, context), phrase) in enumerate(
        grid(reference_underspecified, underspecified_phrases, limit=25),
        start=35,
    ):
        add_case(
            cases,
            "en_review_preference_underspecified",
            f"en_review_preference_underspecified_{offset:03d}",
            event("user_message", f"{context}; {phrase}"),
            [expected("user_preference", "direct_user_statement", "ask_user")],
            scenario=scenario,
            utterance_style="reference_underspecified_generalization",
            source_family="long_dialogue_benchmarks",
        )

    reference_temporary = [
        ("dialog_sampling", "sample 30 public-dialog conversations this time", "do not copy raw utterances into fixtures"),
        ("persona_sampling", "look only at the small persona split today", "the full train split is too large for this pass"),
        ("project_sampling", "inspect the project-state benchmark for this run", "we can decide later whether to add conflict cases"),
        ("longmem_sampling", "use question type as a category hint for now", "do not copy answer text"),
        ("locomo_sampling", "inspect multi-session questions this time", "only to design scenarios"),
    ]
    reference_temporary_templates = [
        "{action}; {reason}.",
        "For now, {action}, because {reason}.",
        "{action}; {reason}, so treat it as a one-off.",
        "Today only: {action}; {reason}.",
        "For this run, {action}; {reason}.",
    ]
    for offset, ((scenario, action, reason), template) in enumerate(
        grid(reference_temporary, reference_temporary_templates, limit=25),
        start=45,
    ):
        add_case(
            cases,
            "en_negative_temporary_request",
            f"en_negative_temporary_request_{offset:03d}",
            event("user_message", template.format(action=action, reason=reason), scope=REPO_SCOPE),
            [],
            scenario=scenario,
            utterance_style="reference_temporary_request",
            source_family="reference_mining",
        )

    reference_casual_likes = [
        ("sports_chat", "that athlete story", "it is only interesting in this chat"),
        ("entertainment_chat", "the premise of that movie", "it is not a stable genre preference"),
        ("game_chat", "that game character", "do not store it as a preference"),
        ("music_chat", "that lyric", "it only matches the current mood"),
        ("travel_chat", "that seaside photo", "do not treat it as my travel preference"),
        ("food_chat", "that restaurant name", "it was mentioned in passing"),
        ("social_chat", "that friend's joke", "do not write it as a fact"),
    ]
    reference_casual_templates = [
        "I like {item}; {reason}.",
        "{item} sounds nice, but {reason}.",
        "{item} works in this moment; {reason}.",
        "Just a passing reaction: I like {item}, but {reason}.",
        "{item} caught my attention; {reason}.",
    ]
    for offset, ((scenario, item, reason), template) in enumerate(
        grid(reference_casual_likes, reference_casual_templates, limit=35),
        start=35,
    ):
        add_case(
            cases,
            "en_negative_casual_like",
            f"en_negative_casual_like_{offset:03d}",
            event("user_message", template.format(item=item, reason=reason)),
            [],
            scenario=scenario,
            utterance_style="reference_casual_like",
            source_family="public_dialog_persona",
        )

    reference_questions = [
        ("abstention", "If the public data has no answer, how should the case be written?", "only asking for the principle"),
        ("temporal_order", "How should cross-session ordering be represented?", "do not store it yet"),
        ("project_state", "Should project-state updates be decision or project_fact?", "wait until we confirm"),
        ("dialog_topics", "Do all public-dialog topics need coverage?", "only a design question"),
        ("persona_profile", "Can persona interest tags be copied directly into cases?", "do not copy raw values"),
        ("dataset_license", "Can raw external utterances go into fixtures?", "treat the answer as no for now"),
    ]
    reference_question_templates = [
        "{question} {tail}.",
        "I want to confirm: {question} {tail}.",
        "Treat this as a question only: {question} {tail}.",
        "Quick question: {question} {tail}.",
        "Dataset question: {question} {tail}.",
    ]
    for offset, ((scenario, question, tail), template) in enumerate(
        grid(reference_questions, reference_question_templates, limit=30),
        start=30,
    ):
        add_case(
            cases,
            "en_negative_question_only",
            f"en_negative_question_only_{offset:03d}",
            event("user_message", template.format(question=question, tail=tail)),
            [],
            scenario=scenario,
            utterance_style="reference_question_only",
            source_family="reference_mining",
        )

    reference_emotions = [
        ("dataset_overload", "the external corpora feel like too much at once", "just classify them first"),
        ("license_concern", "I am worried about copyright and privacy boundaries", "this is only my current concern"),
        ("quality_confusion", "I still cannot tell which lines are memory-worthy", "do not store that as a preference"),
        ("sampling_anxiety", "the persona dataset size makes me unsure", "do not treat this as long-term information"),
        ("benchmark_fatigue", "these benchmark names are getting confusing", "help me organize them first"),
    ]
    reference_emotional_templates = [
        "{emotion}; {tail}.",
        "Honestly, {emotion}; {tail}.",
        "{tail}, because {emotion}.",
        "My current state is: {emotion}; {tail}.",
        "{emotion}; please {tail}.",
    ]
    for offset, ((scenario, emotion, tail), template) in enumerate(
        grid(reference_emotions, reference_emotional_templates, limit=25),
        start=25,
    ):
        add_case(
            cases,
            "en_negative_emotional_or_social",
            f"en_negative_emotional_or_social_{offset:03d}",
            event("user_message", template.format(emotion=emotion, tail=tail)),
            [],
            scenario=scenario,
            utterance_style="reference_emotional_or_social",
            source_family="reference_mining",
        )

    reference_project_facts = [
        ("naturalconv_inventory", "NaturalConv size", "NaturalConv has 19,919 dialogues and 400,562 utterances."),
        ("naturalconv_topics", "NaturalConv topics", "NaturalConv topics include sports, health, entertainment, education, games, and technology."),
        ("personal_dialog_inventory", "PersonalDialog size", "PersonalDialog train split has 5,438,165 rows."),
        ("personal_dialog_profiles", "PersonalDialog fields", "PersonalDialog includes dialog, profile, and uid fields."),
        ("longmemeval_inventory", "LongMemEval size", "the local LongMemEval mirror has 500 QA rows."),
        ("locomo_inventory", "LoCoMo size", "the local LoCoMo dialogue file has 35 rows."),
        ("realmem_inventory", "RealMemBench size", "the local RealMemBench mirror has 10 dialogue files at 256k context."),
    ]
    reference_project_templates = [
        "Confirmed: {subject}; {fact}",
        "Local inventory confirmed: {subject}; {fact}",
        "Reference corpus fact: {subject}. {fact}",
        "Tool output confirmed: {subject}; {fact}",
        "Verified external corpus inventory: {subject}; {fact}",
    ]
    for offset, ((scenario, subject, fact), template) in enumerate(
        grid(reference_project_facts, reference_project_templates, limit=35),
        start=45,
    ):
        content = template.format(subject=subject, fact=fact)
        add_case(
            cases,
            "en_positive_project_fact_observed",
            f"en_positive_project_fact_observed_{offset:03d}",
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
        ("hf_xet_tls", "Hugging Face Xet download hit a TLS handshake EOF", "do not assume the dataset is missing", "setting HF_HUB_DISABLE_XET=1 and retrying passed validation"),
        ("naturalconv_partial", "NaturalConv directory existed but lacked dialog_release.json", "exists does not mean complete", "refreshing with --force passed validation"),
        ("large_personal_dialog", "PersonalDialog train split is very large", "use dev/test and sampled statistics first", "generating the inventory passed validation"),
        ("windows_invalid_path", "a RealMemBench zip included Windows-invalid names", "skip trailing-space paths during extraction", "manifesting skipped paths passed validation"),
        ("external_raw_boundary", "raw external text should not enter repo fixtures", "extract structure and scenario shapes only", "rewriting as synthetic cases passed validation"),
    ]
    reference_troubleshooting_templates = [
        "Problem: {problem}. Lesson: {lesson}. Solution: {solution}. Verified.",
        "Troubleshooting note: Problem: {problem}. Lesson: {lesson}. Solution: {solution}.",
        "Verified troubleshooting note: Problem: {problem}. Lesson: {lesson}. Solution: {solution}.",
        "Problem: {problem}; lesson: {lesson}; solution: {solution}. Validation passed.",
    ]
    for offset, ((scenario, problem, lesson, solution), template) in enumerate(
        grid(reference_troubleshooting, reference_troubleshooting_templates, limit=20),
        start=40,
    ):
        content = template.format(problem=problem, lesson=lesson, solution=solution)
        add_case(
            cases,
            "en_positive_troubleshooting_verified",
            f"en_positive_troubleshooting_verified_{offset:03d}",
            event("tool_result", content, source="download_public_memory_datasets", scope=REPO_SCOPE),
            [expected("troubleshooting", "tool_result", "write", commit=True)],
            scenario=scenario,
            utterance_style="reference_troubleshooting",
            source_family="reference_download",
        )

    reference_tool_rules = [
        ("external_raw", "rewriting external corpora", "use only structure and expression distribution, never raw text"),
        ("download_retry", "downloading Hugging Face corpora", "try HF_HUB_DISABLE_XET=1 after Xet TLS errors"),
        ("inventory", "expanding public corpora", "update the download script before generating inventory"),
        ("fixture_source", "generating fixtures", "tag every case with source_family"),
        ("quality_check", "expanding English write gates", "check scenario and utterance_style dispersion"),
        ("naturalconv_license", "using NaturalConv", "reuse topics and dialogue shape, not original sentences"),
        ("persona_boundary", "using persona profiles", "abstract interests and identity types, not raw values"),
        ("longmem_abstention", "designing abstention cases", "keep expected.candidates empty or ask_user when evidence is missing"),
        ("locomo_temporal", "designing timeline cases", "preserve time changes instead of mixing them into current facts"),
        ("realmem_project_state", "designing project-memory cases", "separate goals, progress, decisions, and constraints"),
        ("derived_inventory", "reading derived inventory", "prefer statistics and structure over raw text"),
        ("scenario_labels", "expanding scenarios", "each group should span multiple source families"),
        ("utterance_styles", "expanding utterance styles", "do not only swap nouns within a category"),
        ("sensitive_profile", "handling profile fields", "do not write suspected personal information"),
        ("test_gate", "after expansion", "run the new fixture, audit, and full pytest"),
    ]
    for offset, (scenario, action, rule) in enumerate(reference_tool_rules, start=25):
        claim = f"Confirmed tool rule: for {action}, {rule}."
        add_case(
            cases,
            "en_positive_tool_rule_explicit",
            f"en_positive_tool_rule_explicit_{offset:03d}",
            event(
                "user_confirmation",
                claim,
                scope=REPO_SCOPE,
                metadata=explicit_metadata("tool_rule", f"{action} tool rule", claim),
            ),
            [expected("tool_rule", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="reference_tool_rule",
            source_family="reference_mining",
        )

    reference_workflows = [
        ("corpus_adaptation", "public corpus adaptation", "download to E:/Xu/data, generate inventory, then rewrite as synthetic fixtures"),
        ("quality_gate_v2", "write-gate v2 expansion", "expand scenario sources before running audit and full pytest"),
        ("dataset_refresh", "external data refresh", "run the download script with --force before checking manifest and core files"),
        ("source_boundary", "external data usage", "confirm raw text is not copied before keeping scenario shapes"),
        ("fixture_review", "fixture human review", "check template-like repetition before semantic coverage"),
        ("dialog_adaptation", "public dialogue adaptation", "extract topic shifts before generating chat negatives and uncertain preferences"),
        ("persona_adaptation", "persona data adaptation", "abstract profile fields before building interest and identity boundaries"),
        ("longmem_adaptation", "LongMemEval adaptation", "read question types before making abstention and update cases"),
        ("locomo_adaptation", "LoCoMo adaptation", "extract multi-session event shape before recall and write boundaries"),
        ("realmem_adaptation", "RealMemBench adaptation", "split goals, progress, decisions, and constraints before memory_type mapping"),
        ("inventory_refresh", "inventory refresh", "run the summarize script before reading derived reports"),
        ("raw_data_boundary", "raw data boundary", "keep external raw text on E drive and synthetic samples in the repo"),
        ("scenario_review", "scenario review", "inspect source_family distribution before natural-language spot checks"),
        ("negative_review", "negative review", "confirm no candidate is created before running write policy tests"),
        ("doc_sync_public", "public data doc sync", "update the download script before docs/12"),
    ]
    for offset, (scenario, name, step) in enumerate(reference_workflows, start=25):
        claim = f"Confirmed workflow: {name} means {step}."
        add_case(
            cases,
            "en_positive_workflow_explicit",
            f"en_positive_workflow_explicit_{offset:03d}",
            event(
                "user_confirmation",
                claim,
                scope=REPO_SCOPE,
                metadata=explicit_metadata("workflow", f"{name} workflow", claim),
            ),
            [expected("workflow", "direct_user_statement", "write", commit=True)],
            scenario=scenario,
            utterance_style="reference_workflow",
            source_family="reference_mining",
        )

    reference_env = [
        ("reference_root", "public corpus root", "the public corpus root is E:/Xu/data/memory_benchmarks"),
        ("derived_inventory", "public corpus inventory report", "the inventory report lives under E:/Xu/data/memory_benchmarks/derived"),
        ("naturalconv_file", "NaturalConv core file", "the NaturalConv core file is dialog_release.json"),
        ("personal_dialog_file", "PersonalDialog train file", "the PersonalDialog train file is dialogues_train.jsonl.gz"),
        ("manifest_file", "public corpus manifest", "the manifest file is E:/Xu/data/memory_benchmarks/manifest.json"),
    ]
    reference_env_templates = [
        "Confirmed environment state: {area}; {fact}.",
        "Tool output confirmed: {area}; {fact}.",
    ]
    for offset, ((scenario, area, fact), template) in enumerate(
        grid(reference_env, reference_env_templates, limit=10),
        start=20,
    ):
        claim = template.format(area=area, fact=fact)
        add_case(
            cases,
            "en_positive_environment_fact_explicit",
            f"en_positive_environment_fact_explicit_{offset:03d}",
            event(
                "tool_result",
                claim,
                source="reference_corpus_inventory",
                scope=REPO_SCOPE,
                metadata=explicit_metadata(
                    "environment_fact",
                    f"{area} environment state",
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
        ("raw_utterance", "raw external utterances may contain nicknames or locations", "do not copy them into fixtures"),
        ("profile_tags", "persona tags may imply sensitive identity", "use only the type, not the raw value"),
        ("document_url", "NaturalConv document URLs may contain original URLs", "do not treat them as user facts"),
        ("token_log", "a download log may contain token=[REDACTED]", "do not create a candidate"),
        ("email_profile", "a sample may contain email=[REDACTED_EMAIL]", "keep only the redacted placeholder"),
    ]
    reference_sensitive_templates = [
        "{item}; {rule}.",
        "Note: {item}; {rule}.",
        "{item}; {rule}, and keep it out of long-term memory.",
    ]
    for offset, ((scenario, item, rule), template) in enumerate(
        grid(reference_sensitive, reference_sensitive_templates, limit=15),
        start=25,
    ):
        add_case(
            cases,
            "en_negative_sensitive",
            f"en_negative_sensitive_{offset:03d}",
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
