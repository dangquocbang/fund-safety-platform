# Discovery Instructions

You are a senior engineer scanning a Go codebase to identify
all functions and methods that require idempotency and retry-safety audit.

## Scanning criteria — flag a method if it matches ANY of these:

### Must audit (P0)
Methods that directly touch money movement or are the entry point of a financial pipeline:
- Is an entry point that orchestrates a full payment order flow (submit, process, execute payment)
- Performs charge or debit from a source of fund (wallet, bank card, bank account, BNPL)
- Performs add-cash or credit to a destination of fund (wallet, bank account, payout)
- Performs asset exchange between two parties or two funds
- Makes a direct HTTP/gRPC call to external bank API, payment gateway, or third-party financial partner
- Calls internal bookkeeping or accounting service to record a financial entry
- Calls internal promotion or discount service to apply and lock a voucher/coupon
- Calls internal fee service to charge or calculate a transaction fee
- Calls internal wallet service to debit or credit a wallet balance
- Calls internal refund, fund-back, or reversal service to reverse a financial entry
- Writes directly to balance, amount, or fund-related columns inside a database transaction

### Should audit (P1)
Methods that coordinate or react to financial events but are one level removed from money movement:
- Receives webhook, IPN, or async callback from external bank or payment partner
- Consumes events from message queue (Kafka, RabbitMQ, SQS, NATS) that trigger financial state change
- Orchestrates multiple internal service calls in sequence as part of a Saga or workflow
- Has explicit idempotencyKey, requestID, transactionID, or correlationID in function signature
- Has retry logic or uses a retry library (go-retry, backoff, etc.)
- Calls internal rule engine or limit service that guards a financial operation
- Uses a distributed lock (Redis, etcd, database row lock) around a financial operation
- Handles order confirmation, cancellation, or expiry that may trigger a refund or reversal

### Consider audit (P2)
Methods that mutate supporting state around financial operations:
- Function that creates or updates Order, Transaction, Wallet, Account, or Ledger entity
  without directly touching balance or fund columns
- Function name contains: confirm, cancel, reverse, compensate, settle, revert, rollback, expire
- Function that writes to an outbox table or event store as part of a financial flow
- Function that updates transaction status or order status without moving funds directly
- Function that calls more than one downstream service and has no visible dedup guard

## Output format

Produce a valid YAML file exactly matching this structure.
Output ONLY the YAML — no explanation, no markdown fences.

The index file starts with a header block (before the first `===` line) that contains:
  PROJECT_NAME, MODULE_PATH, GO_VERSION, BASE_PACKAGE, PACKAGES, GOMOD_FILE

Use these fields to fill in the `project:` block exactly as follows:
  - project.name        = PROJECT_NAME value from the index header
  - project.base_package = BASE_PACKAGE (= MODULE_PATH) value from the index header
  - project.description = 1-2 sentence summary inferred from PACKAGES list in the metadata block.
    Focus on business domain, not folder structure.
    (e.g. "Acquiring core service handling payment order flows including charge, reversal, and disbursement.")

Do NOT leave any project field empty or as a placeholder.

project:
  name: <PROJECT_NAME from index header>
  description: >
    <1-2 sentences inferred from PACKAGES list — focus on business domain>
  base_package: <BASE_PACKAGE from index header>

defaults:
  criteria: all
  output_format: full
  trace_depth: 2

targets:
  - id: <GROUP>-<3-digit-seq>
    class: <fully qualified struct name, e.g. github.com/company/svc/internal/payment.Handler>
    method: <method or function name>
    signature: <method name with param types, e.g. ProcessPayment(ctx context.Context, req *pb.PaymentRequest) (*pb.PaymentResponse, error)>
    group: <payment-flow|reversal|wallet|order|event|other>
    priority: <P0|P1|P2>
    context: >
      <1-3 câu mô tả tại sao method này cần audit,
      external calls nào được thực hiện,
      risk cụ thể là gì>
    focus_criteria: <all | [R1, R2, ...]>
    notes: >
      <điểm nghi ngờ cụ thể nếu có, để trống nếu không>

## Rules
- Scan ALL exported functions and methods (starting with uppercase) from the index
- Do NOT include:
  - Pure query / read-only functions (no state mutation, no external write call)
  - Getter / setter / accessor functions (Get*, Set*, Has*, Is*)
  - Proto / serialization functions (String(), Marshal*, Unmarshal*, ProtoReflect(), Enum*)
  - Constructor / builder functions (New*, Make*, Must*, Build*)
  - Config, logger, tracer, middleware, interceptor setup functions
  - Mock, stub, fake, test helper functions
  - Pure mapping / conversion functions (Map*, Convert*, To*, From*, As*)
- If a function delegates entirely to another function in the same file/struct, flag only the outer one
- For gRPC services: flag the concrete implementation method, not the interface definition
- For HTTP handlers: flag the handler function registered to the router, not middleware
- Sort output: P0 first, then P1, then P2
- If unsure about priority, default to P1
- Use the FILE and PACKAGE fields from the index to infer the fully qualified struct name
- When a function both orchestrates the flow AND calls money-movement services directly,
  flag it as P0 — do not split into two entries
