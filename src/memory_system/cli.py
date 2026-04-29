from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from memory_system.event_log import EventLog
from memory_system.memory_store import (
    MemoryNotFoundError,
    MemoryPolicyError,
    MemoryStore,
    build_memory_embedding_text,
)
from memory_system.remote import (
    RemoteAdapterConfig,
    RemoteAdapterError,
    RemoteAdapterNotConfiguredError,
    RemoteEmbeddingClient,
    RemoteLLMClient,
    route_item_to_memory_candidate,
)
from memory_system.remote_evaluation import (
    backfill_remote_memory_embeddings,
    evaluate_remote_candidate_quality,
    evaluate_remote_retrieval_fixture,
    load_events_for_remote_evaluation,
    remote_guarded_hybrid_search,
    remote_llm_guarded_hybrid_search,
    remote_selective_llm_guarded_hybrid_search,
)
from memory_system.schemas import (
    ConflictReviewItemRead,
    EventRead,
    MaintenanceReviewItemRead,
    RemoteCandidateImportResult,
    SearchMemoryInput,
)
from memory_system.session_memory import SessionMemoryStore, session_item_from_route_item


DEFAULT_DB_PATH = os.environ.get("MEMORY_SYSTEM_DB", "data/memory.sqlite")
REVIEW_STATUSES = ("pending", "resolved", "needs_user", "dismissed")
REVIEW_ACTIONS = (
    "accept_new",
    "keep_existing",
    "keep_both_scoped",
    "ask_user",
    "archive_all",
)
MAINTENANCE_ACTIONS = ("keep", "review", "mark_stale", "archive")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memoryctl",
        description="Inspect and manage memory-system review queues.",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path. Defaults to {DEFAULT_DB_PATH!r} or MEMORY_SYSTEM_DB.",
    )

    commands = parser.add_subparsers(dest="command", required=True)
    reviews = commands.add_parser("reviews", help="Manage conflict review items.")
    review_commands = reviews.add_subparsers(dest="review_command", required=True)

    generate = review_commands.add_parser(
        "generate",
        help="Create pending review items from current graph conflicts.",
    )
    _add_review_filters(generate)
    generate.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    generate.set_defaults(func=_cmd_reviews_generate)

    list_reviews = review_commands.add_parser("list", help="List conflict review items.")
    _add_review_filters(list_reviews, include_status=True)
    list_reviews.add_argument("--offset", type=int, default=0)
    list_reviews.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    list_reviews.set_defaults(func=_cmd_reviews_list)

    show = review_commands.add_parser("show", help="Show one conflict review with sources.")
    show.add_argument("review_id")
    show.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    show.set_defaults(func=_cmd_reviews_show)

    resolve = review_commands.add_parser("resolve", help="Resolve one conflict review.")
    resolve.add_argument("review_id")
    resolve.add_argument("--action", required=True, choices=REVIEW_ACTIONS)
    resolve.add_argument(
        "--keep-memory-id",
        dest="keep_memory_ids",
        action="append",
        default=[],
        help="Memory id to keep. Can be passed multiple times.",
    )
    resolve.add_argument("--reason")
    resolve.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    resolve.set_defaults(func=_cmd_reviews_resolve)

    maintenance = commands.add_parser("maintenance", help="Manage memory maintenance reviews.")
    maintenance_commands = maintenance.add_subparsers(
        dest="maintenance_command",
        required=True,
    )

    maintenance_generate = maintenance_commands.add_parser(
        "generate",
        help="Create pending maintenance reviews from usage stats.",
    )
    _add_maintenance_filters(maintenance_generate, include_scope_type=True)
    maintenance_generate.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    maintenance_generate.set_defaults(func=_cmd_maintenance_generate)

    maintenance_list = maintenance_commands.add_parser(
        "list",
        help="List maintenance reviews.",
    )
    _add_maintenance_filters(
        maintenance_list,
        include_status=True,
        include_memory_id=True,
    )
    maintenance_list.add_argument("--offset", type=int, default=0)
    maintenance_list.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    maintenance_list.set_defaults(func=_cmd_maintenance_list)

    maintenance_show = maintenance_commands.add_parser(
        "show",
        help="Show one maintenance review with memory usage stats.",
    )
    maintenance_show.add_argument("review_id")
    maintenance_show.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    maintenance_show.set_defaults(func=_cmd_maintenance_show)

    maintenance_resolve = maintenance_commands.add_parser(
        "resolve",
        help="Resolve one maintenance review.",
    )
    maintenance_resolve.add_argument("review_id")
    maintenance_resolve.add_argument("--action", required=True, choices=MAINTENANCE_ACTIONS)
    maintenance_resolve.add_argument("--reason")
    maintenance_resolve.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    maintenance_resolve.set_defaults(func=_cmd_maintenance_resolve)

    remote = commands.add_parser("remote", help="Inspect and call configured remote adapters.")
    remote_commands = remote.add_subparsers(dest="remote_command", required=True)

    remote_status = remote_commands.add_parser(
        "status",
        help="Show remote adapter configuration without exposing secrets.",
    )
    remote_status.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    remote_status.set_defaults(func=_cmd_remote_status)

    remote_health = remote_commands.add_parser(
        "health",
        help="Call the remote adapter health endpoint.",
    )
    remote_health.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    remote_health.set_defaults(func=_cmd_remote_health)

    remote_extract = remote_commands.add_parser(
        "extract",
        help=(
            "Legacy long-term-only dry run: ask the remote LLM adapter to propose "
            "candidates for one event. Prefer `remote route` for normal memory routing."
        ),
    )
    remote_extract.add_argument("event_id")
    remote_extract.add_argument("--instructions")
    remote_extract.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    remote_extract.set_defaults(func=_cmd_remote_extract)

    remote_import = remote_commands.add_parser(
        "import",
        help=(
            "Legacy long-term-only import: write remote LLM candidates into the local "
            "pending candidate queue. Prefer `remote route` for normal memory routing."
        ),
    )
    remote_import.add_argument("event_id")
    remote_import.add_argument("--instructions")
    remote_import.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    remote_import.set_defaults(func=_cmd_remote_import)

    remote_route = remote_commands.add_parser(
        "route",
        help="Route remote LLM memory items into long-term candidates and session memory.",
    )
    remote_route.add_argument(
        "--event-id",
        dest="event_ids",
        action="append",
        default=[],
        help="Target event id to route. Can be passed multiple times.",
    )
    remote_route.add_argument(
        "--recent-event-id",
        dest="recent_event_ids",
        action="append",
        default=[],
        help="Context-only event id. Can be passed multiple times.",
    )
    remote_route.add_argument("--session-id", default="default")
    remote_route.add_argument("--instructions")
    remote_route.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    remote_route.set_defaults(func=_cmd_remote_route)

    remote_evaluate = remote_commands.add_parser(
        "evaluate",
        help="Compare local rule extraction with remote LLM extraction without writing candidates.",
    )
    remote_evaluate.add_argument(
        "--event-id",
        dest="event_ids",
        action="append",
        default=[],
        help="Event id to evaluate. Can be passed multiple times.",
    )
    remote_evaluate.add_argument("--source")
    remote_evaluate.add_argument("--scope")
    remote_evaluate.add_argument("--task-id")
    remote_evaluate.add_argument("--limit", type=int, default=20)
    remote_evaluate.add_argument("--instructions")
    remote_evaluate.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    remote_evaluate.set_defaults(func=_cmd_remote_evaluate)

    remote_embed = remote_commands.add_parser(
        "embed",
        help="Ask the remote embedding adapter to embed one or more texts.",
    )
    remote_embed.add_argument("text", nargs="+")
    remote_embed.add_argument("--model")
    remote_embed.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    remote_embed.set_defaults(func=_cmd_remote_embed)

    remote_embed_memory = remote_commands.add_parser(
        "embed-memory",
        help="Generate and cache a remote embedding for one committed memory.",
    )
    remote_embed_memory.add_argument("memory_id")
    remote_embed_memory.add_argument("--model")
    remote_embed_memory.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    remote_embed_memory.set_defaults(func=_cmd_remote_embed_memory)

    remote_embed_backfill = remote_commands.add_parser(
        "embed-backfill",
        help="Generate and cache missing remote embeddings for committed memories.",
    )
    remote_embed_backfill.add_argument("--model")
    remote_embed_backfill.add_argument("--scope")
    remote_embed_backfill.add_argument("--memory-type")
    remote_embed_backfill.add_argument("--limit", type=int, default=100)
    remote_embed_backfill.add_argument("--batch-size", type=int, default=16)
    remote_embed_backfill.add_argument("--dry-run", action="store_true")
    remote_embed_backfill.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    remote_embed_backfill.set_defaults(func=_cmd_remote_embed_backfill)

    remote_hybrid_search = remote_commands.add_parser(
        "hybrid-search",
        help="Embed a query remotely and run local hybrid memory search.",
    )
    remote_hybrid_search.add_argument("query")
    remote_hybrid_search.add_argument("--model")
    remote_hybrid_search.add_argument("--scope", action="append", default=[])
    remote_hybrid_search.add_argument("--memory-type", action="append", default=[])
    remote_hybrid_search.add_argument("--limit", type=int, default=10)
    remote_hybrid_search.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    remote_hybrid_search.set_defaults(func=_cmd_remote_hybrid_search)

    remote_guarded_hybrid_search = remote_commands.add_parser(
        "guarded-hybrid-search",
        help="Run remote hybrid search and guard close or low-similarity matches.",
    )
    remote_guarded_hybrid_search.add_argument("query")
    remote_guarded_hybrid_search.add_argument("--model")
    remote_guarded_hybrid_search.add_argument("--scope", action="append", default=[])
    remote_guarded_hybrid_search.add_argument("--memory-type", action="append", default=[])
    remote_guarded_hybrid_search.add_argument("--limit", type=int, default=10)
    remote_guarded_hybrid_search.add_argument("--guard-top-k", type=int, default=3)
    remote_guarded_hybrid_search.add_argument("--guard-min-similarity", type=float, default=0.20)
    remote_guarded_hybrid_search.add_argument("--guard-ambiguity-margin", type=float, default=0.03)
    remote_guarded_hybrid_search.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    remote_guarded_hybrid_search.set_defaults(func=_cmd_remote_guarded_hybrid_search)

    remote_llm_guarded_hybrid_search = remote_commands.add_parser(
        "llm-guarded-hybrid-search",
        help="Run remote hybrid search, local guard, then remote LLM recall judging.",
    )
    remote_llm_guarded_hybrid_search.add_argument("query")
    remote_llm_guarded_hybrid_search.add_argument("--model")
    remote_llm_guarded_hybrid_search.add_argument("--scope", action="append", default=[])
    remote_llm_guarded_hybrid_search.add_argument("--memory-type", action="append", default=[])
    remote_llm_guarded_hybrid_search.add_argument("--limit", type=int, default=10)
    remote_llm_guarded_hybrid_search.add_argument("--guard-top-k", type=int, default=3)
    remote_llm_guarded_hybrid_search.add_argument("--guard-min-similarity", type=float, default=0.20)
    remote_llm_guarded_hybrid_search.add_argument(
        "--guard-ambiguity-margin",
        type=float,
        default=0.03,
    )
    remote_llm_guarded_hybrid_search.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    remote_llm_guarded_hybrid_search.set_defaults(func=_cmd_remote_llm_guarded_hybrid_search)

    remote_selective_llm_guarded_hybrid_search = remote_commands.add_parser(
        "selective-llm-guarded-hybrid-search",
        help="Run remote hybrid search and call the remote LLM judge only when local guard is uncertain.",
    )
    remote_selective_llm_guarded_hybrid_search.add_argument("query")
    remote_selective_llm_guarded_hybrid_search.add_argument("--model")
    remote_selective_llm_guarded_hybrid_search.add_argument("--scope", action="append", default=[])
    remote_selective_llm_guarded_hybrid_search.add_argument(
        "--memory-type",
        action="append",
        default=[],
    )
    remote_selective_llm_guarded_hybrid_search.add_argument("--limit", type=int, default=10)
    remote_selective_llm_guarded_hybrid_search.add_argument("--guard-top-k", type=int, default=3)
    remote_selective_llm_guarded_hybrid_search.add_argument(
        "--guard-min-similarity",
        type=float,
        default=0.20,
    )
    remote_selective_llm_guarded_hybrid_search.add_argument(
        "--guard-ambiguity-margin",
        type=float,
        default=0.03,
    )
    remote_selective_llm_guarded_hybrid_search.add_argument(
        "--selective-min-similarity",
        type=float,
        default=0.20,
    )
    remote_selective_llm_guarded_hybrid_search.add_argument(
        "--selective-ambiguity-margin",
        type=float,
        default=0.03,
    )
    remote_selective_llm_guarded_hybrid_search.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    remote_selective_llm_guarded_hybrid_search.set_defaults(
        func=_cmd_remote_selective_llm_guarded_hybrid_search
    )

    remote_evaluate_retrieval = remote_commands.add_parser(
        "evaluate-retrieval",
        help="Compare keyword, semantic, and hybrid retrieval against a golden fixture.",
    )
    remote_evaluate_retrieval.add_argument(
        "--fixture",
        default="tests/fixtures/golden_cases/semantic_retrieval.jsonl",
    )
    remote_evaluate_retrieval.add_argument("--model")
    remote_evaluate_retrieval.add_argument("--limit", type=int)
    remote_evaluate_retrieval.add_argument(
        "--sample-size",
        type=int,
        help="Randomly sample this many retrieval cases before applying limit.",
    )
    remote_evaluate_retrieval.add_argument(
        "--sample-seed",
        type=int,
        help="Seed for reproducible retrieval fixture sampling.",
    )
    remote_evaluate_retrieval.add_argument("--batch-size", type=int, default=16)
    remote_evaluate_retrieval.add_argument(
        "--case-concurrency",
        type=int,
        default=1,
        help="Number of test cases to evaluate concurrently.",
    )
    remote_evaluate_retrieval.add_argument(
        "--judge-concurrency",
        type=int,
        default=1,
        help="Number of remote LLM judge requests to run concurrently.",
    )
    remote_evaluate_retrieval.add_argument(
        "--judge-group-size",
        type=int,
        default=1,
        help="Number of pending judge tasks to put in each remote LLM judge request.",
    )
    remote_evaluate_retrieval.add_argument(
        "--embedding-cache",
        help="Optional JSONL cache path for remote embedding vectors.",
    )
    remote_evaluate_retrieval.add_argument(
        "--report-path",
        help="Optional path to write the full JSON evaluation report.",
    )
    remote_evaluate_retrieval.add_argument("--guard-top-k", type=int, default=3)
    remote_evaluate_retrieval.add_argument("--guard-min-similarity", type=float, default=0.20)
    remote_evaluate_retrieval.add_argument("--guard-ambiguity-margin", type=float, default=0.03)
    remote_evaluate_retrieval.add_argument(
        "--llm-judge",
        action="store_true",
        help="Also evaluate llm_guarded_hybrid using the remote LLM recall judge.",
    )
    remote_evaluate_retrieval.add_argument(
        "--selective-llm-judge",
        action="store_true",
        help="Also evaluate selective_llm_guarded_hybrid with conditional remote LLM judging.",
    )
    remote_evaluate_retrieval.add_argument("--selective-min-similarity", type=float, default=0.20)
    remote_evaluate_retrieval.add_argument(
        "--selective-ambiguity-margin",
        type=float,
        default=0.03,
    )
    remote_evaluate_retrieval.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    remote_evaluate_retrieval.set_defaults(func=_cmd_remote_evaluate_retrieval)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = MemoryStore(Path(args.db))
    try:
        return args.func(args, store)
    except MemoryNotFoundError as exc:
        print(f"not found: {exc}", file=sys.stderr)
        return 2
    except RemoteAdapterNotConfiguredError as exc:
        print(f"remote not configured: {exc}", file=sys.stderr)
        return 2
    except RemoteAdapterError as exc:
        print(f"remote error: {exc}", file=sys.stderr)
        return 1
    except (MemoryPolicyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _add_review_filters(parser: argparse.ArgumentParser, *, include_status: bool = False) -> None:
    if include_status:
        parser.add_argument("--status", choices=REVIEW_STATUSES)
    parser.add_argument("--scope")
    parser.add_argument("--relation-type")
    parser.add_argument("--limit", type=int, default=100)


def _add_maintenance_filters(
    parser: argparse.ArgumentParser,
    *,
    include_status: bool = False,
    include_scope_type: bool = False,
    include_memory_id: bool = False,
) -> None:
    if include_status:
        parser.add_argument("--status", choices=REVIEW_STATUSES)
    if include_scope_type:
        parser.add_argument("--scope")
        parser.add_argument("--memory-type")
    parser.add_argument("--recommended-action", choices=MAINTENANCE_ACTIONS)
    if include_memory_id:
        parser.add_argument("--memory-id")
    parser.add_argument("--limit", type=int, default=100)


def _cmd_reviews_generate(args: argparse.Namespace, store: MemoryStore) -> int:
    reviews = store.create_conflict_reviews(
        scope=args.scope,
        relation_type=args.relation_type,
        limit=args.limit,
    )
    if args.json:
        _print_json([_review_summary_payload(review) for review in reviews])
    else:
        _print_review_list(reviews)
    return 0


def _cmd_reviews_list(args: argparse.Namespace, store: MemoryStore) -> int:
    reviews = store.list_conflict_reviews(
        status=args.status,
        scope=args.scope,
        relation_type=args.relation_type,
        limit=args.limit,
        offset=args.offset,
    )
    if args.json:
        _print_json([_review_summary_payload(review) for review in reviews])
    else:
        _print_review_list(reviews)
    return 0


def _cmd_reviews_show(args: argparse.Namespace, store: MemoryStore) -> int:
    review = _require_review(store, args.review_id)
    if args.json:
        _print_json(_review_detail_payload(store, review))
    else:
        _print_review_detail(store, review)
    return 0


def _cmd_reviews_resolve(args: argparse.Namespace, store: MemoryStore) -> int:
    review = store.resolve_conflict_review(
        args.review_id,
        action=args.action,
        keep_memory_ids=args.keep_memory_ids,
        reason=args.reason,
    )
    if args.json:
        _print_json(_review_detail_payload(store, review))
    else:
        print(f"Resolved review: {review.id}")
        print(f"Status: {review.status}")
        print(f"Action: {review.resolution_action}")
    return 0


def _cmd_maintenance_generate(args: argparse.Namespace, store: MemoryStore) -> int:
    reviews = store.create_maintenance_reviews(
        scope=args.scope,
        memory_type=args.memory_type,
        recommended_action=args.recommended_action,
        limit=args.limit,
    )
    if args.json:
        _print_json([_maintenance_review_payload(store, review) for review in reviews])
    else:
        _print_maintenance_review_list(reviews)
    return 0


def _cmd_maintenance_list(args: argparse.Namespace, store: MemoryStore) -> int:
    reviews = store.list_maintenance_reviews(
        status=args.status,
        recommended_action=args.recommended_action,
        memory_id=args.memory_id,
        limit=args.limit,
        offset=args.offset,
    )
    if args.json:
        _print_json([_maintenance_review_payload(store, review) for review in reviews])
    else:
        _print_maintenance_review_list(reviews)
    return 0


def _cmd_maintenance_show(args: argparse.Namespace, store: MemoryStore) -> int:
    review = _require_maintenance_review(store, args.review_id)
    if args.json:
        _print_json(_maintenance_review_payload(store, review))
    else:
        _print_maintenance_review_detail(store, review)
    return 0


def _cmd_maintenance_resolve(args: argparse.Namespace, store: MemoryStore) -> int:
    review = store.resolve_maintenance_review(
        args.review_id,
        action=args.action,
        reason=args.reason,
    )
    if args.json:
        _print_json(_maintenance_review_payload(store, review))
    else:
        print(f"Resolved maintenance review: {review.id}")
        print(f"Status: {review.status}")
        print(f"Action: {review.resolution_action}")
    return 0


def _cmd_remote_status(args: argparse.Namespace, store: MemoryStore) -> int:
    del store
    llm_payload = RemoteAdapterConfig.llm_from_env().to_read_model().model_dump(mode="json")
    embedding_payload = (
        RemoteAdapterConfig.embedding_from_env().to_read_model().model_dump(mode="json")
    )
    payload = {**llm_payload, "llm": llm_payload, "embedding": embedding_payload}
    if args.json:
        _print_json(payload)
    else:
        print("LLM:")
        print(f"  Configured: {llm_payload['configured']}")
        print(f"  Base URL: {llm_payload['base_url'] or '-'}")
        print(f"  Compatibility: {llm_payload['compatibility']}")
        print(f"  Timeout seconds: {llm_payload['timeout_seconds']}")
        print(f"  API key configured: {llm_payload['api_key_configured']}")
        print(f"  LLM extract path: {llm_payload['llm_extract_path']}")
        print(f"  Health path: {llm_payload['health_path']}")
        print(f"  LLM model: {llm_payload['llm_model'] or '-'}")
        print("Embedding:")
        print(f"  Configured: {embedding_payload['configured']}")
        print(f"  Base URL: {embedding_payload['base_url'] or '-'}")
        print(f"  Compatibility: {embedding_payload['compatibility']}")
        print(f"  Embedding compatibility: {embedding_payload['embedding_compatibility']}")
        print(f"  Timeout seconds: {embedding_payload['timeout_seconds']}")
        print(f"  API key configured: {embedding_payload['api_key_configured']}")
        print(f"  Embedding path: {embedding_payload['embedding_path']}")
        print(f"  Embedding model: {embedding_payload['embedding_model'] or '-'}")
    return 0


def _cmd_remote_health(args: argparse.Namespace, store: MemoryStore) -> int:
    del store
    payload = RemoteLLMClient(RemoteAdapterConfig.llm_from_env()).health()
    if args.json:
        _print_json(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_remote_extract(args: argparse.Namespace, store: MemoryStore) -> int:
    del store
    event = EventLog(Path(args.db)).get_event(args.event_id)
    if event is None:
        raise MemoryNotFoundError(args.event_id)
    result = RemoteLLMClient(RemoteAdapterConfig.llm_from_env()).extract_candidates(
        event,
        instructions=args.instructions,
    )
    payload = result.model_dump(mode="json")
    if args.json:
        _print_json(payload)
    else:
        print(f"Provider: {result.provider}")
        print(f"Candidates: {len(result.candidates)}")
        for candidate in result.candidates:
            print(f"- [{candidate.memory_type}/{candidate.confidence}] {candidate.subject}")
            print(f"  {candidate.content}")
        for warning in result.warnings:
            print(f"warning: {warning}")
    return 0


def _cmd_remote_import(args: argparse.Namespace, store: MemoryStore) -> int:
    event = EventLog(Path(args.db)).get_event(args.event_id)
    if event is None:
        raise MemoryNotFoundError(args.event_id)
    extracted = RemoteLLMClient(RemoteAdapterConfig.llm_from_env()).extract_candidates(
        event,
        instructions=args.instructions,
    )
    candidates = [store.create_candidate(candidate) for candidate in extracted.candidates]
    result = RemoteCandidateImportResult(
        provider=extracted.provider,
        candidates=candidates,
        warnings=extracted.warnings,
        metadata={
            **extracted.metadata,
            "event_id": event.id,
            "source": "remote_llm",
            "auto_committed": False,
        },
    )
    if args.json:
        _print_json(result.model_dump(mode="json"))
    else:
        print(f"Provider: {result.provider}")
        print(f"Imported candidates: {len(result.candidates)}")
        for candidate in result.candidates:
            print(
                f"- {candidate.id} [{candidate.status}/{candidate.memory_type}/"
                f"{candidate.confidence}] {candidate.subject}"
            )
        for warning in result.warnings:
            print(f"warning: {warning}")
    return 0


def _cmd_remote_route(args: argparse.Namespace, store: MemoryStore) -> int:
    if not args.event_ids:
        raise ValueError("at least one --event-id is required")

    event_log = EventLog(Path(args.db))
    events = [_require_event(event_log, event_id) for event_id in args.event_ids]
    recent_events = [
        _require_event(event_log, event_id)
        for event_id in args.recent_event_ids
    ]
    routed = RemoteLLMClient(RemoteAdapterConfig.llm_from_env()).route_memories(
        events,
        recent_events=recent_events,
        instructions=args.instructions,
    )

    event_by_id = {event.id: event for event in [*events, *recent_events]}
    session_store = SessionMemoryStore()
    long_term: list[dict[str, Any]] = []
    session_memories: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    ask_user: list[dict[str, Any]] = []

    for item in routed.items:
        primary_event = _primary_route_event(item.source_event_ids, event_by_id, events)
        route_payload = item.model_dump(mode="json")
        if item.route == "long_term":
            candidate = route_item_to_memory_candidate(item, primary_event)
            if candidate is None:
                ask_user.append(
                    {
                        "route_item": route_payload,
                        "reason": "long_term route could not be converted into a candidate",
                    }
                )
                continue
            stored_candidate = store.create_candidate(candidate)
            decision = store.evaluate_candidate(stored_candidate.id)
            long_term.append(
                {
                    "route_item": route_payload,
                    "candidate": stored_candidate.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                }
            )
            continue

        if item.route == "session":
            session_item = session_item_from_route_item(
                primary_event,
                item,
                session_id=args.session_id,
            )
            if session_item is None:
                ask_user.append(
                    {
                        "route_item": route_payload,
                        "reason": "session route could not be converted into session memory",
                    }
                )
                continue
            stored_session = session_store.add_item(session_item)
            session_memories.append(stored_session.model_dump(mode="json"))
            continue

        if item.route == "ignore":
            ignored.append(route_payload)
        elif item.route == "reject":
            rejected.append(route_payload)
        elif item.route == "ask_user":
            ask_user.append(route_payload)

    payload = {
        "provider": routed.provider,
        "long_term": long_term,
        "session": session_memories,
        "ignored": ignored,
        "rejected": rejected,
        "ask_user": ask_user,
        "warnings": routed.warnings,
        "metadata": {
            **routed.metadata,
            "event_ids": [event.id for event in events],
            "recent_event_ids": [event.id for event in recent_events],
            "session_id": args.session_id,
            "auto_committed": False,
            "session_persisted": False,
        },
    }

    if args.json:
        _print_json(payload)
    else:
        print(f"Provider: {routed.provider}")
        print(f"Long-term candidates: {len(long_term)}")
        print(f"Session memories: {len(session_memories)}")
        print(f"Ignored: {len(ignored)}")
        print(f"Rejected: {len(rejected)}")
        print(f"Ask user: {len(ask_user)}")
        for item in long_term:
            candidate = item["candidate"]
            decision = item["decision"]
            print(
                f"- long_term {candidate['id']} "
                f"[{candidate['memory_type']}/{decision['decision']}] "
                f"{candidate['subject']}"
            )
        for item in session_memories:
            print(f"- session [{item['memory_type']}] {item['subject']}")
        for warning in routed.warnings:
            print(f"warning: {warning}")
    return 0


def _cmd_remote_evaluate(args: argparse.Namespace, store: MemoryStore) -> int:
    events = load_events_for_remote_evaluation(
        EventLog(Path(args.db)),
        event_ids=args.event_ids,
        source=args.source,
        scope=args.scope,
        task_id=args.task_id,
        limit=args.limit,
    )
    result = evaluate_remote_candidate_quality(
        events,
        store,
        RemoteLLMClient(RemoteAdapterConfig.llm_from_env()),
        instructions=args.instructions,
    )
    if args.json:
        _print_json(result.model_dump(mode="json"))
    else:
        summary = result.summary
        print(f"Provider: {result.provider}")
        print(f"Events: {summary.event_count}")
        print(f"Remote success: {summary.remote_success_count}")
        print(f"Remote errors: {summary.remote_error_count}")
        print(f"Local candidates: {summary.local_candidate_count}")
        print(f"Remote candidates: {summary.remote_candidate_count}")
        print(f"Divergent events: {summary.divergent_event_count}")
        print(f"Average remote latency ms: {summary.average_remote_latency_ms or '-'}")
        for warning in result.warnings:
            print(f"warning: {warning}")
    return 0


def _cmd_remote_embed(args: argparse.Namespace, store: MemoryStore) -> int:
    del store
    result = RemoteEmbeddingClient(RemoteAdapterConfig.embedding_from_env()).embed_texts(
        args.text,
        model=args.model,
    )
    payload = result.model_dump(mode="json")
    if args.json:
        _print_json(payload)
    else:
        print(f"Provider: {result.provider}")
        print(f"Model: {result.model or '-'}")
        print(f"Vectors: {len(result.vectors)}")
        print(f"Dimensions: {result.dimensions}")
    return 0


def _cmd_remote_embed_memory(args: argparse.Namespace, store: MemoryStore) -> int:
    memory = store.get_memory(args.memory_id)
    if memory is None:
        raise MemoryNotFoundError(args.memory_id)
    text = build_memory_embedding_text(memory)
    result = RemoteEmbeddingClient(RemoteAdapterConfig.embedding_from_env()).embed_texts(
        [text],
        model=args.model,
    )
    model = result.model or args.model
    if model is None:
        raise RemoteAdapterError("remote embedding did not return a model")
    embedding = store.upsert_memory_embedding(
        memory.id,
        vector=result.vectors[0],
        model=model,
        embedded_text=text,
    )
    payload = embedding.model_dump(mode="json")
    if args.json:
        _print_json(payload)
    else:
        print(f"Memory: {embedding.memory_id}")
        print(f"Model: {embedding.model}")
        print(f"Dimensions: {embedding.dimensions}")
    return 0


def _cmd_remote_embed_backfill(args: argparse.Namespace, store: MemoryStore) -> int:
    result = backfill_remote_memory_embeddings(
        store,
        RemoteEmbeddingClient(RemoteAdapterConfig.embedding_from_env()),
        model=args.model,
        scope=args.scope,
        memory_type=args.memory_type,
        limit=args.limit,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
    payload = result.model_dump(mode="json")
    if args.json:
        _print_json(payload)
    else:
        print(f"Provider: {result.provider}")
        print(f"Model: {result.model or '-'}")
        print(f"Requested: {result.requested_count}")
        print(f"Embedded: {result.embedded_count}")
        print(f"Skipped: {result.skipped_count}")
        print(f"Errors: {result.error_count}")
        print(f"Batches: {result.batch_count}")
        print(f"Dimensions: {result.dimensions or '-'}")
        if result.dry_run:
            print("Dry run: true")
        for error in result.errors:
            print(f"error: {error}")
    return 0


def _cmd_remote_hybrid_search(args: argparse.Namespace, store: MemoryStore) -> int:
    result = RemoteEmbeddingClient(RemoteAdapterConfig.embedding_from_env()).embed_texts(
        [args.query],
        model=args.model,
    )
    model = result.model or args.model
    memories = store.search_memory(
        SearchMemoryInput(
            query=args.query,
            scopes=args.scope,
            memory_types=args.memory_type,
            limit=args.limit,
            retrieval_mode="hybrid",
            query_embedding=result.vectors[0],
            embedding_model=model,
        ),
        metadata={"remote_embedding_model": model},
    )
    if args.json:
        _print_json([memory.model_dump(mode="json") for memory in memories])
    else:
        for memory in memories:
            print(f"- {memory.id} [{memory.memory_type}/{memory.scope}] {memory.subject}")
            print(f"  {memory.content}")
    return 0


def _cmd_remote_guarded_hybrid_search(args: argparse.Namespace, store: MemoryStore) -> int:
    result = remote_guarded_hybrid_search(
        store,
        RemoteEmbeddingClient(RemoteAdapterConfig.embedding_from_env()),
        query=args.query,
        scopes=args.scope,
        memory_types=args.memory_type,
        model=args.model,
        limit=args.limit,
        guard_top_k=args.guard_top_k,
        min_similarity=args.guard_min_similarity,
        ambiguity_margin=args.guard_ambiguity_margin,
    )
    payload = result.model_dump(mode="json")
    if args.json:
        _print_json(payload)
    else:
        for memory in result.memories:
            print(f"- {memory.id} [{memory.memory_type}/{memory.scope}] {memory.subject}")
            print(f"  {memory.content}")
        if not result.memories:
            print("No guarded results accepted.")
        for decision in result.decisions:
            print(
                f"decision: {decision.decision} rank={decision.rank} "
                f"similarity={decision.similarity} margin={decision.score_margin} "
                f"subject={decision.subject} reason={decision.reason}"
            )
        for warning in result.warnings:
            print(f"warning: {warning}")
    return 0


def _cmd_remote_llm_guarded_hybrid_search(args: argparse.Namespace, store: MemoryStore) -> int:
    embedding_config = RemoteAdapterConfig.embedding_from_env()
    llm_config = RemoteAdapterConfig.llm_from_env()
    result = remote_llm_guarded_hybrid_search(
        store,
        RemoteEmbeddingClient(embedding_config),
        RemoteLLMClient(llm_config),
        query=args.query,
        scopes=args.scope,
        memory_types=args.memory_type,
        model=args.model,
        limit=args.limit,
        guard_top_k=args.guard_top_k,
        min_similarity=args.guard_min_similarity,
        ambiguity_margin=args.guard_ambiguity_margin,
    )
    payload = result.model_dump(mode="json")
    if args.json:
        _print_json(payload)
    else:
        print(f"Judge: {result.judge.decision}")
        print(f"Reason: {result.judge.reason}")
        for memory in result.memories:
            print(f"- {memory.id} [{memory.memory_type}/{memory.scope}] {memory.subject}")
            print(f"  {memory.content}")
        if not result.memories:
            print("No LLM-guarded results accepted.")
        for decision in result.local_guard.decisions:
            print(
                f"local: {decision.decision} rank={decision.rank} "
                f"similarity={decision.similarity} margin={decision.score_margin} "
                f"subject={decision.subject} reason={decision.reason}"
            )
        for warning in result.warnings:
            print(f"warning: {warning}")
    return 0


def _cmd_remote_selective_llm_guarded_hybrid_search(
    args: argparse.Namespace,
    store: MemoryStore,
) -> int:
    embedding_config = RemoteAdapterConfig.embedding_from_env()
    llm_config = RemoteAdapterConfig.llm_from_env()
    result = remote_selective_llm_guarded_hybrid_search(
        store,
        RemoteEmbeddingClient(embedding_config),
        RemoteLLMClient(llm_config),
        query=args.query,
        scopes=args.scope,
        memory_types=args.memory_type,
        model=args.model,
        limit=args.limit,
        guard_top_k=args.guard_top_k,
        min_similarity=args.guard_min_similarity,
        ambiguity_margin=args.guard_ambiguity_margin,
        selective_min_similarity=args.selective_min_similarity,
        selective_ambiguity_margin=args.selective_ambiguity_margin,
    )
    payload = result.model_dump(mode="json")
    if args.json:
        _print_json(payload)
    else:
        print(f"Judge: {result.judge.decision}")
        print(f"Reason: {result.judge.reason}")
        print(f"Remote judge called: {result.metadata.get('remote_judge_called')}")
        if result.metadata.get("skip_reason"):
            print(f"Skip reason: {result.metadata['skip_reason']}")
        if result.metadata.get("call_reason"):
            print(f"Call reason: {result.metadata['call_reason']}")
        for memory in result.memories:
            print(f"- {memory.id} [{memory.memory_type}/{memory.scope}] {memory.subject}")
            print(f"  {memory.content}")
        if not result.memories:
            print("No selective LLM-guarded results accepted.")
        for decision in result.local_guard.decisions:
            print(
                f"local: {decision.decision} rank={decision.rank} "
                f"similarity={decision.similarity} margin={decision.score_margin} "
                f"subject={decision.subject} reason={decision.reason}"
            )
        for warning in result.warnings:
            print(f"warning: {warning}")
    return 0


def _cmd_remote_evaluate_retrieval(args: argparse.Namespace, store: MemoryStore) -> int:
    del store
    embedding_config = RemoteAdapterConfig.embedding_from_env()
    llm_config = RemoteAdapterConfig.llm_from_env()
    result = evaluate_remote_retrieval_fixture(
        args.fixture,
        RemoteEmbeddingClient(embedding_config),
        remote_llm=RemoteLLMClient(llm_config)
        if args.llm_judge or args.selective_llm_judge
        else None,
        include_llm_judge=args.llm_judge,
        include_selective_llm_judge=args.selective_llm_judge,
        model=args.model,
        limit=args.limit,
        sample_size=args.sample_size,
        sample_seed=args.sample_seed,
        batch_size=args.batch_size,
        case_concurrency=args.case_concurrency,
        judge_concurrency=args.judge_concurrency,
        judge_group_size=args.judge_group_size,
        guard_top_k=args.guard_top_k,
        guard_min_similarity=args.guard_min_similarity,
        guard_ambiguity_margin=args.guard_ambiguity_margin,
        selective_min_similarity=args.selective_min_similarity,
        selective_ambiguity_margin=args.selective_ambiguity_margin,
        embedding_cache_path=args.embedding_cache,
    )
    payload = result.model_dump(mode="json")
    if args.report_path:
        report_path = Path(args.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        _print_json(payload)
    else:
        summary = result.summary
        print(f"Provider: {result.provider}")
        print(f"Model: {result.model or '-'}")
        print(f"Cases: {summary.case_count}")
        print(f"Embedded memories: {summary.embedded_memory_count}")
        print(f"Embedded queries: {summary.embedded_query_count}")
        for mode in summary.modes:
            print(
                f"{mode}: passed={summary.passed_by_mode.get(mode, 0)} "
                f"failed={summary.failed_by_mode.get(mode, 0)} "
                f"FN={summary.false_negative_by_mode.get(mode, 0)} "
                f"unexpected={summary.unexpected_by_mode.get(mode, 0)} "
                f"ambiguous={summary.ambiguous_by_mode.get(mode, 0)} "
                f"top1={summary.top1_hit_by_mode.get(mode, 0)}"
            )
            if mode in summary.judge_called_by_mode or mode in summary.judge_skipped_by_mode:
                print(
                    f"  judge: called={summary.judge_called_by_mode.get(mode, 0)} "
                    f"skipped={summary.judge_skipped_by_mode.get(mode, 0)} "
                    f"skip_reasons={summary.judge_skip_reason_by_mode.get(mode, {})}"
                )
        if result.category_summary:
            print("Categories:")
            for category, category_summary in result.category_summary.items():
                parts = [
                    f"{mode}=p{category_summary.passed_by_mode.get(mode, 0)}"
                    f"/fn{category_summary.false_negative_by_mode.get(mode, 0)}"
                    f"/u{category_summary.unexpected_by_mode.get(mode, 0)}"
                    f"/a{category_summary.ambiguous_by_mode.get(mode, 0)}"
                    for mode in category_summary.passed_by_mode
                ]
                print(f"{category}: cases={category_summary.case_count} " + " ".join(parts))
        cache_meta = result.metadata.get("embedding_cache", {})
        if isinstance(cache_meta, dict) and cache_meta.get("enabled"):
            print(
                "Embedding cache: "
                f"hits={cache_meta.get('hits', 0)} "
                f"misses={cache_meta.get('misses', 0)} "
                f"writes={cache_meta.get('writes', 0)} "
                f"path={cache_meta.get('path', '-')}"
            )
        if args.report_path:
            print(f"Report: {args.report_path}")
        print(f"Case concurrency: {result.metadata.get('case_concurrency', 1)}")
        judge_meta = result.metadata.get("judge", {})
        if isinstance(judge_meta, dict):
            print(
                "Judge: "
                f"mode={judge_meta.get('mode', 'single')} "
                f"group_size={judge_meta.get('group_size', 1)} "
                f"concurrency={judge_meta.get('concurrency', 1)} "
                f"pending={judge_meta.get('pending_tasks', 0)} "
                f"single_calls={judge_meta.get('single_calls', 0)} "
                f"batch_count={judge_meta.get('batch_count', 0)} "
                f"batch_calls={judge_meta.get('batch_calls', 0)} "
                f"fallback_single={judge_meta.get('fallback_single_calls', 0)}"
            )
        for warning in result.warnings:
            print(f"warning: {warning}")
    return 0


def _require_review(store: MemoryStore, review_id: str) -> ConflictReviewItemRead:
    review = store.get_conflict_review(review_id)
    if review is None:
        raise MemoryNotFoundError(review_id)
    return review


def _require_event(event_log: EventLog, event_id: str) -> EventRead:
    event = event_log.get_event(event_id)
    if event is None:
        raise MemoryNotFoundError(event_id)
    return event


def _primary_route_event(
    source_event_ids: list[str],
    event_by_id: dict[str, EventRead],
    events: list[EventRead],
) -> EventRead:
    for event_id in source_event_ids:
        event = event_by_id.get(event_id)
        if event is not None:
            return event
    return events[0]


def _require_maintenance_review(
    store: MemoryStore,
    review_id: str,
) -> MaintenanceReviewItemRead:
    review = store.get_maintenance_review(review_id)
    if review is None:
        raise MemoryNotFoundError(review_id)
    return review


def _review_summary_payload(review: ConflictReviewItemRead) -> dict[str, Any]:
    return review.model_dump(mode="json")


def _review_detail_payload(store: MemoryStore, review: ConflictReviewItemRead) -> dict[str, Any]:
    payload = _review_summary_payload(review)
    from_entity = store.get_entity(review.from_entity_id)
    payload["from_entity"] = from_entity.model_dump(mode="json") if from_entity else None
    payload["target_entities"] = [
        entity.model_dump(mode="json")
        for entity_id in review.target_entity_ids
        if (entity := store.get_entity(entity_id)) is not None
    ]
    payload["relations"] = [
        relation.model_dump(mode="json")
        for relation_id in review.relation_ids
        if (relation := store.get_relation(relation_id)) is not None
    ]
    payload["memories"] = [
        memory.model_dump(mode="json")
        for memory_id in review.memory_ids
        if (memory := store.get_memory(memory_id)) is not None
    ]
    return payload


def _maintenance_review_payload(
    store: MemoryStore,
    review: MaintenanceReviewItemRead,
) -> dict[str, Any]:
    payload = review.model_dump(mode="json")
    memory = store.get_memory(review.memory_id)
    payload["memory"] = memory.model_dump(mode="json") if memory else None
    if memory is not None:
        payload["usage"] = store.get_memory_usage_stats(memory.id).model_dump(mode="json")
    return payload


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_review_list(reviews: list[ConflictReviewItemRead]) -> None:
    if not reviews:
        print("No conflict reviews found.")
        return
    print("id\tstatus\trecommended_action\tscope\trelation_type")
    for review in reviews:
        print(
            f"{review.id}\t{review.status}\t{review.recommended_action}\t"
            f"{review.scope}\t{review.relation_type}"
        )


def _print_maintenance_review_list(reviews: list[MaintenanceReviewItemRead]) -> None:
    if not reviews:
        print("No maintenance reviews found.")
        return
    print("id\tstatus\trecommended_action\tmemory_id\tusage_score")
    for review in reviews:
        print(
            f"{review.id}\t{review.status}\t{review.recommended_action}\t"
            f"{review.memory_id}\t{review.usage_score:.2f}"
        )


def _print_review_detail(store: MemoryStore, review: ConflictReviewItemRead) -> None:
    print(f"Review: {review.id}")
    print(f"Status: {review.status}")
    print(f"Scope: {review.scope}")
    print(f"Relation: {review.relation_type}")
    print(f"Conflict key: {review.conflict_key}")
    print(f"Recommended action: {review.recommended_action}")
    print(f"Recommended keep memories: {', '.join(review.recommended_keep_memory_ids) or '-'}")
    if review.resolution_action:
        print(f"Resolution action: {review.resolution_action}")
    if review.resolution_reason:
        print(f"Resolution reason: {review.resolution_reason}")
    print(f"Reason: {review.reason}")
    if review.required_action:
        print(f"Required action: {review.required_action}")

    print()
    print("From entity:")
    print(f"  {_format_entity(store, review.from_entity_id)}")

    print("Target entities:")
    for entity_id in review.target_entity_ids:
        print(f"  - {_format_entity(store, entity_id)}")

    print("Relations:")
    for relation_id in review.relation_ids:
        relation = store.get_relation(relation_id)
        if relation is None:
            print(f"  - {relation_id} [missing]")
            continue
        print(
            f"  - {relation.id} {relation.from_id} --{relation.relation_type}--> "
            f"{relation.to_id} [{relation.confidence}]"
        )

    print("Memories:")
    recommended = set(review.recommended_keep_memory_ids)
    for memory_id in review.memory_ids:
        memory = store.get_memory(memory_id)
        marker = " *recommended*" if memory_id in recommended else ""
        if memory is None:
            print(f"  - {memory_id} [missing]{marker}")
            continue
        print(
            f"  - {memory.id} [{memory.status}/{memory.confidence}/{memory.memory_type}]"
            f"{marker}"
        )
        print(f"    subject: {memory.subject}")
        print(f"    scope: {memory.scope}")
        print(f"    content: {_one_line(memory.content)}")


def _print_maintenance_review_detail(
    store: MemoryStore,
    review: MaintenanceReviewItemRead,
) -> None:
    print(f"Maintenance review: {review.id}")
    print(f"Status: {review.status}")
    print(f"Recommended action: {review.recommended_action}")
    print(f"Usage score: {review.usage_score:.2f}")
    if review.resolution_action:
        print(f"Resolution action: {review.resolution_action}")
    if review.resolution_reason:
        print(f"Resolution reason: {review.resolution_reason}")
    if review.required_action:
        print(f"Required action: {review.required_action}")

    print("Reasons:")
    for reason in review.reasons:
        print(f"  - {reason}")

    memory = store.get_memory(review.memory_id)
    print("Memory:")
    if memory is None:
        print(f"  {review.memory_id} [missing]")
        return
    print(f"  {memory.id} [{memory.status}/{memory.confidence}/{memory.memory_type}]")
    print(f"  subject: {memory.subject}")
    print(f"  scope: {memory.scope}")
    print(f"  content: {_one_line(memory.content)}")

    usage = store.get_memory_usage_stats(memory.id)
    print("Usage:")
    print(f"  retrieved: {usage.retrieved_count}")
    print(f"  used: {usage.used_count}")
    print(f"  skipped: {usage.skipped_count}")
    print(f"  useful feedback: {usage.useful_feedback_count}")
    print(f"  not useful feedback: {usage.not_useful_feedback_count}")


def _format_entity(store: MemoryStore, entity_id: str) -> str:
    entity = store.get_entity(entity_id)
    if entity is None:
        return f"{entity_id} [missing]"
    return f"{entity.id} [{entity.entity_type}] {entity.name} ({entity.scope})"


def _one_line(value: str) -> str:
    return " ".join(value.split())


if __name__ == "__main__":
    raise SystemExit(main())
