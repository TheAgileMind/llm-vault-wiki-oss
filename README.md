# llm-vault-wiki

A deterministic, local Python CLI that lets coding agents (Codex, Claude Code)
maintain a large Obsidian vault safely. It is inspired by Andrej Karpathy's
"LLM Wiki" idea, with guardrails added for a vault that is already in daily use.

The CLI makes no LLM API calls. It does the deterministic work (scan, index,
retrieve, lint, validate) and produces context packs and plans; the agent
does the reasoning; a human approves every write.

What it demonstrates:

- **Retrieval with measured quality.** `evaluate-search` reports precision@k,
  recall, misses, and noisy hits against regex truth sets. Saved profiles act
  as regression benchmarks.
- **Guarded writes.** Changes go through JSON apply plans that are checked
  against per-folder policy, dry-run by default, and require
  `--execute --reviewed` to touch the vault.
- **An end-to-end agent workflow.** `process-source` takes one inbox capture
  through scan, ingest, a file-back brief, an apply-plan skeleton and writer
  prompt, reviewed execution, and post-write quality gates.
- **System health checks.** `validate-system` and `brain-health` run scan, lint,
  stale-manifest checks, and saved search profiles, and write JSON/Markdown reports.

## Install

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp llm-vault-wiki.example.yaml llm-vault-wiki.yaml   # set vault_root
```

## Usage

```bash
llm-vault-wiki --config llm-vault-wiki.yaml scan
llm-vault-wiki --config llm-vault-wiki.yaml query "AI agent guardrails"
llm-vault-wiki --config llm-vault-wiki.yaml evaluate-search --profile agent_systems
llm-vault-wiki --config llm-vault-wiki.yaml process-source --source "00_Inbox/transcript.md" --draft-apply-plan
llm-vault-wiki --config llm-vault-wiki.yaml apply path/to/plan.json                 # dry run
llm-vault-wiki --config llm-vault-wiki.yaml apply path/to/plan.json --execute --reviewed
llm-vault-wiki --config llm-vault-wiki.yaml validate-system
llm-vault-wiki --config llm-vault-wiki.yaml lint
```

Runtime state (manifests, reports, run artifacts) is written to
`.llm-vault-wiki/`, which is gitignored because it can contain vault excerpts.
See `docs/operator-guide-guided-source-workflow.md` and
`docs/scheduled-validation.md` for the operating loop.

## Tests

```bash
python -m pytest -q
```

The 72 tests use a synthetic vault built in a temp directory; CI runs them on
every push.

## License

MIT
