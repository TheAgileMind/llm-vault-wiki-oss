import json
from pathlib import Path

import pytest

from llm_vault_wiki.scan import scan_vault
from llm_vault_wiki.synthesize import run_synthesize


def _vault_snapshot(vault: Path) -> dict[str, str]:
    return {
        str(path.relative_to(vault).as_posix()): path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(vault.rglob("*.md"))
    }


def test_synthesize_writes_read_only_brief_with_gap_signals(sample_project):
    scan_vault(sample_project.config)
    before = _vault_snapshot(sample_project.vault)

    result = run_synthesize(sample_project.config, "HarborOps AI agents", limit=3)

    assert result["read_only"] is True
    assert result["result_count"] >= 1
    assert result["gap_count"] >= 1
    assert Path(result["json_report"]).exists()
    assert Path(result["markdown_report"]).exists()
    assert Path(result["prompt"]).exists()
    assert _vault_snapshot(sample_project.vault) == before

    payload = json.loads(Path(result["json_report"]).read_text(encoding="utf-8"))
    assert payload["summary"]["question"] == "HarborOps AI agents"
    assert "01_Projects/HarborOps.md" in {item["path"] for item in payload["results"]}
    markdown = Path(result["markdown_report"]).read_text(encoding="utf-8")
    assert "## Gap Signals" in markdown
    assert "## Candidate Notes" in markdown
    assert "01_Projects/HarborOps.md" in markdown
    prompt = Path(result["prompt"]).read_text(encoding="utf-8")
    assert "Do not write, move, archive, or edit vault notes" in prompt


def test_synthesize_reports_no_context_without_crashing(sample_project):
    scan_vault(sample_project.config)

    result = run_synthesize(sample_project.config, "zzzz unmatched term", limit=3)

    assert result["result_count"] == 0
    payload = json.loads(Path(result["json_report"]).read_text(encoding="utf-8"))
    assert payload["gap_signals"][0]["type"] == "no_context"


def test_synthesize_requires_scan_manifest(sample_project):
    with pytest.raises(FileNotFoundError, match="Run `scan` first"):
        run_synthesize(sample_project.config, "HarborOps")
