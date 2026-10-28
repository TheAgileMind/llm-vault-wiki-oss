from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class FrontmatterResult:
    data: dict[str, Any]
    body: str
    error: str | None = None


def parse_frontmatter(text: str) -> FrontmatterResult:
    if not text.startswith("---"):
        return FrontmatterResult({}, text)
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return FrontmatterResult({}, text)
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return FrontmatterResult({}, text, "frontmatter start without closing delimiter")
    raw = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1:]).lstrip("\n")
    try:
        parsed = yaml.safe_load(raw) or {}
        if not isinstance(parsed, dict):
            return FrontmatterResult({}, body, "frontmatter is not a mapping")
        return FrontmatterResult(parsed, body)
    except Exception as exc:
        return FrontmatterResult({}, body, f"frontmatter parse error: {exc}")


def derive_title(path_stem: str, frontmatter: dict[str, Any], body: str) -> str:
    title = frontmatter.get("title")
    if title:
        return str(title)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path_stem.replace("_", " ").replace("-", " ").strip().title()
