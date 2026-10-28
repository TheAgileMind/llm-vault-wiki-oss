from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any

from .config import Config
from .manifests import extract_phrase_counts, normalize_phrase_token
from .storage import create_run_dir, read_json, write_json

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]+", re.IGNORECASE)
QUERY_STOP_TERMS = {
    "a", "about", "all", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how",
    "i", "in", "is", "it", "know", "me", "of", "on", "or", "should", "tell", "that", "the", "this", "to", "what",
    "when", "where", "which", "who", "why", "with",
}


def tokenize(text: str) -> set[str]:
    return set(tokenize_list(text))


def tokenize_list(text: str) -> list[str]:
    terms: list[str] = []
    for match in TOKEN_RE.finditer(text or ""):
        term = match.group(0).lower()
        if len(term) < 2:
            continue
        terms.append(term)
        for part in re.split(r"[-_]", term):
            if len(part) >= 2 and part != term:
                terms.append(part)
    return terms


def load_inventory(config: Config) -> dict[str, Any]:
    path = config.state_dir / "manifests" / "vault.inventory.json"
    if not path.exists():
        raise FileNotFoundError("No scan manifest found. Run `scan` first.")
    return read_json(path)


def _metadata_text(item: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("domains", "thesis_areas", "tags"):
        raw = item.get(key) or []
        values.extend(str(v) for v in raw)
    for key in ("type", "status"):
        if item.get(key):
            values.append(str(item[key]))
    return " ".join(values)


def _terms_with_phrases(text: str, phrase_terms: tuple[str, ...]) -> set[str]:
    return tokenize(text) | set(extract_phrase_counts(text, phrase_terms))


def _query_terms(text: str, phrase_terms: tuple[str, ...]) -> set[str]:
    terms = tokenize(text)
    phrase_tokens = set(extract_phrase_counts(text, phrase_terms))
    for phrase in phrase_terms:
        phrase_parts = tokenize(phrase)
        phrase_token = normalize_phrase_token(phrase)
        if phrase_token in phrase_tokens:
            terms -= phrase_parts
    return terms | phrase_tokens


def query_terms(text: str, phrase_terms: tuple[str, ...]) -> set[str]:
    return _query_terms(text, phrase_terms)


def _search_terms_by_field(item: dict[str, Any], phrase_terms: tuple[str, ...]) -> dict[str, set[str]]:
    term_counts = item.get("term_counts") or {}
    phrase_counts = item.get("phrase_counts") or {}
    return {
        "title": _terms_with_phrases(item.get("title", ""), phrase_terms),
        "path": _terms_with_phrases(item.get("path", ""), phrase_terms),
        "metadata": _terms_with_phrases(_metadata_text(item), phrase_terms),
        "excerpt": _terms_with_phrases(item.get("excerpt", ""), phrase_terms),
        "links": _terms_with_phrases(" ".join(item.get("links", []) + item.get("backlinks", [])), phrase_terms),
        "full_text": set(term_counts) | set(phrase_counts),
    }


def _document_frequencies(files: list[dict[str, Any]], phrase_terms: tuple[str, ...]) -> Counter[str]:
    frequencies: Counter[str] = Counter()
    for item in files:
        document_terms: set[str] = set()
        for terms in _search_terms_by_field(item, phrase_terms).values():
            document_terms.update(terms)
        frequencies.update(document_terms)
    return frequencies


def _query_anchor_terms(query_terms: set[str], generic_terms: set[str], frequencies: Counter[str], total_documents: int) -> set[str]:
    if not total_documents:
        return set()
    return {
        term
        for term in query_terms
        if term not in generic_terms
        and frequencies.get(term, 0) > 0
        and (frequencies[term] <= 3 or frequencies[term] / total_documents <= 0.2)
    }


def _idf(term: str, frequencies: Counter[str], total_documents: int) -> float:
    return 1.0 + math.log((total_documents + 1) / (frequencies.get(term, 0) + 1))


def rank_notes(config: Config, question: str, limit: int = 10) -> list[dict[str, Any]]:
    inventory = load_inventory(config)
    files = inventory.get("files", [])
    phrase_terms = config.search_policy.phrase_terms
    generic_terms = QUERY_STOP_TERMS | set(config.search_policy.generic_anchor_terms)
    query_terms = _query_terms(question, phrase_terms) - QUERY_STOP_TERMS
    frequencies = _document_frequencies(files, phrase_terms)
    anchor_terms = _query_anchor_terms(query_terms, generic_terms, frequencies, len(files))
    ranked = []
    for item in files:
        term_counts = item.get("term_counts") or {}
        phrase_counts = item.get("phrase_counts") or {}
        haystacks = _search_terms_by_field(item, phrase_terms)
        if anchor_terms and not any(anchor_terms & terms for terms in haystacks.values()):
            continue
        score = 0.0
        reasons = []
        weights = {"title": 5, "path": 3, "metadata": 4, "excerpt": 1, "links": 2, "full_text": 1}
        for name, terms in haystacks.items():
            overlap = sorted(query_terms & terms)
            if overlap:
                if name == "full_text":
                    score += sum(
                        min(int(term_counts.get(term, phrase_counts.get(term, 1))), 3) * _idf(term, frequencies, len(files))
                        for term in overlap
                    ) * weights[name]
                else:
                    score += sum(_idf(term, frequencies, len(files)) for term in overlap) * weights[name]
                reasons.append(f"{name}: {', '.join(overlap[:5])}")
        if score:
            ranked.append({"score": round(score, 3), "score_reasons": reasons, **item})
    return sorted(ranked, key=lambda r: (-r["score"], r["path"]))[:limit]


def run_query(config: Config, question: str, limit: int = 10, prompt: bool = True):
    run_dir = create_run_dir(config.state_dir, "query")
    ranked = rank_notes(config, question, limit=limit)
    payload = {"question": question, "results": ranked}
    write_json(run_dir / "query.context.json", payload)
    lines = ["# Query Context", "", f"Question: {question}", "", f"Results: {len(ranked)}", ""]
    for index, item in enumerate(ranked, start=1):
        lines.extend([
            f"## {index}. {item['title']}",
            "",
            f"- Path: `{item['path']}`",
            f"- Score: {item['score']}",
            f"- Reasons: {'; '.join(item['score_reasons'])}",
            f"- Risk: {item.get('risk')}",
            f"- Links: {', '.join(item.get('links', [])[:10]) or 'None'}",
            f"- Backlinks: {', '.join(item.get('backlinks', [])[:10]) or 'None'}",
            "",
            "### Excerpt",
            "",
            item.get("excerpt", ""),
            "",
        ])
    (run_dir / "query.context.md").write_text("\n".join(lines), encoding="utf-8")
    if prompt:
        prompt_lines = [
            "# Agent Prompt",
            "",
            "Use the attached context pack to answer the question. Ground claims in the listed vault notes and open full files when needed.",
            "",
            f"Question: {question}",
            "",
            "Context pack: `query.context.md`",
        ]
        (run_dir / "query.prompt.md").write_text("\n".join(prompt_lines) + "\n", encoding="utf-8")
    return run_dir
