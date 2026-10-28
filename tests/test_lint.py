from llm_vault_wiki.lint import lint_vault
from llm_vault_wiki.scan import scan_vault


def test_lint_passes_clean_fixture_and_writes_reports(sample_project):
    scan_vault(sample_project.config)

    result = lint_vault(sample_project.config)

    assert result["ok"]
    assert not result["errors"]
    assert (sample_project.config.state_dir / "generated" / "lint.report.md").exists()


def test_lint_fails_before_scan(sample_project):
    result = lint_vault(sample_project.config)

    assert not result["ok"]
    assert result["errors"][0]["code"] == "missing_manifest"
