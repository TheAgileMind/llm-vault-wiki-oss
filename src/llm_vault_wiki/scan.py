from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import Config
from .frontmatter import derive_title, parse_frontmatter
from .links import extract_wikilinks
from .manifests import TEXT_EXTENSIONS, extract_phrase_counts, extract_term_counts, hash_file, safe_excerpt
from .paths import vault_relative
from .storage import ensure_state_dirs, read_json, write_json


def _iter_files(config: Config) -> list[Path]:
    files: list[Path] = []
    for folder in config.folders:
        if folder.include not in (True, "partial"):
            continue
        root = config.vault_root / folder.prefix
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS:
                rel = vault_relative(path, config.vault_root)
                if config.is_included(rel):
                    files.append(path)
    return sorted(files)


def scan_vault(config: Config) -> dict[str, Any]:
    ensure_state_dirs(config.state_dir)
    previous_path = config.state_dir / "manifests" / "vault.inventory.json"
    previous_hashes = {}
    if previous_path.exists():
        previous_hashes = {item["path"]: item.get("hash") for item in read_json(previous_path).get("files", [])}

    files = []
    frontmatter = {}
    policy_manifest = {}
    link_edges = []
    warnings = []

    for path in _iter_files(config):
        rel = vault_relative(path, config.vault_root)
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        if fm.error:
            warnings.append({"path": rel, "warning": fm.error})
        policy = config.classify(rel)
        stat = path.stat()
        links = extract_wikilinks(text)
        title = derive_title(path.stem, fm.data, fm.body)
        record = {
            "path": rel,
            "title": title,
            "hash": hash_file(path),
            "modified_time": stat.st_mtime,
            "size": stat.st_size,
            "extension": path.suffix.lower(),
            "type": fm.data.get("type"),
            "status": fm.data.get("status"),
            "domains": fm.data.get("domains", []) or [],
            "thesis_areas": fm.data.get("thesis_areas", []) or [],
            "tags": fm.data.get("tags", []) or [],
            "risk": policy.risk if policy else "unclassified",
            "role": policy.role if policy else "unclassified",
            "allowed_ops": list(policy.allowed_ops) if policy else [],
            "review_required_for": list(policy.review_required_for) if policy else [],
            "links": links,
            "excerpt": safe_excerpt(fm.body),
            "term_counts": extract_term_counts(fm.body),
            "phrase_counts": extract_phrase_counts(fm.body, config.search_policy.phrase_terms),
        }
        files.append(record)
        frontmatter[rel] = fm.data
        policy_manifest[rel] = {
            "role": record["role"],
            "risk": record["risk"],
            "allowed_ops": list(policy.allowed_ops) if policy else [],
            "review_required_for": list(policy.review_required_for) if policy else [],
        }
        for target in links:
            link_edges.append({"source": rel, "target": target})

    backlinks: dict[str, list[str]] = defaultdict(list)
    known_by_stem = {Path(item["path"]).stem: item["path"] for item in files}
    known_by_title = {item["title"]: item["path"] for item in files}
    for edge in link_edges:
        target = known_by_title.get(edge["target"]) or known_by_stem.get(Path(edge["target"]).stem) or edge["target"]
        backlinks[target].append(edge["source"])
    for item in files:
        item["backlinks"] = sorted(backlinks.get(item["path"], []))

    current_hashes = {item["path"]: item["hash"] for item in files}
    changes = {
        "new": sorted(path for path in current_hashes if path not in previous_hashes),
        "modified": sorted(path for path, digest in current_hashes.items() if path in previous_hashes and previous_hashes[path] != digest),
        "deleted": sorted(path for path in previous_hashes if path not in current_hashes),
    }

    inventory = {"vault_root": str(config.vault_root), "file_count": len(files), "files": files, "warnings": warnings}
    links = {"links": link_edges, "backlinks": dict(sorted(backlinks.items()))}

    manifest_dir = config.state_dir / "manifests"
    write_json(manifest_dir / "vault.inventory.json", inventory)
    write_json(manifest_dir / "vault.frontmatter.json", frontmatter)
    write_json(manifest_dir / "vault.policy.json", policy_manifest)
    write_json(manifest_dir / "vault.links.json", links)
    write_json(manifest_dir / "vault.changes.json", changes)
    index_path = write_index(config, files, changes)
    return {"inventory": inventory, "changes": changes, "index_path": str(index_path)}


def write_index(config: Config, files: list[dict[str, Any]], changes: dict[str, Any]) -> Path:
    lines = ["# Vault Index", "", f"Files indexed: {len(files)}", "", "## Recent Changes", ""]
    for key in ("new", "modified", "deleted"):
        lines.append(f"- {key}: {len(changes.get(key, []))}")
    by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in files:
        by_role[item.get("role") or "unclassified"].append(item)
    lines.extend(["", "## Notes By Role"])
    for role in sorted(by_role):
        lines.extend(["", f"### {role}"])
        for item in sorted(by_role[role], key=lambda r: r["path"]):
            details = []
            if item.get("type"):
                details.append(f"type={item['type']}")
            if item.get("status"):
                details.append(f"status={item['status']}")
            detail = ", ".join(details) or item["risk"]
            lines.append(f"- [[{item['path']}|{item['title']}]] ({detail})")
    output = config.state_dir / "generated" / "vault-index.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
