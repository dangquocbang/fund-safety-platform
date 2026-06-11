from __future__ import annotations
from .models import MethodEvidence, CallEdge, KeyFlow, Finding, Severity, CallEvidence, CallKind, EvidenceLevel
from .graph import downstream_reachable


def _scope(m: MethodEvidence, downstream: dict[str, list[MethodEvidence]]) -> list[MethodEvidence]:
    return [m] + downstream.get(m.id, [])


def _calls(scope: list[MethodEvidence], kind: CallKind | None = None, level: EvidenceLevel | None = None) -> list[tuple[MethodEvidence, CallEvidence]]:
    result=[]
    for method in scope:
        if not method.is_executable_logic:
            continue
        for ev in method.call_evidence:
            if kind is not None and ev.kind != kind:
                continue
            if level is not None and ev.level != level:
                continue
            result.append((method, ev))
    return result


def _proven_fund_calls(scope: list[MethodEvidence]) -> list[tuple[MethodEvidence, CallEvidence]]:
    return _calls(scope, CallKind.EXTERNAL_FUND, EvidenceLevel.PROVEN)


def _plausible_fund_calls(scope: list[MethodEvidence]) -> list[tuple[MethodEvidence, CallEvidence]]:
    return _calls(scope, CallKind.EXTERNAL_FUND, EvidenceLevel.PLAUSIBLE)


def _has_control(scope: list[MethodEvidence], kind: CallKind) -> bool:
    return bool(_calls(scope, kind))


def _evidence(method: MethodEvidence, ev: CallEvidence, prefix: str = "Evidence") -> list[str]:
    return [
        f"{prefix}: {method.file_path}:{ev.line} `{ev.raw or ev.name}`",
        f"Call classification: {ev.kind.value}/{ev.level.value}, confidence={ev.confidence:.2f}, reason={ev.reason}",
        f"Method: {method.method_name} lines {method.start_line}-{method.end_line}",
    ]


def _durable_before(method: MethodEvidence, fund_call: CallEvidence) -> bool:
    return any(ev.kind == CallKind.DURABLE_STATE and ev.line <= fund_call.line for ev in method.call_evidence)


def _idempotency_before(method: MethodEvidence, fund_call: CallEvidence) -> bool:
    return any(ev.kind == CallKind.IDEMPOTENCY_CONTROL and ev.line <= fund_call.line for ev in method.call_evidence)


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    seen=set(); out=[]
    for f in findings:
        key=(f.rule_id, f.method_id, f.start_line, tuple(f.evidence[:1]))
        if key not in seen:
            seen.add(key); out.append(f)
    return out


def evaluate(methods: list[MethodEvidence], edges: list[CallEdge], key_flows: list[KeyFlow]) -> list[Finding]:
    """Evidence-first fund-safety rules.

    Important design rule: HIGH/CRITICAL findings are created only from PROVEN call evidence,
    never from raw keywords such as `transferId` or DTO/model fields. PLAUSIBLE calls are kept
    in assessment/knowledge graph but only produce lower-confidence hints when tied to concrete controls.
    """
    by_id={m.id:m for m in methods}
    findings=[]
    downstream={m.id: [by_id[x] for x in downstream_reachable(m.id,edges,2) if x in by_id] for m in methods}

    for m in methods:
        if not m.is_executable_logic:
            continue
        scope=_scope(m, downstream)
        proven_fund=_proven_fund_calls(scope)
        if not proven_fund:
            # No concrete money-moving call evidence => no fund-risk finding.
            continue

        has_idem=_has_control(scope, CallKind.IDEMPOTENCY_CONTROL)
        has_inbox=_has_control(scope, CallKind.INBOX_DEDUP) or any(x.has_inbox_dedup_signal for x in scope)
        has_comp=_has_control(scope, CallKind.COMPENSATION) or any(x.has_compensation_signal for x in scope)
        has_tx=any(x.has_transaction_boundary for x in scope)
        has_retry=_has_control(scope, CallKind.RETRY_CONTROL) or any(x.has_retry_signal for x in scope)

        # FS-001 boundary idempotency: only entrypoint/consumer methods are responsible for boundary controls.
        if (m.is_entrypoint or m.is_consumer) and not has_idem:
            target_method, ev = proven_fund[0]
            findings.append(Finding(
                rule_id='FS-001', title='Missing idempotency boundary for confirmed fund flow', severity=Severity.CRITICAL,
                confidence=0.91, file_path=m.file_path, start_line=m.start_line, end_line=m.end_line,
                method_id=m.id, method_name=m.method_name, evidence=_evidence(target_method, ev, 'Confirmed fund side effect'),
                reasoning='Entrypoint/consumer reaches a PROVEN external fund-moving call within depth=2, but no idempotency/dedup/operation-key control was found in the reachable flow.',
                remediation='At the boundary, create or load a durable operation record keyed by idempotency_key/operation_id before any external fund side effect.',
                evidence_level=EvidenceLevel.PROVEN,
            ))

        # FS-002 direct unsafe ordering: side-effect before durable state in the same method.
        for target_method, ev in proven_fund:
            if target_method.id != m.id:
                continue
            if not _durable_before(target_method, ev):
                findings.append(Finding(
                    rule_id='FS-002', title='External fund side effect before durable operation state', severity=Severity.HIGH,
                    confidence=0.88, file_path=target_method.file_path, start_line=ev.line, end_line=target_method.end_line,
                    method_id=target_method.id, method_name=target_method.method_name, evidence=_evidence(target_method, ev, 'Unsafe ordering'),
                    reasoning='A confirmed external fund-moving call appears before any repository/DAO/store operation-state write in the same method.',
                    remediation='Persist PROCESSING operation state first, then call the external dependency, then persist terminal state with CAS/version guard.',
                    evidence_level=EvidenceLevel.PROVEN,
                ))

        # FS-003 retry safety: retry + proven fund + no idem.
        if has_retry and not has_idem:
            target_method, ev = proven_fund[0]
            findings.append(Finding(
                rule_id='FS-003', title='Retry path can re-execute confirmed fund side effect without idempotency', severity=Severity.CRITICAL,
                confidence=0.89, file_path=target_method.file_path, start_line=ev.line, end_line=target_method.end_line,
                method_id=target_method.id, method_name=target_method.method_name, evidence=_evidence(target_method, ev, 'Retry/fund evidence'),
                reasoning='Retry/timeout handling exists in a reachable confirmed fund-flow, but no idempotency control was found. Retrying may execute the side effect more than once.',
                remediation='All retries must reuse the same operation_id/idempotency_key and check terminal operation state before re-executing side effects.',
                evidence_level=EvidenceLevel.PROVEN,
            ))

        # FS-004 consumer replay protection.
        if m.is_consumer and not has_inbox:
            target_method, ev = proven_fund[0]
            findings.append(Finding(
                rule_id='FS-004', title='Consumer reaches confirmed fund side effect without inbox/dedup barrier', severity=Severity.HIGH,
                confidence=0.86, file_path=m.file_path, start_line=m.start_line, end_line=m.end_line,
                method_id=m.id, method_name=m.method_name, evidence=_evidence(target_method, ev, 'Consumer replay evidence'),
                reasoning='A message consumer can reach a confirmed external fund-moving call, but no inbox/dedup barrier was found in the reachable flow.',
                remediation='Insert an inbox record keyed by message_id/business_operation_id before executing fund side effects; commit offset only after durable state.',
                evidence_level=EvidenceLevel.PROVEN,
            ))

        # FS-005 missing compensation: only for outbound debit/transfer-like side effects. Keep MEDIUM unless stronger cross-flow evidence exists.
        risky_movements=[(tm, ev) for tm, ev in proven_fund if any(v in ev.method.lower() for v in ('debit','transfer','payout','disburse','withdraw','capture','charge'))]
        if risky_movements and not has_comp:
            target_method, ev = risky_movements[0]
            findings.append(Finding(
                rule_id='FS-005', title='No local compensation/reversal evidence for debit/transfer flow', severity=Severity.MEDIUM,
                confidence=0.70, file_path=target_method.file_path, start_line=ev.line, end_line=target_method.end_line,
                method_id=target_method.id, method_name=target_method.method_name, evidence=_evidence(target_method, ev, 'Compensation gap evidence'),
                reasoning='The scan found a confirmed debit/transfer-like external fund side effect, but no refund/reversal/compensation signal in the local depth=2 evidence. This is a review item, not a proven defect by itself.',
                remediation='Document or implement a reachable compensation/reversal/reconciliation path for half-failed states.',
                evidence_level=EvidenceLevel.PROVEN,
            ))

        # FS-006 transaction boundary: lower severity because many systems use async/outbox patterns.
        if any(_durable_before(tm, ev) for tm, ev in proven_fund) and not has_tx:
            target_method, ev = proven_fund[0]
            findings.append(Finding(
                rule_id='FS-006', title='Confirmed fund flow has durable state but no visible transaction boundary', severity=Severity.MEDIUM,
                confidence=0.60, file_path=target_method.file_path, start_line=ev.line, end_line=target_method.end_line,
                method_id=target_method.id, method_name=target_method.method_name, evidence=_evidence(target_method, ev, 'Transaction-boundary evidence'),
                reasoning='Durable operation state and confirmed fund side effect exist in the reachable flow, but no local transaction boundary marker was found. This may be acceptable if enforced in lower layers/outbox.',
                remediation='Verify local DB state transitions are transactional and protected by unique/CAS/version guard.',
                evidence_level=EvidenceLevel.PLAUSIBLE,
            ))

    for k in key_flows:
        if k.lossy:
            m=by_id.get(k.method_id)
            if m and m.is_executable_logic:
                findings.append(Finding(
                    rule_id='FS-007', title='Lossy business identity key transformation', severity=Severity.HIGH,
                    confidence=k.confidence, file_path=m.file_path, start_line=m.start_line, end_line=m.end_line,
                    method_id=m.id, method_name=m.method_name, evidence=[f"{k.source_key} -> {k.target_key} = {k.transformation}"],
                    reasoning='Business identity key is transformed using a potentially non-bijective/lossy operation. This can break end-to-end idempotency.',
                    remediation='Use canonical operation_id or persist a bijective mapping with uniqueness constraints.',
                    evidence_level=EvidenceLevel.PLAUSIBLE,
                ))
    return _dedupe_findings(findings)
