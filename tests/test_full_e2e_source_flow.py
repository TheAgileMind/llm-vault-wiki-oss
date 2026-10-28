from pathlib import Path

from llm_vault_wiki.apply_plan_helper import draft_apply_plan
from llm_vault_wiki.frontmatter import parse_frontmatter
from llm_vault_wiki.lint import lint_vault
from llm_vault_wiki.query import rank_notes, run_query
from llm_vault_wiki.storage import read_json, write_json
from llm_vault_wiki.workflow import process_source


def _write_raw(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_orbit_project_context(sample_project) -> None:
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

Project memory for the ORBIT analytics platform, logistics team workflows,
lead follow-up, customer engagement, and trust-preserving automation.
""",
    )


def _write_fresh_source_capture(sample_project) -> str:
    source = "00_Inbox/2026-05-16_Source_ORBIT_Customer_Follow_Up_Signal.md"
    _write_raw(
        sample_project.vault / source,
        """---
title: Source Capture - ORBIT Customer Follow-Up Signal
type: voice-capture
status: seed
domains: [ai-ml, business-strategy]
thesis_areas: []
related:
  - "[[01_Projects/ORBIT_Analytics_Platform/Project Brief]]"
tags: [orbit, logistics, customer-follow-up, agents]
---

# Source Capture - ORBIT Customer Follow-Up Signal

ORBIT should treat customer follow-up as a high-value agent workflow because real
estate teams lose trust when customer questions, delivery requests, and order
updates sit idle.

The source argues for a supervised AI agent that drafts follow-up, flags intent,
and escalates hot customer moments to the human agent instead of replacing the
relationship.

Source: [Customer follow-up automation brief](https://example.com/orbit-customer-follow-up)
""",
    )
    return source


def _fill_generated_apply_plan(skeleton_path: str, output_path: Path) -> Path:
    plan = read_json(Path(skeleton_path))
    operation = plan["operations"][0]
    content = operation["content"]
    replacements = {
        "<Replace with a concise synthesis grounded only in the source package and cited source material.>": (
            "Customer follow-up is a strong ORBIT workflow candidate because the source frames idle customer "
            "questions, delivery requests, and order updates as trust leaks in logistics operations."
        ),
        "<List claims that are directly supported by the source. Keep citations attached to the claims they support.>": (
            "- The source says logistics teams lose trust when customer questions, delivery requests, and "
            "order updates sit idle. [Customer follow-up automation brief](https://example.com/orbit-customer-follow-up)\n"
            "- The source recommends supervised AI that drafts follow-up, flags intent, and escalates hot "
            "customer moments to the human agent. [Customer follow-up automation brief](https://example.com/orbit-customer-follow-up)"
        ),
        "<Add clearly labeled implications for the project or vault. Do not present interpretation as source fact.>": (
            "Implication: ORBIT should position customer follow-up as agent assistive infrastructure, not "
            "relationship replacement. This keeps the human agent visibly accountable while reducing latency."
        ),
        "<State the next practical action this note should drive, or write 'No immediate action.'>": (
            "Add customer follow-up to the ORBIT workflow evaluation backlog and test it against the source "
            "policy review loop before turning it into product copy."
        ),
    }
    for placeholder, replacement in replacements.items():
        content = content.replace(placeholder, replacement)
    operation["content"] = content
    assert "<" not in content
    write_json(output_path, plan)
    return output_path


def test_fresh_source_runs_full_file_back_to_query_loop(sample_project):
    _write_orbit_project_context(sample_project)
    source = _write_fresh_source_capture(sample_project)

    review = process_source(sample_project.config, source=source, limit=5)
    assert review["ok"] is True
    assert review["status"] == "review_ready"
    assert review["file_back"]["ready_for_agent_draft"] is True

    draft = draft_apply_plan(sample_project.config, review["file_back_brief"]["json"])
    assert draft["target_exists"] is False
    assert draft["target_path"].startswith("01_Projects/ORBIT_Analytics_Platform/")
    target = sample_project.vault / draft["target_path"]
    assert not target.exists()

    filled_plan = _fill_generated_apply_plan(
        draft["apply_plan_skeleton"],
        sample_project.root / "filled-apply-plan.json",
    )

    dry_run = process_source(sample_project.config, source=source, plan=str(filled_plan), limit=5)
    assert dry_run["ok"] is True
    assert dry_run["status"] == "awaiting_final_approval"
    assert dry_run["proposed_operations"][0]["status"] == "dry_run"
    assert not target.exists()

    applied = process_source(
        sample_project.config,
        source=source,
        plan=str(filled_plan),
        execute=True,
        reviewed=True,
    )
    assert applied["ok"] is True
    assert applied["status"] == "applied"
    assert applied["verification"]["lint_ok"] is True
    assert target.exists()

    lint_result = lint_vault(sample_project.config)
    assert lint_result["ok"] is True

    ranked = rank_notes(sample_project.config, "ORBIT customer follow-up agent workflow", limit=5)
    assert any(item["path"] == draft["target_path"] for item in ranked)

    query_run = Path(run_query(sample_project.config, "How should ORBIT handle customer follow-up?", limit=5))
    query_context = read_json(query_run / "query.context.json")
    assert any(item["path"] == draft["target_path"] for item in query_context["results"])


def test_fresh_source_can_be_archived_after_canonical_apply(sample_project):
    _write_orbit_project_context(sample_project)
    source = _write_fresh_source_capture(sample_project)

    review = process_source(
        sample_project.config,
        source=source,
        limit=5,
        draft_apply_plan=True,
        archive_source=True,
    )
    draft = review["draft_apply_plan"]
    filled_plan = _fill_generated_apply_plan(
        draft["apply_plan_skeleton"],
        sample_project.root / "filled-archive-apply-plan.json",
    )

    applied = process_source(
        sample_project.config,
        source=source,
        plan=str(filled_plan),
        execute=True,
        reviewed=True,
    )

    target = sample_project.vault / draft["target_path"]
    archive = sample_project.vault / draft["archive_path"]
    source_path = sample_project.vault / source
    assert applied["ok"] is True
    assert [operation["op"] for operation in applied["proposed_operations"]] == ["create_file", "archive_file"]
    assert applied["quality_validation"]["ok"] is True
    assert applied["quality_validation"]["created_files"] == [draft["target_path"]]
    assert applied["quality_validation"]["archived_files"] == [draft["archive_path"]]
    assert applied["quality_validation"]["retrieval"]["rank"] <= 3
    assert applied["quality_validation"]["stale_manifest"]["count"] == 0
    assert target.exists()
    assert archive.exists()
    assert not source_path.exists()
    canonical = parse_frontmatter(target.read_text(encoding="utf-8"))
    assert canonical.data["source"] == draft["archive_path"]
    assert canonical.data["source_capture"] == source

    ranked = rank_notes(sample_project.config, "ORBIT customer follow-up agent workflow", limit=5)
    assert ranked[0]["path"] == draft["target_path"]
    assert all(item["path"] != source for item in ranked)
