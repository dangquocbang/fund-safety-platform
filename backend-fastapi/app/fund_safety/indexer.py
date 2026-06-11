from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import re
from typing import Any

from .models import MethodEvidence, CallKind, EvidenceLevel
from .scanner import scan_repo

EXCLUDE_PATH_HINTS = (
    "/test/", "/tests/", "/generated/", "/migration/", "/resources/",
    "/common/", "/util/", "/utils/", "/proto/", "/logging/", "/mock/",
    "/mocked/", "/entity/", "/model/", "/dto/", "/config/", "/constant/",
    "/exception/", "/target/", "/build/", "/vendor/", "/node_modules/", "/.git/",
)
EXCLUDE_NAME_HINTS = (
    "dto", "request", "response", "config", "configuration", "properties",
    "constant", "data", "mapper", "converter", "exception", "test", "mock",
)
# Lifecycle / framework boilerplate methods that never handle fund logic directly.
LIFECYCLE_METHOD_NAMES = frozenset({
    "start", "stop", "shutdown", "close", "open", "init", "initialize",
    "boot", "teardown", "configure", "setup", "cleanup", "destroy", "run",
    "model",  # DB row-to-domain mapper — not fund business logic
})
P0_HINTS = (
    "debit", "credit", "charge", "capture", "transfer", "payout", "disburse",
    "withdraw", "settle", "settlement", "refund", "reverse", "reversal",
    "book", "postentry", "ledger", "wallet", "bank", "paymentgateway", "partner",
)
P1_HINTS = (
    "webhook", "ipn", "callback", "consumer", "kafka", "rabbit", "event",
    "process", "execute", "submit", "confirm", "cancel", "expire", "retry",
    "timeout", "transaction", "order", "requestid", "operationid", "idempotency",
)
P2_HINTS = (
    "outbox", "status", "state", "create", "update", "mark", "lock", "dedup",
    "compensate", "reconcile", "reconciliation",
)

@dataclass
class IndexEntry:
    id: str
    language: str
    file_path: str
    class_name: str | None
    method_name: str
    signature: str
    start_line: int
    end_line: int
    annotations: list[str]
    dependencies: list[str]
    call_names: list[str]
    signals: list[str]
    candidate_priority: str
    candidate_reason: str


def _path_excluded(path: str) -> bool:
    p = "/" + path.replace("\\", "/").lower()
    return any(h in p for h in EXCLUDE_PATH_HINTS) or any(h in Path(p).name for h in EXCLUDE_NAME_HINTS)


def _dependencies(method: MethodEvidence) -> list[str]:
    deps: set[str] = set()
    for ev in method.call_evidence:
        if ev.receiver:
            deps.add(ev.receiver)
    return sorted(deps)[:12]


def _signals(method: MethodEvidence) -> list[str]:
    sig = []
    if method.is_entrypoint: sig.append("entrypoint")
    if method.is_consumer: sig.append("consumer")
    if method.has_transaction_boundary: sig.append("transactional")
    if method.has_idempotency_signal: sig.append("idempotency_signal")
    if method.has_durable_state_signal: sig.append("durable_state_signal")
    if method.has_retry_signal: sig.append("retry_signal")
    if method.has_compensation_signal: sig.append("compensation_signal")
    if method.has_inbox_dedup_signal: sig.append("inbox_dedup_signal")
    for ev in method.call_evidence:
        if ev.kind == CallKind.EXTERNAL_FUND and ev.level == EvidenceLevel.PROVEN:
            sig.append("proven_external_fund_call")
            break
    return sorted(set(sig))


def classify_candidate(method: MethodEvidence) -> tuple[str, str]:
    if not method.is_executable_logic or _path_excluded(method.file_path):
        return "SKIP", "non-business/support/test/model method"
    if method.method_name.lower() in LIFECYCLE_METHOD_NAMES:
        return "SKIP", "lifecycle/infrastructure method"
    # Exclude callee names from hint matching: a method that merely calls fund code
    # (e.g. start() → processPayment()) must not itself appear as a fund candidate.
    text = " ".join([method.method_name, method.signature, method.file_path]).lower()
    proven_fund = [ev for ev in method.call_evidence if ev.kind == CallKind.EXTERNAL_FUND and ev.level == EvidenceLevel.PROVEN]
    plausible_fund = [ev for ev in method.call_evidence if ev.kind == CallKind.EXTERNAL_FUND and ev.level == EvidenceLevel.PLAUSIBLE]
    if proven_fund or (method.is_entrypoint and any(h in text for h in P0_HINTS)):
        return "P0", "direct or boundary-reachable financial side-effect candidate"
    if method.is_consumer or method.has_retry_signal or method.has_idempotency_signal or plausible_fund or any(h in text for h in P1_HINTS):
        return "P1", "financial workflow/event/idempotency/retry candidate"
    if method.has_durable_state_signal or method.has_compensation_signal or any(h in text for h in P2_HINTS):
        return "P2", "supporting state mutation around financial flow"
    return "SKIP", "no finance/idempotency discovery signal"


def build_method_index(source: str | Path) -> tuple[list[MethodEvidence], list[IndexEntry]]:
    methods = scan_repo(source)
    entries: list[IndexEntry] = []
    for m in methods:
        priority, reason = classify_candidate(m)
        if priority == "SKIP":
            continue
        entries.append(IndexEntry(
            id=m.id,
            language=m.language.value,
            file_path=m.file_path,
            class_name=m.class_name,
            method_name=m.method_name,
            signature=m.signature.replace("\n", " ")[:240],
            start_line=m.start_line,
            end_line=m.end_line,
            annotations=m.annotations,
            dependencies=_dependencies(m),
            call_names=m.calls[:24],
            signals=_signals(m),
            candidate_priority=priority,
            candidate_reason=reason,
        ))
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    entries.sort(key=lambda e: (priority_order.get(e.candidate_priority, 9), e.file_path, e.start_line))
    return methods, entries


def render_index_text(entries: list[IndexEntry], project: str) -> str:
    lines = [f"PROJECT: {project}", "", "# Method/API Index", ""]
    grouped: dict[str, list[IndexEntry]] = {}
    for e in entries:
        cls = e.class_name or Path(e.file_path).stem
        grouped.setdefault(f"{e.file_path}::{cls}", []).append(e)
    for key, items in grouped.items():
        file_path, cls = key.split("::", 1)
        lines += [f"CLASS: {cls}", f"FILE: {file_path}"]
        anns = sorted({a for e in items for a in e.annotations})
        deps = sorted({d for e in items for d in e.dependencies})[:12]
        lines += [f"ANNOTATIONS: {' '.join(anns)}", f"DEPENDENCIES: {', '.join(deps)}", "METHODS:"]
        for e in items[:40]:
            lines.append(f"- [{e.candidate_priority}] {e.method_name} lines {e.start_line}-{e.end_line} :: {e.signature}")
            lines.append(f"  signals: {', '.join(e.signals) or '-'}")
            lines.append(f"  reason: {e.candidate_reason}")
            if e.call_names:
                lines.append(f"  calls: {', '.join(e.call_names[:12])}")
        lines.append("---")
    return "\n".join(lines)


def entries_to_dict(entries: list[IndexEntry]) -> list[dict[str, Any]]:
    return [asdict(e) for e in entries]
