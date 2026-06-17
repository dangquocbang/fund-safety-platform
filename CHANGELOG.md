# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Markdown rendering in chat.** Assistant replies (which are markdown) now
  render as formatted HTML — headings, bold/italic, inline & fenced code,
  ordered/unordered lists, tables, and links — instead of showing raw `##`,
  `**`, and `|` characters. Rendering escapes HTML first and only allows safe
  link schemes, so model output can't inject markup. User messages stay plain.
- **Syntax highlighting for code blocks.** Fenced code is colorized with a
  vendored, offline copy of highlight.js (github-dark theme), with language
  auto-detection when the fence has no language hint. highlight.js escapes its
  own output, keeping rendering XSS-safe.
- **Dashboard polish.** Consistent section spacing; the redundant "Open" metric
  card (always equal to Findings) was replaced with a red "Critical" card; and
  Recent Scans gained a Project column so each scan shows which project it ran
  against.
- **Role-aware Create Project.** The dashboard's Create Project form (inputs +
  button) is now disabled for read-only `viewer` accounts, with a short note
  explaining why — matching the backend, which already rejects creation by
  viewers.

### Changed
- **Chat is now LLM-first.** When a provider is enabled, the model answers every
  question grounded in the full audit context (audited functions, R1–R11
  statuses, risks, fixes, scores) plus the focused function's source when one is
  clearly referenced — instead of the old keyword router that only reached the
  model on an exact "function + rule" match and otherwise returned canned
  clarification/generic text. The deterministic router is kept only as the
  fallback when the LLM is intentionally disabled (`mock`/`off`).
- **Out-of-scope guard.** A dedicated chat system prompt restricts the assistant
  to this project's fund-safety audit: it grounds answers only in the provided
  audit data, says so when a named function wasn't audited, politely declines
  unrelated questions, and replies in the user's language.

## [1.1.0] - 2026-06-17

### Added
- **Chat history persistence** — chat turns are now stored server-side
  (`ChatMessageRecord` table) scoped by scan + user, restored when the chat
  page is opened. Added `GET` (load history) and `DELETE` (clear history)
  endpoints under `/ui/api/chats/{scan_id}/messages` and
  `/api/chats/{scan_id}/messages`.
- **Multi-turn chat context** — prior conversation turns are now included in
  the LLM prompt, so follow-up questions are answered with context.

### Changed
- **Chat surfaces real LLM errors** — when the model call fails (bad key,
  network/timeout, provider 4xx, etc.) the chat now returns an explicit error
  with the provider's reason instead of silently falling back to a generic
  deterministic message that users mistook for a real answer. Failed turns are
  not persisted, so a retry starts clean.
- **Scan/assessment surfaces audit failures** — when the assessment model is
  enabled but the call fails (or returns unusable/incomplete output), the scan
  is now reported as `FAILED` with the model error instead of silently
  producing a default heuristic R1–R10 assessment matrix. The deterministic
  assessment is still used when the provider is intentionally disabled
  (`mock`/`off`).
- **OpenAI-compatible provider** — `temperature` is only sent when explicitly
  configured (the `gpt-5` family rejects `temperature=0`), and provider `4xx`
  responses now surface the error body explaining why the call failed.

### Fixed
- **`config/llm.yaml`** — corrected the `api_key_env` typo
  `OPEN_API_KEY` → `OPENAI_API_KEY`. The wrong variable name meant the API key
  was never read, which is why the model never ran and the fallback result kept
  showing.

### Chore
- Stopped tracking `.venv/` and `__pycache__/` in git and added them to
  `.gitignore` (the committed `.venv` was a broken cross-machine symlink tree).

[Unreleased]: https://github.com/dangquocbang/fund-safety-platform/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/dangquocbang/fund-safety-platform/releases/tag/v1.1.0
