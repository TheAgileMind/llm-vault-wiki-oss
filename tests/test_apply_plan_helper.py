from pathlib import Path

import pytest

from llm_vault_wiki.apply import apply_plan
from llm_vault_wiki.apply_plan_helper import ApplyPlanHelperError, draft_apply_plan
from llm_vault_wiki.frontmatter import parse_frontmatter
from llm_vault_wiki.ingest import ingest
from llm_vault_wiki.scan import scan_vault
from llm_vault_wiki.storage import read_json, write_json


def _write_raw(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_orbit_capture(sample_project):
    _write_raw(
        sample_project.vault / "00_Inbox" / "ORBIT Signal.md",
        """---
title: "Source Capture - ORBIT Signal: Competitive Note"
type: voice-capture
status: seed
domains: [ai-ml, business-strategy]
thesis_areas: []
related:
  - "[[01_Projects/ORBIT_Analytics_Platform/Project Brief]]"
tags: [orbit, agents]
---

# Source Capture - ORBIT Signal: Competitive Note

 is positioning around an agentic operating system for logistics teams.
The source describes lead routing, marketing workflows, fulfillment support,
and positioning pressure that ORBIT should treat as category evidence.
Source: [Example product launch](https://example.com/launch)
Additional source: https://example.com/launch-analysis
""",
    )
    _write_raw(
        sample_project.vault / "01_Projects" / "ORBIT_Analytics_Platform" / "Project Brief.md",
        """---
title: ORBIT Project Brief
type: project-note
status: active
domains: [ai-ml, business-strategy]
thesis_areas: []
related: []
tags: [orbit, logistics, agents]
---

# ORBIT Project Brief

Project memory for the ORBIT analytics platform and agent workflow.
""",
    )


def test_draft_apply_plan_creates_valid_skeleton_and_writer_prompt(sample_project):
    _write_orbit_capture(sample_project)
    scan_vault(sample_project.config)
    ingest_run = ingest(sample_project.config, source="00_Inbox/ORBIT Signal.md", limit=5)

    result = draft_apply_plan(sample_project.config, ingest_run / "file-back.brief.json")

    skeleton = read_json(Path(result["apply_plan_skeleton"]))
    operation = skeleton["operations"][0]
    assert result["target_path"] == "01_Projects/ORBIT_Analytics_Platform/ORBIT_Signal_Competitive_Note.md"
    assert result["target_exists"] is False
    assert operation["op"] == "create_file"
    assert operation["path"] == result["target_path"]
    assert not (sample_project.vault / result["target_path"]).exists()

    parsed = parse_frontmatter(operation["content"])
    assert parsed.error is None
    assert parsed.data["type"] == "project-note"
    assert parsed.data["status"] == "draft"
    assert parsed.data["domains"] == ["ai-ml", "business-strategy"]
    assert parsed.data["tags"] == ["orbit", "agents", "file-back", "agent-draft-needed"]
    assert parsed.data["source"] == "00_Inbox/ORBIT Signal.md"
    assert parsed.data["source_capture"] == "00_Inbox/ORBIT Signal.md"
    assert "[[01_Projects/ORBIT_Analytics_Platform/Project Brief|ORBIT Project Brief]]" in operation["content"]
    assert "https://example.com/launch" in operation["content"]
    assert "## Direct Source Claims" in operation["content"]
    assert "## Agent Interpretation / Implications" in operation["content"]
    assert "<Replace with" in operation["content"]

    dry_run = apply_plan(sample_project.config, result["apply_plan_skeleton"])
    assert dry_run["results"][0]["status"] == "dry_run"
    assert not (sample_project.vault / result["target_path"]).exists()

    prompt_text = Path(result["writer_prompt"]).read_text(encoding="utf-8")
    assert "Do not edit the vault directly" in prompt_text
    assert "Target currently exists: `false`" in prompt_text
    assert "Keep direct source claims separate from agent interpretation" in prompt_text


def test_draft_apply_plan_can_include_reviewed_source_archive_operation(sample_project):
    _write_orbit_capture(sample_project)
    scan_vault(sample_project.config)
    ingest_run = ingest(sample_project.config, source="00_Inbox/ORBIT Signal.md", limit=5)

    result = draft_apply_plan(
        sample_project.config,
        ingest_run / "file-back.brief.json",
        archive_source=True,
    )

    skeleton = read_json(Path(result["apply_plan_skeleton"]))
    assert result["archive_source"] is True
    assert result["archive_path"] == "08_Archive/LLM_Vault_Wiki/00_Inbox_ORBIT Signal.md"
    assert [operation["op"] for operation in skeleton["operations"]] == ["create_file", "archive_file"]
    parsed = parse_frontmatter(skeleton["operations"][0]["content"])
    assert parsed.data["source"] == "08_Archive/LLM_Vault_Wiki/00_Inbox_ORBIT Signal.md"
    assert parsed.data["source_capture"] == "00_Inbox/ORBIT Signal.md"
    assert "[[08_Archive/LLM_Vault_Wiki/00_Inbox_ORBIT Signal]]" in parsed.data["related"]
    assert "Source capture: [[08_Archive/LLM_Vault_Wiki/00_Inbox_ORBIT Signal]]" in skeleton["operations"][0]["content"]
    assert "Source capture: [[00_Inbox/ORBIT Signal]]" not in skeleton["operations"][0]["content"]
    assert skeleton["operations"][1] == {
        "op": "archive_file",
        "path": "00_Inbox/ORBIT Signal.md",
        "to": "08_Archive/LLM_Vault_Wiki/00_Inbox_ORBIT Signal.md",
    }

    dry_run = apply_plan(sample_project.config, result["apply_plan_skeleton"])
    assert [item["status"] for item in dry_run["results"]] == ["dry_run", "dry_run"]
    assert not (sample_project.vault / result["target_path"]).exists()
    assert (sample_project.vault / "00_Inbox" / "ORBIT Signal.md").exists()

    prompt_text = Path(result["writer_prompt"]).read_text(encoding="utf-8")
    assert "Archive source after apply: `true`" in prompt_text
    assert "keep it after the create-file operation" in prompt_text


def test_draft_apply_plan_uses_available_archive_path_when_source_archive_exists(sample_project):
    _write_orbit_capture(sample_project)
    _write_raw(
        sample_project.vault / "08_Archive" / "LLM_Vault_Wiki" / "00_Inbox_ORBIT Signal.md",
        "already archived\n",
    )
    scan_vault(sample_project.config)
    ingest_run = ingest(sample_project.config, source="00_Inbox/ORBIT Signal.md", limit=5)

    result = draft_apply_plan(
        sample_project.config,
        ingest_run / "file-back.brief.json",
        archive_source=True,
    )

    skeleton = read_json(Path(result["apply_plan_skeleton"]))
    assert result["archive_path"] == "08_Archive/LLM_Vault_Wiki/00_Inbox_ORBIT Signal-2.md"
    parsed = parse_frontmatter(skeleton["operations"][0]["content"])
    assert parsed.data["source"] == result["archive_path"]
    assert skeleton["operations"][1]["to"] == result["archive_path"]


def test_draft_apply_plan_refuses_not_ready_file_back_package(sample_project):
    brief_path = sample_project.root / "not-ready.file-back.brief.json"
    write_json(
        brief_path,
        {
            "sources": [
                {
                    "source": "00_Inbox/Needs Work.md",
                    "title": "Needs Work",
                    "primary_destination": {
                        "suggested_path": "03_Research/Needs Work.md",
                        "note_type": "intelligence-brief",
                    },
                    "ready_for_agent_draft": False,
                }
            ]
        },
    )

    with pytest.raises(ApplyPlanHelperError, match="not ready"):
        draft_apply_plan(sample_project.config, brief_path)


def test_draft_apply_plan_validates_source_index(sample_project):
    brief_path = sample_project.root / "empty.file-back.brief.json"
    write_json(brief_path, {"sources": []})

    with pytest.raises(ApplyPlanHelperError, match="non-empty sources"):
        draft_apply_plan(sample_project.config, brief_path)
