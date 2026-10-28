from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .apply import apply_plan
from .apply_plan_helper import draft_apply_plan
from .config import load_config
from .evaluate import evaluate_search
from .health import run_health
from .ingest import ingest
from .lint import lint_vault
from .query import run_query
from .scan import scan_vault
from .synthesize import run_synthesize
from .validate import validate_system
from .workflow import process_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-vault-wiki")
    parser.add_argument("--config", default="llm-vault-wiki.yaml", help="Path to project config")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("scan", help="Build vault manifests and generated index")

    query_parser = subparsers.add_parser("query", help="Create a cited context pack for a question")
    query_parser.add_argument("question")
    query_parser.add_argument("--limit", type=int, default=10)
    query_parser.add_argument("--no-prompt", action="store_true")

    synthesize_parser = subparsers.add_parser("synthesize", help="Create a read-only cited synthesis package for a question")
    synthesize_parser.add_argument("question")
    synthesize_parser.add_argument("--limit", type=int, default=10)

    eval_parser = subparsers.add_parser("evaluate-search", help="Measure query precision and recall against relevance regexes")
    eval_parser.add_argument("query", nargs="?")
    eval_parser.add_argument("--profile", help="Named search evaluation profile from config")
    eval_parser.add_argument(
        "--relevant-pattern",
        action="append",
        help="Regex that marks a file relevant. Use label=regex for named patterns. Repeatable.",
    )
    eval_parser.add_argument("--limit", type=int)
    eval_parser.add_argument("--at", type=int, action="append", help="Precision/recall cutoff. Repeatable.")
    eval_parser.add_argument("--fail-on-misses", action="store_true", help="Return non-zero when any relevant file is missed.")

    validate_parser = subparsers.add_parser("validate-system", help="Run read-only system validation across scan, lint, and saved profiles")
    validate_parser.add_argument("--profile", action="append", help="Named search evaluation profile to run. Repeatable. Defaults to all profiles.")
    validate_parser.add_argument("--fail-on-warnings", action="store_true", help="Treat lint warnings as validation failures.")
    validate_parser.add_argument(
        "--duration-warning-factor",
        type=float,
        default=1.5,
        help="Warn when a stage is this many times slower than the previous validation run.",
    )

    subparsers.add_parser("brain-health", help="Create a read-only operator health report from latest manifests and validation")

    ingest_parser = subparsers.add_parser("ingest", help="Triage inbox files into proposed notes, links, and destinations")
    ingest_parser.add_argument("--source", help="Specific inbox/source file to triage")
    ingest_parser.add_argument("--limit", type=int, default=10)

    draft_parser = subparsers.add_parser("draft-apply-plan", help="Generate an apply-plan skeleton from a file-back brief")
    draft_parser.add_argument("--brief", required=True, help="Path to file-back.brief.json")
    draft_parser.add_argument("--source-index", type=int, default=0, help="Source package index inside the file-back brief")
    draft_parser.add_argument(
        "--archive-source",
        action="store_true",
        help="Append a reviewed archive operation for the processed source after the create-file operation",
    )

    process_parser = subparsers.add_parser("process-source", help="Run the guided one-source workflow")
    process_parser.add_argument("--source", required=True, help="Vault-relative source file to process")
    process_parser.add_argument("--plan", help="Optional apply plan to dry-run or execute after ingest")
    process_parser.add_argument("--limit", type=int, default=10)
    process_parser.add_argument("--execute", action="store_true", help="Execute the reviewed apply plan after dry-run")
    process_parser.add_argument("--reviewed", action="store_true", help="Acknowledge human review before execution")
    process_parser.add_argument("--fail-on-warnings", action="store_true", help="Treat lint warnings as verification failure")
    process_parser.add_argument(
        "--draft-apply-plan",
        action="store_true",
        help="Generate apply-plan skeleton and writer prompt from the file-back brief after ingest",
    )
    process_parser.add_argument(
        "--archive-source",
        action="store_true",
        help="When used with --draft-apply-plan, include a reviewed archive operation for the processed source",
    )

    lint_parser = subparsers.add_parser("lint", help="Check manifests, policies, and wiki link health")
    lint_parser.add_argument("--fail-on-warnings", action="store_true")

    apply_parser = subparsers.add_parser("apply", help="Validate or execute a guarded apply plan")
    apply_parser.add_argument("plan", help="JSON plan path")
    apply_parser.add_argument("--execute", action="store_true", help="Mutate the vault after policy validation")
    apply_parser.add_argument("--reviewed", action="store_true", help="Acknowledge human review")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(Path(args.config))
        if args.command == "scan":
            scan_result = scan_vault(config)
            result = {
                "file_count": scan_result["inventory"]["file_count"],
                "warnings": len(scan_result["inventory"].get("warnings", [])),
                "changes": scan_result["changes"],
                "index_path": scan_result["index_path"],
            }
        elif args.command == "query":
            result = {"run_dir": str(run_query(config, args.question, limit=args.limit, prompt=not args.no_prompt))}
        elif args.command == "synthesize":
            result = run_synthesize(config, args.question, limit=args.limit)
        elif args.command == "evaluate-search":
            if args.profile:
                mixed_fields = []
                if args.query:
                    mixed_fields.append("query")
                if args.relevant_pattern:
                    mixed_fields.append("--relevant-pattern")
                if args.limit is not None:
                    mixed_fields.append("--limit")
                if args.at:
                    mixed_fields.append("--at")
                if args.fail_on_misses:
                    mixed_fields.append("--fail-on-misses")
                if mixed_fields:
                    raise ValueError(
                        "--profile cannot be combined with ad hoc evaluation inputs: "
                        + ", ".join(mixed_fields)
                    )
                profile = config.search_evaluations.get(args.profile)
                if profile is None:
                    available = ", ".join(sorted(config.search_evaluations)) or "none configured"
                    raise ValueError(f"Unknown search evaluation profile: {args.profile}. Available profiles: {available}")
                result = evaluate_search(
                    config,
                    query=profile.query,
                    relevance_patterns=list(profile.relevance_patterns),
                    limit=profile.limit,
                    precision_points=list(profile.precision_points),
                    fail_on_misses=profile.fail_on_misses,
                    profile_name=args.profile,
                    min_precision_at=profile.min_precision_at,
                )
            else:
                if not args.query:
                    raise ValueError("evaluate-search requires a query unless --profile is provided.")
                if not args.relevant_pattern:
                    raise ValueError("At least one --relevant-pattern is required unless --profile is provided.")
                result = evaluate_search(
                    config,
                    query=args.query,
                    relevance_patterns=args.relevant_pattern,
                    limit=args.limit if args.limit is not None else 10000,
                    precision_points=args.at,
                    fail_on_misses=args.fail_on_misses,
                )
        elif args.command == "validate-system":
            result = validate_system(
                config,
                profiles=args.profile,
                fail_on_warnings=args.fail_on_warnings,
                duration_warning_factor=args.duration_warning_factor,
            )
        elif args.command == "brain-health":
            result = run_health(config)
        elif args.command == "ingest":
            result = {"run_dir": str(ingest(config, source=args.source, limit=args.limit))}
        elif args.command == "draft-apply-plan":
            result = draft_apply_plan(
                config,
                args.brief,
                source_index=args.source_index,
                archive_source=args.archive_source,
            )
        elif args.command == "process-source":
            result = process_source(
                config,
                source=args.source,
                plan=args.plan,
                limit=args.limit,
                execute=args.execute,
                reviewed=args.reviewed,
                fail_on_warnings=args.fail_on_warnings,
                draft_apply_plan=args.draft_apply_plan,
                archive_source=args.archive_source,
            )
        elif args.command == "lint":
            lint_result = lint_vault(config, fail_on_warnings=args.fail_on_warnings)
            result = {
                "ok": lint_result["ok"],
                "errors": len(lint_result["errors"]),
                "warnings": len(lint_result["warnings"]),
                "json_report": str(config.state_dir / "generated" / "lint.report.json"),
                "markdown_report": str(config.state_dir / "generated" / "lint.report.md"),
            }
        elif args.command == "apply":
            result = apply_plan(config, args.plan, execute=args.execute, reviewed=args.reviewed)
        else:
            parser.error(f"Unknown command: {args.command}")
            return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    if isinstance(result, dict) and result.get("ok") is False:
        return 1
    return 0
