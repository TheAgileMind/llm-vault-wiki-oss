from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .config import Config
from .query import load_inventory, rank_notes
from .storage import create_run_dir, write_json


@dataclass(frozen=True)
class RelevancePattern:
    label: str
    pattern: re.Pattern[str]


def _compile_relevance_patterns(raw_patterns: list[str]) -> list[RelevancePattern]:
    compiled = []
    for index, raw in enumerate(raw_patterns, start=1):
        if "=" in raw:
            label, pattern = raw.split("=", 1)
            label = label.strip() or f"pattern_{index}"
        else:
            label, pattern = f"pattern_{index}", raw
        compiled.append(RelevancePattern(label=label, pattern=re.compile(pattern, re.IGNORECASE)))
    return compiled


def _matching_labels(text: str, patterns: list[RelevancePattern]) -> list[str]:
    return [entry.label for entry in patterns if entry.pattern.search(text)]


def _precision(relevant_count: int, total_count: int) -> float:
    return round(relevant_count / total_count, 3) if total_count else 0.0


def _recall(relevant_count: int, corpus_relevant_count: int) -> float:
    return round(relevant_count / corpus_relevant_count, 3) if corpus_relevant_count else 0.0


def evaluate_search(
    config: Config,
    *,
    query: str,
    relevance_patterns: list[str],
    limit: int = 10000,
    precision_points: list[int] | None = None,
    fail_on_misses: bool = False,
    profile_name: str | None = None,
    min_precision_at: dict[int, float] | None = None,
) -> dict[str, Any]:
    if not relevance_patterns:
        raise ValueError("At least one relevance pattern is required.")
    points = sorted(set(precision_points or [10, 25, 50, 100]))
    precision_gates = min_precision_at or {}
    points = sorted(set([*points, *precision_gates.keys()]))
    patterns = _compile_relevance_patterns(relevance_patterns)
    inventory = load_inventory(config)
    files = inventory.get("files", [])

    relevance_by_path: dict[str, list[str]] = {}
    stale_manifest_files = []
    for item in files:
        path = item["path"]
        file_path = config.vault_root / path
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            stale_manifest_files.append({"path": path, "reason": "missing_from_vault"})
            continue
        labels = _matching_labels(text, patterns)
        if labels:
            relevance_by_path[path] = labels

    stale_paths = {item["path"] for item in stale_manifest_files}
    ranked = [item for item in rank_notes(config, query, limit=limit) if item["path"] not in stale_paths]
    ranked_paths = {item["path"] for item in ranked}
    relevant_paths = set(relevance_by_path)
    missed_paths = sorted(relevant_paths - ranked_paths)
    noise_results = [item for item in ranked if item["path"] not in relevant_paths]

    ranked_results = []
    for rank, item in enumerate(ranked, start=1):
        path = item["path"]
        ranked_results.append({
            "rank": rank,
            "path": path,
            "title": item.get("title"),
            "score": item.get("score"),
            "relevant": path in relevant_paths,
            "matching_patterns": relevance_by_path.get(path, []),
            "score_reasons": item.get("score_reasons", []),
        })

    precision_at = {}
    recall_at = {}
    for point in points:
        sample = ranked_results[:point]
        relevant_count = sum(1 for item in sample if item["relevant"])
        precision_at[str(point)] = _precision(relevant_count, len(sample))
        recall_at[str(point)] = _recall(relevant_count, len(relevant_paths))

    quality_gate_violations = []
    for point, minimum in sorted(precision_gates.items()):
        actual = precision_at[str(point)]
        if actual < minimum:
            quality_gate_violations.append({
                "gate": "min_precision_at",
                "point": point,
                "minimum": minimum,
                "actual": actual,
            })

    summary = {
        "ok": not ((fail_on_misses and missed_paths) or quality_gate_violations),
        "profile": profile_name,
        "query": query,
        "indexed_files": len(files),
        "evaluated_files": len(files) - len(stale_manifest_files),
        "stale_manifest_files": len(stale_manifest_files),
        "limit": limit,
        "relevance_patterns": relevance_patterns,
        "quality_gates": {
            "fail_on_misses": fail_on_misses,
            "min_precision_at": {str(point): value for point, value in sorted(precision_gates.items())},
        },
        "quality_gate_violations": quality_gate_violations,
        "corpus_relevant_files": len(relevant_paths),
        "ranked_files": len(ranked_results),
        "relevant_ranked_files": sum(1 for item in ranked_results if item["relevant"]),
        "noise_ranked_files": len(noise_results),
        "missed_relevant_files": len(missed_paths),
        "overall_precision": _precision(sum(1 for item in ranked_results if item["relevant"]), len(ranked_results)),
        "overall_recall": _recall(sum(1 for item in ranked_results if item["relevant"]), len(relevant_paths)),
        "precision_at": precision_at,
        "recall_at": recall_at,
    }

    run_dir = create_run_dir(config.state_dir, "search-evaluation")
    payload = {
        "summary": summary,
        "stale_manifest_files": stale_manifest_files,
        "missed": [{"path": path, "matching_patterns": relevance_by_path[path]} for path in missed_paths],
        "noise_examples": [
            {
                "path": item["path"],
                "title": item.get("title"),
                "score": item.get("score"),
                "score_reasons": item.get("score_reasons", []),
            }
            for item in noise_results[:50]
        ],
        "ranked_results": ranked_results,
    }
    write_json(run_dir / "search-evaluation.json", payload)
    _write_markdown_report(run_dir / "search-evaluation.md", payload)
    return {"run_dir": str(run_dir), **summary}


def _write_markdown_report(path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# Search Evaluation",
        "",
    ]
    if summary.get("profile"):
        lines.extend([f"Profile: `{summary['profile']}`", ""])
    lines.extend([
        f"Query: `{summary['query']}`",
        "",
        "## Summary",
        "",
        f"- Indexed files: {summary['indexed_files']}",
        f"- Evaluated files: {summary['evaluated_files']}",
        f"- Stale manifest files: {summary['stale_manifest_files']}",
        f"- Corpus relevant files: {summary['corpus_relevant_files']}",
        f"- Ranked files: {summary['ranked_files']}",
        f"- Relevant ranked files: {summary['relevant_ranked_files']}",
        f"- Noise ranked files: {summary['noise_ranked_files']}",
        f"- Missed relevant files: {summary['missed_relevant_files']}",
        f"- Overall precision: {summary['overall_precision']}",
        f"- Overall recall: {summary['overall_recall']}",
        "",
        "## Precision And Recall",
        "",
        "| K | Precision | Recall |",
        "|---:|---:|---:|",
    ])
    for point, precision in summary["precision_at"].items():
        lines.append(f"| {point} | {precision} | {summary['recall_at'][point]} |")

    gates = summary.get("quality_gates", {})
    violations = summary.get("quality_gate_violations", [])
    if gates.get("fail_on_misses") or gates.get("min_precision_at"):
        lines.extend(["", "## Quality Gates", ""])
        lines.append(f"- Fail on misses: {gates.get('fail_on_misses', False)}")
        for point, minimum in gates.get("min_precision_at", {}).items():
            lines.append(f"- Precision@{point} >= {minimum}")
        if violations:
            lines.extend(["", "### Violations", ""])
            for violation in violations:
                lines.append(
                    f"- {violation['gate']}@{violation['point']}: "
                    f"actual {violation['actual']} < minimum {violation['minimum']}"
                )

    if payload["stale_manifest_files"]:
        lines.extend(["", "## Stale Manifest Files", ""])
        for item in payload["stale_manifest_files"][:100]:
            lines.append(f"- `{item['path']}` ({item['reason']})")

    if payload["missed"]:
        lines.extend(["", "## Missed Relevant Files", ""])
        for item in payload["missed"][:100]:
            lines.append(f"- `{item['path']}` ({', '.join(item['matching_patterns'])})")

    if payload["noise_examples"]:
        lines.extend(["", "## Noise Examples", ""])
        for item in payload["noise_examples"][:25]:
            lines.append(f"- `{item['path']}` score={item['score']} reasons={'; '.join(item['score_reasons'])}")

    lines.extend(["", "## Top Results", ""])
    for item in payload["ranked_results"][:50]:
        labels = ", ".join(item["matching_patterns"]) if item["matching_patterns"] else "not relevant"
        lines.append(f"- {item['rank']}. `{item['path']}` score={item['score']} relevance={labels}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
