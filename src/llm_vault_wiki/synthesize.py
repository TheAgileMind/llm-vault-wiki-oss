from __future__ import annotations

from collections import Counter
from typing import Any

from .config import Config
from .query import query_terms, rank_notes
from .storage import create_run_dir, write_json


def _risk_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in results:
        counts[str(item.get("risk") or "unknown")] += 1
    return dict(sorted(counts.items()))


def _gap_signals(config: Config, question: str, results: list[dict[str, Any]]) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    if not results:
        return [{
            "type": "no_context",
            "message": "No indexed notes ranked for this question. Run scan or capture/source better notes before synthesizing.",
        }]

    if len(results) < 3:
        signals.append({
            "type": "thin_context",
            "message": f"Only {len(results)} note(s) ranked. Treat synthesis as preliminary.",
        })

    top_prefixes = {str(item.get("path", "")).split("/", 1)[0] for item in results[:5]}
    if len(top_prefixes) <= 1:
        signals.append({
            "type": "low_source_diversity",
            "message": "Top context comes from one vault area. Check whether another project/domain note should be included.",
        })

    no_backlinks = [item["path"] for item in results[:5] if not item.get("backlinks")]
    if no_backlinks:
        signals.append({
            "type": "weak_backlinks",
            "message": f"{len(no_backlinks)} top note(s) have no backlinks. Related context may be under-connected.",
        })

    high_risk = [item["path"] for item in results[:5] if item.get("risk") == "high"]
    if high_risk:
        signals.append({
            "type": "high_risk_context",
            "message": "Top context includes high-risk vault areas. Do not write back without reviewed apply plans.",
        })

    matched_terms = set()
    for item in results[:10]:
        for reason in item.get("score_reasons", []):
            if ":" not in reason:
                continue
            _, terms = reason.split(":", 1)
            matched_terms.update(term.strip() for term in terms.split(",") if term.strip())
    question_terms = query_terms(question, config.search_policy.phrase_terms)
    unmatched_terms = sorted(question_terms - matched_terms)
    if unmatched_terms:
        signals.append({
            "type": "unmatched_query_terms",
            "message": "Some query terms did not appear in score reasons: " + ", ".join(unmatched_terms[:8]),
        })

    return signals


def run_synthesize(config: Config, question: str, limit: int = 10) -> dict[str, Any]:
    run_dir = create_run_dir(config.state_dir, "synthesis")
    results = rank_notes(config, question, limit=limit)
    gaps = _gap_signals(config, question, results)
    summary = {
        "question": question,
        "run_dir": str(run_dir),
        "json_report": str(run_dir / "synthesis.brief.json"),
        "markdown_report": str(run_dir / "synthesis.brief.md"),
        "prompt": str(run_dir / "synthesis.prompt.md"),
        "result_count": len(results),
        "gap_count": len(gaps),
        "risk_counts": _risk_counts(results),
        "read_only": True,
    }
    payload = {
        "summary": summary,
        "gap_signals": gaps,
        "results": [
            {
                "rank": index,
                "path": item["path"],
                "title": item.get("title"),
                "score": item.get("score"),
                "risk": item.get("risk"),
                "score_reasons": item.get("score_reasons", []),
                "links": item.get("links", [])[:20],
                "backlinks": item.get("backlinks", [])[:20],
                "excerpt": item.get("excerpt", ""),
            }
            for index, item in enumerate(results, start=1)
        ],
    }
    write_json(run_dir / "synthesis.brief.json", payload)
    _write_markdown(run_dir / "synthesis.brief.md", payload)
    _write_prompt(run_dir / "synthesis.prompt.md", payload)
    return summary


def _write_markdown(path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# Synthesis Brief",
        "",
        f"Question: {summary['question']}",
        "",
        "Status: read-only synthesis package. No vault files were changed.",
        "",
        "## Gap Signals",
        "",
    ]
    if payload["gap_signals"]:
        for signal in payload["gap_signals"]:
            lines.append(f"- **{signal['type']}**: {signal['message']}")
    else:
        lines.append("- No deterministic gap signals found.")

    lines.extend(["", "## Candidate Notes", ""])
    for item in payload["results"]:
        lines.extend([
            f"### {item['rank']}. {item['title']}",
            "",
            f"- Path: `{item['path']}`",
            f"- Score: {item['score']}",
            f"- Risk: {item['risk']}",
            f"- Reasons: {'; '.join(item['score_reasons']) or 'None'}",
            f"- Links: {', '.join(item['links']) or 'None'}",
            f"- Backlinks: {', '.join(item['backlinks']) or 'None'}",
            "",
            "#### Excerpt",
            "",
            item.get("excerpt", ""),
            "",
        ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_prompt(path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# Agent Synthesis Prompt",
        "",
        "Use `synthesis.brief.md` to answer the question.",
        "",
        "Rules:",
        "",
        "- Cite vault note paths for factual claims.",
        "- Separate source-backed claims from interpretation.",
        "- Include a `What the vault does not know yet` section using the gap signals.",
        "- Do not write, move, archive, or edit vault notes from this prompt.",
        "",
        f"Question: {summary['question']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
