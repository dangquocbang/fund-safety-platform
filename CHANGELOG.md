# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
