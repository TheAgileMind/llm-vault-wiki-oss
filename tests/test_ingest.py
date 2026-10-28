from pathlib import Path

from llm_vault_wiki.frontmatter import parse_frontmatter
from llm_vault_wiki.ingest import _is_redundant_alternate, ingest
from llm_vault_wiki.scan import scan_vault
from llm_vault_wiki.storage import read_json


def _write_raw(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_redundant_alternate_detection_filters_parent_and_child_paths():
    primary = "01_Projects/ORBIT_Analytics_Platform"

    assert _is_redundant_alternate(primary, "01_Projects") is True
    assert _is_redundant_alternate(primary, "01_Projects/ORBIT_Analytics_Platform") is True
    assert _is_redundant_alternate(primary, "01_Projects/ORBIT_Analytics_Platform/SubFolder") is True
    assert _is_redundant_alternate(primary, "03_Research") is False


def test_ingest_creates_plan_report_and_draft_without_mutating_vault(sample_project):
    scan_vault(sample_project.config)

    run_dir = ingest(sample_project.config, source="00_Inbox/YouTube Transcript.md", limit=5)
    run_path = Path(run_dir)

    assert (run_path / "ingest.report.md").exists()
    assert (run_path / "file-back.brief.json").exists()
    assert (run_path / "file-back.brief.md").exists()
    assert list((run_path / "drafts").glob("*-draft.md"))
    plan = read_json(run_path / "ingest.plan.json")
    assert plan["sources"][0]["source"] == "00_Inbox/YouTube Transcript.md"
    assert plan["sources"][0]["proposed_destinations"]
    assert plan["sources"][0]["suggested_wikilinks"]
    assert plan["sources"][0]["file_back"]["primary_destination"]["suggested_path"]
    assert plan["sources"][0]["file_back"]["ready_for_agent_draft"] is True
    assert not (sample_project.vault / "03_Research" / "YouTube Transcript.md").exists()


def test_ingest_file_back_package_preserves_source_context_and_project_target(sample_project):
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
    scan_vault(sample_project.config)

    run_dir = ingest(sample_project.config, source="00_Inbox/ORBIT Signal.md", limit=5)
    run_path = Path(run_dir)
    plan = read_json(run_path / "ingest.plan.json")
    file_back = plan["sources"][0]["file_back"]

    assert file_back["source_metadata"] == {
        "domains": ["ai-ml", "business-strategy"],
        "tags": ["orbit", "agents"],
        "thesis_areas": [],
    }
    assert file_back["source_urls"] == ["https://example.com/launch", "https://example.com/launch-analysis"]
    assert file_back["primary_destination"]["folder"] == "01_Projects/ORBIT_Analytics_Platform"
    assert file_back["primary_destination"]["note_type"] == "project-note"
    assert file_back["primary_destination"]["suggested_path"].endswith("/ORBIT_Signal_Competitive_Note.md")
    assert "01_Projects" not in [dest["folder"] for dest in file_back["alternate_destinations"]]
    assert file_back["quality_checks"]["has_claims_vs_interpretation_outline"] is True
    assert file_back["related_notes"][0]["path"] == "01_Projects/ORBIT_Analytics_Platform/Project Brief.md"

    brief = read_json(run_path / "file-back.brief.json")
    assert brief["sources"][0]["primary_destination"]["folder"] == "01_Projects/ORBIT_Analytics_Platform"
    draft_text = next((run_path / "drafts").glob("*-draft.md")).read_text(encoding="utf-8")
    assert parse_frontmatter(draft_text).error is None
    assert "## Direct Source Claims" in draft_text
    assert "## Agent Interpretation / Implications" in draft_text
    assert "https://example.com/launch" in draft_text
    assert "https://example.com/launch-analysis" in draft_text


def test_ingest_prioritizes_explicit_related_notes_over_generic_journal_noise(sample_project):
    _write_raw(
        sample_project.vault / "00_Inbox" / "Voice" / "Chronotype Moment.md",
        """---
title: Chronotype Moment
type: voice-capture
status: active
domains: [chronobiology, career-brand, communication]
thesis_areas: [ai-productivity-paradox, credential-erosion]
related:
  - "[[06_Proof_Points/Circadian_Optimization_Journey]]"
  - "[[04_Content/Ideas/Circadian_AI_Advantage_Article_Roadmap_2026-03-10]]"
tags: [interview, chronotype-moment, circadian, systems]
---

# Chronotype Moment

This voice capture is about Circadian chronotype, systems realization, intent,
time constraints, therapy, and how AI tools later helped turn the realization
into a productive operating system.
""",
    )
    _write_raw(
        sample_project.vault / "06_Proof_Points" / "Circadian_Optimization_Journey.md",
        """---
title: Circadian Optimization Journey
type: proof-point
status: active
domains: [chronobiology, career-brand]
thesis_areas: [ai-productivity-paradox, credential-erosion]
related: []
tags: [circadian, systems, chronotype]
---

# Circadian Optimization Journey

Evidence about chronotype, systems, and Circadian-compatible operating models.
""",
    )
    _write_raw(
        sample_project.vault / "04_Content" / "Ideas" / "Circadian_AI_Advantage_Article_Roadmap_2026-03-10.md",
        """---
title: Circadian AI Advantage Article Roadmap
type: content-idea
status: seed
domains: [chronobiology, communication]
thesis_areas: [ai-productivity-paradox]
related: []
tags: [circadian, ai, article-roadmap]
---

# Circadian AI Advantage Article Roadmap

Roadmap for turning chronotype and systems interview material into article structure.
""",
    )
    _write_raw(
        sample_project.vault / "05_Journal" / "Ideas" / "Generic Voice AI Agent Idea.md",
        """---
title: Generic Voice AI Agent Idea
type: daily
status: seed
domains: [ai-ml]
thesis_areas: []
related: []
tags: [voice, ai]
---

# Generic Voice AI Agent Idea

Voice voice voice about doing something with AI agents and notes.
""",
    )
    scan_vault(sample_project.config)

    run_dir = ingest(sample_project.config, source="00_Inbox/Voice/Chronotype Moment.md", limit=5)
    plan = read_json(Path(run_dir) / "ingest.plan.json")
    paths = [link["path"] for link in plan["sources"][0]["suggested_wikilinks"]]

    assert set(paths[:2]) == {
        "04_Content/Ideas/Circadian_AI_Advantage_Article_Roadmap_2026-03-10.md",
        "06_Proof_Points/Circadian_Optimization_Journey.md",
    }
    assert "05_Journal/Ideas/Generic Voice AI Agent Idea.md" not in paths


def test_ingest_explicit_domain_related_note_beats_non_explicit_project_noise(sample_project):
    _write_raw(
        sample_project.vault / "00_Inbox" / "Training Source.md",
        """---
title: Source Capture - Training OpenAI Agents Guardrails
type: voice-capture
status: seed
domains: [ai-ml, coding-agents, product-dev]
thesis_areas: []
related:
  - "[[02_Domains/Coding_Agent_Capabilities/Agent_Execution_Protocol]]"
tags: [training-source, agents, guardrails, openai]
---

# Source Capture - Training OpenAI Agents Guardrails

This source is about agent guardrails, reviewed apply plans, source separation,
tool boundaries, and validation loops for agent-native workflows.
Source: https://openai.github.io/openai-agents-python/guardrails/
""",
    )
    _write_raw(
        sample_project.vault / "02_Domains" / "Coding_Agent_Capabilities" / "Agent_Execution_Protocol.md",
        """---
title: Agent Execution Protocol
type: domain-note
status: active
domains: [ai-ml, coding-agents]
thesis_areas: []
related: []
tags: [agents, guardrails, workflows]
---

# Agent Execution Protocol

Domain synthesis for guardrails, apply plans, and agent-native workflows.
""",
    )
    _write_raw(
        sample_project.vault / "01_Projects" / "ORBIT_Analytics_Platform" / "Specialist Briefing.md",
        """---
title: Specialist Briefing
type: project-note
status: active
domains: [ai-ml, business-strategy]
thesis_areas: []
related: []
tags: [agents, guardrails, orbit]
---

# Specialist Briefing

Project memory with overlapping agent and guardrail terms that should not
override explicit domain routing for a training source.
""",
    )
    scan_vault(sample_project.config)

    run_dir = ingest(sample_project.config, source="00_Inbox/Training Source.md", limit=5)
    file_back = read_json(Path(run_dir) / "ingest.plan.json")["sources"][0]["file_back"]

    assert file_back["primary_destination"]["folder"] == "02_Domains/Coding_Agent_Capabilities"
    assert file_back["primary_destination"]["note_type"] == "domain-note"
    assert file_back["primary_destination"]["suggested_path"] == "02_Domains/Coding_Agent_Capabilities/Training_OpenAI_Agents_Guardrails.md"
    assert "explicitly links" in file_back["primary_destination"]["reason"]
    assert file_back["primary_destination"]["destination_confidence"]["winning_signal"] == (
        "explicit related note: 02_Domains/Coding_Agent_Capabilities/Agent_Execution_Protocol.md"
    )


def test_ingest_reports_alternate_explicit_safe_subfolder_candidates(sample_project):
    _write_raw(
        sample_project.vault / "00_Inbox" / "Mixed Explicit Source.md",
        """---
title: Source Capture - Mixed Explicit Agent Workflow Note
type: voice-capture
status: seed
domains: [ai-ml, product-dev]
thesis_areas: []
related:
  - "[[02_Domains/Coding_Agent_Capabilities/Agent_Execution_Protocol]]"
  - "[[02_Domains/Marketing_Growth/Agentic_Positioning]]"
tags: [agents, workflows, positioning]
---

# Source Capture - Mixed Explicit Agent Workflow Note

This source is mostly about agent workflow guardrails, execution protocol,
tool boundaries, and validation loops. It also has a smaller positioning angle.
""",
    )
    _write_raw(
        sample_project.vault / "02_Domains" / "Coding_Agent_Capabilities" / "Agent_Execution_Protocol.md",
        """---
title: Agent Execution Protocol
type: domain-note
status: active
domains: [ai-ml, coding-agents]
thesis_areas: []
related: []
tags: [agents, workflows, guardrails]
---

# Agent Execution Protocol

Agent workflow guardrails, execution protocol, tool boundaries, and validation loops.
""",
    )
    _write_raw(
        sample_project.vault / "02_Domains" / "Marketing_Growth" / "Agentic_Positioning.md",
        """---
title: Agentic Positioning
type: domain-note
status: active
domains: [marketing-growth]
thesis_areas: []
related: []
tags: [positioning]
---

# Agentic Positioning

Positioning and market language for agentic products.
""",
    )
    scan_vault(sample_project.config)

    run_dir = ingest(sample_project.config, source="00_Inbox/Mixed Explicit Source.md", limit=5)
    file_back = read_json(Path(run_dir) / "ingest.plan.json")["sources"][0]["file_back"]
    confidence = file_back["primary_destination"]["destination_confidence"]

    assert file_back["primary_destination"]["folder"] == "02_Domains/Coding_Agent_Capabilities"
    assert confidence["winning_signal"] == (
        "explicit related note: 02_Domains/Coding_Agent_Capabilities/Agent_Execution_Protocol.md"
    )
    assert {
        "path": "02_Domains/Marketing_Growth/Agentic_Positioning.md",
        "folder": "02_Domains/Marketing_Growth",
        "reason": "explicit related note also points to a safe destination folder",
    } in confidence["alternatives"]
