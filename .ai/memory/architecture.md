# Architecture Decisions

## ADR-001: Python-only GUI

Status: Accepted

Use FastAPI + Jinja2 templates for Phase 1.

Reason:

- Avoid npm dependency.
- Easier PyCharm development.
- More reliable contest demo.

## ADR-002: SQLite-first

Status: Accepted

Use SQLite for Phase 1.

Reason:

- No external DB service required.
- Easy local run.
- Can migrate to Postgres later.

## ADR-003: Scanner merged into backend

Status: Accepted

Scanner logic lives inside `backend-fastapi/app`.

Reason:

- Phase 1 does not need worker/service separation.
- Easier debugging and deployment.

## ADR-004: Discovery and Assessment are separate providers

Status: Accepted

Discovery provider creates `targets.yml`.
Assessment provider creates `assessment.json` and `assessment_summary.md`.

Reason:

- Discovery and assessment require different reasoning styles.
- Allows combinations such as Claude discovery + Junie assessment.

## ADR-005: Assessment summary is canonical human report

Status: Accepted

The canonical human-readable report is `assessment_summary.md`.

Reason:

- Same artifact works for Claude/Junie/OpenAI/Ollama output.
- Easy runtime rendering.

## ADR-006: Runtime HTML rendering

Status: Accepted

Do not persist HTML reports. Render Markdown to HTML at runtime.

Forbidden persisted files:

- `summary.html`
- `assessment_summary.html`
- `idempotency_audit_summary.html`

Reason:

- Avoid duplicated artifacts.
- Keep scan folder clean.

## ADR-007: Hide internal artifacts from UI

Status: Accepted

UI shows only the Fund Safety Assessment Report.

Internal artifacts remain available for backend/AI use only.

## ADR-008: No `docs/POLICY_RULES.md`

Status: Accepted

Rules are maintained in:

- `backend-fastapi/config/assessment.yaml`
- `backend-fastapi/prompts/assessment/*.md`

Reason:

- Avoid duplicated policy documents and knowledge drift.

## ADR-009: RBAC document is kept

Status: Accepted

Keep `docs/rbac.md` as an architecture/security document.

Reason:

- It documents user roles and permissions.
- It is not duplicated with LLM prompts.
