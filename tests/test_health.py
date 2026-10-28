from pathlib import Path

from llm_vault_wiki.health import run_health
from llm_vault_wiki.scan import scan_vault
from llm_vault_wiki.validate import validate_system


def _vault_snapshot(vault: Path) -> dict[str, str]:
    return {
        str(path.relative_to(vault).as_posix()): path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(vault.rglob("*.md"))
    }


def test_brain_health_reports_latest_validation_without_mutating_vault(sample_project):
    validate_system(sample_project.config)
    before = _vault_snapshot(sample_project.vault)

    result = run_health(sample_project.config)

    assert result["ok"] is True
    assert Path(result["json_report"]).exists()
    assert Path(result["markdown_report"]).exists()
    assert result["health"]["validation_available"] is True
    assert result["health"]["inventory_available"] is True
    assert "00_Inbox/YouTube Transcript.md" in result["health"]["source_candidates"]
    assert _vault_snapshot(sample_project.vault) == before

    markdown = Path(result["markdown_report"]).read_text(encoding="utf-8")
    assert "## Recommended Next Actions" in markdown
    assert "Source Candidates" in markdown


def test_brain_health_reports_stale_manifest_files(sample_project):
    scan_vault(sample_project.config)
    (sample_project.vault / "01_Projects" / "HarborOps.md").unlink()

    result = run_health(sample_project.config)

    assert result["ok"] is False
    assert result["health"]["stale_manifest_files"][0]["path"] == "01_Projects/HarborOps.md"
    assert "Rerun scan" in " ".join(result["recommended_next_actions"])


def test_brain_health_without_manifests_requests_scan(sample_project):
    result = run_health(sample_project.config)

    assert result["ok"] is False
    assert result["health"]["inventory_available"] is False
    assert "Run `scan`" in result["recommended_next_actions"][0]
