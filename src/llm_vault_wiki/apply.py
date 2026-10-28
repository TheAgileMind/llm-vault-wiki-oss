from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config
from .frontmatter import parse_frontmatter
from .paths import resolve_vault_path, vault_relative
from .storage import create_run_dir, write_json

SUPPORTED_OPS = {"create_file", "move_file", "archive_file"}


class ApplyPlanError(ValueError):
    pass


def apply_plan(config: Config, plan_path: str | Path, execute: bool = False, reviewed: bool = False) -> dict[str, Any]:
    plan_file = Path(plan_path).resolve()
    if not plan_file.exists():
        raise FileNotFoundError(f"Apply plan not found: {plan_file}")
    plan = _load_plan(plan_file)
    operations = plan.get("operations")
    if not isinstance(operations, list):
        raise ApplyPlanError("Apply plan must contain an operations list")

    run_dir = create_run_dir(config.state_dir, "apply")
    if execute and config.apply_policy.mode == "dry_run_only":
        raise PermissionError("Execution is blocked by apply_policy mode dry_run_only.")
    mutations_blocked = execute and config.apply_policy.mode == "dry_run_required" and not reviewed
    if mutations_blocked:
        raise PermissionError("Execution is blocked by apply_policy. Re-run with human review acknowledgement.")
    validated = [_validate_operation(config, op, execute=execute, reviewed=reviewed) for op in operations]

    results = []
    for item in validated:
        if execute:
            _execute_operation(config, item["operation"])
        results.append({
            "operation": item["operation"],
            "status": "applied" if execute else "dry_run",
            "risk": item["risk"],
            "policy_role": item["policy_role"],
        })

    report = {"execute": execute, "reviewed": reviewed, "plan": _display_path(plan_file, config), "results": results}
    write_json(run_dir / "apply.report.json", report)
    _write_markdown_report(run_dir, report)
    return {"run_dir": str(run_dir), **report}


def _load_plan(plan_file: Path) -> dict[str, Any]:
    import json

    return json.loads(plan_file.read_text(encoding="utf-8"))


def _validate_operation(config: Config, operation: dict[str, Any], execute: bool, reviewed: bool) -> dict[str, Any]:
    op = str(operation.get("op") or "")
    if op not in SUPPORTED_OPS:
        raise ApplyPlanError(f"Unsupported operation: {op}")

    target_value = _operation_target(config, operation)
    if not target_value:
        raise ApplyPlanError(f"Operation {op} requires path or to")
    target_path = resolve_vault_path(str(target_value), config.vault_root)
    target_rel = vault_relative(target_path, config.vault_root)
    policy = config.classify(target_rel)
    if not policy or not config.is_included(target_rel):
        raise PermissionError(f"Target is outside included vault policy: {target_rel}")
    if op not in policy.allowed_ops:
        raise PermissionError(f"Operation {op} is not allowed for {target_rel}")
    if op in {"move_file", "archive_file"}:
        source = resolve_vault_path(str(operation.get("from") or operation.get("path") or ""), config.vault_root)
        source_rel = vault_relative(source, config.vault_root)
        if not source.exists():
            raise FileNotFoundError(f"Source does not exist: {source_rel}")
        if not config.is_included(source_rel):
            raise PermissionError(f"Source is outside included vault policy: {source_rel}")
        source_policy = config.classify(source_rel)
        if not source_policy or op not in source_policy.allowed_ops:
            raise PermissionError(f"Operation {op} is not allowed for source {source_rel}")
        if execute and source_policy.risk == "high" and config.apply_policy.high_risk_requires_review and not reviewed:
            raise PermissionError(f"Human review is required before touching high-risk source path: {source_rel}")
        if execute and op in source_policy.review_required_for and not reviewed:
            raise PermissionError(f"Human review is required for {op} on source {source_rel}")

    if op == "create_file":
        content = str(operation.get("content") or "")
        fm = parse_frontmatter(content)
        if not fm.data.get("type") or not fm.data.get("status"):
            raise ApplyPlanError(f"create_file content for {target_rel} must include type and status frontmatter")

    if execute and policy.risk == "high" and config.apply_policy.high_risk_requires_review and not reviewed:
        raise PermissionError(f"Human review is required before touching high-risk path: {target_rel}")
    if execute and op in policy.review_required_for and not reviewed:
        raise PermissionError(f"Human review is required for {op} on {target_rel}")

    return {"operation": operation, "risk": policy.risk, "policy_role": policy.role}


def _execute_operation(config: Config, operation: dict[str, Any]) -> None:
    op = operation["op"]
    if op == "create_file":
        target = resolve_vault_path(str(operation["path"]), config.vault_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not operation.get("overwrite"):
            raise FileExistsError(f"Refusing to overwrite existing file: {vault_relative(target, config.vault_root)}")
        target.write_text(str(operation.get("content") or ""), encoding="utf-8")
        return

    if op == "move_file":
        source = resolve_vault_path(str(operation["from"]), config.vault_root)
        target = resolve_vault_path(str(operation["to"]), config.vault_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not operation.get("overwrite"):
            raise FileExistsError(f"Refusing to overwrite existing file: {vault_relative(target, config.vault_root)}")
        source.replace(target)
        return

    if op == "archive_file":
        source = resolve_vault_path(str(operation["path"]), config.vault_root)
        target = resolve_vault_path(str(_operation_target(config, operation)), config.vault_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not operation.get("overwrite"):
            raise FileExistsError(f"Refusing to overwrite existing archive file: {target}")
        source.replace(target)
        return

    raise ApplyPlanError(f"Unsupported operation: {op}")


def _operation_target(config: Config, operation: dict[str, Any]) -> str:
    op = str(operation.get("op") or "")
    if op == "archive_file":
        if operation.get("to"):
            return str(operation["to"])
        source_value = str(operation.get("path") or "")
        source = resolve_vault_path(source_value, config.vault_root)
        return f"08_Archive/LLM_Vault_Wiki/{Path(vault_relative(source, config.vault_root)).name}"
    return str(operation.get("path") or operation.get("to") or "")


def _display_path(path: Path, config: Config) -> str:
    for root, label in ((config.path.parent, "."), (config.vault_root, "<vault>")):
        try:
            return f"{label}/{path.relative_to(root).as_posix()}"
        except ValueError:
            continue
    return path.name


def _write_markdown_report(run_dir: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Apply Report",
        "",
        f"Mode: {'execute' if report['execute'] else 'dry-run'}",
        f"Reviewed: {report['reviewed']}",
        f"Plan: `{report['plan']}`",
        "",
        "## Operations",
    ]
    for result in report["results"]:
        op = result["operation"]
        path = op.get("path") or op.get("to")
        lines.append(f"- {result['status']}: {op['op']} `{path}` ({result['risk']}, {result['policy_role']})")
    (run_dir / "apply.report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
