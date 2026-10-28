from pathlib import Path

from llm_vault_wiki.config import load_config
from llm_vault_wiki.validate import validate_system


def _vault_snapshot(vault: Path) -> dict[str, str]:
    return {
        str(path.relative_to(vault).as_posix()): path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(vault.rglob("*.md"))
    }


def test_validate_system_runs_scan_lint_and_profiles(sample_project):
    result = validate_system(sample_project.config)

    assert result["ok"] is True
    assert result["scan"]["file_count"] >= 7
    assert result["lint"]["ok"] is True
    assert result["stale_manifest"]["ok"] is True
    assert result["profiles"][0]["profile"] == "harbor_profile"
    assert result["profiles"][0]["ok"] is True
    assert result["durations"]["total_seconds"] >= 0
    assert result["trend"]["status"] == "baseline"
    assert result["brain_health"]["ok"] is True
    assert Path(result["brain_health"]["markdown_report"]).exists()
    assert Path(result["json_report"]).exists()
    assert Path(result["markdown_report"]).exists()
    assert Path(result["latest_report"]).exists()


def test_validate_system_can_run_selected_profiles(sample_project):
    result = validate_system(sample_project.config, profiles=["harbor_profile"])

    assert result["ok"] is True
    assert [profile["profile"] for profile in result["profiles"]] == ["harbor_profile"]


def test_validate_system_rejects_unknown_profile(sample_project):
    try:
        validate_system(sample_project.config, profiles=["missing"])
    except ValueError as exc:
        assert "Unknown search evaluation profile: missing" in str(exc)
        assert "harbor_profile" in str(exc)
    else:
        raise AssertionError("Expected unknown profile to fail")


def test_validate_system_reports_lint_gate_failure_when_warnings_fail(sample_project):
    (sample_project.vault / "03_Research" / "Missing Frontmatter.md").write_text(
        "# Missing Frontmatter\n\nThis note intentionally has no frontmatter.\n",
        encoding="utf-8",
    )

    result = validate_system(sample_project.config, fail_on_warnings=True)

    assert result["ok"] is False
    assert result["lint"]["ok"] is False
    assert result["quality_gate_violations"][0]["gate"] == "lint"


def test_validate_system_reports_profile_gate_failure(sample_project):
    config_path = sample_project.root / "failing-profile.yaml"
    config_path.write_text(
        sample_project.config_path.read_text(encoding="utf-8").replace(
            "harbor_profile:",
            """failing_profile:
    query: NeedleOnly
    relevance_patterns:
      - harbor=\\bHarborOps\\b
    limit: 20
    precision_points: [1]
    fail_on_misses: true
  harbor_profile:""",
        ),
        encoding="utf-8",
    )
    config = load_config(config_path)

    result = validate_system(config, profiles=["failing_profile"])

    assert result["ok"] is False
    assert result["profiles"][0]["profile"] == "failing_profile"
    assert result["profiles"][0]["ok"] is False
    assert result["quality_gate_violations"][0]["gate"] == "search_profile"


def test_validate_system_reports_profile_exceptions(sample_project):
    config_path = sample_project.root / "invalid-profile.yaml"
    config_path.write_text(
        sample_project.config_path.read_text(encoding="utf-8").replace(
            "harbor_profile:",
            """invalid_profile:
    query: HarborOps SMS operations
    relevance_patterns:
      - broken=(
    limit: 20
    precision_points: [1]
  harbor_profile:""",
        ),
        encoding="utf-8",
    )
    config = load_config(config_path)

    result = validate_system(config, profiles=["invalid_profile"])

    assert result["ok"] is False
    assert result["profiles"][0]["profile"] == "invalid_profile"
    assert result["profiles"][0]["quality_gate_violations"][0]["gate"] == "profile_exception"


def test_validate_system_compares_to_previous_run(sample_project):
    first = validate_system(sample_project.config)
    second = validate_system(sample_project.config)

    assert first["trend"]["status"] == "baseline"
    assert second["trend"]["status"] == "compared"
    assert second["trend"]["previous_run_dir"] == first["run_dir"]
    assert second["trend"]["comparisons"]["file_count"]["current"] == second["scan"]["file_count"]


def test_validate_system_does_not_mutate_vault_notes(sample_project):
    before = _vault_snapshot(sample_project.vault)

    validate_system(sample_project.config)

    assert _vault_snapshot(sample_project.vault) == before
