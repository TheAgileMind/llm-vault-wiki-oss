from llm_vault_wiki.scan import scan_vault
from llm_vault_wiki.storage import read_json


def _write_raw(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scan_builds_manifests_and_excludes_private_paths(sample_project):
    result = scan_vault(sample_project.config)

    inventory = result["inventory"]
    paths = {item["path"] for item in inventory["files"]}
    assert "05_Journal/Personal/Private.md" not in paths
    assert "06_Proof_Points/Widget_Classifier.md" in paths
    assert result["index_path"].endswith("vault-index.md")
    inbox = next(item for item in inventory["files"] if item["path"] == "00_Inbox/YouTube Transcript.md")
    assert "archive_file" in inbox["allowed_ops"]

    links = read_json(sample_project.config.state_dir / "manifests" / "vault.links.json")
    assert {"source": "00_Inbox/YouTube Transcript.md", "target": "02_Domains/AI_ML_Systems/Agents"} in links["links"]


def test_scan_indexes_full_body_terms_beyond_safe_excerpt(sample_project):
    filler = " ".join(["ordinary context"] * 120)
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

    result = scan_vault(sample_project.config)
    note = next(item for item in result["inventory"]["files"] if item["path"] == "03_Research/Late Circadian Mention.md")

    assert "circadian" not in note["excerpt"].lower()
    assert note["term_counts"]["circadian"] == 1


def test_scan_indexes_configured_full_body_phrases(sample_project):
    filler = " ".join(["ordinary context"] * 120)
    _write_raw(
        sample_project.vault / "03_Research" / "Late Phrase Mention.md",
        f"""---
title: Late Phrase
type: intelligence-brief
status: active
domains: [research]
thesis_areas: []
related: []
tags: [test]
---

# Late Phrase

{filler}

The important detail appears late: sleep hygiene support changes the workflow.
""",
    )

    result = scan_vault(sample_project.config)
    note = next(item for item in result["inventory"]["files"] if item["path"] == "03_Research/Late Phrase Mention.md")

    assert "sleep hygiene" not in note["excerpt"].lower()
    assert note["phrase_counts"]["sleep_hygiene"] == 1
