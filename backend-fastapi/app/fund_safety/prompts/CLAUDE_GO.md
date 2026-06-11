# Idempotency Audit Tool

## Project Overview

Tool for auditing idempotency and retry-safety in Go systems —
identifying operations that may produce different results when executed
multiple times with the same input.

---

## Development Commands

<!-- Add build, test, and run commands here -->

---

## Architecture

<!-- Describe the high-level architecture here -->

---

## Key Conventions

<!-- Document coding standards and project-specific conventions here -->

---

## Your behavior

- Always read the full function body and ALL referenced structs and interfaces before concluding
- Trace into repository, service dependencies, database transactions (sql.Tx, gorm.DB.Transaction),
  Redis locks, and outbox tables if they exist
- Do not assume — if evidence is absent, mark as FAIL
- Be specific: cite file paths, struct names, function names, and line numbers as evidence
- If the target specifies `focus_criteria`, audit ONLY those R# criteria.
  Mark all others as N/A without explanation — do not audit them
- If a target struct or function cannot be found in the codebase,
  write a single row in the summary with status `NOT_FOUND` and skip
  per-method detail. Do not guess or infer a substitute function
- For each function: complete the per-method detail first,
  then append one row to the summary matrix

---

## Criteria reference

> Read and internalize all 11 criteria before applying any guidelines below.

| ID  | Name                                    | Key question                                              |
|-----|-----------------------------------------|-----------------------------------------------------------|
| R1  | Idempotency Boundary Defined            | Key defined? Scope clear? TTL set?                        |
| R2  | Unique Business Intent Defined          | Compound key from inputs? Intent unambiguous?             |
| R3  | Duplicate Detection Exists              | Dedup mechanism exists AND runs before external call?     |
| R4  | In-progress Concurrency Handling        | Two concurrent requests handled correctly?                |
| R5  | State Machine Safe for Retry            | Terminal states immutable? Retry per-state defined?       |
| R6  | Timeout & Partial Execution Recovery    | Timeout ≠ failed? Probe/reconcile exists?                 |
| R7  | External Side-effect Guarded            | Guard before charge/debit/credit? Partner ID stable?      |
| R8  | Persistence & Side-effect Ordering Safe | Local write before external call? No orphan success risk? |
| R9  | Response Consistency                    | Identical response body and status code for same key?     |
| R10 | Compensate / Reversal Safeguard         | Amount ≤ charged? Compensate itself idempotent?           |

### Detailed criteria checklist

**R1. Idempotency Boundary Defined**
- Is an idempotency key / operation ID / transaction ID / refund ID /
  order ID / payment ID / request ID explicitly defined?
- Is the key scope clear (per-user / per-merchant / global)?
- Is a TTL defined for the key?

**R2. Unique Business Intent Defined**
- Is a compound unique key derived from input parameters?
- Is intent unambiguous when partial params change?

**R3. Duplicate Detection Exists**
- Is there a dedup mechanism: unique index / insert-if-absent /
  compare-and-set / dedup table / processed-event registry?
- Does detection happen BEFORE the external call, not after?

**R4. In-progress Concurrency Handling**
- What happens if 2 requests with the same key arrive simultaneously?
- Is there a distributed lock (Redis SETNX, Redlock, etcd) or
  optimistic/pessimistic database lock?

**R5. State Machine Safe for Retry**
- Is the state flow explicit: NEW → PROCESSING → SUCCEEDED / FAILED_FINAL?
- Are SUCCEEDED and FAILED_FINAL immutable terminal states?
- What happens on retry at each state?

**R6. Timeout & Partial Execution Recovery**
- Can the system distinguish: not-started / timed-out-in-flight /
  completed-but-response-lost?
- Is there a probe/reconcile mechanism to verify external state?
- Is context.DeadlineExceeded / context.Canceled handled separately from
  a business error — not silently treated as a retryable failure?

**R7. External Side-effect Guarded**
- Is there a guard check before charge / debit / credit / bank call?
- Is the partner request ID stable across retries?
- Is callback / IPN dedup handled?

**R8. Persistence & Side-effect Ordering Safe**
- Is local state written BEFORE the external call?
- Is transactional outbox used if needed?
- Is there orphan external success risk or double-commit window?
- Are database writes and external calls within the same sql.Tx or gorm transaction?

**R9. Response Consistency**
- Is the response body identical (not just equivalent) for same key?
- Is gRPC status code (codes.OK, codes.AlreadyExists, etc.) consistent across retries?
- Is HTTP status code consistent across retries?

**R10. Compensate / Reversal Safeguard**
- Is compensate only allowed from explicit terminal states?
- Is compensate amount ≤ original charged amount?
- Is the compensate operation itself idempotent?
- Is the compensate key separate from the original operation key?

---

## Audit guidelines for mapping & utility functions

> Exception rules that override the default criteria above.
> Apply ONLY to pure mapping or read-only utility functions.

1. **Determinism (R9)**
    - Key question: does the same input always return the same output
      within the same processing session?
    - Data from in-memory map, constant, or static config → **PASS**
    - Data from database or external API → check if data can change
      between retries; if yes → **PARTIAL**

2. **Atomicity (R5 / R8)**
    - Identify where mapping sits in the main processing flow
    - If mapping occurs BEFORE any side-effect (external API call, DB write):
      a mapping error causes early return → correct behavior → **PASS**

3. **Distributed lock exemption (R4)**
    - Do NOT require distributed lock for pure mapping or read-only functions
    - R4 is only required at the handler or service layer where state
      mutation or external side-effects begin

4. **Evidence-based notes**
    - State confirmations, not questions.
    - Write: `Confirmed: in-memory lookup ensures determinism (R9)`
    - Not: `Check if lookup is deterministic`

---

## Status values

| Status    | Meaning                                                        |
|-----------|----------------------------------------------------------------|
| PASS      | Fully satisfied — clear evidence in code                       |
| PARTIAL   | Partially satisfied — gap exists but not immediately critical  |
| FAIL      | Not satisfied — clear production risk                          |
| N/A       | Not applicable to this function                                |
| NOT_FOUND | Struct or function not found in codebase — audit skipped       |

---

## Output 1: per-method detail report

Append each function's result to `.junie/idempotency_audit_detail.md`.
Use the structure below for each function, separated by `---`.

    ---
    # Audit: `StructName.FuncName`
    **ID:** <target id from targets.yml, e.g. PAY-001>
    **Date:** <today yyyy-MM-dd>
    **Priority:** <P0 | P1 | P2>
    **Context:** <context from targets.yml>

    ## R1. Idempotency Boundary Defined
    - **Status:** PASS | FAIL | PARTIAL | N/A
    - **Evidence:** <specific file path / struct / function / line number>
    - **Risk:** <production risk — leave blank if PASS>
    - **Fix:** <concrete code-level suggestion — leave blank if PASS>

    ## R2. Unique Business Intent Defined
    - **Status:**
    - **Evidence:**
    - **Risk:**
    - **Fix:**

    ## R3. Duplicate Detection Exists
    - **Status:**
    - **Evidence:**
    - **Risk:**
    - **Fix:**

    ## R4. In-progress Concurrency Handling
    - **Status:**
    - **Evidence:**
    - **Risk:**
    - **Fix:**

    ## R5. State Machine Safe for Retry
    - **Status:**
    - **Evidence:**
    - **Risk:**
    - **Fix:**

    ## R6. Timeout & Partial Execution Recovery
    - **Status:**
    - **Evidence:**
    - **Risk:**
    - **Fix:**

    ## R7. External Side-effect Guarded
    - **Status:**
    - **Evidence:**
    - **Risk:**
    - **Fix:**

    ## R8. Persistence & Side-effect Ordering Safe
    - **Status:**
    - **Evidence:**
    - **Risk:**
    - **Fix:**

    ## R9. Response Consistency
    - **Status:**
    - **Evidence:**
    - **Risk:**
    - **Fix:**

    ## R10. Compensate / Reversal Safeguard
    - **Status:**
    - **Evidence:**
    - **Risk:**
    - **Fix:**

    ## Overall
    - **Score:** X / Y  (Y = 10 minus count of N/A)
    - **FAIL:** R#, R#, ...  (or "none")
    - **PARTIAL:** R#, R#, ...  (or "none")
    ---

---

## Output 2: summary matrix

After ALL per-function audits are complete,
produce `.junie/idempotency_audit_summary.md`.

### Matrix rules

1. One row per function, sorted by priority (P0 → P1 → P2) then by struct name
2. Each R# cell contains only the status badge — nothing else
3. Status badges: `✅` PASS · `❌` FAIL · `⚠️` PARTIAL · `—` N/A · `🔍` NOT_FOUND
4. **"Score"** column: `X/Y` where Y = 10 minus count of N/A for that function
5. **"Issues"** column: list every FAIL and PARTIAL R# with a reason,
   max 15 words per item, items separated by ` · `
   If no FAIL and no PARTIAL → write `—`

### `idempotency_audit_summary.md` format

    # Idempotency & Retry-Safety Audit — Summary

    **Project:** <project name from targets.yml>
    **Date:** <today yyyy-MM-dd>
    **Total functions audited:** <n>
    **P0 with FAIL:** <n>
    **P0 with PARTIAL:** <n>

    ---

    ## Result matrix

    | # | Function | Pri | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 | R9 | R10 | Score | Issues |
    |---|----------|-----|----|----|----|----|----|----|----|----|----|----|-------|--------|
    | 1 | `PaymentHandler.ProcessPayment` | P0 | ✅ | ⚠️ | ❌ | ✅ | ✅ | ❌ | ✅ | ⚠️ | ✅ | — | 5/9 | R2: amount missing from compound key · R3: dedup runs after bank call · R6: DeadlineExceeded mapped as retryable · R8: state written after external call |
    | 2 | `RefundService.Refund` | P0 | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | ⚠️ | 8/10 | R6: no reconcile probe for timed-out refunds · R10: compensate key reuses original payment key |

    ---

    ## FAIL details

    > All FAIL items grouped by criteria for cross-cutting visibility.

    ### R3 — Duplicate Detection Exists
    - `PaymentHandler.ProcessPayment`: dedup check at line 87 runs after bankClient.Charge()

    ### R6 — Timeout & Partial Execution Recovery
    - `PaymentHandler.ProcessPayment`: context.DeadlineExceeded at line 102 returned as retryable error

    ---

    ## PARTIAL details

    > All PARTIAL items grouped by criteria.

    ### R2 — Unique Business Intent Defined
    - `PaymentHandler.ProcessPayment`: compound key uses only orderID — amount and currency not included

    ### R8 — Persistence & Side-effect Ordering Safe
    - `PaymentHandler.ProcessPayment`: success state write has a window after external response

    ### R10 — Compensate / Reversal Safeguard
    - `RefundService.Refund`: compensate key falls back to paymentID when refundID is nil

    ---

    ## Recommended fix priority

    | Priority | Function | R# | Action |
    |----------|----------|----|--------|
    | 1 | `PaymentHandler.ProcessPayment` | R3 | Move dedup check before bankClient.Charge() |
    | 2 | `PaymentHandler.ProcessPayment` | R6 | Do not map context.DeadlineExceeded as retryable — add reconcile probe |
    | 3 | `RefundService.Refund` | R10 | Generate stable compensate key independent of paymentID |

---

## File output mapping

| File | Content |
|------|---------|
| `.junie/idempotency_audit_detail.md` | All per-function detail reports, appended sequentially |
| `.junie/idempotency_audit_summary.md` | Matrix + FAIL/PARTIAL details + fix priority table |
