from pathlib import Path

import pytest

from llm_vault_wiki.evaluate import evaluate_search
from llm_vault_wiki.scan import scan_vault
from llm_vault_wiki.storage import read_json


def _write_raw(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_evaluate_search_writes_generic_precision_recall_report(sample_project):
    _write_raw(
        sample_project.vault / "03_Research" / "HarborOps Case Study.md",
        """---
title: HarborOps Case Study
type: intelligence-brief
status: active
domains: [business-strategy]
thesis_areas: []
related: []
tags: [harborops]
---

# HarborOps Case Study

HarborOps uses SMS operations and AI workflow support.
""",
    )
    scan_vault(sample_project.config)

    result = evaluate_search(
        sample_project.config,
        query="HarborOps SMS operations AI workflow",
        relevance_patterns=[r"harbor=\bHarborOps\b"],
        limit=20,
        precision_points=[1, 5, 10],
    )

    assert result["ok"] is True
    assert result["corpus_relevant_files"] >= 2
    assert result["missed_relevant_files"] == 0
    assert result["overall_recall"] == 1.0
    assert "1" in result["precision_at"]

    run_dir = Path(result["run_dir"])
    payload = read_json(run_dir / "search-evaluation.json")
    assert payload["summary"]["query"] == "HarborOps SMS operations AI workflow"
    assert (run_dir / "search-evaluation.md").exists()


def test_evaluate_search_can_fail_on_missed_relevant_files(sample_project):
    _write_raw(
        sample_project.vault / "03_Research" / "Unqueried Case Study.md",
        """---
title: Unqueried Case Study
type: intelligence-brief
status: active
domains: [business-strategy]
thesis_areas: []
related: []
tags: [case-study]
---

# Unqueried Case Study

NeedleOnly appears here, but the query will not search for it.
""",
    )
    scan_vault(sample_project.config)

    result = evaluate_search(
        sample_project.config,
        query="HarborOps SMS operations",
        relevance_patterns=[r"needle=NeedleOnly"],
        limit=20,
        fail_on_misses=True,
    )

    assert result["ok"] is False
    assert result["corpus_relevant_files"] == 1
    assert result["missed_relevant_files"] == 1


def test_evaluate_search_reports_stale_manifest_files_without_crashing(sample_project):
    stale_note = sample_project.vault / "03_Research" / "Deleted Circadian Brief.md"
    _write_raw(
        stale_note,
        """---
title: Deleted Circadian Brief
type: intelligence-brief
status: active
domains: [chronobiology]
thesis_areas: []
related: []
tags: [circadian]
---

# Deleted Circadian Brief

Circadian appears here, but the file will be deleted after scan.
""",
    )
    scan_vault(sample_project.config)
    stale_note.unlink()

    result = evaluate_search(
        sample_project.config,
        query="Circadian",
        relevance_patterns=[r"circadian=\bCircadian\b"],
        limit=20,
        fail_on_misses=True,
    )

    assert result["ok"] is True
    assert result["stale_manifest_files"] == 1
    assert result["evaluated_files"] == result["indexed_files"] - 1
    assert result["missed_relevant_files"] == 0

    run_dir = Path(result["run_dir"])
    payload = read_json(run_dir / "search-evaluation.json")
    assert payload["stale_manifest_files"] == [{"path": "03_Research/Deleted Circadian Brief.md", "reason": "missing_from_vault"}]
    report = (run_dir / "search-evaluation.md").read_text(encoding="utf-8")
    assert "## Stale Manifest Files" in report
    assert "03_Research/Deleted Circadian Brief.md" in report


def test_evaluate_search_reports_profile_and_precision_gate_failures(sample_project):
    scan_vault(sample_project.config)

    result = evaluate_search(
        sample_project.config,
        query="HarborOps SMS operations",
        relevance_patterns=[r"harbor=\bHarborOps\b"],
        limit=20,
        precision_points=[1],
        profile_name="harbor_profile",
        min_precision_at={1: 1.01},
    )

    assert result["ok"] is False
    assert result["profile"] == "harbor_profile"
    assert result["quality_gates"]["min_precision_at"] == {"1": 1.01}
    assert result["quality_gate_violations"] == [
        {"gate": "min_precision_at", "point": 1, "minimum": 1.01, "actual": result["precision_at"]["1"]}
    ]

    run_dir = Path(result["run_dir"])
    payload = read_json(run_dir / "search-evaluation.json")
    assert payload["summary"]["profile"] == "harbor_profile"
    report = (run_dir / "search-evaluation.md").read_text(encoding="utf-8")
    assert "Profile: `harbor_profile`" in report
    assert "## Quality Gates" in report


def test_source_workflow_profile_ignores_generic_workflow_plan_source_noise(sample_project):
    _write_raw(
        sample_project.vault / "03_Research" / "Generic Workflow Plan.md",
        """---
title: Generic Workflow Plan
type: intelligence-brief
status: active
domains: [product-dev]
thesis_areas: []
related: []
tags: [workflow]
---

# Generic Workflow Plan

This note discusses a source, workflow, plan, file, canonical note, archive, and validation process.
It is a generic operational planning note.
""",
    )
    _write_raw(
        sample_project.vault / "00_Inbox" / "Session Journals" / "Workflow Docs.md",
        """---
title: LLM Vault Wiki Workflow Docs
type: session-journal
status: active
domains: [coding-agents]
thesis_areas: []
related: []
tags: [llm-vault-wiki]
---

# LLM Vault Wiki Workflow Docs

The process-source command creates a file-back.brief and draft-apply-plan creates an apply-plan.skeleton.
""",
    )
    scan_vault(sample_project.config)

    result = evaluate_search(
        sample_project.config,
        query="llm-vault-wiki process-source file-back draft-apply-plan apply-plan skeleton quality_validation",
        relevance_patterns=[r"workflow_docs=process-source|draft-apply-plan|file-back\.brief|apply-plan\.skeleton|quality_validation|LLM Vault Wiki"],
        limit=100,
        precision_points=[10],
    )

    run_dir = Path(result["run_dir"])
    payload = read_json(run_dir / "search-evaluation.json")
    relevant_paths = {item["path"] for item in payload["ranked_results"] if item["relevant"]}
    assert "00_Inbox/Session Journals/Workflow Docs.md" in relevant_paths
    assert "03_Research/Generic Workflow Plan.md" not in relevant_paths


def test_source_capture_and_canonical_profiles_use_specific_file_back_anchors(sample_project):
    _write_raw(
        sample_project.vault / "00_Inbox" / "2026-05-17_Source_Example.md",
        """---
title: Source Capture - Example
type: voice-capture
status: seed
domains: [ai-ml]
thesis_areas: []
related: []
tags: [source]
---

# Source Capture - Example

Raw captured source for processing.
""",
    )
    _write_raw(
        sample_project.vault / "03_Research" / "Canonical File Back Note.md",
        """---
title: Canonical File Back Note
type: intelligence-brief
status: active
domains: [ai-ml]
thesis_areas: []
related: []
tags: [file-back, source]
source: 08_Archive/LLM_Vault_Wiki/00_Inbox_2026-05-17_Source_Example.md
source_capture: 00_Inbox/2026-05-17_Source_Example.md
---

# Canonical File Back Note

## Direct Source Claims

Source-grounded facts.

## Agent Interpretation

Agent interpretation stays separate.

## Recommended Action

Act on the source.
""",
    )
    _write_raw(
        sample_project.vault / "03_Research" / "Generic Source Note.md",
        """---
title: Generic Source Note
type: intelligence-brief
status: active
domains: [research]
thesis_areas: []
related: []
tags: [source]
---

# Generic Source Note

This mentions source capture, canonical note, source claims, and recommended action in generic prose.
""",
    )
    scan_vault(sample_project.config)

    capture_result = evaluate_search(
        sample_project.config,
        query="Source Capture ORBIT Training OpenAI Anthropic Order Coordination Archive Test",
        relevance_patterns=[
            r'source_capture_title=title:\s*"?Source Capture -|# Source Capture -',
        ],
        limit=100,
        precision_points=[10],
    )
    capture_payload = read_json(Path(capture_result["run_dir"]) / "search-evaluation.json")
    capture_relevant = {item["path"] for item in capture_payload["ranked_results"] if item["relevant"]}
    assert "00_Inbox/2026-05-17_Source_Example.md" in capture_relevant
    assert "03_Research/Generic Source Note.md" not in capture_relevant

    canonical_result = evaluate_search(
        sample_project.config,
        query="file-back source_capture direct source claims agent interpretation recommended action canonical note",
        relevance_patterns=[
            r"file_back_frontmatter=tags:\s*\[[^\]]*file-back|^\s*-\s*file-back\s*$",
            r"canonical_sections=source_capture:|## Direct Source Claims|## Agent Interpretation|## Recommended Action",
        ],
        limit=100,
        precision_points=[10],
    )
    canonical_payload = read_json(Path(canonical_result["run_dir"]) / "search-evaluation.json")
    canonical_relevant = {item["path"] for item in canonical_payload["ranked_results"] if item["relevant"]}
    assert "03_Research/Canonical File Back Note.md" in canonical_relevant
    assert "03_Research/Generic Source Note.md" not in canonical_relevant


def test_evaluate_search_requires_relevance_patterns(sample_project):
    scan_vault(sample_project.config)

    with pytest.raises(ValueError, match="relevance pattern"):
        evaluate_search(sample_project.config, query="anything", relevance_patterns=[])
