# Project State

## Product

Fund Safety Platform is an AI-assisted auditor for fintech source code. It reviews idempotency, retry-safety and fund-loss risk in Java/Golang services.

## Current Phase

Phase 1: Python-only demo/platform suitable for AI Agent contest and early internal validation.

## Current Architecture

- Python-only GUI using FastAPI + Jinja2.
- No NextJS.
- No npm.
- SQLite-first.
- Scanner logic merged into `backend-fastapi`.
- Configuration-driven LLM providers.
- Discovery provider and assessment provider are separated.
- UI only shows the Fund Safety Assessment Report.
- Internal artifacts are hidden from UI.

## Current Pipeline

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

## Runtime Inputs

- `backend-fastapi/config/*.yaml`
- `backend-fastapi/prompts/discovery/*.md`
- `backend-fastapi/prompts/assessment/*.md`

## Scan Artifacts

Each scan creates an immutable workspace under:

```text
backend-fastapi/scan_storage/user-<user_id>/<project_slug>/scan-<timestamp>/
```

The canonical human-readable artifact is:

```text
assessment_summary.md
```

HTML is rendered at runtime; it is not persisted.

## Kept Documents

- `docs/rbac.md`

## Removed Documents

- `docs/POLICY_RULES.md`

## Important Principles

- Do not use keyword scanner as final truth.
- `fund_methods` is ontology/context only.
- Assessment provider output is the source of truth for R1-R11 results.
