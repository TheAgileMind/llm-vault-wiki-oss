import json

from llm_vault_wiki.cli import main


def _write_cli_plan(path):
    content = "\n".join([
        "---",
        "title: CLI Workflow Note",
        "type: intelligence-brief",
        "status: draft",
        "domains: [ai-ml]",
        "thesis_areas: []",
        "related: []",
        "tags: [test]",
        "---",
        "",
        "# CLI Workflow Note",
        "",
        "Created by the guided source workflow E2E test.",
        "",
    ])
    path.write_text(json.dumps({"operations": [{"op": "create_file", "path": "03_Research/CLI Workflow Note.md", "content": content}]}), encoding="utf-8")
    return path


def test_cli_scan_query_lint_flow(sample_project, capsys):
    assert main(["--config", str(sample_project.config_path), "scan"]) == 0
    scan_output = capsys.readouterr().out
    assert '"file_count"' in scan_output
    assert '"index_path"' in scan_output
    assert '"files"' not in scan_output

    assert main(["--config", str(sample_project.config_path), "query", "AI agents and proof points", "--limit", "2"]) == 0
    query_output = capsys.readouterr().out
    assert '"run_dir"' in query_output

    assert main(["--config", str(sample_project.config_path), "synthesize", "HarborOps AI agents", "--limit", "3"]) == 0
    synthesize_output = capsys.readouterr().out
    assert '"read_only": true' in synthesize_output
    assert '"markdown_report"' in synthesize_output

    assert main([
        "--config",
        str(sample_project.config_path),
        "evaluate-search",
        "HarborOps AI agents",
        "--relevant-pattern",
        r"harbor=\bHarborOps\b",
        "--limit",
        "20",
    ]) == 0
    eval_output = capsys.readouterr().out
    assert '"corpus_relevant_files"' in eval_output
    assert '"precision_at"' in eval_output

    assert main([
        "--config",
        str(sample_project.config_path),
        "evaluate-search",
        "--profile",
        "harbor_profile",
    ]) == 0
    profile_output = capsys.readouterr().out
    assert '"profile": "harbor_profile"' in profile_output
    assert '"quality_gates"' in profile_output

    assert main(["--config", str(sample_project.config_path), "validate-system"]) == 0
    validate_output = capsys.readouterr().out
    assert '"scan"' in validate_output
    assert '"profiles"' in validate_output
    assert '"brain_health"' in validate_output
    assert 'system-validation.md' in validate_output

    assert main(["--config", str(sample_project.config_path), "brain-health"]) == 0
    health_output = capsys.readouterr().out
    assert '"markdown_report"' in health_output
    assert '"recommended_next_actions"' in health_output

    assert main([
        "--config",
        str(sample_project.config_path),
        "validate-system",
        "--profile",
        "harbor_profile",
    ]) == 0
    selected_validate_output = capsys.readouterr().out
    assert '"profile": "harbor_profile"' in selected_validate_output

    assert main([
        "--config",
        str(sample_project.config_path),
        "validate-system",
        "--profile",
        "missing_profile",
    ]) == 1
    missing_validate_output = capsys.readouterr()
    assert "Unknown search evaluation profile: missing_profile" in missing_validate_output.err

    assert main(["--config", str(sample_project.config_path), "lint"]) == 0
    lint_output = capsys.readouterr().out
    assert '"ok": true' in lint_output
    assert '"warnings"' in lint_output


def test_cli_evaluate_search_profile_validation(sample_project, capsys):
    assert main(["--config", str(sample_project.config_path), "scan"]) == 0
    capsys.readouterr()

    assert main([
        "--config",
        str(sample_project.config_path),
        "evaluate-search",
        "--profile",
        "missing_profile",
    ]) == 1
    missing_output = capsys.readouterr()
    assert "Unknown search evaluation profile: missing_profile" in missing_output.err
    assert "harbor_profile" in missing_output.err

    assert main([
        "--config",
        str(sample_project.config_path),
        "evaluate-search",
        "HarborOps",
        "--profile",
        "harbor_profile",
    ]) == 1
    mixed_output = capsys.readouterr()
    assert "--profile cannot be combined" in mixed_output.err

    assert main([
        "--config",
        str(sample_project.config_path),
        "evaluate-search",
        "HarborOps",
    ]) == 1
    ad_hoc_output = capsys.readouterr()
    assert "At least one --relevant-pattern is required" in ad_hoc_output.err


def test_cli_process_source_flow(sample_project, capsys):
    assert main([
        "--config",
        str(sample_project.config_path),
        "process-source",
        "--source",
        "00_Inbox/YouTube Transcript.md",
        "--limit",
        "5",
    ]) == 0
    review_output = capsys.readouterr().out
    assert '"status": "review_ready"' in review_output
    assert '"ingest_run_dir"' in review_output
    assert '"file_back_brief"' in review_output
    assert '"ready_for_agent_draft": true' in review_output
    assert '"quality_validation"' in review_output
    assert not (sample_project.vault / "03_Research" / "CLI Workflow Note.md").exists()
    review_result = json.loads(review_output)

    assert main([
        "--config",
        str(sample_project.config_path),
        "draft-apply-plan",
        "--brief",
        review_result["file_back_brief"]["json"],
    ]) == 0
    draft_output = capsys.readouterr().out
    draft_result = json.loads(draft_output)
    assert '"apply_plan_skeleton"' in draft_output
    assert '"writer_prompt"' in draft_output
    assert draft_result["target_path"].endswith(".md")
    assert not (sample_project.vault / draft_result["target_path"]).exists()

    assert main([
        "--config",
        str(sample_project.config_path),
        "draft-apply-plan",
        "--brief",
        review_result["file_back_brief"]["json"],
        "--archive-source",
    ]) == 0
    archive_draft_output = capsys.readouterr().out
    archive_draft_result = json.loads(archive_draft_output)
    assert archive_draft_result["archive_source"] is True
    assert archive_draft_result["archive_path"].startswith("08_Archive/LLM_Vault_Wiki/")

    assert main([
        "--config",
        str(sample_project.config_path),
        "process-source",
        "--source",
        "00_Inbox/YouTube Transcript.md",
        "--draft-apply-plan",
        "--archive-source",
        "--limit",
        "5",
    ]) == 0
    compressed_output = capsys.readouterr().out
    compressed_result = json.loads(compressed_output)
    assert compressed_result["status"] == "review_ready"
    assert compressed_result["draft_apply_plan"]["archive_source"] is True
    assert compressed_result["draft_apply_plan"]["apply_plan_skeleton"].endswith("apply-plan.skeleton.json")

    plan = _write_cli_plan(sample_project.root / "cli-plan.json")
    assert main([
        "--config",
        str(sample_project.config_path),
        "process-source",
        "--source",
        "00_Inbox/YouTube Transcript.md",
        "--plan",
        str(plan),
    ]) == 0
    dry_run_output = capsys.readouterr().out
    assert '"status": "awaiting_final_approval"' in dry_run_output
    assert '"apply_dry_run"' in dry_run_output
    assert '"dry_run"' in dry_run_output
    assert not (sample_project.vault / "03_Research" / "CLI Workflow Note.md").exists()

    assert main([
        "--config",
        str(sample_project.config_path),
        "process-source",
        "--source",
        "00_Inbox/YouTube Transcript.md",
        "--plan",
        str(plan),
        "--execute",
    ]) == 1
    execute_without_review_output = capsys.readouterr().out
    assert '"status": "failed"' in execute_without_review_output
    assert '"apply_execute"' in execute_without_review_output
    assert not (sample_project.vault / "03_Research" / "CLI Workflow Note.md").exists()

    assert main([
        "--config",
        str(sample_project.config_path),
        "process-source",
        "--source",
        "00_Inbox/YouTube Transcript.md",
        "--plan",
        str(plan),
        "--execute",
        "--reviewed",
    ]) == 0
    execute_output = capsys.readouterr().out
    assert '"status": "applied"' in execute_output
    assert '"verify_lint"' in execute_output
    assert '"quality_validation"' in execute_output
    assert '"retrieval"' in execute_output
    assert (sample_project.vault / "03_Research" / "CLI Workflow Note.md").exists()
