from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "semantic_retrieval_public.jsonl"
REPO_SCOPE = "repo:C:/workspace/demo"


PUBLIC_BENCHMARK_NOTES = {
    "longmemeval": "Single-session, multi-session, temporal, update, and abstention QA.",
    "locomo": "Long multi-session everyday dialogue with events, relationships, and preferences.",
    "realmem": "Project-oriented long-term memory with goals, progress, decisions, and constraints.",
}


TOPICS: list[dict[str, Any]] = [
    {
        "key": "single_user",
        "category": "public_longmem_single_session_user",
        "benchmark_family": "longmemeval",
        "subject": "passport location",
        "content": "The user said Maya keeps her passport in the blue folder beside the printer.",
        "memory_type": "project_fact",
        "scope": "global",
        "tags": ["longmem", "single-session", "user-fact"],
        "queries": [
            "Where does Maya keep her passport?",
            "What folder has Maya's passport?",
            "If Maya needs travel documents, where should she look?",
            "Which place did the user mention for Maya's passport?",
            "What did the user say about the passport location?",
            "Where is the travel document stored?",
            "What should be checked near the printer?",
            "Which color folder matters for Maya?",
            "Where would Maya find the passport quickly?",
            "What location detail did the user give for Maya's documents?",
            "Maya is packing; where is the passport?",
            "Which folder is tied to Maya's passport?",
            "What did the conversation establish about the passport?",
            "Where should I tell Maya to look for her passport?",
            "What physical location is associated with the passport?",
            "Which item is in the blue folder?",
            "Where did the user say the passport was kept?",
            "What storage detail matters for Maya's travel prep?",
            "If asked about Maya's passport, what should be recalled?",
            "Which document location came from the user?",
        ],
    },
    {
        "key": "single_assistant",
        "category": "public_longmem_single_session_assistant",
        "benchmark_family": "longmemeval",
        "subject": "stale server fix",
        "content": "The assistant recommended checking the active port and process when the local page still shows old behavior.",
        "memory_type": "troubleshooting",
        "scope": REPO_SCOPE,
        "tags": ["longmem", "single-session", "assistant-advice"],
        "queries": [
            "What fix was suggested for a stale local page?",
            "What should be checked when the endpoint still looks old?",
            "Which troubleshooting step did the assistant recommend for stale behavior?",
            "How did the assistant say to verify the running server?",
            "What advice was given for a page that ignores the latest patch?",
            "Which process detail matters when localhost looks outdated?",
            "What should I inspect if a restart did not change the page?",
            "What was the assistant's recommendation for stale service output?",
            "How do I confirm the app is serving the new code?",
            "Which runtime check was proposed for old UI behavior?",
            "What port/process step should be remembered?",
            "What did the assistant say to do before trusting the running page?",
            "What is the remembered fix for stale localhost behavior?",
            "Which verification did the assistant suggest for active service confusion?",
            "What local-server advice came from the assistant?",
            "What should be done when live behavior differs from the patch?",
            "Which check helps avoid testing the wrong server?",
            "What did the assistant recommend for old code still appearing?",
            "How should a stale dev service be investigated?",
            "What troubleshooting memory applies to an unchanged endpoint?",
        ],
    },
    {
        "key": "preference",
        "category": "public_longmem_single_session_preference",
        "benchmark_family": "longmemeval",
        "subject": "explanation preference",
        "content": "The user prefers explanations that start with one concrete example before abstract rules.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["longmem", "preference", "teaching"],
        "queries": [
            "How should a new concept be explained to the user?",
            "Should the explanation begin with rules or an example?",
            "What teaching style does the user prefer?",
            "What should come before abstract guidance?",
            "How should I introduce a technical idea?",
            "What format makes explanations easier for the user?",
            "When explaining a mechanism, what should appear first?",
            "What user preference applies to teaching?",
            "Should I start with definitions or a concrete case?",
            "How do they like to learn abstractions?",
            "What explanation order should be remembered?",
            "Which response pattern helps the user understand?",
            "What should I do before generalizing the rule?",
            "How should I frame an unfamiliar API?",
            "What did the user prefer about examples?",
            "What learning preference matters here?",
            "How should conceptual material be introduced?",
            "What should the first paragraph include?",
            "Which explanation style fits this user?",
            "What memory guides teaching a complex idea?",
        ],
    },
    {
        "key": "multi_session",
        "category": "public_longmem_multi_session",
        "benchmark_family": "longmemeval",
        "subject": "project direction across sessions",
        "content": "Across earlier sessions, the user moved from a Python-only CLI plan to a FastAPI service with a CLI wrapper.",
        "memory_type": "project_fact",
        "scope": REPO_SCOPE,
        "tags": ["longmem", "multi-session", "project-direction"],
        "queries": [
            "What direction did the project settle on across sessions?",
            "Did the plan remain Python CLI only?",
            "How did the implementation plan evolve?",
            "What did the user move toward after earlier discussions?",
            "Which architecture replaced the CLI-only idea?",
            "What multi-session project decision should be recalled?",
            "What did the user decide about API support?",
            "How should I describe the current project direction?",
            "What changed from the original implementation plan?",
            "What is the remembered cross-session shift?",
            "Did FastAPI become part of the plan?",
            "What does the project now include besides a CLI?",
            "Which previous plan was superseded?",
            "What long-running decision affects implementation?",
            "What should be remembered about CLI and API scope?",
            "What was the final direction after multiple sessions?",
            "How did the scope grow beyond a command-line tool?",
            "Which project direction is current?",
            "What should I recall from earlier planning sessions?",
            "What architecture memory applies to the current work?",
        ],
    },
    {
        "key": "temporal",
        "category": "public_longmem_temporal_reasoning",
        "benchmark_family": "longmemeval",
        "subject": "appointment timeline",
        "content": "On April 3 the user scheduled a dentist visit for April 18, then on April 10 postponed it to April 22.",
        "memory_type": "project_fact",
        "scope": "global",
        "tags": ["longmem", "temporal", "calendar"],
        "queries": [
            "What is the latest dentist appointment date?",
            "Which date replaced the original dentist visit?",
            "After the postponement, when is the dentist appointment?",
            "What date should I use for the dental visit now?",
            "Did the April 18 appointment remain current?",
            "What is the updated appointment date?",
            "Which event happened after the first scheduling?",
            "What should be remembered about the dentist timeline?",
            "What was the appointment changed to?",
            "Which date is no longer current for the dentist visit?",
            "When should the user go to the dentist now?",
            "What later date superseded the first plan?",
            "What did the April 10 update change?",
            "How did the appointment date evolve?",
            "What is the final calendar fact?",
            "What should I answer if asked about the current dentist visit?",
            "Which dentist date is latest?",
            "What temporal update matters for the appointment?",
            "What date should not be treated as current anymore?",
            "What did the user postpone the visit to?",
        ],
        "stale_memory": {
            "subject": "old appointment date",
            "content": "The user scheduled a dentist visit for April 18.",
        },
    },
    {
        "key": "knowledge_update",
        "category": "public_longmem_knowledge_update",
        "benchmark_family": "longmemeval",
        "subject": "preferred notebook update",
        "content": "The user's current preferred notebook is the graph-paper A5 notebook, replacing the old dotted journal.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["longmem", "update", "preference"],
        "queries": [
            "Which notebook does the user currently prefer?",
            "What replaced the old dotted journal?",
            "What is the latest notebook preference?",
            "Should I recommend the dotted journal or graph paper?",
            "Which writing notebook is current?",
            "What preference update should be remembered?",
            "What did the user switch to?",
            "Which notebook choice is outdated?",
            "What should I buy if choosing a notebook for them?",
            "What did the newer preference say?",
            "Which paper style is preferred now?",
            "What memory supersedes the old journal preference?",
            "What is the current stationery preference?",
            "Which notebook detail should guide a purchase?",
            "What did the user replace the dotted journal with?",
            "Should the old notebook preference still be used?",
            "What updated preference matters?",
            "What should be recalled about A5 notebooks?",
            "Which preference is latest?",
            "What notebook would match the user's current taste?",
        ],
        "stale_memory": {
            "subject": "old notebook preference",
            "content": "The user preferred a dotted journal for notes.",
        },
    },
    {
        "key": "abstention_personal",
        "category": "public_longmem_abstention_personal",
        "benchmark_family": "longmemeval",
        "no_match": True,
        "queries": [
            "What is the user's blood type?",
            "Which high school did the user attend?",
            "What is the user's passport number?",
            "What is the exact name of the user's childhood pet?",
            "Which apartment number does the user live in?",
            "What was the user's first concert?",
            "What is the user's emergency contact phone number?",
            "Which gym class did the user book tomorrow?",
            "What is the user's favorite childhood song?",
            "What size shoes does the user wear?",
            "Which doctor did the user visit last week?",
            "What was the user's breakfast this morning?",
            "What is the user's current bank branch?",
            "Which airline seat did the user choose?",
            "What is the user's license plate?",
            "Which friend is visiting on Saturday?",
            "What is the user's insurance policy number?",
            "What was the user's last haircut date?",
            "Which exact hotel room did the user reserve?",
            "What is the user's employee ID?",
        ],
        "distractors": ["single_user", "preference", "temporal"],
    },
    {
        "key": "locomo_event",
        "category": "public_locomo_daily_event",
        "benchmark_family": "locomo",
        "subject": "garden visit",
        "content": "During a weekend chat, Nora said she visited the riverside garden after the rain stopped.",
        "memory_type": "project_fact",
        "scope": "global",
        "tags": ["locomo", "daily-event"],
        "queries": [
            "Where did Nora go after the rain stopped?",
            "What weekend outing did Nora mention?",
            "Which place did Nora visit in the conversation?",
            "What happened after the rain cleared?",
            "Where was Nora's casual walk?",
            "What daily event should be recalled about Nora?",
            "Which garden was mentioned?",
            "What did Nora do that weekend?",
            "Where did the post-rain visit happen?",
            "What outing detail came from Nora?",
            "Which location fits Nora's weekend story?",
            "Where should I say Nora went?",
            "What place did the dialogue establish?",
            "What did Nora mention doing outside?",
            "Which event followed the rain stopping?",
            "What was Nora's small weekend memory?",
            "What should be remembered about Nora's garden visit?",
            "Which riverside place did Nora visit?",
            "What did the user share about Nora's weekend?",
            "Where did the conversation place Nora after the rain?",
        ],
    },
    {
        "key": "locomo_relationship",
        "category": "public_locomo_relationship",
        "benchmark_family": "locomo",
        "subject": "roommate relationship",
        "content": "In the dialogue, Leo referred to Priya as his former roommate from the design residency.",
        "memory_type": "project_fact",
        "scope": "global",
        "tags": ["locomo", "relationship"],
        "queries": [
            "Who is Priya to Leo?",
            "How did Leo know Priya?",
            "What relationship connects Leo and Priya?",
            "Where did Leo and Priya live together?",
            "What did Leo call Priya?",
            "Which residency connects the two people?",
            "What should be recalled about Priya?",
            "Was Priya Leo's colleague or former roommate?",
            "How should I describe Priya in relation to Leo?",
            "What past living arrangement was mentioned?",
            "Who was Leo's former roommate?",
            "What memory links Priya to the design residency?",
            "What role did Priya have in Leo's story?",
            "Which person came from the residency context?",
            "What relationship fact did the dialogue establish?",
            "How are Leo and Priya connected?",
            "What did Leo say about his old roommate?",
            "Which relationship should be remembered from the chat?",
            "What was Priya's connection to Leo's residency?",
            "How did the conversation identify Priya?",
        ],
    },
    {
        "key": "locomo_preference",
        "category": "public_locomo_preference",
        "benchmark_family": "locomo",
        "subject": "movie preference",
        "content": "During casual conversation, Mina said she prefers quiet documentaries over loud action movies.",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["locomo", "preference", "media"],
        "queries": [
            "What kind of movie does Mina prefer?",
            "Should I suggest an action film for Mina?",
            "What media preference did Mina mention?",
            "Which film style fits Mina better?",
            "What should be remembered when choosing a movie?",
            "Does Mina like loud action movies?",
            "What type of documentary preference was stated?",
            "How should I pick a movie for Mina?",
            "What entertainment detail came from the chat?",
            "Which movie genre should be avoided?",
            "What would be a safer film recommendation?",
            "What is Mina's media taste?",
            "What kind of viewing experience does Mina prefer?",
            "Should I choose calm or loud entertainment?",
            "Which preference applies to movie night?",
            "What did Mina say about documentaries?",
            "What film recommendation should match the memory?",
            "How should Mina's preference guide planning?",
            "What style of movie is less suitable?",
            "What should be recalled about Mina's movie taste?",
        ],
    },
    {
        "key": "realm_goal",
        "category": "public_realmem_project_goal",
        "benchmark_family": "realmem",
        "subject": "project goal",
        "content": "The project goal is to build a memory assistant that tracks research tasks across months without storing secrets.",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["realmem", "project-goal"],
        "queries": [
            "What is the long-term goal of the project?",
            "What kind of assistant is being built?",
            "What should the project track over months?",
            "What constraint is part of the project goal?",
            "How should I describe the memory assistant objective?",
            "What is the purpose of the system?",
            "What long-running work should the assistant support?",
            "What does the project avoid storing?",
            "Which project goal should guide design choices?",
            "What is the remembered high-level objective?",
            "What should the assistant help with over time?",
            "Which goal came from the project brief?",
            "What is the memory system trying to achieve?",
            "How should months-long research be handled?",
            "What goal combines task tracking and privacy?",
            "What should I recall about the target product?",
            "What is the project's north star?",
            "Which objective matters for future implementation?",
            "What long-term memory goal applies here?",
            "What should the system become?",
        ],
    },
    {
        "key": "realm_progress",
        "category": "public_realmem_project_progress",
        "benchmark_family": "realmem",
        "subject": "project progress",
        "content": "The latest project progress is that local write policy, lifecycle, graph recall, and remote retrieval fixtures are implemented.",
        "memory_type": "project_fact",
        "scope": REPO_SCOPE,
        "tags": ["realmem", "project-progress"],
        "queries": [
            "What parts of the memory project are already implemented?",
            "What is the current progress of the project?",
            "Which memory-system modules are done?",
            "Has graph recall been implemented yet?",
            "What should be listed as completed work?",
            "What does the latest progress say?",
            "Which fixtures are already in place?",
            "What local capabilities exist now?",
            "What should I recall about implementation status?",
            "Which stage has the project reached?",
            "What progress should guide the next roadmap?",
            "What has been built before this step?",
            "What project facts describe completed components?",
            "Which retrieval work is already implemented?",
            "What local memory features are ready?",
            "What is not just planned anymore?",
            "Which implemented parts should be mentioned?",
            "What current status matters for planning?",
            "What should I say if asked what exists?",
            "What progress memory applies to this project?",
        ],
    },
    {
        "key": "realm_decision",
        "category": "public_realmem_project_decision",
        "benchmark_family": "realmem",
        "subject": "dataset decision",
        "content": "The dataset decision is to keep deterministic synthetic fixtures in the repo and external public benchmarks under E:/Xu/data.",
        "memory_type": "decision",
        "scope": REPO_SCOPE,
        "tags": ["realmem", "project-decision", "dataset"],
        "queries": [
            "Where should external public datasets live?",
            "What was decided about repo fixtures versus downloaded data?",
            "Should public benchmark files be committed?",
            "How are synthetic fixtures separated from external datasets?",
            "What dataset storage decision should be remembered?",
            "Where do deterministic fixtures belong?",
            "What path should hold public benchmark downloads?",
            "What was the project decision about data placement?",
            "How should we avoid mixing external data into CI?",
            "Which dataset policy applies here?",
            "What should be kept in the repository?",
            "What should stay outside the repository?",
            "How should downloaded benchmarks be managed?",
            "What memory explains the dataset folder split?",
            "Where should LongMemEval and RealMemBench be stored?",
            "What decision prevents committing external corpora?",
            "What is the current data management rule?",
            "Which location is used for public memory benchmarks?",
            "How should fixture data and reference data differ?",
            "What dataset decision affects future scripts?",
        ],
    },
    {
        "key": "realm_constraint",
        "category": "public_realmem_project_constraint",
        "benchmark_family": "realmem",
        "subject": "privacy constraint",
        "content": "A hard project constraint is that raw secrets, tokens, and personal identifiers must not be written into memory fixtures.",
        "memory_type": "tool_rule",
        "scope": REPO_SCOPE,
        "tags": ["realmem", "constraint", "privacy"],
        "queries": [
            "What privacy constraint applies to memory fixtures?",
            "Can raw tokens be written into the dataset?",
            "What must be excluded from memory fixtures?",
            "How should secrets be handled in test data?",
            "Which data should never be stored?",
            "What project constraint protects sensitive information?",
            "Should personal identifiers become fixture content?",
            "What rule applies to API keys in memory tests?",
            "What should be redacted before writing samples?",
            "Which privacy rule should guide dataset generation?",
            "What is forbidden in fixture rows?",
            "How should test data treat raw credentials?",
            "What constraint matters when mining public data?",
            "Can downloaded examples with identifiers be copied directly?",
            "What memory rule prevents sensitive leakage?",
            "What should not enter synthetic fixtures?",
            "Which safety rule applies to tokens?",
            "How should private values be represented?",
            "What should I recall about sensitive test cases?",
            "What fixture constraint is non-negotiable?",
        ],
    },
    {
        "key": "realm_no_match",
        "category": "public_realmem_project_abstention",
        "benchmark_family": "realmem",
        "no_match": True,
        "queries": [
            "Which production customer uses the memory assistant today?",
            "What is the exact cloud bucket for benchmark exports?",
            "Who owns the private deployment contract?",
            "What is the current paid user count?",
            "Which real API key is configured for the project?",
            "What is the internal incident ticket number?",
            "Which company purchased the enterprise plan?",
            "What is the production database password?",
            "Which legal reviewer approved the dataset license?",
            "What is the user's government identifier?",
            "Which private Slack channel stores benchmark notes?",
            "What is the production region for customer data?",
            "Who is the external vendor contact?",
            "What exact billing account is attached?",
            "Which customer transcript should be imported?",
            "What is the secret evaluation endpoint?",
            "Which employee owns the benchmark budget?",
            "What is the real user email in the corpus?",
            "Which private dataset cannot be shared?",
            "What is the unreleased model access token?",
        ],
        "distractors": ["realm_goal", "realm_progress", "realm_constraint"],
    },
]


def memory(
    alias: str,
    topic: dict[str, Any],
    *,
    content: str | None = None,
    subject: str | None = None,
    status: str = "active",
) -> dict[str, Any]:
    return {
        "alias": alias,
        "content": content if content is not None else topic["content"],
        "memory_type": topic["memory_type"],
        "scope": topic["scope"],
        "subject": subject if subject is not None else topic["subject"],
        "confidence": "confirmed",
        "source_event_ids": [f"evt_{alias}"],
        "tags": list(topic["tags"]),
        "status": status,
    }


def retrieval_case(
    *,
    topic: dict[str, Any],
    query: str,
    query_index: int,
    distractor_a: dict[str, Any],
    distractor_b: dict[str, Any],
) -> dict[str, Any]:
    suffix = f"{topic['key']}_{query_index:03d}"
    target_alias = f"{suffix}_target"
    distractor_a_alias = f"{suffix}_distractor_a"
    distractor_b_alias = f"{suffix}_distractor_b"
    memories = [memory(target_alias, topic)]
    if "stale_memory" in topic:
        old = topic["stale_memory"]
        old_alias = f"{suffix}_old_stale"
        memories.append(
            memory(
                old_alias,
                topic,
                content=old["content"],
                subject=old["subject"],
                status="stale",
            )
        )
        absent_aliases = [old_alias, distractor_a_alias]
        memories.append(memory(distractor_a_alias, distractor_a))
    else:
        absent_aliases = [distractor_a_alias, distractor_b_alias]
        memories.extend([memory(distractor_a_alias, distractor_a), memory(distractor_b_alias, distractor_b)])

    return {
        "category": topic["category"],
        "benchmark_family": topic["benchmark_family"],
        "mode": "retrieval",
        "name": f"semantic_public_{suffix}",
        "search": {
            "query": query,
            "scopes": [REPO_SCOPE, "global"],
            "limit": 1,
        },
        "expected": {
            "ordered_prefix": [target_alias],
            "absent_aliases": absent_aliases,
        },
        "memories": memories,
    }


def no_match_case(
    *,
    topic: dict[str, Any],
    query: str,
    query_index: int,
    topics_by_key: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    aliases = [f"{topic['key']}_{query_index:03d}_distractor_{idx}" for idx in range(3)]
    distractors = [topics_by_key[key] for key in topic["distractors"]]
    return {
        "category": topic["category"],
        "benchmark_family": topic["benchmark_family"],
        "mode": "retrieval",
        "name": f"semantic_public_{topic['key']}_{query_index:03d}",
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
            memory(alias, distractor)
            for alias, distractor in zip(aliases, distractors)
        ],
    }


def build_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    topics_by_key = {topic["key"]: topic for topic in TOPICS}
    retrieval_topics = [topic for topic in TOPICS if not topic.get("no_match")]
    for topic_index, topic in enumerate(TOPICS):
        for query_index, query in enumerate(topic["queries"]):
            if topic.get("no_match"):
                cases.append(
                    no_match_case(
                        topic=topic,
                        query=query,
                        query_index=query_index,
                        topics_by_key=topics_by_key,
                    )
                )
                continue
            distractor_a = retrieval_topics[(topic_index + 4) % len(retrieval_topics)]
            distractor_b = retrieval_topics[(topic_index + 9) % len(retrieval_topics)]
            cases.append(
                retrieval_case(
                    topic=topic,
                    query=query,
                    query_index=query_index,
                    distractor_a=distractor_a,
                    distractor_b=distractor_b,
                )
            )
    return cases


def main() -> None:
    cases = build_cases()
    if len(cases) != 300:
        raise RuntimeError(f"expected 300 cases, got {len(cases)}")
    if len({case["name"] for case in cases}) != len(cases):
        raise RuntimeError("case names must be unique")
    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False, separators=(",", ":")) for case in cases)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
