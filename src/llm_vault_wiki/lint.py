from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config
from .paths import to_posix
from .storage import read_json, write_json

REQUIRED_MANIFESTS = (
    "vault.inventory.json",
    "vault.frontmatter.json",
    "vault.policy.json",
    "vault.links.json",
    "vault.changes.json",
)
WRITE_OPS = {"create_file", "move_file", "archive_file", "write", "delete"}


def _manifest_dir(config: Config) -> Path:
    return config.state_dir / "manifests"


def _known_targets(files: list[dict[str, Any]]) -> set[str]:
    targets: set[str] = set()
    for item in files:
        path = to_posix(item["path"])
        targets.add(path)
        targets.add(Path(path).stem)
        targets.add(str(item.get("title") or ""))
    return {target for target in targets if target}


def lint_vault(config: Config, fail_on_warnings: bool = False) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    manifest_dir = _manifest_dir(config)

    for name in REQUIRED_MANIFESTS:
        if not (manifest_dir / name).exists():
            errors.append({"code": "missing_manifest", "message": f"Run scan first; missing {name}"})

    if errors:
        result = {"ok": False, "errors": errors, "warnings": warnings}
        _write_lint_report(config, result)
        return result

    inventory = read_json(manifest_dir / "vault.inventory.json")
    links = read_json(manifest_dir / "vault.links.json")
    files = inventory.get("files", [])
    known_targets = _known_targets(files)

    seen_paths: set[str] = set()
    for item in files:
        path = to_posix(item["path"])
        if path in seen_paths:
            errors.append({"code": "duplicate_inventory_path", "path": path, "message": "Duplicate path in inventory"})
        seen_paths.add(path)
        if not config.is_included(path):
            errors.append({"code": "excluded_path_indexed", "path": path, "message": "Indexed path violates folder/exclusion policy"})
        if item.get("risk") == "high" and WRITE_OPS.intersection(item.get("allowed_ops") or []):
            errors.append({"code": "high_risk_write", "path": path, "message": "High-risk paths cannot expose direct write ops"})
        if not item.get("type"):
            warnings.append({"code": "missing_type", "path": path, "message": "Note is missing required type frontmatter"})
        if not item.get("status"):
            warnings.append({"code": "missing_status", "path": path, "message": "Note is missing required status frontmatter"})

    for edge in links.get("links", []):
        target = str(edge.get("target") or "")
        normalized = to_posix(target)
        if normalized not in known_targets and Path(normalized).stem not in known_targets:
            warnings.append({
                "code": "unresolved_wikilink",
                "path": str(edge.get("source") or ""),
                "target": target,
                "message": "Wikilink target was not found in the indexed vault",
            })

    ok = not errors and (not fail_on_warnings or not warnings)
    result = {"ok": ok, "errors": errors, "warnings": warnings}
    _write_lint_report(config, result)
    return result


def _write_lint_report(config: Config, result: dict[str, Any]) -> None:
    report_dir = config.state_dir / "generated"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(report_dir / "lint.report.json", result)
    lines = [
        "# Lint Report",
        "",
        f"Status: {'pass' if result['ok'] else 'fail'}",
        f"Errors: {len(result['errors'])}",
        f"Warnings: {len(result['warnings'])}",
        "",
        "## Errors",
    ]
    lines.extend(_format_issue(issue) for issue in result["errors"])
    lines.extend(["", "## Warnings"])
    lines.extend(_format_issue(issue) for issue in result["warnings"])
    (report_dir / "lint.report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_issue(issue: dict[str, str]) -> str:
    path = f" `{issue['path']}`" if issue.get("path") else ""
    target = f" -> `{issue['target']}`" if issue.get("target") else ""
    return f"- {issue['code']}{path}{target}: {issue['message']}"
