---
title: Guided Source Workflow Operator Guide
type: operator-guide
status: active
date: 2026-05-17
---

# Guided Source Workflow Operator Guide

Use this guide when processing one raw source capture from the Obsidian vault into a canonical vault note.

## Success Criteria

A source-processing run is complete when:

- the raw source is archived under `08_Archive/LLM_Vault_Wiki/`;
- the canonical note exists in the right project/domain/research/content folder;
- the canonical note preserves source metadata and citations;
- the canonical note's `source` points to the archive path;
- the canonical note's `source_capture` points to the original inbox path;
- `process-source` reports `quality_validation.ok: true`;
- lint has 0 errors;
- stale manifest count is 0;
- the canonical note ranks top 3 for its validation query;
- saved evaluation profiles remain green.

## Normal Command Loop

Run commands from the repo root:

```powershell
$env:PYTHONPATH='src'
```

### 1. Generate The Handoff

```powershell
python -m llm_vault_wiki --config llm-vault-wiki.yaml process-source `
  --source "00_Inbox/source-name.md" `
  --draft-apply-plan `
  --archive-source `
  --limit 8
```

Read the JSON output and confirm:

- `status` is `review_ready`;
- `file_back.ready_for_agent_draft` is `true`;
- `draft_apply_plan.target_exists` is `false`;
- `draft_apply_plan.target_path` is the right folder;
- `draft_apply_plan.archive_path` is under `08_Archive/LLM_Vault_Wiki/`;
- `quality_validation.status` is `pending_execution`.

Open the generated files:

- `draft_apply_plan.apply_plan_skeleton`
- `draft_apply_plan.writer_prompt`
- `file_back_brief.markdown`

### 2. Fill The Apply Plan

Edit only the semantic placeholders in `apply-plan.skeleton.json`:

- `Source-Grounded Summary`
- `Direct Source Claims`
- `Agent Interpretation / Implications`
- `Recommended Action`

Do not change:

- operation order;
- operation paths;
- `source`;
- `source_capture`;
- `domains`;
- `tags`;
- policy-sensitive frontmatter;
- archive operation.

The archive operation must remain after `create_file`.

### 3. Dry-Run The Filled Plan

```powershell
python -m llm_vault_wiki --config llm-vault-wiki.yaml process-source `
  --source "00_Inbox/source-name.md" `
  --plan "path/to/filled-apply-plan.json" `
  --limit 8
```

Proceed only when:

- `status` is `awaiting_final_approval`;
- every proposed operation has `status: dry_run`;
- `quality_validation.created_files` lists the canonical note path;
- `quality_validation.archived_files` lists the archive path;
- no file has been created or archived yet.

### 4. Execute After Review

```powershell
python -m llm_vault_wiki --config llm-vault-wiki.yaml process-source `
  --source "00_Inbox/source-name.md" `
  --plan "path/to/filled-apply-plan.json" `
  --execute `
  --reviewed `
  --limit 8
```

The run is complete when:

- `status` is `applied`;
- every proposed operation has `status: applied`;
- `quality_validation.ok` is `true`;
- `quality_validation.lint.errors` is `0`;
- `quality_validation.stale_manifest.count` is `0`;
- `quality_validation.retrieval.rank` is `1`, `2`, or `3`;
- every saved profile in `quality_validation.saved_profiles.profiles` has `ok: true`.

## Post-Run Spot Check

Open the canonical note and verify:

- the title is right;
- frontmatter metadata is preserved;
- `source` points to `08_Archive/LLM_Vault_Wiki/...`;
- `source_capture` points to the original inbox path;
- source claims cite the source URLs;
- interpretation is separated from source facts.

Confirm the raw source no longer exists in `00_Inbox` and exists in the archive.

## If A Gate Fails

Use `quality_validation.quality_gate_violations` as the repair list.

Common fixes:

- `lint`: open the lint report and fix the reported note/frontmatter/link issue.
- `stale_manifest`: rerun `scan`, then inspect missing files.
- `retrieval_rank`: improve title, metadata, or canonical note wording so the target ranks top 3.
- `saved_evaluation_profiles`: inspect the failed profile report under the listed `run_dir`.

Do not manually move/delete vault files to force the gate green. Fix the plan or note, then rerun the guarded workflow.

## Periodic Health Check

Run this after merges or before a larger processing session:

```powershell
python -m pytest -q
$env:PYTHONPATH='src'; python -m llm_vault_wiki --config llm-vault-wiki.yaml validate-system
```

`validate-system` is read-only. It runs scan, lint, stale-manifest checks, saved
evaluation profiles, and duration/trend reporting, then writes JSON and Markdown
reports under `.llm-vault-wiki/runs/`.

`validate-system` also writes a read-only brain-health report. Use it as the
operator summary before opening lower-level scan, lint, or profile artifacts.

For a question-specific synthesis package, run:

```powershell
python -m llm_vault_wiki --config llm-vault-wiki.yaml synthesize "AI agent guardrails and evaluation" --limit 8
```

`synthesize` is read-only. It does not call an LLM provider and does not mutate
the vault. It creates a cited brief, deterministic gap signals, and an agent
prompt that Codex or Claude can use to answer with citations.

For a standalone health report from the latest manifests and validation run:

```powershell
python -m llm_vault_wiki --config llm-vault-wiki.yaml brain-health
```

`brain-health` is also read-only. It surfaces stale manifests, profile failures,
weak profiles, inbox/source candidates, and recommended next actions.

Saved profile intent (see `llm-vault-wiki.example.yaml`):

- `agent_systems`: protects AI agent, coding agent, guardrail, evaluation, and context-pack retrieval.
- `source_workflow_docs`: protects guided source workflow, file-back, apply-plan, and quality-validation documentation retrieval.
- `canonical_file_back_notes`: protects canonical notes produced by the file-back loop.

For local scheduling, see `docs/scheduled-validation.md`.
