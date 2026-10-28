from pathlib import Path

from llm_vault_wiki.query import rank_notes, run_query, tokenize
from llm_vault_wiki.scan import scan_vault


def _write_raw(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_query_ranks_relevant_notes_and_writes_context_pack(sample_project):
    scan_vault(sample_project.config)

    ranked = rank_notes(sample_project.config, "HarborOps AI agents proof point", limit=3)
    assert ranked
    assert any(item["path"] == "01_Projects/HarborOps.md" for item in ranked)

    run_dir = run_query(sample_project.config, "How do AI agents connect to HarborOps?", limit=3)
    assert (Path(run_dir) / "query.context.md").exists()
    assert (Path(run_dir) / "query.prompt.md").exists()


def test_tokenize_keeps_ai_as_meaningful_term():
    assert "ai" in tokenize("AI agents")


def test_tokenize_splits_metadata_compounds():
    terms = tokenize("chronobiology-cognitive AI_ML")

    assert "chronobiology-cognitive" in terms
    assert "chronobiology" in terms
    assert "cognitive" in terms
    assert "ai" in terms
    assert "ml" in terms


def test_query_finds_full_body_term_when_excerpt_misses_it(sample_project):
    filler = " ".join(["background system note"] * 120)
    _write_raw(
        sample_project.vault / "03_Research" / "Late Circadian Mention.md",
        f"""---
title: Late Mention
type: intelligence-brief
status: active
domains: [research]
thesis_areas: []
related: []
tags: [test]
---

# Late Mention

{filler}

The important detail appears late: Circadian changes the operating model.
""",
    )
    scan_vault(sample_project.config)

    ranked = rank_notes(sample_project.config, "Circadian", limit=20)

    assert any(item["path"] == "03_Research/Late Circadian Mention.md" for item in ranked)
    note = next(item for item in ranked if item["path"] == "03_Research/Late Circadian Mention.md")
    assert any(reason.startswith("full_text: circadian") for reason in note["score_reasons"])


def test_broad_query_requires_discriminative_anchor_match(sample_project):
    _write_raw(
        sample_project.vault / "03_Research" / "Circadian Systems Brief.md",
        """---
title: Circadian Systems Brief
type: intelligence-brief
status: active
domains: [chronobiology]
thesis_areas: []
related: []
tags: [circadian, systems]
---

# Circadian Systems Brief

Circadian, chronotype, sleep hygiene, AI, systems, and intent all connect here.
""",
    )
    _write_raw(
        sample_project.vault / "03_Research" / "Generic AI Systems Brief.md",
        """---
title: Generic AI Systems Brief
type: intelligence-brief
status: active
domains: [ai-ml]
thesis_areas: []
related: []
tags: [ai, systems]
---

# Generic AI Systems Brief

AI systems and intent are discussed here, but there is no chronobiology anchor.
""",
    )
    scan_vault(sample_project.config)

    ranked = rank_notes(sample_project.config, "Circadian chronotype sleep hygiene AI systems intent", limit=20)
    paths = [item["path"] for item in ranked]

    assert "03_Research/Circadian Systems Brief.md" in paths
    assert "03_Research/Generic AI Systems Brief.md" not in paths


def test_query_matches_configured_phrase_as_single_anchor(sample_project):
    _write_raw(
        sample_project.vault / "03_Research" / "Sleep Hygiene Brief.md",
        """---
title: Sleep Hygiene Brief
type: intelligence-brief
status: active
domains: [research]
thesis_areas: []
related: []
tags: [cognition]
---

# Sleep Hygiene Brief

This note is specifically about sleep hygiene support for planning.
""",
    )
    _write_raw(
        sample_project.vault / "03_Research" / "Split Executive Planning.md",
        """---
title: Split Executive Planning
type: intelligence-brief
status: active
domains: [research]
thesis_areas: []
related: []
tags: [planning]
---

# Split Executive Planning

This note says executive leadership should function well inside AI systems, but it does not contain the configured phrase.
""",
    )
    scan_vault(sample_project.config)

    ranked = rank_notes(sample_project.config, "sleep hygiene AI systems", limit=20)
    paths = [item["path"] for item in ranked]

    assert "03_Research/Sleep Hygiene Brief.md" in paths
    assert "03_Research/Split Executive Planning.md" not in paths
    note = next(item for item in ranked if item["path"] == "03_Research/Sleep Hygiene Brief.md")
    assert any("sleep_hygiene" in reason for reason in note["score_reasons"])
