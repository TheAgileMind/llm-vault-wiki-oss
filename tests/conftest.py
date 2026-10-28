from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from llm_vault_wiki.config import Config, load_config


@dataclass(frozen=True)
class SampleProject:
    root: Path
    vault: Path
    config_path: Path
    config: Config


def write_note(path: Path, *, title: str, body: str, note_type: str = "domain-note", status: str = "active", extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join([
            "---",
            f"title: {title}",
            f"type: {note_type}",
            f"status: {status}",
            "domains: [ai-ml, business-strategy]",
            "thesis_areas: []",
            "related: []",
            "tags: [test]",
            extra.rstrip(),
            "---",
            "",
            f"# {title}",
            "",
            body,
            "",
        ]),
        encoding="utf-8",
    )


@pytest.fixture
def sample_project(tmp_path: Path) -> SampleProject:
    vault = tmp_path / "vault"
    write_note(
        vault / "00_Inbox" / "YouTube Transcript.md",
        title="YouTube Transcript",
        note_type="voice-capture",
        status="seed",
        body="A transcript about AI agents, HarborOps, proof points, and vault maintenance. [[02_Domains/AI_ML_Systems/Agents]]",
    )
    write_note(
        vault / "01_Projects" / "HarborOps.md",
        title="HarborOps",
        note_type="project-note",
        body="SMS logistics operations project connected to agent workflows and proof points.",
    )
    write_note(
        vault / "02_Domains" / "AI_ML_Systems" / "Agents.md",
        title="Agents",
        body="Agent systems, context packs, retrieval, and guarded tool execution.",
    )
    write_note(
        vault / "03_Research" / "Builder Brief.md",
        title="Builder Brief",
        note_type="intelligence-brief",
        body="Research on non-traditional builders using LLMs to ship products.",
    )
    write_note(
        vault / "04_Content" / "Ideas" / "Agent Post.md",
        title="Agent Post",
        note_type="content-idea",
        status="seed",
        body="A content idea about using agents to maintain a knowledge vault.",
    )
    write_note(
        vault / "05_Journal" / "Daily" / "2026-05-12.md",
        title="Daily 2026-05-12",
        note_type="daily",
        body="Business idea: turn the mature vault into an LLM-maintained wiki.",
    )
    write_note(
        vault / "06_Proof_Points" / "Widget_Classifier.md",
        title="Widget Classifier",
        note_type="proof-point",
        body="10x cost reduction proof point linked to production builder credibility.",
    )
    write_note(
        vault / "05_Journal" / "Personal" / "Private.md",
        title="Private",
        note_type="daily",
        body="Personal note that must stay outside the wiki index.",
    )
    (vault / ".env").write_text("SECRET=value\n", encoding="utf-8")

    config_path = tmp_path / "llm-vault-wiki.yaml"
    config_path.write_text(
        f"""
vault_root: "{vault.as_posix()}"
state_dir: "{(tmp_path / "state").as_posix()}"
apply_policy:
  mode: dry_run_required
  high_risk_requires_review: true
search_policy:
  generic_anchor_terms: [ai, system, systems, intent]
  phrase_terms: [sleep hygiene, light exposure]
search_evaluations:
  harbor_profile:
    query: HarborOps SMS operations AI workflow
    relevance_patterns:
      - harbor=\\bHarborOps\\b
    limit: 20
    precision_points: [1, 5, 10]
    fail_on_misses: true
    min_precision_at:
      1: 0.5
folders:
  "00_Inbox":
    role: raw_capture
    include: partial
    risk: low
    allowed_ops: [create_file, move_file, archive_file]
  "01_Projects":
    role: project_memory
    include: true
    risk: medium
    allowed_ops: [create_file]
    review_required_for: [create_file]
  "02_Domains":
    role: domain_synthesis
    include: true
    risk: medium
    allowed_ops: [create_file]
    review_required_for: [create_file]
  "03_Research":
    role: research_artifacts
    include: true
    risk: medium
    allowed_ops: [create_file]
    review_required_for: [create_file]
  "04_Content":
    role: content_engine
    include: true
    risk: medium
    allowed_ops: [create_file]
    review_required_for: [create_file]
  "05_Journal/Daily":
    role: business_signal
    include: partial
    risk: high
    allowed_ops: []
  "05_Journal/Personal":
    role: private_journal
    include: false
    risk: excluded
    allowed_ops: []
  "06_Proof_Points":
    role: evidence_base
    include: true
    risk: high
    allowed_ops: []
  "08_Archive/LLM_Vault_Wiki":
    role: controlled_archive
    include: true
    risk: low
    allowed_ops: [archive_file, create_file]
exclude:
  - "05_Journal/Personal/**"
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    return SampleProject(root=tmp_path, vault=vault, config_path=config_path, config=config)
