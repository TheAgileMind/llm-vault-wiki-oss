from __future__ import annotations

import hashlib
import re
from pathlib import Path

TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
TERM_RE = re.compile(r"[a-z0-9][a-z0-9_-]+", re.IGNORECASE)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_excerpt(text: str, max_chars: int = 700) -> str:
    cleaned = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rsplit(" ", 1)[0].strip() + "..."


def extract_term_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in TERM_RE.finditer(text or ""):
        term = match.group(0).lower()
        if len(term) < 2:
            continue
        counts[term] = counts.get(term, 0) + 1
        for part in re.split(r"[-_]", term):
            if len(part) >= 2 and part != term:
                counts[part] = counts.get(part, 0) + 1
    return dict(sorted(counts.items()))


def normalize_phrase_token(phrase: str) -> str:
    return "_".join(match.group(0).lower() for match in TERM_RE.finditer(phrase or ""))


def extract_phrase_counts(text: str, phrases: tuple[str, ...] | list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for phrase in phrases:
        parts = [match.group(0).lower() for match in TERM_RE.finditer(phrase or "")]
        if len(parts) < 2:
            continue
        token = "_".join(parts)
        pattern = re.compile(r"\b" + r"[-_\s]+".join(re.escape(part) for part in parts) + r"\b", re.IGNORECASE)
        matches = pattern.findall(text or "")
        if matches:
            counts[token] = len(matches)
    return dict(sorted(counts.items()))
