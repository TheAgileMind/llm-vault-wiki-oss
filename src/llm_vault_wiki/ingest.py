from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

from .config import Config
from .frontmatter import derive_title, parse_frontmatter
from .links import extract_wikilinks
from .manifests import safe_excerpt
from .paths import resolve_vault_path, vault_relative
from .query import rank_notes, tokenize, tokenize_list
from .storage import create_run_dir, write_json

DESTINATION_ROLES = {
    "research_artifacts": "03_Research",
    "domain_synthesis": "02_Domains",
    "content_engine": "04_Content",
    "project_memory": "01_Projects",
}

NOTE_TYPES_BY_FOLDER = {
    "01_Projects": "project-note",
    "02_Domains": "domain-note",
    "03_Research": "intelligence-brief",
    "04_Content": "content-idea",
}


def _list_frontmatter_values(data: dict[str, Any], key: str) -> list[str]:
    raw = data.get(key) or []
    if not isinstance(raw, list):
        raw = [raw]
    return [str(value).strip() for value in raw if str(value).strip()]


def _source_metadata(data: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "domains": _list_frontmatter_values(data, "domains"),
        "tags": _list_frontmatter_values(data, "tags"),
        "thesis_areas": _list_frontmatter_values(data, "thesis_areas"),
    }


def _frequent_terms(text: str, limit: int = 20) -> list[str]:
    stop = {
        "the", "and", "for", "that", "this", "with", "from", "you", "your", "are", "was", "were", "have", "has", "but", "not",
        "about", "after", "again", "all", "also", "at", "back", "been", "being", "can", "could", "did", "doing", "done", "each",
        "do", "does", "everything", "get", "got", "had", "he", "her", "him", "his", "how", "in", "into", "is", "it", "just", "kind", "like",
        "lot", "me", "more", "much", "my", "now", "of", "one", "only", "or", "our", "out", "over", "point", "really",
        "said", "same", "see", "she", "some", "something", "still", "take", "than", "their", "them", "then", "there",
        "these", "they", "thing", "think", "thought", "through", "time", "to", "voice", "want", "way", "well",
        "we", "when", "where", "which", "while", "will", "work", "would", "us",
    }
    terms = [term for term in tokenize_list(text) if term not in stop]
    return [term for term, _ in Counter(terms).most_common(limit)]


def _metadata_terms(data: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("title", "type", "status"):
        if data.get(key):
            values.append(str(data[key]))
    for key in ("domains", "thesis_areas", "tags"):
        raw = data.get(key) or []
        if isinstance(raw, list):
            values.extend(str(value) for value in raw)
        else:
            values.append(str(raw))
    return sorted(tokenize(" ".join(values)))


def _explicit_related_targets(data: dict[str, Any]) -> set[str]:
    raw = data.get("related") or []
    if not isinstance(raw, list):
        raw = [raw]
    targets: set[str] = set()
    for value in raw:
        text = str(value)
        links = extract_wikilinks(text)
        targets.update(links or [text])
    return {_normalize_target(target) for target in targets if _normalize_target(target)}


def _normalize_target(target: str) -> str:
    cleaned = target.strip().strip('"').strip("'")
    if cleaned.startswith("[[") and cleaned.endswith("]]"):
        cleaned = cleaned[2:-2].split("|", 1)[0].split("#", 1)[0].strip()
    return cleaned.removesuffix(".md").lower().replace("\\", "/")


def _item_targets(item: dict[str, Any]) -> set[str]:
    path = str(item.get("path") or "")
    title = str(item.get("title") or "")
    stem = Path(path).stem
    return {_normalize_target(value) for value in (path, path.removesuffix(".md"), stem, title) if value}


def _overlap(left: list[str], right: Any) -> set[str]:
    raw = right or []
    if not isinstance(raw, list):
        raw = [raw]
    return set(left) & set(tokenize(" ".join(str(value) for value in raw)))


def _rerank_for_ingest(
    items: list[dict[str, Any]],
    *,
    source_rel: str,
    metadata_terms: list[str],
    explicit_targets: set[str],
    preferred_roles: set[str],
) -> list[dict[str, Any]]:
    reranked: list[dict[str, Any]] = []
    source_parent = str(Path(source_rel).parent).replace("\\", "/")
    for item in items:
        if item["path"] == source_rel:
            continue
        score = int(item["score"])
        reasons = list(item["score_reasons"])
        is_explicit = bool(explicit_targets & _item_targets(item))
        if is_explicit:
            score += 100
            reasons.append("source-related: explicit related wikilink")
        if item.get("role") in preferred_roles:
            score += 8
            reasons.append(f"role boost: {item['role']}")
        metadata_overlap = _overlap(metadata_terms, [item.get("title", ""), *(item.get("domains") or []), *(item.get("thesis_areas") or []), *(item.get("tags") or [])])
        if metadata_overlap:
            score += len(metadata_overlap) * 6
            reasons.append(f"source metadata: {', '.join(sorted(metadata_overlap)[:5])}")
        item_parent = str(Path(item["path"]).parent).replace("\\", "/")
        if item_parent == source_parent and not is_explicit:
            score -= 8
            reasons.append("source-neighborhood penalty")
        if item["path"].startswith("05_Journal/") and not is_explicit and len(metadata_overlap) < 2:
            score -= 24
            reasons.append("journal-noise penalty")
        if score > 0:
            reranked.append({**item, "score": score, "score_reasons": reasons})
    return sorted(reranked, key=lambda item: (-item["score"], item["path"]))


def _source_candidates(config: Config) -> list[str]:
    inbox = config.vault_root / "00_Inbox"
    if not inbox.exists():
        return []
    rels = []
    for path in sorted(inbox.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".md", ".markdown", ".txt"}:
            rel = vault_relative(path, config.vault_root)
            if config.is_included(rel):
                rels.append(rel)
    return rels


def _source_urls(text: str) -> list[str]:
    urls = []
    markdown_matches = re.findall(r"!?\[[^\]]*\]\((https?://[^)\s]+)\)", text)
    for match in [*markdown_matches, *re.findall(r"https?://[^\s\]\)>,]+", text)]:
        cleaned = match.rstrip(".,;:")
        if cleaned not in urls:
            urls.append(cleaned)
    return urls


def _safe_note_name(title: str) -> str:
    cleaned = title.removeprefix("Source Capture - ").strip() or title
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", cleaned).strip("_")
    return f"{cleaned or 'Canonical_Note'}.md"


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _project_folder(path_value: str) -> str | None:
    parts = Path(path_value.replace("\\", "/")).parts
    if len(parts) >= 2 and parts[0] == "01_Projects":
        return f"01_Projects/{parts[1]}"
    return None


def _note_type_for_folder(folder: str) -> str:
    top_folder = folder.split("/", 1)[0]
    return NOTE_TYPES_BY_FOLDER.get(top_folder, "intelligence-brief")


def _role_folder(role: Any) -> str | None:
    return DESTINATION_ROLES.get(str(role))


def _specific_related_folder(config: Config, item: dict[str, Any]) -> tuple[str | None, str | None]:
    path_value = str(item.get("path") or "").replace("\\", "/")
    if not path_value:
        return None, "related note has no path"

    parent = Path(path_value).parent.as_posix()
    role_folder = _role_folder(item.get("role"))
    if not role_folder:
        return None, "related note role is not a writable destination role"
    if parent in {".", ""}:
        return role_folder, None
    if parent != role_folder and not parent.startswith(f"{role_folder}/"):
        return None, f"related note parent `{parent}` is outside role folder `{role_folder}`"
    if not config.is_included(parent):
        return None, f"related note parent `{parent}` is excluded by folder policy"
    return parent, None


def _destination_confidence(
    *,
    winning_signal: str,
    primary_folder: str,
    alternatives: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "winning_signal": winning_signal,
        "alternatives": alternatives,
        "primary_folder": primary_folder,
    }


def _infer_primary_destination(
    *,
    config: Config,
    title: str,
    related: list[dict[str, Any]],
    destinations: list[dict[str, Any]],
) -> dict[str, Any]:
    explicit_related = [
        item
        for item in related
        if any("source-related" in reason for reason in item.get("score_reasons", []))
    ]

    for item in explicit_related:
        folder = _project_folder(str(item.get("path") or ""))
        if folder:
            return {
                "folder": folder,
                "note_type": "project-note",
                "suggested_path": f"{folder}/{_safe_note_name(title)}",
                "reason": "Source frontmatter explicitly links to an existing project memory area.",
                "destination_confidence": _destination_confidence(
                    winning_signal=f"explicit related project link: {item.get('path')}",
                    primary_folder=folder,
                    alternatives=[],
                ),
            }

    explicit_candidates: list[tuple[dict[str, Any], str]] = []
    explicit_alternatives: list[dict[str, str]] = []
    for item in explicit_related:
        folder, skipped_reason = _specific_related_folder(config, item)
        if folder:
            explicit_candidates.append((item, folder))
        if skipped_reason:
            explicit_alternatives.append({
                "path": str(item.get("path") or ""),
                "reason": skipped_reason,
            })
    if explicit_candidates:
        item, folder = explicit_candidates[0]
        alternatives = [
            {
                "path": str(alternate_item.get("path") or ""),
                "folder": alternate_folder,
                "reason": "explicit related note also points to a safe destination folder",
            }
            for alternate_item, alternate_folder in explicit_candidates[1:]
            if alternate_folder != folder
        ]
        return {
            "folder": folder,
            "note_type": _note_type_for_folder(folder),
            "suggested_path": f"{folder}/{_safe_note_name(title)}",
            "reason": f"Source frontmatter explicitly links to `{item.get('role')}` context in `{folder}`.",
            "destination_confidence": _destination_confidence(
                winning_signal=f"explicit related note: {item.get('path')}",
                primary_folder=folder,
                alternatives=[*alternatives, *explicit_alternatives],
            ),
        }

    if related:
        folder = _project_folder(str(related[0].get("path") or ""))
        if folder:
            return {
                "folder": folder,
                "note_type": "project-note",
                "suggested_path": f"{folder}/{_safe_note_name(title)}",
                "reason": "Top related context points to an existing project memory area.",
                "destination_confidence": _destination_confidence(
                    winning_signal=f"top related project note: {related[0].get('path')}",
                    primary_folder=folder,
                    alternatives=[],
                ),
            }

    for item in related:
        role = item.get("role")
        folder = _role_folder(role)
        if folder:
            return {
                "folder": folder,
                "note_type": _note_type_for_folder(folder),
                "suggested_path": f"{folder}/{_safe_note_name(title)}",
                "reason": f"Top related context carries the `{role}` role.",
                "destination_confidence": _destination_confidence(
                    winning_signal=f"top related role: {role}",
                    primary_folder=folder,
                    alternatives=[],
                ),
            }

    folder = destinations[0]["folder"] if destinations else "03_Research"
    return {
        "folder": folder,
        "note_type": _note_type_for_folder(folder),
        "suggested_path": f"{folder}/{_safe_note_name(title)}",
        "reason": "Fallback destination from ingest destination policy.",
        "destination_confidence": _destination_confidence(
            winning_signal="fallback destination policy",
            primary_folder=folder,
            alternatives=[],
        ),
    }


def _related_note_reasons(related: list[dict[str, Any]]) -> list[dict[str, str]]:
    notes = []
    for item in related[:10]:
        raw_reasons = item.get("score_reasons") or []
        if any("source-related" in reason for reason in raw_reasons):
            reason = "Explicitly linked from the source frontmatter."
        elif item.get("role") == "project_memory":
            reason = "Project memory that can anchor the canonical note."
        elif item.get("role") == "domain_synthesis":
            reason = "Domain synthesis context related to the source."
        elif item.get("role") == "research_artifacts":
            reason = "Research context related to the source."
        elif any("source metadata" in reason for reason in raw_reasons):
            reason = "Shares metadata terms with the source."
        else:
            reason = "Ranked by source query overlap."
        notes.append({
            "title": str(item.get("title") or Path(str(item.get("path") or "")).stem),
            "path": str(item.get("path") or ""),
            "why_it_matters": reason,
        })
    return notes


def _is_redundant_alternate(primary_folder: str, alternate_folder: str) -> bool:
    return (
        alternate_folder == primary_folder
        or primary_folder.startswith(f"{alternate_folder}/")
        or alternate_folder.startswith(f"{primary_folder}/")
    )


def _canonical_note_outline(excerpt: str) -> list[str]:
    outline = ["Source-Grounded Summary"]
    if len(tokenize_list(excerpt)) >= 8:
        outline.extend(["Direct Source Claims", "Agent Interpretation / Implications"])
    outline.extend(["Recommended Action", "Related Notes", "Sources"])
    return outline


def _build_file_back_package(
    *,
    config: Config,
    rel: str,
    title: str,
    body: str,
    excerpt: str,
    source_metadata: dict[str, list[str]],
    related: list[dict[str, Any]],
    destinations: list[dict[str, Any]],
) -> dict[str, Any]:
    primary = _infer_primary_destination(config=config, title=title, related=related, destinations=destinations)
    related_notes = _related_note_reasons(related)
    urls = _source_urls(body)
    outline = _canonical_note_outline(excerpt)
    has_claims_vs_interpretation_outline = (
        "Direct Source Claims" in outline
        and "Agent Interpretation / Implications" in outline
    )
    quality_checks = {
        "has_primary_destination": bool(primary.get("folder")),
        "has_suggested_path": bool(primary.get("suggested_path")),
        "has_source_excerpt": bool(excerpt.strip()),
        "has_related_notes": bool(related_notes),
        "has_claims_vs_interpretation_outline": has_claims_vs_interpretation_outline,
    }
    primary_folder = str(primary.get("folder") or "")
    return {
        "source": rel,
        "title": title,
        "source_metadata": source_metadata,
        "compounding_action": "create_canonical_note",
        "primary_destination": primary,
        "alternate_destinations": [
            dest
            for dest in destinations
            if not _is_redundant_alternate(primary_folder, str(dest.get("folder") or ""))
        ],
        "source_urls": urls,
        "source_excerpt": excerpt,
        "related_notes": related_notes,
        "canonical_note_outline": outline,
        "quality_checks": quality_checks,
        "ready_for_agent_draft": all(quality_checks.values()),
        "writer_instruction": (
            "Use this package to draft a canonical vault note. Keep direct source claims separate from "
            "agent interpretation, preserve source citations, and return a reviewed apply plan before mutation."
        ),
    }


def ingest(config: Config, source: str | None = None, limit: int = 10):
    run_dir = create_run_dir(config.state_dir, "ingest")
    sources = [source] if source else _source_candidates(config)
    plans: list[dict[str, Any]] = []
    for source_value in sources:
        path = resolve_vault_path(source_value, config.vault_root)
        rel = vault_relative(path, config.vault_root)
        if not config.is_included(rel):
            raise PermissionError(f"Source is excluded or not included by policy: {rel}")
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        title = derive_title(path.stem, fm.data, fm.body)
        source_metadata = _source_metadata(fm.data)
        terms = _frequent_terms(fm.body)
        metadata_terms = _metadata_terms({**fm.data, "title": title})
        explicit_targets = _explicit_related_targets(fm.data)
        query_text = " ".join([title, *metadata_terms, *terms, *explicit_targets])
        candidates = rank_notes(config, query_text, limit=max(limit * 6, 50))
        related = _rerank_for_ingest(
            candidates,
            source_rel=rel,
            metadata_terms=metadata_terms,
            explicit_targets=explicit_targets,
            preferred_roles=set(DESTINATION_ROLES),
        )[:limit]
        destinations = []
        for role, folder in DESTINATION_ROLES.items():
            if any(item.get("role") == role for item in related) or role in {"research_artifacts", "domain_synthesis"}:
                destinations.append({"folder": folder, "reason": f"candidate {role} surface"})
        wikilinks = [{"title": item["title"], "path": item["path"], "reason": "; ".join(item["score_reasons"])} for item in related[:limit]]
        excerpt = safe_excerpt(fm.body, max_chars=1000)
        file_back = _build_file_back_package(
            config=config,
            rel=rel,
            title=title,
            body=fm.body,
            excerpt=excerpt,
            source_metadata=source_metadata,
            related=related,
            destinations=destinations[:4],
        )
        plan = {
            "source": rel,
            "title": title,
            "kind": "transcript" if "transcript" in path.name.lower() or "youtube" in fm.body.lower() else "text",
            "terms": terms,
            "proposed_destinations": destinations[:4],
            "suggested_wikilinks": wikilinks,
            "excerpt": excerpt,
            "file_back": file_back,
            "recommended_next_action": "Agent should review context, choose destination, and draft canonical note or patch bundle.",
        }
        _write_draft(run_dir, rel, title, plan["excerpt"], wikilinks, file_back)
        plans.append(plan)
    write_json(run_dir / "ingest.plan.json", {"sources": plans})
    _write_file_back_brief(run_dir, plans)
    _write_report(run_dir, plans)
    return run_dir


def _write_draft(run_dir: Path, rel: str, title: str, excerpt: str, wikilinks: list[dict[str, Any]], file_back: dict[str, Any]) -> None:
    draft_dir = run_dir / "drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_name = Path(rel).stem.replace(" ", "-") + "-draft.md"
    primary = file_back["primary_destination"]
    draft = [
        "---",
        f"title: {_yaml_scalar(title)}",
        f"type: {primary['note_type']}",
        "status: draft",
        f"source: {_yaml_scalar(rel)}",
        "---",
        "",
        f"# {title}",
        "",
        "## File-Back Target",
        "",
        f"- Suggested path: `{primary['suggested_path']}`",
        f"- Destination reason: {primary['reason']}",
        f"- Compounding action: {file_back['compounding_action']}",
        "",
        "## Source-Grounded Summary",
        "",
        "<Draft a concise synthesis grounded in the source excerpt and citations.>",
        "",
        "## Direct Source Claims",
        "",
        "<List claims directly supported by the source.>",
        "",
        "## Agent Interpretation / Implications",
        "",
        "<Separate interpretation, implications, and recommended strategy from direct claims.>",
        "",
        "## Recommended Action",
        "",
        "<State the practical next action this note should support.>",
        "",
        "## Source Excerpt",
        "",
        excerpt,
        "",
        "## Suggested Wikilinks",
        "",
    ]
    draft.extend(f"- [[{link['path']}|{link['title']}]]" for link in wikilinks[:10])
    draft.extend(["", "## Sources", ""])
    if file_back["source_urls"]:
        draft.extend(f"- {url}" for url in file_back["source_urls"])
    draft.append(f"- `{rel}`")
    (draft_dir / draft_name).write_text("\n".join(draft) + "\n", encoding="utf-8")


def _write_file_back_brief(run_dir: Path, plans: list[dict[str, Any]]) -> None:
    packages = [plan["file_back"] for plan in plans]
    write_json(run_dir / "file-back.brief.json", {"sources": packages})

    lines = ["# File-Back Brief", "", f"Sources packaged: {len(packages)}", ""]
    for package in packages:
        primary = package["primary_destination"]
        lines.extend([
            f"## {package['title']}",
            "",
            f"- Source: `{package['source']}`",
            f"- Compounding action: {package['compounding_action']}",
            f"- Primary destination: `{primary['folder']}`",
            f"- Suggested path: `{primary['suggested_path']}`",
            f"- Note type: {primary['note_type']}",
            f"- Ready for agent draft: {package['ready_for_agent_draft']}",
            f"- Destination reason: {primary['reason']}",
            "",
            "### Quality Checks",
        ])
        lines.extend(f"- {name}: {value}" for name, value in package["quality_checks"].items())
        lines.extend(["", "### Related Notes"])
        lines.extend(
            f"- [[{note['path']}|{note['title']}]] - {note['why_it_matters']}"
            for note in package["related_notes"][:10]
        )
        lines.extend(["", "### Source URLs"])
        if package["source_urls"]:
            lines.extend(f"- {url}" for url in package["source_urls"])
        else:
            lines.append("- None detected")
        lines.extend(["", "### Canonical Note Outline"])
        lines.extend(f"- {section}" for section in package["canonical_note_outline"])
        lines.extend(["", "### Source Excerpt", "", package["source_excerpt"], ""])
    (run_dir / "file-back.brief.md").write_text("\n".join(lines), encoding="utf-8")


def _write_report(run_dir: Path, plans: list[dict[str, Any]]) -> None:
    lines = ["# Ingest Report", "", f"Sources triaged: {len(plans)}", ""]
    for plan in plans:
        primary = plan["file_back"]["primary_destination"]
        lines.extend([
            f"## {plan['title']}",
            "",
            f"- Source: `{plan['source']}`",
            f"- Kind: {plan['kind']}",
            f"- Frequent terms: {', '.join(plan['terms'][:15])}",
            f"- File-back suggested path: `{primary['suggested_path']}`",
            f"- File-back ready: {plan['file_back']['ready_for_agent_draft']}",
            "",
            "### Proposed Destinations",
        ])
        lines.extend(f"- `{dest['folder']}` - {dest['reason']}" for dest in plan["proposed_destinations"])
        lines.extend(["", "### Suggested Wikilinks"])
        lines.extend(f"- [[{link['path']}|{link['title']}]] - {link['reason']}" for link in plan["suggested_wikilinks"][:10])
        lines.extend(["", "### Next Action", "", plan["recommended_next_action"], ""])
    (run_dir / "ingest.report.md").write_text("\n".join(lines), encoding="utf-8")
