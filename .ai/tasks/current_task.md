# Current Task — Update README.md

## Status: COMPLETED ✅

---

## Vấn đề phát hiện

README.md hiện đang có 4 nhóm lỗi:

| # | Vấn đề | Vị trí |
|---|--------|--------|
| 1 | `R1-R11` → phải là `R1-R10` (đã rename R11→R10) | Config section, Why this design, Clean artifact contract |
| 2 | Entrypoint-first discovery chưa được đề cập | Workflow, Config section |
| 3 | Chat feature thiếu trong Workflow | Workflow |
| 4 | `discovery.yaml` không mô tả `entrypoint_mode` | Config section |

---

## README mới — nội dung đầy đủ

````markdown
# Fund Safety Platform

AI-assisted auditor for fintech source code — reviews idempotency, retry-safety,
and fund-loss risk in Java / Go services.

Stack: FastAPI + Jinja2 + SQLite. No Node.js, no npm, no Postgres.

---

## Quick start

```bash
cd backend-fastapi
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open: `http://localhost:8000`

Demo accounts:

| Email | Password | Role |
|---|---|---|
| admin@fundsafe.local | admin123 | Admin |
| architect@fundsafe.local | architect123 | Architect |
| dev@fundsafe.local | dev123 | Developer |
| viewer@fundsafe.local | viewer123 | Viewer |

---

## How it works

```
Create Project
→ Upload Java / Go service ZIP
→ build_method_index          (Python: scanner + indexer)
→ detect_entrypoints          (entrypoint-first: HTTP/gRPC handlers, Kafka/RabbitMQ consumers)
→ Discovery Provider          (entrypoint-first by default; or Claude / Ollama / mock with LLM)
→ targets.yml                 (selected entrypoints, priority P0/P1/P2, depth-2 evidence)
→ Assessment Provider         (Junie / Claude / OpenAI / Ollama / mock)
→ assessment.json + assessment_summary.md
→ UI renders assessment_summary.md to HTML at request time
→ Risk score / Knowledge graph / Chat
```

### Entrypoint-first discovery

By default (`entrypoint_mode: true` in `discovery.yaml`), the platform selects only
real system entry points as audit targets:

- **HTTP handlers** — `gin.Context`, `echo.Context`, `http.ResponseWriter`, `fiber.Ctx`
- **gRPC service methods** — receiver ending in `Server` / `ServiceServer` + `context.Context`
- **Kafka consumers** — `kafka.Message`, `sarama.ConsumerMessage` parameter
- **RabbitMQ consumers** — `amqp.Delivery` parameter
- **Java** — `@PostMapping`, `@GetMapping`, `@KafkaListener`, `@RabbitListener`, `@GrpcService`

Internal business methods, infra setup functions, and proto boilerplate are excluded.
Targets are assigned priority P0 / P1 / P2 based on fund-signal evidence in the
depth-2 call graph. Falls back to hint-based discovery if no entrypoints are found.

---

## Assessment criteria R1–R10

Every discovered target is evaluated against 10 idempotency and retry-safety criteria:

| ID  | Name                                    | Key question |
|-----|-----------------------------------------|---|
| R1  | Idempotency Boundary Defined            | Key defined? Scope clear? TTL set? |
| R2  | Unique Business Intent Defined          | Compound key from inputs? Intent unambiguous? |
| R3  | Duplicate Detection Exists              | Dedup runs BEFORE external call? |
| R4  | In-progress Concurrency Handling        | Two concurrent same-key requests handled? |
| R5  | State Machine Safe for Retry            | Terminal states immutable? Retry per-state defined? |
| R6  | Timeout & Partial Execution Recovery    | Timeout ≠ failed? Probe/reconcile exists? |
| R7  | External Side-effect Guarded            | Guard before charge/debit/credit? Partner ID stable? |
| R8  | Persistence & Side-effect Ordering Safe | Local write before external call? No orphan success? |
| R9  | Response Consistency                    | Identical response body and status for same key? |
| R10 | Compensate / Reversal Safeguard         | Amount ≤ charged? Compensate itself idempotent? |

Each criterion is rated **PASS / PARTIAL / FAIL / N/A**. Score is shown as `X/Y`
where Y = 10 minus the count of N/A criteria for that target.

---

## Config-first design

Runtime behaviour is driven entirely by YAML under `backend-fastapi/config/`:

```
config/
  app.yaml          # SQLite path, upload path, JWT secret, demo users
  llm.yaml          # discovery provider + assessment provider per stage
  discovery.yaml    # entrypoint_mode, depth, ignore/exclude hints
  assessment.yaml   # R1-R10 enable/disable per criterion, LLM target limits
  graph.yaml        # risk-score weights
  java.yaml         # Java domain vocabulary / fund-signal hints
  golang.yaml       # Go domain vocabulary / fund-signal hints
```

Environment variables override YAML for secrets:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

### discovery.yaml — key settings

```yaml
entrypoint_mode: true   # true → HTTP/gRPC/Kafka/RabbitMQ handlers only (recommended)
                        # false → legacy hint-based fund-keyword mode
depth: 2                # call-graph depth for evidence collection
max_targets: 80
```

---

## Multi-provider reasoning

Discovery and assessment use separate providers. Edit `config/llm.yaml`.

**Example 1 — Claude Code discovery + Junie assessment:**

```yaml
enabled: true

discovery:
  provider: claude_code
  model: claude-sonnet-4-6

assessment:
  provider: junie
  model: junie-local

providers:
  claude_code:
    binary: claude
    args: ["-p"]
  junie:
    binary: junie
    args: ["-p"]
```

**Example 2 — Ollama discovery + OpenAI assessment:**

```yaml
enabled: true

discovery:
  provider: ollama
  model: qwen2.5-coder:14b

assessment:
  provider: openai
  model: gpt-4.1
```

Supported providers:

```
Discovery:  mock | claude_code | anthropic_api | ollama
Assessment: mock | junie | claude_code | anthropic_api | openai | ollama
```

> When `entrypoint_mode: true` (default), the discovery provider is only invoked
> if LLM discovery is explicitly enabled. Otherwise, entrypoint-first discovery
> runs deterministically with no LLM call.

---

## Scan artifacts

Each scan writes into its own immutable folder:

```
backend-fastapi/uploads/reports/user-<id>/<project_slug>/scan-<id>-<timestamp>/
  assessment.json                   ← machine-readable R1-R10 matrix
  <prefix>_assessment_summary.md    ← canonical human-readable report
  artifact_manifest.json            ← canonical artifact names + routes
  index.txt                         ← full method index
  targets.yml                       ← discovered entrypoints + priority
  target_assessments.json           ← per-target R1-R10 results
  findings.md                       ← FAIL/PARTIAL findings
  knowledge_graph.json
  risk_scores.json
```

The **Fund Safety Assessment Report** is rendered from `assessment_summary.md`
at request time — no HTML file is persisted on disk:

```
GET /ui/scans/{scan_id}/assessment-report
```

---

## Why this design

Python is the deterministic orchestrator: upload, indexing, entrypoint detection,
evidence scoping, DB persistence, artifact generation, and UI.

Discovery / assessment providers are invoked only where they are strongest: target
selection and R1-R10 reasoning. The platform is repeatable because providers receive
scoped evidence (entrypoints + depth-2 call graph) instead of the entire repository.

### Clean artifact contract

One human-readable source of truth per scan:
```
*_assessment_summary.md
```

One machine-readable source of truth per scan:
```
assessment.json
```

HTML is a view, rendered on demand. `summary.html` and `assessment_summary.html`
are never written to disk.

---

## Phase 1 scope

The UI intentionally exposes only the canonical **Fund Safety Assessment Report**.
Internal artifacts (`risk_scores.json`, `assessment.json`, `knowledge_graph.json`,
`targets.yml`) remain available for backend / AI Chat use only.
````

---

## Thay đổi so với README cũ

| Mục | Cũ | Mới |
|-----|----|-----|
| `R1-R11` | 4 chỗ | Đổi thành `R1-R10` |
| Workflow | Không có entrypoint-first | Thêm `detect_entrypoints` step |
| Section mới | Không có | Thêm **Assessment criteria R1–R10** (bảng đầy đủ) |
| Section mới | Không có | Thêm **Entrypoint-first discovery** (mô tả HTTP/gRPC/Kafka/RabbitMQ patterns) |
| `discovery.yaml` config | Chỉ liệt kê tên file | Thêm mô tả `entrypoint_mode`, `depth` |
| `assessment.yaml` config | `R1-R11 enable/disable` | `R1-R10 enable/disable` |
| LLM provider note | Không có | Thêm note: entrypoint-first chạy deterministic, không cần LLM |
| Scan artifacts | `targets.yml` không mô tả | Thêm `← discovered entrypoints + priority` |
| Why this design | `R1-R11 reasoning` | `R1-R10 reasoning`, thêm "entrypoint detection" |