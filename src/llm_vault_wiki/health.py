from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config
from .storage import create_run_dir, read_json, write_json


def _load_latest_validation(config: Config) -> dict[str, Any] | None:
    path = config.state_dir / "generated" / "system-validation.latest.json"
    if not path.exists():
        return None
    try:
        return read_json(path).get("summary")
    except Exception:
        return None


def _load_inventory(config: Config) -> dict[str, Any] | None:
    path = config.state_dir / "manifests" / "vault.inventory.json"
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def _stale_files(config: Config, inventory: dict[str, Any] | None) -> list[dict[str, str]]:
    if not inventory:
        return []
    stale = []
    for item in inventory.get("files", []):
        rel_path = item.get("path")
        if rel_path and not (config.vault_root / rel_path).exists():
            stale.append({"path": rel_path, "reason": "missing_from_vault"})
    return stale


def _source_candidates(inventory: dict[str, Any] | None) -> list[str]:
    if not inventory:
        return []
    candidates = []
    for item in inventory.get("files", []):
        path = str(item.get("path") or "")
        if path.startswith("00_Inbox/") and item.get("status") in {"seed", "draft", "active"}:
            candidates.append(path)
    return sorted(candidates)[:25]


def build_health_summary(config: Config, validation_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    validation = validation_summary if validation_summary is not None else _load_latest_validation(config)
    inventory = _load_inventory(config)
    stale = _stale_files(config, inventory)
    source_candidates = _source_candidates(inventory)
    actions: list[str] = []
    warnings: list[dict[str, Any]] = []

    if inventory is None:
        actions.append("Run `scan` before relying on brain-health output.")
    if validation is None:
        actions.append("Run `validate-system` to create a baseline system-validation report.")

    lint = validation.get("lint", {}) if validation else {}
    if lint.get("errors", 0):
        actions.append("Open the lint report and fix errors.")

    profile_failures = []
    weak_profiles = []
    for profile in (validation or {}).get("profiles", []):
        if not profile.get("ok", False):
            profile_failures.append(profile.get("profile"))
        elif profile.get("missed_relevant_files", 0):
            weak_profiles.append(profile.get("profile"))
    if profile_failures:
        actions.append("Inspect failed search profile reports: " + ", ".join(str(p) for p in profile_failures))
    if stale:
        actions.append("Rerun scan and inspect stale manifest files.")
    if source_candidates:
        actions.append("Review unprocessed inbox/source candidates before the next source-processing session.")
    if not actions:
        actions.append("No immediate action required. The read-only health signals are clean.")

    if weak_profiles:
        warnings.append({
            "type": "profile_missed_relevant_files",
            "profiles": weak_profiles,
            "message": "Profiles passed configured gates but still missed relevant files.",
        })

    ok = bool(validation and validation.get("ok", False) and not stale)
    return {
        "ok": ok,
        "validation_available": validation is not None,
        "inventory_available": inventory is not None,
        "indexed_files": (inventory or {}).get("file_count", 0),
        "validation_report": (validation or {}).get("markdown_report"),
        "lint_errors": lint.get("errors", 0),
        "lint_warnings": lint.get("warnings", 0),
        "stale_manifest_files": stale[:100],
        "profile_failures": profile_failures,
        "weak_profiles": weak_profiles,
        "source_candidates": source_candidates,
        "warnings": warnings,
        "recommended_next_actions": actions,
    }


def run_health(config: Config, validation_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    run_dir = create_run_dir(config.state_dir, "brain-health")
    health = build_health_summary(config, validation_summary=validation_summary)
    summary = {
        "ok": health["ok"],
        "run_dir": str(run_dir),
        "json_report": str(run_dir / "brain-health.json"),
        "markdown_report": str(run_dir / "brain-health.md"),
        "recommended_next_actions": health["recommended_next_actions"],
    }
    payload = {"summary": summary, "health": health}
    write_json(Path(summary["json_report"]), payload)
    _write_markdown(Path(summary["markdown_report"]), payload)
    return {**summary, "health": health}


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    health = payload["health"]
    lines = [
        "# Brain Health",
        "",
        f"Status: {'pass' if health['ok'] else 'needs attention'}",
        "",
        "## Summary",
        "",
        f"- Validation available: {health['validation_available']}",
        f"- Inventory available: {health['inventory_available']}",
        f"- Indexed files: {health['indexed_files']}",
        f"- Lint errors: {health['lint_errors']}",
        f"- Lint warnings: {health['lint_warnings']}",
        f"- Stale manifest files: {len(health['stale_manifest_files'])}",
        f"- Profile failures: {len(health['profile_failures'])}",
        f"- Weak profiles: {len(health['weak_profiles'])}",
        f"- Source candidates: {len(health['source_candidates'])}",
        "",
        "## Recommended Next Actions",
        "",
    ]
    for action in health["recommended_next_actions"]:
        lines.append(f"- {action}")

    if health["stale_manifest_files"]:
        lines.extend(["", "## Stale Manifest Files", ""])
        for item in health["stale_manifest_files"]:
            lines.append(f"- `{item['path']}` ({item['reason']})")

    if health["profile_failures"] or health["weak_profiles"]:
        lines.extend(["", "## Profiles", ""])
        for profile in health["profile_failures"]:
            lines.append(f"- `{profile}` failed configured gates.")
        for profile in health["weak_profiles"]:
            lines.append(f"- `{profile}` passed gates but missed relevant files.")

    if health["source_candidates"]:
        lines.extend(["", "## Source Candidates", ""])
        for path_item in health["source_candidates"]:
            lines.append(f"- `{path_item}`")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
