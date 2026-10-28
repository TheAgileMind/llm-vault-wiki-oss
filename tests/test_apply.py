import json

import pytest

from llm_vault_wiki.apply import ApplyPlanError, apply_plan
from llm_vault_wiki.config import load_config


def _write_plan(path, operations):
    path.write_text(json.dumps({"operations": operations}), encoding="utf-8")
    return path


def _create_plan(path, target="03_Research/New Brief.md", content=None):
    content = content or "\n".join([
        "---",
        "title: New Brief",
        "type: intelligence-brief",
        "status: draft",
        "---",
        "",
        "# New Brief",
        "",
        "A drafted brief with [[01_Projects/HarborOps]].",
        "",
    ])
    return _write_plan(path, [{"op": "create_file", "path": target, "content": content}])


def test_apply_plan_defaults_to_dry_run(sample_project):
    plan_path = _create_plan(sample_project.root / "plan.json")

    result = apply_plan(sample_project.config, plan_path)

    assert result["results"][0]["status"] == "dry_run"
    assert not (sample_project.vault / "03_Research" / "New Brief.md").exists()


def test_apply_plan_requires_review_for_execution(sample_project):
    plan_path = _create_plan(sample_project.root / "plan.json")

    with pytest.raises(PermissionError):
        apply_plan(sample_project.config, plan_path, execute=True)

    result = apply_plan(sample_project.config, plan_path, execute=True, reviewed=True)
    assert result["results"][0]["status"] == "applied"
    assert (sample_project.vault / "03_Research" / "New Brief.md").exists()


def test_apply_plan_dry_run_only_blocks_execution_even_when_reviewed(sample_project):
    plan_path = _create_plan(sample_project.root / "plan.json")
    config_path = sample_project.config_path
    config_path.write_text(config_path.read_text(encoding="utf-8").replace("mode: dry_run_required", "mode: dry_run_only"), encoding="utf-8")

    config = load_config(config_path)

    with pytest.raises(PermissionError, match="dry_run_only"):
        apply_plan(config, plan_path, execute=True, reviewed=True)

    assert not (sample_project.vault / "03_Research" / "New Brief.md").exists()


def test_apply_plan_blocks_execution_before_operation_validation(sample_project):
    plan_path = _create_plan(sample_project.root / "plan.json", content="# Missing frontmatter")

    with pytest.raises(PermissionError, match="apply_policy"):
        apply_plan(sample_project.config, plan_path, execute=True)


def test_apply_plan_requires_frontmatter_for_new_files(sample_project):
    plan_path = _create_plan(sample_project.root / "plan.json", content="# Missing frontmatter")

    with pytest.raises(ApplyPlanError):
        apply_plan(sample_project.config, plan_path)


def test_apply_plan_can_move_files_inside_allowed_policy(sample_project):
    plan_path = _write_plan(sample_project.root / "plan.json", [{
        "op": "move_file",
        "from": "00_Inbox/YouTube Transcript.md",
        "to": "00_Inbox/Processed Transcript.md",
    }])

    result = apply_plan(sample_project.config, plan_path, execute=True, reviewed=True)

    assert result["results"][0]["status"] == "applied"
    assert not (sample_project.vault / "00_Inbox" / "YouTube Transcript.md").exists()
    assert (sample_project.vault / "00_Inbox" / "Processed Transcript.md").exists()


def test_apply_plan_requires_review_for_move_source_policy(sample_project):
    config_path = sample_project.config_path
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "allowed_ops: [create_file, move_file, archive_file]",
            "allowed_ops: [create_file, move_file, archive_file]\n    review_required_for: [move_file]",
        ).replace("mode: dry_run_required", "mode: direct"),
        encoding="utf-8",
    )

    config = load_config(config_path)
    plan_path = _write_plan(sample_project.root / "plan.json", [{
        "op": "move_file",
        "from": "00_Inbox/YouTube Transcript.md",
        "to": "00_Inbox/Processed Transcript.md",
    }])

    with pytest.raises(PermissionError, match="source 00_Inbox/YouTube Transcript.md"):
        apply_plan(config, plan_path, execute=True, reviewed=False)

    assert (sample_project.vault / "00_Inbox" / "YouTube Transcript.md").exists()
    assert not (sample_project.vault / "00_Inbox" / "Processed Transcript.md").exists()


def test_apply_plan_archives_only_to_policy_included_archive(sample_project):
    plan_path = _write_plan(sample_project.root / "plan.json", [{
        "op": "archive_file",
        "path": "00_Inbox/YouTube Transcript.md",
    }])

    result = apply_plan(sample_project.config, plan_path, execute=True, reviewed=True)

    assert result["results"][0]["status"] == "applied"
    assert not (sample_project.vault / "00_Inbox" / "YouTube Transcript.md").exists()
    assert (sample_project.vault / "08_Archive" / "LLM_Vault_Wiki" / "YouTube Transcript.md").exists()


def test_apply_plan_requires_review_for_archive_source_policy(sample_project):
    config_path = sample_project.config_path
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "allowed_ops: [create_file, move_file, archive_file]",
            "allowed_ops: [create_file, move_file, archive_file]\n    review_required_for: [archive_file]",
        ).replace("mode: dry_run_required", "mode: direct"),
        encoding="utf-8",
    )

    config = load_config(config_path)
    plan_path = _write_plan(sample_project.root / "plan.json", [{
        "op": "archive_file",
        "path": "00_Inbox/YouTube Transcript.md",
    }])

    with pytest.raises(PermissionError, match="source 00_Inbox/YouTube Transcript.md"):
        apply_plan(config, plan_path, execute=True, reviewed=False)

    assert (sample_project.vault / "00_Inbox" / "YouTube Transcript.md").exists()
    assert not (sample_project.vault / "08_Archive" / "LLM_Vault_Wiki" / "YouTube Transcript.md").exists()


def test_apply_plan_rejects_archive_destination_outside_policy(sample_project):
    plan_path = _write_plan(sample_project.root / "plan.json", [{
        "op": "archive_file",
        "path": "00_Inbox/YouTube Transcript.md",
        "to": "08_Archive/Other/YouTube Transcript.md",
    }])

    with pytest.raises(PermissionError, match="outside included vault policy"):
        apply_plan(sample_project.config, plan_path)
