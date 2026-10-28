import json
from pathlib import Path

from llm_vault_wiki.storage import read_json
from llm_vault_wiki.workflow import process_source


def _write_plan(path: Path, operations):
    path.write_text(json.dumps({"operations": operations}), encoding="utf-8")
    return path


def _create_file_plan(path: Path, target: str = "03_Research/YouTube Transcript Story Source.md"):
    content = "\n".join([
        "---",
        "title: YouTube Transcript Story Source",
        "type: content-idea",
        "status: draft",
        "domains: [ai-ml]",
        "thesis_areas: []",
        "related: []",
        "tags: [test]",
        "---",
        "",
        "# YouTube Transcript Story Source",
        "",
        "Source-derived note for the transcript workflow.",
        "",
    ])
    return _write_plan(path, [{"op": "create_file", "path": target, "content": content}])


def test_process_source_prepares_review_without_mutating_vault(sample_project):
    result = process_source(sample_project.config, source="00_Inbox/YouTube Transcript.md", limit=5)

    assert result["ok"] is True
    assert result["status"] == "review_ready"
    assert [stage["name"] for stage in result["stages"]] == ["scan", "ingest"]
    assert result["ingest_run_dir"]
    assert result["file_back_brief"]["markdown"].endswith("file-back.brief.md")
    assert result["file_back"]["ready_for_agent_draft"] is True
    assert result["file_back"]["primary_destination"]["suggested_path"]
    assert result["quality_validation"]["status"] == "pending_execution"
    assert Path(result["run_dir"], "process-source.summary.md").exists()
    summary_text = Path(result["run_dir"], "process-source.summary.md").read_text(encoding="utf-8")
    assert "## File-Back Package" in summary_text
    assert "Ready for agent draft: True" in summary_text
    assert not (sample_project.vault / "03_Research" / "YouTube Transcript Story Source.md").exists()


def test_process_source_can_generate_draft_apply_plan_after_ingest(sample_project):
    result = process_source(
        sample_project.config,
        source="00_Inbox/YouTube Transcript.md",
        limit=5,
        draft_apply_plan=True,
        archive_source=True,
    )

    assert result["ok"] is True
    assert result["status"] == "review_ready"
    assert [stage["name"] for stage in result["stages"]] == ["scan", "ingest", "draft_apply_plan"]
    draft = result["draft_apply_plan"]
    assert draft["apply_plan_skeleton"].endswith("apply-plan.skeleton.json")
    assert draft["writer_prompt"].endswith("canonical-note.writer-prompt.md")
    assert draft["archive_source"] is True
    assert draft["archive_path"].startswith("08_Archive/LLM_Vault_Wiki/")
    assert Path(draft["apply_plan_skeleton"]).exists()
    assert Path(draft["writer_prompt"]).exists()

    skeleton = read_json(Path(draft["apply_plan_skeleton"]))
    assert [operation["op"] for operation in skeleton["operations"]] == ["create_file", "archive_file"]
    assert not (sample_project.vault / draft["target_path"]).exists()
    assert (sample_project.vault / "00_Inbox" / "YouTube Transcript.md").exists()

    summary_text = Path(result["run_dir"], "process-source.summary.md").read_text(encoding="utf-8")
    assert "## Draft Apply Plan" in summary_text
    assert "Archive source: True" in summary_text


def test_process_source_rejects_archive_source_without_draft_apply_plan(sample_project):
    result = process_source(
        sample_project.config,
        source="00_Inbox/YouTube Transcript.md",
        archive_source=True,
    )

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["error"]["type"] == "ValueError"
    assert "--archive-source requires --draft-apply-plan" in result["error"]["message"]
    assert result["stages"] == []


def test_process_source_rejects_draft_apply_plan_with_existing_plan(sample_project):
    plan = _create_file_plan(sample_project.root / "plan.json")

    result = process_source(
        sample_project.config,
        source="00_Inbox/YouTube Transcript.md",
        plan=str(plan),
        draft_apply_plan=True,
    )

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["error"]["type"] == "ValueError"
    assert "--draft-apply-plan cannot be combined with --plan" in result["error"]["message"]
    assert result["stages"] == []


def test_process_source_with_plan_runs_dry_run_and_stops_before_write(sample_project):
    plan = _create_file_plan(sample_project.root / "plan.json")

    result = process_source(sample_project.config, source="00_Inbox/YouTube Transcript.md", plan=str(plan), limit=5)

    assert result["ok"] is True
    assert result["status"] == "awaiting_final_approval"
    assert [stage["name"] for stage in result["stages"]] == ["scan", "ingest", "apply_dry_run"]
    assert result["proposed_operations"][0]["status"] == "dry_run"
    assert result["quality_validation"]["status"] == "pending_execution"
    assert result["quality_validation"]["created_files"] == ["03_Research/YouTube Transcript Story Source.md"]
    assert result["proposed_operations"][0]["risk"] == "medium"
    assert result["proposed_operations"][0]["policy_role"] == "research_artifacts"
    assert not (sample_project.vault / "03_Research" / "YouTube Transcript Story Source.md").exists()


def test_process_source_executes_reviewed_plan_and_verifies(sample_project):
    plan = _create_file_plan(sample_project.root / "plan.json")

    result = process_source(
        sample_project.config,
        source="00_Inbox/YouTube Transcript.md",
        plan=str(plan),
        execute=True,
        reviewed=True,
    )

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert [stage["name"] for stage in result["stages"]] == [
        "scan",
        "ingest",
        "apply_dry_run",
        "apply_execute",
        "verify_scan",
        "verify_lint",
    ]
    assert result["proposed_operations"][0]["status"] == "applied"
    assert result["verification"]["lint_ok"] is True
    assert result["quality_validation"]["ok"] is True
    assert result["quality_validation"]["created_files"] == ["03_Research/YouTube Transcript Story Source.md"]
    assert result["quality_validation"]["scan"]["status"] == "checked"
    assert result["quality_validation"]["lint"]["ok"] is True
    assert result["quality_validation"]["retrieval"]["rank"] is not None
    assert result["quality_validation"]["retrieval"]["rank"] <= 3
    assert result["quality_validation"]["saved_profiles"]["status"] == "checked"
    assert result["quality_validation"]["stale_manifest"]["count"] == 0
    assert (sample_project.vault / "03_Research" / "YouTube Transcript Story Source.md").exists()


def test_process_source_execution_without_review_fails_before_mutation(sample_project):
    plan = _create_file_plan(sample_project.root / "plan.json")

    result = process_source(
        sample_project.config,
        source="00_Inbox/YouTube Transcript.md",
        plan=str(plan),
        execute=True,
    )

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["stages"][-1]["name"] == "apply_execute"
    assert result["stages"][-1]["status"] == "failed"
    assert not (sample_project.vault / "03_Research" / "YouTube Transcript Story Source.md").exists()


def test_process_source_excluded_source_fails_without_mutation(sample_project):
    result = process_source(sample_project.config, source="05_Journal/Personal/Private.md")

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["stages"] == []
    assert result["error"]["type"] == "PermissionError"
