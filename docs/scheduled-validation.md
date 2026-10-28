---
title: Scheduled Validation Guide
type: operator-guide
status: active
date: 2026-05-17
---

# Scheduled Validation Guide

Use scheduled validation to keep `llm-vault-wiki` honest after the guided source workflow is working. The scheduled run is read-only: it scans, lints, evaluates saved profiles, records timings, and writes reports. It does not create, edit, move, or archive vault notes.

## What Runs Where

- GitHub Actions validates repo health with tests and fixture-based checks.
- Local scheduled validation validates the real Obsidian vault because the vault path is private and local.
- Do not point GitHub-hosted runners at the real vault path unless a deliberate self-hosted runner is added later.

## Manual Validation

Run from the repo root:

```powershell
$env:PYTHONPATH='src'
python -m llm_vault_wiki --config llm-vault-wiki.yaml validate-system
```

The command writes:

- `.llm-vault-wiki/runs/<timestamp>-system-validation/system-validation.json`
- `.llm-vault-wiki/runs/<timestamp>-system-validation/system-validation.md`
- `.llm-vault-wiki/generated/system-validation.latest.json`
- `.llm-vault-wiki/runs/<timestamp>-brain-health/brain-health.json`
- `.llm-vault-wiki/runs/<timestamp>-brain-health/brain-health.md`

The run is healthy when:

- `ok` is `true`;
- lint errors are `0`;
- stale manifest count is `0`;
- saved profiles are green;
- brain health is pass or has only understood advisory next actions;
- warnings are explainable and not quality gate failures.

## Suggested Cadence

### Daily Lightweight Check

Use this before or after a normal source-processing session:

```powershell
$env:PYTHONPATH='src'
python -m llm_vault_wiki --config llm-vault-wiki.yaml validate-system
```

### Weekly Deep Check

Run the system validation, then inspect the Markdown report and profile reports listed in the JSON:

```powershell
$env:PYTHONPATH='src'
python -m llm_vault_wiki --config llm-vault-wiki.yaml validate-system
```

If a profile fails, open the profile's `search-evaluation.md` report before changing query policy or relevance patterns.

Also inspect the linked `brain-health.md` report. It is the fastest operator
view for stale manifests, profile failures, weak profiles, source candidates,
and next actions.

The source-filing signal is split into narrower profiles:

- `source_workflow_docs` checks the workflow documentation and session-note surface.
- `processed_source_captures` checks source-capture and archive retrieval.
- `canonical_file_back_notes` checks canonical notes produced by the file-back loop.

## Windows Task Scheduler Recipe

After one manual validation passes, create a local scheduled task. Adjust the time if needed.

```powershell
schtasks /Create /SC DAILY /TN "LLM Vault Wiki Validation" /TR "powershell -NoProfile -ExecutionPolicy Bypass -Command Set-Location '<repo-root>'; $env:PYTHONPATH='src'; python -m llm_vault_wiki --config llm-vault-wiki.yaml validate-system" /ST 08:00
```

The local machine must be awake and able to access the vault path when the task runs.

## Codex Automation Option

Codex can also create a recurring local validation after `validate-system` has passed manually. The automation should run the same read-only command and report the latest JSON/Markdown artifact path.

Do not schedule vault mutation commands. Scheduled runs should only validate.

## Failure Triage

Start with `quality_gate_violations` in the validation JSON.

- `lint`: open `.llm-vault-wiki/generated/lint.report.md`.
- `stale_manifest`: rerun `scan`, then inspect missing files.
- `search_profile`: open the failed profile's `search-evaluation.md`.
- `duration_regression`: compare the current and previous run before optimizing.

After fixing the cause, rerun:

```powershell
$env:PYTHONPATH='src'
python -m llm_vault_wiki --config llm-vault-wiki.yaml validate-system
```
