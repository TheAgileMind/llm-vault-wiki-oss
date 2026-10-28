from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .apply import apply_plan
from .apply_plan_helper import draft_apply_plan as draft_apply_plan_from_brief
from .config import Config
from .evaluate import evaluate_search
from .ingest import ingest
from .lint import lint_vault
from .paths import resolve_vault_path, vault_relative
from .query import load_inventory, rank_notes
from .scan import scan_vault
from .storage import create_run_dir, read_json, write_json


def process_source(
    config: Config,
    *,
    source: str,
    plan: str | None = None,
    limit: int = 10,
    execute: bool = False,
    reviewed: bool = False,
    fail_on_warnings: bool = False,
    draft_apply_plan: bool = False,
    archive_source: bool = False,
) -> dict[str, Any]:
    run_dir = create_run_dir(config.state_dir, "process-source")
    stages: list[dict[str, Any]] = []
    proposed_operations: list[dict[str, Any]] = []
    verification: dict[str, Any] = {}
    quality_validation: dict[str, Any] = {}
    draft_apply_plan_data: dict[str, Any] | None = None
    source_rel = source

    try:
        source_rel = _validate_source(config, source)
        if execute and not plan:
            raise ValueError("Execution requires an apply plan.")
        if archive_source and not draft_apply_plan:
            raise ValueError("--archive-source requires --draft-apply-plan.")
        if draft_apply_plan and plan:
            raise ValueError("--draft-apply-plan cannot be combined with --plan.")

        scan_data = _run_stage(stages, "scan", lambda: _scan_stage(config))
        ingest_data = _run_stage(stages, "ingest", lambda: _ingest_stage(config, source_rel, limit))
        status = "review_ready"

        if draft_apply_plan:
            draft_apply_plan_data = _run_stage(
                stages,
                "draft_apply_plan",
                lambda: _draft_apply_plan_stage(config, ingest_data["file_back_brief"]["json"], archive_source=archive_source),
            )

        if plan:
            dry_run = _run_stage(stages, "apply_dry_run", lambda: _apply_stage(config, plan, execute=False, reviewed=reviewed))
            proposed_operations = _operation_summaries(dry_run)
            status = "awaiting_final_approval"

            if execute:
                execution = _run_stage(stages, "apply_execute", lambda: _apply_stage(config, plan, execute=True, reviewed=reviewed))
                proposed_operations = _operation_summaries(execution)
                verify_scan = _run_stage(stages, "verify_scan", lambda: _scan_stage(config))
                verify_lint = _run_stage(stages, "verify_lint", lambda: _lint_stage(config, fail_on_warnings))
                verification = {
                    "scan_file_count": verify_scan["file_count"],
                    "lint_ok": verify_lint["ok"],
                    "lint_errors": verify_lint["errors"],
                    "lint_warnings": verify_lint["warnings"],
                }
                quality_validation = _quality_validation(config, proposed_operations, verification, executed=True)
                status = "applied" if quality_validation["ok"] else "applied_with_verification_failure"

        if not quality_validation:
            quality_validation = _quality_validation(config, proposed_operations, verification, executed=False)

        summary = {
            "ok": status != "applied_with_verification_failure" and quality_validation.get("ok", True),
            "status": status,
            "source": source_rel,
            "run_dir": str(run_dir),
            "scan_file_count": scan_data["file_count"],
            "ingest_run_dir": ingest_data["run_dir"],
            "file_back_brief": ingest_data.get("file_back_brief"),
            "file_back": ingest_data.get("file_back"),
            "draft_apply_plan": draft_apply_plan_data,
            "plan": str(Path(plan).resolve()) if plan else None,
            "execute_requested": execute,
            "reviewed": reviewed,
            "proposed_operations": proposed_operations,
            "verification": verification,
            "quality_validation": quality_validation,
            "stages": stages,
        }
    except Exception as exc:
        summary = {
            "ok": False,
            "status": "failed",
            "source": source_rel,
            "run_dir": str(run_dir),
            "plan": str(Path(plan).resolve()) if plan else None,
            "execute_requested": execute,
            "reviewed": reviewed,
            "proposed_operations": proposed_operations,
            "verification": verification,
            "quality_validation": quality_validation,
            "stages": stages,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }

    write_json(run_dir / "process-source.summary.json", summary)
    _write_markdown_summary(run_dir / "process-source.summary.md", summary)
    return summary


def _validate_source(config: Config, source: str) -> str:
    path = resolve_vault_path(source, config.vault_root)
    rel = vault_relative(path, config.vault_root)
    if not path.exists():
        raise FileNotFoundError(f"Source does not exist: {rel}")
    if not config.is_included(rel):
        raise PermissionError(f"Source is excluded or not included by policy: {rel}")
    return rel


def _run_stage(stages: list[dict[str, Any]], name: str, action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        data = action()
    except Exception as exc:
        stages.append({"name": name, "status": "failed", "error": {"type": type(exc).__name__, "message": str(exc)}})
        raise
    stages.append({"name": name, "status": "ok", **data})
    return data


def _scan_stage(config: Config) -> dict[str, Any]:
    result = scan_vault(config)
    return {
        "file_count": result["inventory"]["file_count"],
        "warnings": len(result["inventory"].get("warnings", [])),
        "changes": result["changes"],
        "index_path": result["index_path"],
    }


def _ingest_stage(config: Config, source: str, limit: int) -> dict[str, Any]:
    run_dir = Path(ingest(config, source=source, limit=limit))
    plan = read_json(run_dir / "ingest.plan.json")
    source_plan = plan["sources"][0] if plan.get("sources") else {}
    file_back = source_plan.get("file_back", {})
    return {
        "run_dir": str(run_dir),
        "report": str(run_dir / "ingest.report.md"),
        "plan": str(run_dir / "ingest.plan.json"),
        "file_back_brief": {
            "json": str(run_dir / "file-back.brief.json"),
            "markdown": str(run_dir / "file-back.brief.md"),
        },
        "file_back": {
            "primary_destination": file_back.get("primary_destination"),
            "compounding_action": file_back.get("compounding_action"),
            "ready_for_agent_draft": file_back.get("ready_for_agent_draft"),
            "quality_checks": file_back.get("quality_checks", {}),
        },
        "drafts": len(list((run_dir / "drafts").glob("*.md"))),
        "suggested_wikilinks": len(source_plan.get("suggested_wikilinks", [])),
        "proposed_destinations": source_plan.get("proposed_destinations", []),
    }


def _apply_stage(config: Config, plan: str, *, execute: bool, reviewed: bool) -> dict[str, Any]:
    result = apply_plan(config, plan, execute=execute, reviewed=reviewed)
    return {
        "run_dir": result["run_dir"],
        "execute": result["execute"],
        "reviewed": result["reviewed"],
        "results": result["results"],
    }


def _draft_apply_plan_stage(config: Config, brief_path: str, *, archive_source: bool) -> dict[str, Any]:
    result = draft_apply_plan_from_brief(config, brief_path, archive_source=archive_source)
    return {
        "run_dir": result["run_dir"],
        "apply_plan_skeleton": result["apply_plan_skeleton"],
        "writer_prompt": result["writer_prompt"],
        "target_path": result["target_path"],
        "target_exists": result["target_exists"],
        "archive_source": result["archive_source"],
        "archive_path": result["archive_path"],
    }


def _lint_stage(config: Config, fail_on_warnings: bool) -> dict[str, Any]:
    result = lint_vault(config, fail_on_warnings=fail_on_warnings)
    return {"ok": result["ok"], "errors": len(result["errors"]), "warnings": len(result["warnings"])}


def _operation_summaries(apply_result: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for result in apply_result.get("results", []):
        operation = result.get("operation", {})
        summaries.append({
            "op": operation.get("op"),
            "path": operation.get("path"),
            "from": operation.get("from"),
            "to": operation.get("to"),
            "status": result.get("status"),
            "risk": result.get("risk"),
            "policy_role": result.get("policy_role"),
        })
    return summaries


def _operation_paths(proposed_operations: list[dict[str, Any]], op: str, field: str) -> list[str]:
    return [
        str(operation[field])
        for operation in proposed_operations
        if operation.get("op") == op and operation.get(field)
    ]


def _stale_manifest_count(config: Config) -> int:
    inventory = load_inventory(config)
    count = 0
    for item in inventory.get("files", []):
        path = item.get("path")
        if path and not (config.vault_root / str(path)).exists():
            count += 1
    return count


def _retrieval_status(config: Config, target_path: str | None) -> dict[str, Any]:
    if not target_path:
        return {"status": "not_applicable", "ok": True}

    title_query = Path(target_path).stem.replace("_", " ")
    ranked = rank_notes(config, title_query, limit=10)
    rank = None
    for index, item in enumerate(ranked, start=1):
        if item.get("path") == target_path:
            rank = index
            break
    top_result = ranked[0]["path"] if ranked else None
    return {
        "status": "checked",
        "ok": rank is not None and rank <= 3,
        "query": title_query,
        "target_path": target_path,
        "rank": rank,
        "top_result": top_result,
        "gate": "target_ranks_top_3",
    }


def _saved_profile_status(config: Config) -> dict[str, Any]:
    if not config.search_evaluations:
        return {"status": "not_configured", "ok": True, "profiles": []}

    profiles = []
    ok = True
    for name, profile in config.search_evaluations.items():
        try:
            result = evaluate_search(
                config,
                query=profile.query,
                relevance_patterns=list(profile.relevance_patterns),
                limit=profile.limit,
                precision_points=list(profile.precision_points),
                fail_on_misses=profile.fail_on_misses,
                profile_name=name,
                min_precision_at=profile.min_precision_at,
            )
            profile_ok = bool(result["ok"])
            ok = ok and profile_ok
            profiles.append({
                "profile": name,
                "ok": profile_ok,
                "run_dir": result["run_dir"],
                "stale_manifest_files": result["stale_manifest_files"],
                "quality_gate_violations": result["quality_gate_violations"],
            })
        except Exception as exc:
            ok = False
            profiles.append({
                "profile": name,
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            })
    return {"status": "checked", "ok": ok, "profiles": profiles}


def _quality_validation(
    config: Config,
    proposed_operations: list[dict[str, Any]],
    verification: dict[str, Any],
    *,
    executed: bool,
) -> dict[str, Any]:
    created_files = _operation_paths(proposed_operations, "create_file", "path")
    archived_files = _operation_paths(proposed_operations, "archive_file", "to")
    validation: dict[str, Any] = {
        "ok": True,
        "status": "checked" if executed else "pending_execution",
        "created_files": created_files,
        "archived_files": archived_files,
        "scan": {"status": "pending_execution"},
        "lint": {"status": "pending_execution"},
        "retrieval": {"status": "pending_execution"},
        "saved_profiles": {"status": "pending_execution", "profiles": []},
        "stale_manifest": {"status": "pending_execution"},
        "quality_gate_violations": [],
    }
    if not executed:
        return validation

    validation["scan"] = {
        "status": "checked",
        "file_count": verification.get("scan_file_count"),
    }
    lint_ok = bool(verification.get("lint_ok"))
    validation["lint"] = {
        "status": "checked",
        "ok": lint_ok,
        "errors": verification.get("lint_errors", 0),
        "warnings": verification.get("lint_warnings", 0),
    }
    stale_count = _stale_manifest_count(config)
    validation["stale_manifest"] = {
        "status": "checked",
        "count": stale_count,
        "ok": stale_count == 0,
    }
    target_path = created_files[0] if created_files else None
    validation["retrieval"] = _retrieval_status(config, target_path)
    validation["saved_profiles"] = _saved_profile_status(config)

    violations = []
    if not lint_ok:
        violations.append({
            "gate": "lint",
            "artifact": "vault",
            "next_action": "Open the lint report and fix errors before treating the source workflow as complete.",
        })
    if stale_count:
        violations.append({
            "gate": "stale_manifest",
            "artifact": "scan inventory",
            "count": stale_count,
            "next_action": "Rerun scan and inspect missing files before evaluating retrieval quality.",
        })
    if not validation["retrieval"].get("ok", True):
        violations.append({
            "gate": "retrieval_rank",
            "artifact": target_path,
            "rank": validation["retrieval"].get("rank"),
            "next_action": "Improve title, metadata, or canonical note content so the target ranks top 3 for its title query.",
        })
    if not validation["saved_profiles"].get("ok", True):
        violations.append({
            "gate": "saved_evaluation_profiles",
            "artifact": "search_evaluations",
            "next_action": "Review failed profile reports and repair search quality regressions.",
        })

    validation["quality_gate_violations"] = violations
    validation["ok"] = not violations
    return validation


def _write_markdown_summary(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Process Source Summary",
        "",
        f"Status: {summary['status']}",
        f"OK: {summary['ok']}",
        f"Source: `{summary['source']}`",
        f"Plan: `{summary['plan']}`",
        f"Execute requested: {summary['execute_requested']}",
        f"Reviewed: {summary['reviewed']}",
        "",
        "## Stages",
        "",
    ]
    for stage in summary["stages"]:
        if stage["status"] == "ok":
            lines.append(f"- {stage['name']}: ok")
        else:
            error = stage.get("error", {})
            lines.append(f"- {stage['name']}: failed ({error.get('type')}: {error.get('message')})")

    if summary.get("file_back"):
        file_back = summary["file_back"]
        primary = file_back.get("primary_destination") or {}
        brief = summary.get("file_back_brief") or {}
        lines.extend([
            "",
            "## File-Back Package",
            "",
            f"- Brief: `{brief.get('markdown')}`",
            f"- Machine brief: `{brief.get('json')}`",
            f"- Ready for agent draft: {file_back.get('ready_for_agent_draft')}",
            f"- Compounding action: {file_back.get('compounding_action')}",
            f"- Primary destination: `{primary.get('folder')}`",
            f"- Suggested path: `{primary.get('suggested_path')}`",
            f"- Note type: {primary.get('note_type')}",
            "",
            "### Quality Checks",
        ])
        lines.extend(f"- {name}: {value}" for name, value in file_back.get("quality_checks", {}).items())

    if summary.get("draft_apply_plan"):
        draft = summary["draft_apply_plan"]
        lines.extend([
            "",
            "## Draft Apply Plan",
            "",
            f"- Skeleton: `{draft.get('apply_plan_skeleton')}`",
            f"- Writer prompt: `{draft.get('writer_prompt')}`",
            f"- Target path: `{draft.get('target_path')}`",
            f"- Target exists: {draft.get('target_exists')}",
            f"- Archive source: {draft.get('archive_source')}",
            f"- Archive path: `{draft.get('archive_path')}`",
        ])

    if summary.get("proposed_operations"):
        lines.extend(["", "## Proposed Operations", ""])
        for operation in summary["proposed_operations"]:
            path_value = operation.get("path") or operation.get("to")
            source_value = f" from `{operation['from']}`" if operation.get("from") else ""
            lines.append(
                f"- {operation['status']}: {operation['op']}{source_value} -> `{path_value}` "
                f"({operation['risk']}, {operation['policy_role']})"
            )

    if summary.get("verification"):
        verification = summary["verification"]
        lines.extend([
            "",
            "## Verification",
            "",
            f"- Scan file count: {verification.get('scan_file_count')}",
            f"- Lint ok: {verification.get('lint_ok')}",
            f"- Lint errors: {verification.get('lint_errors')}",
            f"- Lint warnings: {verification.get('lint_warnings')}",
        ])

    if summary.get("quality_validation"):
        quality = summary["quality_validation"]
        lines.extend([
            "",
            "## Quality Validation",
            "",
            f"- Status: {quality.get('status')}",
            f"- OK: {quality.get('ok')}",
            f"- Created files: {', '.join(f'`{path}`' for path in quality.get('created_files', [])) or 'none'}",
            f"- Archived files: {', '.join(f'`{path}`' for path in quality.get('archived_files', [])) or 'none'}",
        ])
        scan = quality.get("scan", {})
        lint = quality.get("lint", {})
        retrieval = quality.get("retrieval", {})
        stale = quality.get("stale_manifest", {})
        profiles = quality.get("saved_profiles", {})
        lines.extend([
            f"- Scan: {scan.get('status')} file_count={scan.get('file_count')}",
            f"- Lint: {lint.get('status')} ok={lint.get('ok')} errors={lint.get('errors')} warnings={lint.get('warnings')}",
            f"- Retrieval: {retrieval.get('status')} target=`{retrieval.get('target_path')}` rank={retrieval.get('rank')} top=`{retrieval.get('top_result')}`",
            f"- Stale manifest: {stale.get('status')} count={stale.get('count')}",
            f"- Saved profiles: {profiles.get('status')} ok={profiles.get('ok')}",
        ])
        if profiles.get("profiles"):
            lines.extend(["", "### Saved Profiles", ""])
            for profile in profiles["profiles"]:
                detail = f"- {profile.get('profile')}: ok={profile.get('ok')}"
                if profile.get("run_dir"):
                    detail += f" run=`{profile.get('run_dir')}`"
                if profile.get("error"):
                    detail += f" error={profile['error'].get('type')}: {profile['error'].get('message')}"
                lines.append(detail)
        if quality.get("quality_gate_violations"):
            lines.extend(["", "### Quality Gate Violations", ""])
            for violation in quality["quality_gate_violations"]:
                lines.append(
                    f"- {violation.get('gate')}: `{violation.get('artifact')}` - "
                    f"{violation.get('next_action')}"
                )

    if summary.get("error"):
        error = summary["error"]
        lines.extend(["", "## Error", "", f"{error['type']}: {error['message']}"])

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
