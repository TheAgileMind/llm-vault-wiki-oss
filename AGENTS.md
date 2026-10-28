# LLM Vault Wiki - Agent Context

`llm-vault-wiki` is a deterministic CLI control plane for maintaining a mature
Obsidian vault with coding agents. It implements the LLM Wiki pattern in a
guarded form: index first, generate context packs and proposed edits, and
require dry runs and human review before mutating vault notes.

The vault is the source of truth. Generated manifests, reports, and run
artifacts stay under `.llm-vault-wiki/` (gitignored).

## Core guardrails

- Do not mutate vault notes during scan/query/ingest/lint.
- `apply` must default to dry run.
- Real writes require `--execute --reviewed` and must pass folder policy.
- Never index excluded paths such as `.env`, `node_modules`, `.git`, or
  `05_Journal/Personal/**`.
- Treat high-risk folders (for example `06_Proof_Points`) as read/report only.
- Prefer small batches and generated reports over broad automatic edits.
- Treat `.llm-vault-wiki/` run artifacts as private; they can contain excerpts
  and local paths from the vault.

## Commands

```bash
python -m llm_vault_wiki --config llm-vault-wiki.yaml scan
python -m llm_vault_wiki --config llm-vault-wiki.yaml lint
python -m llm_vault_wiki --config llm-vault-wiki.yaml query "AI agents guardrails" --limit 10
python -m llm_vault_wiki --config llm-vault-wiki.yaml evaluate-search --profile agent_systems
python -m pytest -q
```
