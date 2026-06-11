# Fund Safety Platform - AI Agent Operating Rules

## Mission

Build and maintain **Fund Safety Platform**, an AI-assisted engineering auditor for fintech source code.

The platform helps engineering teams detect idempotency, retry-safety and fund-loss risks before production.

## Non-Negotiable Architecture

### Core Pipeline

Do not break this pipeline:

```text
Upload ZIP
↓
Python build_index
↓
Discovery Provider
↓
targets.yml
↓
Assessment Provider
↓
assessment.json + assessment_summary.md
↓
Runtime HTML Render
↓
UI
```

### Discovery and Assessment Are Separate

Discovery selects targets and expands depth.
Assessment evaluates targets with R1-R11.

Supported discovery providers:

- claude_code
- anthropic_api
- ollama
- mock

Supported assessment providers:

- junie
- claude_code
- anthropic_api
- openai
- ollama
- mock

## Technology Rules

- Python-only GUI.
- No NextJS.
- No npm dependency.
- SQLite-first for Phase 1.
- FastAPI + Jinja2 templates.
- Configuration lives under `backend-fastapi/config/`.
- Prompts live under `backend-fastapi/prompts/`.

## Artifact Rules

Each scan must create an immutable scan workspace under:

```text
backend-fastapi/scan_storage/user-<user_id>/<project_slug>/scan-<timestamp>/
```

Canonical artifacts:

- `artifact_manifest.json`
- `assessment.json`
- `assessment_summary.md`

Internal artifacts:

- `index.txt`
- `targets.yml`
- `target_assessments.json`
- `findings.md`
- `knowledge_graph.json`
- `risk_scores.json`

Never persist duplicated HTML artifacts.

Forbidden files:

- `summary.html`
- `assessment_summary.html`
- `idempotency_audit_summary.html`

HTML report must be rendered at runtime from `assessment_summary.md`.

## UI Rules

The UI should show only the human-facing report:

- Fund Safety Assessment Report

Do not expose internal artifacts in the UI:

- `assessment.json`
- `targets.yml`
- `target_assessments.json`
- `knowledge_graph.json`
- `risk_scores.json`
- `artifact_manifest.json`

## Rule and Reasoning Rules

Never use keyword matching as final truth.

`fund_methods` or fund ontology is only prior knowledge / domain vocabulary.

Final assessment must be driven by:

- method/API index
- discovery target selection
- code evidence
- assessment provider reasoning
- R1-R11 assessment matrix

## Documentation Rules

Keep:

- `docs/rbac.md`

Do not recreate:

- `docs/POLICY_RULES.md`

Rule metadata belongs in:

- `backend-fastapi/config/assessment.yaml`

Assessment reasoning guidelines belong in:

- `backend-fastapi/prompts/assessment/CLAUDE_GO.md`
- `backend-fastapi/prompts/assessment/CLAUDE_JAVA.md`

## Coding Agent Behavior

Before changing code:

1. Read `AGENTS.md`.
2. Read `.ai/memory/project_state.md`.
3. Read `.ai/memory/architecture.md`.
4. Read `.ai/tasks/current_task.md`.
5. Inspect relevant source files.

After changing code:

1. Run `python -m compileall backend-fastapi/app` if possible.
2. Explain changed files.
3. Do not make unrelated changes.
