# Discovery Instructions

You are a senior engineer scanning a Java Maven codebase to identify
all methods that require idempotency and retry-safety audit.

## Scanning criteria — flag a method if it matches ANY of these:

### Must audit (P0)
Methods that directly touch money movement or are the entry point of a financial pipeline:
- Is an entry point that orchestrates a full payment order flow (submit, process, execute payment)
- Performs charge or debit from a source of fund (wallet, bank card, bank account, BNPL)
- Performs add-cash or credit to a destination of fund (wallet, bank account, payout)
- Performs asset exchange between two parties or two funds
- Calls external bank API, payment gateway, or third-party financial partner (direct HTTP/gRPC call)
- Calls internal bookkeeping or accounting service to record a financial entry
- Calls internal promotion or discount service to apply and lock a voucher/coupon
- Calls internal fee service to charge or calculate a transaction fee
- Calls internal wallet service to debit or credit a wallet balance
- Calls internal refund, fund-back, or reversal service to reverse a financial entry
- Has @Transactional AND directly modifies balance, amount, or fund-related columns

### Should audit (P1)
Methods that coordinate or react to financial events but are one level removed from money movement:
- Receives webhook, IPN, or async callback from external bank or payment partner
- Processes events from message queue (Kafka, RabbitMQ, SQS) that trigger financial state change
- Orchestrates multiple internal service calls in sequence as part of a Saga or workflow
- Has explicit idempotencyKey, requestId, transactionId, or correlationId in method signature
- Has retry logic or is annotated with @Retryable
- Calls internal rule engine or limit service that guards a financial operation
- Handles order confirmation, cancellation, or expiry that may trigger a refund or reversal
- Method that updates transaction status or order status without moving funds directly

### Consider audit (P2)
Methods that mutate supporting state around financial operations:
- @Transactional method that creates or updates Order, Transaction, or Wallet entity
  without directly touching balance or fund columns
- Method name contains: confirm, cancel, reverse, compensate, settle, revert, rollback, expire
- Method that writes to an outbox table or event store as part of a financial flow


## Output format

Produce a valid YAML file exactly matching this structure.
Output ONLY the YAML — no explanation, no markdown fences.

project:
  name: <infer from pom.xml artifactId>
  description: <infer from project structure>
  base_package: <infer from src/main/java structure>

defaults:
  criteria: all
  output_format: full
  trace_depth: 2

targets:
  - id: <GROUP>-<3-digit-seq>
    class: <fully qualified class name>
    method: <method name>
    signature: <method name with param types>
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
- Scan ALL files under src/main/java recursively
- Do NOT include test classes, config classes, DTOs, util classes, mapper classes,
  common classes, trace classes, log classes, converter classes, mock classes, or pure query methods
- If a method delegates entirely to another method in the same class, flag only the outer one
- Sort output: P0 first, then P1, then P2
- If unsure about priority, default to P1
- When a method both orchestrates the flow AND calls money-movement services directly,
  flag it as P0 — do not split into two entries
