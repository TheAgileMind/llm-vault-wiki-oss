import pytest

from llm_vault_wiki.config import load_config


def test_load_config_classifies_paths(sample_project):
    config = load_config(sample_project.config_path)

    assert config.vault_root == sample_project.vault.resolve()
    assert config.classify("03_Research/Builder Brief.md").role == "research_artifacts"
    assert config.is_included("00_Inbox/YouTube Transcript.md")
    assert not config.is_included("05_Journal/Personal/Private.md")
    assert config.is_excluded(".env")
    assert config.search_policy.generic_anchor_terms == ("ai", "system", "systems", "intent")
    assert "sleep hygiene" in config.search_policy.phrase_terms


def test_load_config_loads_search_evaluation_profiles(sample_project):
    config = load_config(sample_project.config_path)

    profile = config.search_evaluations["harbor_profile"]
    assert profile.query == "HarborOps SMS operations AI workflow"
    assert profile.relevance_patterns == (r"harbor=\bHarborOps\b",)
    assert profile.limit == 20
    assert profile.precision_points == (1, 5, 10)
    assert profile.fail_on_misses is True
    assert profile.min_precision_at == {1: 0.5}


def test_load_config_rejects_incomplete_search_evaluation_profile(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = tmp_path / "llm-vault-wiki.yaml"
    config_path.write_text(
        f"""
vault_root: "{vault.as_posix()}"
search_evaluations:
  broken:
    query: ""
folders: {{}}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="search_evaluations.broken.query"):
        load_config(config_path)


def test_load_config_rejects_invalid_search_evaluation_precision_gate(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = tmp_path / "llm-vault-wiki.yaml"
    config_path.write_text(
        f"""
vault_root: "{vault.as_posix()}"
search_evaluations:
  broken:
    query: HarborOps
    relevance_patterns: [HarborOps]
    min_precision_at:
      25: 1.5
folders: {{}}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="search_evaluations.broken.min_precision_at values"):
        load_config(config_path)
