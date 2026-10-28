from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .config import Config, SearchEvaluationProfile
from .evaluate import evaluate_search
from .health import run_health
from .lint import lint_vault
from .scan import scan_vault
from .storage import create_run_dir, read_json, write_json


def validate_system(
    config: Config,
    *,
    profiles: list[str] | None = None,
    fail_on_warnings: bool = False,
    duration_warning_factor: float = 1.5,
) -> dict[str, Any]:
    run_dir = create_run_dir(config.state_dir, "system-validation")
    previous = _load_previous_summary(config)
    quality_gate_violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    scan_result, scan_duration = _timed(lambda: scan_vault(config))
    scan_summary = {
        "file_count": scan_result["inventory"]["file_count"],
        "warnings": len(scan_result["inventory"].get("warnings", [])),
        "changes": scan_result["changes"],
        "index_path": scan_result["index_path"],
    }

    lint_result, lint_duration = _timed(lambda: lint_vault(config, fail_on_warnings=fail_on_warnings))
    lint_summary = {
        "ok": lint_result["ok"],
        "errors": len(lint_result["errors"]),
        "warnings": len(lint_result["warnings"]),
        "json_report": str(config.state_dir / "generated" / "lint.report.json"),
        "markdown_report": str(config.state_dir / "generated" / "lint.report.md"),
        "fail_on_warnings": fail_on_warnings,
    }
    if not lint_result["ok"]:
        quality_gate_violations.append({
            "gate": "lint",
            "artifact": lint_summary["markdown_report"],
            "errors": lint_summary["errors"],
            "warnings": lint_summary["warnings"],
            "next_action": "Open the lint report and fix errors before treating the vault as healthy.",
        })

    stale_manifest = _stale_manifest_status(config)
    if not stale_manifest["ok"]:
        quality_gate_violations.append({
            "gate": "stale_manifest",
            "count": stale_manifest["count"],
            "next_action": "Rerun scan and inspect missing files before evaluating retrieval quality.",
        })

    selected_profiles = _select_profiles(config, profiles)
    profile_results, profile_duration = _timed(lambda: _run_profiles(config, selected_profiles))
    for profile in profile_results:
        if not profile["ok"]:
            quality_gate_violations.append({
                "gate": "search_profile",
                "profile": profile["profile"],
                "artifact": profile.get("markdown_report") or profile.get("run_dir"),
                "quality_gate_violations": profile.get("quality_gate_violations", []),
                "next_action": "Open the profile report and inspect missed relevant files, precision failures, or stale manifest entries.",
            })

    durations = {
        "scan_seconds": scan_duration,
        "lint_seconds": lint_duration,
        "profiles_seconds": profile_duration,
    }
    durations["total_seconds"] = round(sum(durations.values()), 3)
    trend = _trend_summary(previous, scan_summary, lint_summary, stale_manifest, profile_results, durations, duration_warning_factor)
    warnings.extend(trend["warnings"])

    summary = {
        "ok": not quality_gate_violations,
        "run_dir": str(run_dir),
        "json_report": str(run_dir / "system-validation.json"),
        "markdown_report": str(run_dir / "system-validation.md"),
        "latest_report": str(config.state_dir / "generated" / "system-validation.latest.json"),
        "scan": scan_summary,
        "lint": lint_summary,
        "stale_manifest": stale_manifest,
        "profiles": profile_results,
        "durations": durations,
        "trend": trend,
        "warnings": warnings,
        "quality_gate_violations": quality_gate_violations,
    }

    brain_health = run_health(config, validation_summary=summary)
    summary["brain_health"] = {
        "ok": brain_health["ok"],
        "run_dir": brain_health["run_dir"],
        "json_report": brain_health["json_report"],
        "markdown_report": brain_health["markdown_report"],
        "recommended_next_actions": brain_health["recommended_next_actions"],
    }

    payload = {"summary": summary}
    write_json(run_dir / "system-validation.json", payload)
    _write_markdown_report(run_dir / "system-validation.md", payload)
    write_json(Path(summary["latest_report"]), payload)
    return summary


def _timed(action: Callable[[], Any]) -> tuple[Any, float]:
    start = time.perf_counter()
    result = action()
    return result, round(time.perf_counter() - start, 3)


def _load_previous_summary(config: Config) -> dict[str, Any] | None:
    path = config.state_dir / "generated" / "system-validation.latest.json"
    if not path.exists():
        return None
    try:
        return read_json(path).get("summary")
    except Exception:
        return None


def _select_profiles(config: Config, requested: list[str] | None) -> dict[str, SearchEvaluationProfile]:
    if not requested:
        return dict(config.search_evaluations)
    profiles: dict[str, SearchEvaluationProfile] = {}
    for name in requested:
        profile = config.search_evaluations.get(name)
        if profile is None:
            available = ", ".join(sorted(config.search_evaluations)) or "none configured"
            raise ValueError(f"Unknown search evaluation profile: {name}. Available profiles: {available}")
        profiles[name] = profile
    return profiles


def _run_profiles(config: Config, profiles: dict[str, SearchEvaluationProfile]) -> list[dict[str, Any]]:
    results = []
    for name, profile in profiles.items():
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
            run_dir = Path(result["run_dir"])
            results.append({
                "profile": name,
                "ok": bool(result["ok"]),
                "run_dir": result["run_dir"],
                "markdown_report": str(run_dir / "search-evaluation.md"),
                "json_report": str(run_dir / "search-evaluation.json"),
                "indexed_files": result["indexed_files"],
                "stale_manifest_files": result["stale_manifest_files"],
                "corpus_relevant_files": result["corpus_relevant_files"],
                "ranked_files": result["ranked_files"],
                "missed_relevant_files": result["missed_relevant_files"],
                "overall_precision": result["overall_precision"],
                "overall_recall": result["overall_recall"],
                "precision_at": result["precision_at"],
                "quality_gate_violations": result["quality_gate_violations"],
            })
        except Exception as exc:
            results.append({
                "profile": name,
                "ok": False,
                "run_dir": None,
                "markdown_report": None,
                "json_report": None,
                "indexed_files": 0,
                "stale_manifest_files": 0,
                "corpus_relevant_files": 0,
                "ranked_files": 0,
                "missed_relevant_files": 0,
                "overall_precision": 0.0,
                "overall_recall": 0.0,
                "precision_at": {},
                "quality_gate_violations": [{
                    "gate": "profile_exception",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }],
            })
    return results


def _stale_manifest_status(config: Config) -> dict[str, Any]:
    inventory_path = config.state_dir / "manifests" / "vault.inventory.json"
    if not inventory_path.exists():
        return {"status": "missing_inventory", "ok": False, "count": 0, "files": []}
    inventory = read_json(inventory_path)
    stale = []
    for item in inventory.get("files", []):
        rel_path = item.get("path")
        if rel_path and not (config.vault_root / str(rel_path)).exists():
            stale.append({"path": rel_path, "reason": "missing_from_vault"})
    return {"status": "checked", "ok": not stale, "count": len(stale), "files": stale[:100]}


def _trend_summary(
    previous: dict[str, Any] | None,
    scan: dict[str, Any],
    lint: dict[str, Any],
    stale_manifest: dict[str, Any],
    profiles: list[dict[str, Any]],
    durations: dict[str, float],
    duration_warning_factor: float,
) -> dict[str, Any]:
    if not previous:
        return {"status": "baseline", "previous_run_dir": None, "comparisons": {}, "warnings": []}

    comparisons = {
        "file_count": _comparison(scan["file_count"], previous.get("scan", {}).get("file_count")),
        "lint_errors": _comparison(lint["errors"], previous.get("lint", {}).get("errors")),
        "lint_warnings": _comparison(lint["warnings"], previous.get("lint", {}).get("warnings")),
        "stale_manifest_count": _comparison(stale_manifest["count"], previous.get("stale_manifest", {}).get("count")),
        "profile_failures": _comparison(
            sum(1 for profile in profiles if not profile["ok"]),
            sum(1 for profile in previous.get("profiles", []) if not profile.get("ok", False)),
        ),
    }
    warnings: list[dict[str, Any]] = []
    previous_durations = previous.get("durations", {})
    for key, value in durations.items():
        prior = previous_durations.get(key)
        comparisons[key] = _comparison(value, prior)
        if isinstance(prior, (int, float)) and prior > 0 and value > prior * duration_warning_factor:
            warnings.append({
                "type": "duration_regression",
                "metric": key,
                "previous": prior,
                "current": value,
                "factor": duration_warning_factor,
            })
    return {
        "status": "compared",
        "previous_run_dir": previous.get("run_dir"),
        "comparisons": comparisons,
        "warnings": warnings,
    }


def _comparison(current: Any, previous: Any) -> dict[str, Any]:
    if previous is None:
        return {"current": current, "previous": None, "delta": None}
    try:
        delta = round(current - previous, 3)
    except TypeError:
        delta = None
    return {"current": current, "previous": previous, "delta": delta}


def _write_markdown_report(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# System Validation",
        "",
        f"Status: {'pass' if summary['ok'] else 'fail'}",
        f"Run directory: `{summary['run_dir']}`",
        "",
        "## Summary",
        "",
        f"- Indexed files: {summary['scan']['file_count']}",
        f"- Scan warnings: {summary['scan']['warnings']}",
        f"- Lint errors: {summary['lint']['errors']}",
        f"- Lint warnings: {summary['lint']['warnings']}",
        f"- Stale manifest files: {summary['stale_manifest']['count']}",
        f"- Profiles checked: {len(summary['profiles'])}",
        f"- Profile failures: {sum(1 for profile in summary['profiles'] if not profile['ok'])}",
        f"- Brain health: {'pass' if summary.get('brain_health', {}).get('ok') else 'needs attention'}",
        f"- Total duration: {summary['durations']['total_seconds']}s",
        "",
        "## Durations",
        "",
        "| Stage | Seconds |",
        "|---|---:|",
    ]
    for key, value in summary["durations"].items():
        lines.append(f"| {key} | {value} |")

    lines.extend(["", "## Profiles", ""])
    if summary["profiles"]:
        lines.extend(["| Profile | Status | P@25 | P@100 | Missed | Report |", "|---|---|---:|---:|---:|---|"])
        for profile in summary["profiles"]:
            precision = profile.get("precision_at", {})
            status = "pass" if profile["ok"] else "fail"
            lines.append(
                f"| `{profile['profile']}` | {status} | {precision.get('25', '')} | "
                f"{precision.get('100', '')} | {profile['missed_relevant_files']} | "
                f"`{profile['markdown_report']}` |"
            )
    else:
        lines.append("No search evaluation profiles are configured.")

    lines.extend(["", "## Trend", ""])
    trend = summary["trend"]
    lines.append(f"- Status: {trend['status']}")
    if trend.get("previous_run_dir"):
        lines.append(f"- Previous run: `{trend['previous_run_dir']}`")
    for name, comparison in trend.get("comparisons", {}).items():
        lines.append(
            f"- {name}: current={comparison['current']} "
            f"previous={comparison['previous']} delta={comparison['delta']}"
        )

    if summary["warnings"]:
        lines.extend(["", "## Warnings", ""])
        for warning in summary["warnings"]:
            lines.append(f"- {warning}")

    brain_health = summary.get("brain_health")
    if brain_health:
        lines.extend(["", "## Brain Health", ""])
        lines.append(f"- Status: {'pass' if brain_health['ok'] else 'needs attention'}")
        lines.append(f"- Report: `{brain_health['markdown_report']}`")
        for action in brain_health.get("recommended_next_actions", []):
            lines.append(f"- Next action: {action}")

    if summary["quality_gate_violations"]:
        lines.extend(["", "## Quality Gate Violations", ""])
        for violation in summary["quality_gate_violations"]:
            lines.append(f"- {violation}")

    lines.extend(["", "## Next Action", ""])
    if summary["ok"]:
        lines.append("No action required. The read-only validation gates passed.")
    else:
        lines.append("Start with the quality gate violations above, then rerun `validate-system`.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
