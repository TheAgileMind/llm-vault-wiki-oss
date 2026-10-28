from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import Config
from .paths import resolve_vault_path
from .storage import create_run_dir, read_json, write_json


class ApplyPlanHelperError(ValueError):
    pass


def draft_apply_plan(
    config: Config,
    brief: str | Path,
    source_index: int = 0,
    archive_source: bool = False,
) -> dict[str, Any]:
    brief_path = _resolve_brief_path(config, brief)
    data = read_json(brief_path)
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ApplyPlanHelperError("file-back brief must contain a non-empty sources list")
    if source_index < 0 or source_index >= len(sources):
        raise ApplyPlanHelperError(f"source index {source_index} is outside the brief source range")

    package = sources[source_index]
    if not isinstance(package, dict):
        raise ApplyPlanHelperError(f"source index {source_index} must contain a file-back package object")
    _validate_ready_package(package)

    primary = package["primary_destination"]
    target_path = str(primary["suggested_path"])
    target_exists = resolve_vault_path(target_path, config.vault_root).exists()
    archive_path = _archive_path(config, str(package["source"])) if archive_source else None
    content = _canonical_note_skeleton(package, source_reference=archive_path or str(package["source"]))
    operations = [
        {
            "op": "create_file",
            "path": target_path,
            "content": content,
        }
    ]
    if archive_source:
        operations.append({
            "op": "archive_file",
            "path": str(package["source"]),
            "to": archive_path,
        })
    skeleton = {"operations": operations}

    run_dir = create_run_dir(config.state_dir, "draft-apply-plan")
    skeleton_path = run_dir / "apply-plan.skeleton.json"
    prompt_path = run_dir / "canonical-note.writer-prompt.md"
    write_json(skeleton_path, skeleton)
    prompt_path.write_text(
        _writer_prompt(
            package,
            skeleton_path,
            target_exists=target_exists,
            archive_source=archive_source,
            archive_path=archive_path,
        ),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "run_dir": str(run_dir),
        "brief": str(brief_path),
        "source_index": source_index,
        "source": str(package["source"]),
        "target_path": target_path,
        "target_exists": target_exists,
        "archive_source": archive_source,
        "archive_path": archive_path,
        "note_type": str(primary["note_type"]),
        "apply_plan_skeleton": str(skeleton_path),
        "writer_prompt": str(prompt_path),
        "ready_for_agent_draft": True,
        "quality_checks": package.get("quality_checks", {}),
    }


def _resolve_brief_path(config: Config, brief: str | Path) -> Path:
    raw_path = Path(brief).expanduser()
    if raw_path.is_absolute():
        brief_path = raw_path.resolve()
    else:
        cwd_path = (Path.cwd() / raw_path).resolve()
        config_path = (config.path.parent / raw_path).resolve()
        brief_path = cwd_path if cwd_path.exists() else config_path
    if not brief_path.exists():
        raise FileNotFoundError(f"file-back brief not found: {brief_path}")
    return brief_path


def _validate_ready_package(package: dict[str, Any]) -> None:
    if package.get("ready_for_agent_draft") is not True:
        raise ApplyPlanHelperError("file-back package is not ready for agent draft")
    if not package.get("source"):
        raise ApplyPlanHelperError("file-back package is missing source")
    primary = package.get("primary_destination")
    if not isinstance(primary, dict):
        raise ApplyPlanHelperError("file-back package is missing primary_destination")
    if not primary.get("suggested_path"):
        raise ApplyPlanHelperError("file-back package primary_destination is missing suggested_path")
    if not primary.get("note_type"):
        raise ApplyPlanHelperError("file-back package primary_destination is missing note_type")


def _canonical_note_skeleton(package: dict[str, Any], *, source_reference: str | None = None) -> str:
    primary = package["primary_destination"]
    title = _canonical_title(package)
    today = date.today().isoformat()
    source_link = source_reference or str(package["source"])
    metadata = package.get("source_metadata") if isinstance(package.get("source_metadata"), dict) else {}
    domains = _metadata_list(metadata, "domains")
    thesis_areas = _metadata_list(metadata, "thesis_areas")
    tags = _merged_tags(_metadata_list(metadata, "tags"), ["file-back", "agent-draft-needed"])
    related_links = [_wikilink(source_link)]
    related_links.extend(_wikilink(str(note["path"]), str(note.get("title") or "")) for note in _related_notes(package))
    frontmatter = yaml.safe_dump(
        {
            "title": title,
            "date_created": today,
            "date_modified": today,
            "type": str(primary["note_type"]),
            "status": "draft",
            "domains": domains,
            "thesis_areas": thesis_areas,
            "related": related_links,
            "tags": tags,
            "source": source_link,
            "source_capture": str(package["source"]),
        },
        sort_keys=False,
        allow_unicode=True,
    ).strip()

    lines = [
        "---",
        frontmatter,
        "---",
        "",
        f"# {title}",
        "",
        "## Source-Grounded Summary",
        "",
        "<Replace with a concise synthesis grounded only in the source package and cited source material.>",
        "",
        "## Direct Source Claims",
        "",
        "<List claims that are directly supported by the source. Keep citations attached to the claims they support.>",
        "",
        "## Agent Interpretation / Implications",
        "",
        "<Add clearly labeled implications for the project or vault. Do not present interpretation as source fact.>",
        "",
        "## Recommended Action",
        "",
        "<State the next practical action this note should drive, or write 'No immediate action.'>",
        "",
        "## Related Notes",
        "",
    ]
    related_notes = _related_notes(package)
    if related_notes:
        for note in related_notes:
            title_value = str(note.get("title") or Path(str(note["path"])).stem)
            why = str(note.get("why_it_matters") or "Related vault context.")
            lines.append(f"- {_wikilink(str(note['path']), title_value)} - {why}")
    else:
        lines.append("- <Add related vault notes if the writer finds a direct connection.>")
    lines.extend([
        "",
        "## Sources",
        "",
        f"- Source capture: {_wikilink(source_link)}",
    ])
    for url in _source_urls(package):
        lines.append(f"- {url}")
    lines.extend([
        "",
        "## Source Excerpt",
        "",
        _excerpt(package),
        "",
    ])
    return "\n".join(lines)


def _writer_prompt(
    package: dict[str, Any],
    skeleton_path: Path,
    *,
    target_exists: bool,
    archive_source: bool,
    archive_path: str | None,
) -> str:
    primary = package["primary_destination"]
    related = "\n".join(
        f"- {_wikilink(str(note['path']), str(note.get('title') or ''))}: {note.get('why_it_matters', '')}"
        for note in _related_notes(package)
    ) or "- None supplied by the file-back package."
    urls = "\n".join(f"- {url}" for url in _source_urls(package)) or "- None detected."
    return "\n".join([
        "# Canonical Note Writer Prompt",
        "",
        "Use the generated apply-plan skeleton as the only editable artifact. Fill the semantic prose placeholders, then run the existing guarded apply workflow. Do not edit the vault directly.",
        "",
        "## Target",
        "",
        f"- Source capture: `{package['source']}`",
        f"- Canonical target: `{primary['suggested_path']}`",
        f"- Target currently exists: `{str(target_exists).lower()}`",
        f"- Archive source after apply: `{str(archive_source).lower()}`",
        f"- Archive target: `{archive_path or 'none'}`",
        f"- Note type: `{primary['note_type']}`",
        f"- Apply-plan skeleton: `{skeleton_path}`",
        "",
        "## Writing Rules",
        "",
        "- Preserve the JSON operation, target path, and frontmatter safety fields unless a human explicitly asks for a change.",
        "- If the target currently exists, do not execute the create-file plan until a human decides whether to rename, overwrite, or handle it outside this helper.",
        "- If the plan includes an archive operation, keep it after the create-file operation so the source remains available until the canonical note write succeeds.",
        "- Replace placeholders with concise prose.",
        "- Keep direct source claims separate from agent interpretation.",
        "- Preserve all usable citations and attach them to the claims they support.",
        "- Do not invent source-backed facts that are not in the source capture, URLs, or supplied related notes.",
        "- Return a reviewed apply plan that can be passed to `process-source --plan` or `apply` for dry-run validation.",
        "",
        "## Source URLs",
        "",
        urls,
        "",
        "## Related Notes",
        "",
        related,
        "",
        "## Source Excerpt",
        "",
        _excerpt(package),
        "",
    ])


def _canonical_title(package: dict[str, Any]) -> str:
    title = str(package.get("title") or Path(str(package["source"])).stem).strip()
    return title.removeprefix("Source Capture - ").strip() or Path(str(package["source"])).stem


def _related_notes(package: dict[str, Any]) -> list[dict[str, Any]]:
    notes = package.get("related_notes") or []
    return [note for note in notes if isinstance(note, dict) and note.get("path")]


def _source_urls(package: dict[str, Any]) -> list[str]:
    return [str(url) for url in package.get("source_urls", []) if str(url).strip()]


def _metadata_list(metadata: dict[str, Any], key: str) -> list[str]:
    raw = metadata.get(key) or []
    if not isinstance(raw, list):
        raw = [raw]
    return [str(value).strip() for value in raw if str(value).strip()]


def _merged_tags(source_tags: list[str], helper_tags: list[str]) -> list[str]:
    return list(dict.fromkeys([*source_tags, *helper_tags]))


def _excerpt(package: dict[str, Any]) -> str:
    excerpt = str(package.get("source_excerpt") or "").strip()
    return excerpt or "<No source excerpt supplied by the file-back package. Review the source capture directly.>"


def _wikilink(path: str, title: str = "") -> str:
    link_target = path[:-3] if path.endswith(".md") else path
    if title and title != Path(path).stem:
        return f"[[{link_target}|{title}]]"
    return f"[[{link_target}]]"


def _archive_path(config: Config, source: str) -> str:
    filename = "_".join(part for part in source.replace("\\", "/").split("/") if part)
    base = Path("08_Archive/LLM_Vault_Wiki") / filename
    candidate = base.as_posix()
    if not resolve_vault_path(candidate, config.vault_root).exists():
        return candidate

    stem = base.stem
    suffix = base.suffix
    parent = base.parent
    counter = 2
    while True:
        candidate = (parent / f"{stem}-{counter}{suffix}").as_posix()
        if not resolve_vault_path(candidate, config.vault_root).exists():
            return candidate
        counter += 1
