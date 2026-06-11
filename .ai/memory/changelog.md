# Change Log

## 2026-06-09

### Architecture

- Adopted Python-only GUI.
- Removed NextJS/npm dependency.
- Adopted SQLite-first local storage.
- Merged scanner logic into backend.
- Separated discovery provider and assessment provider.
- Adopted runtime HTML rendering from Markdown.
- Removed duplicated persisted HTML reports.
- Removed `docs/POLICY_RULES.md`.
- Kept `docs/rbac.md`.

### Artifacts

- Each scan now stores canonical artifacts in scan-specific workspace.
- UI only shows Fund Safety Assessment Report.
- Internal artifacts remain hidden.
