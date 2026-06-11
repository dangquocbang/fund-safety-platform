from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
import json
from typing import Any

from .models import MethodEvidence, CallEdge, CallKind, EvidenceLevel, Finding, Severity
from .discovery import DiscoveryTarget
from .graph import downstream_reachable

CRITERIA = {
    "R1": "Idempotency Boundary Defined",
    "R2": "Unique Business Intent Defined",
    "R3": "Duplicate Detection Exists",
    "R4": "In-progress Concurrency Handling",
    "R5": "State Machine Safe for Retry",
    "R6": "Timeout & Partial Execution Recovery",
    "R7": "External Side-effect Guarded",
    "R8": "Persistence & Side-effect Ordering Safe",
    "R9": "Response Consistency",
    "R10": "Compensate / Reversal Safeguard",
}

ORDERED_CRITERIA = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10"]

@dataclass
class CriterionResult:
    id: str
    name: str
    status: str
    evidence: str
    risk: str
    fix: str

@dataclass
class TargetAssessment:
    target_id: str
    method_id: str
    class_name: str | None
    method: str
    file_path: str
    start_line: int
    priority: str
    context: str
    criteria: list[CriterionResult]
    overall_status: str
    score: str
    issues: list[str]
    findings: list[str]


def _scope(target: DiscoveryTarget, methods: list[MethodEvidence], edges: list[CallEdge]) -> list[MethodEvidence]:
    by_id = {m.id: m for m in methods}
    base = by_id.get(target.method_id)
    if not base:
        return []
    ids = [target.method_id] + list(downstream_reachable(target.method_id, edges, target.depth))
    return [by_id[i] for i in ids if i in by_id]


def _has(scope: list[MethodEvidence], kind: CallKind) -> bool:
    return any(ev.kind == kind for m in scope for ev in m.call_evidence)


def _has_proven(scope: list[MethodEvidence], kind: CallKind) -> bool:
    return any(ev.kind == kind and ev.level == EvidenceLevel.PROVEN for m in scope for ev in m.call_evidence)


def _evidence_line(scope: list[MethodEvidence], kind: CallKind | None = None) -> str:
    for m in scope:
        for ev in m.call_evidence:
            if kind is None or ev.kind == kind:
                return f"{m.file_path}:{ev.line} `{ev.raw or ev.name}` ({ev.kind.value}/{ev.level.value})"
    if scope:
        m = scope[0]
        return f"{m.file_path}:{m.start_line}-{m.end_line} `{m.method_name}`"
    return "No evidence"


def _status_to_icon(status: str) -> str:
    return {"PASS": "✅", "FAIL": "❌", "PARTIAL": "⚠️", "N/A": "—", "NOT_FOUND": "NOT_FOUND"}.get(status, status)


def _criterion(target: DiscoveryTarget, scope: list[MethodEvidence], cid: str) -> CriterionResult:
    name = CRITERIA[cid]
    has_fund = _has(scope, CallKind.EXTERNAL_FUND)
    has_proven_fund = _has_proven(scope, CallKind.EXTERNAL_FUND)
    has_idem = _has(scope, CallKind.IDEMPOTENCY_CONTROL) or any(m.has_idempotency_signal for m in scope)
    has_durable = _has(scope, CallKind.DURABLE_STATE) or any(m.has_durable_state_signal for m in scope)
    has_retry = _has(scope, CallKind.RETRY_CONTROL) or any(m.has_retry_signal for m in scope)
    has_comp = _has(scope, CallKind.COMPENSATION) or any(m.has_compensation_signal for m in scope)
    has_inbox = _has(scope, CallKind.INBOX_DEDUP) or any(m.has_inbox_dedup_signal for m in scope)
    has_tx = any(m.has_transaction_boundary for m in scope)
    has_identity_key = any(m.has_idempotency_signal for m in scope)
    is_consumer = any(m.is_consumer for m in scope)

    if cid == "R1":
        ok = has_identity_key or has_idem
        return CriterionResult(cid, name, "PASS" if ok else "FAIL" if has_fund else "N/A", _evidence_line(scope), "No clear idempotency boundary for retryable fund operation." if has_fund and not ok else "", "Define stable idempotency key/operation ID at API or consumer boundary." if has_fund and not ok else "")
    if cid == "R2":
        ok = has_identity_key
        return CriterionResult(cid, name, "PASS" if ok else "PARTIAL" if has_fund else "N/A", _evidence_line(scope), "Business intent key is not clearly derived from stable request inputs." if has_fund and not ok else "", "Use compound unique business intent key, e.g. merchant_id + request_id/order_id." if has_fund and not ok else "")
    if cid == "R3":
        ok = has_idem or has_inbox
        return CriterionResult(cid, name, "PASS" if ok else "FAIL" if (has_fund or is_consumer) else "N/A", _evidence_line(scope), "Duplicate request/event may execute external side effect more than once." if (has_fund or is_consumer) and not ok else "", "Insert-if-absent/unique index/dedup table before external call." if (has_fund or is_consumer) and not ok else "")
    if cid == "R4":
        ok = has_idem and (has_tx or has_durable)
        return CriterionResult(cid, name, "PASS" if ok else "PARTIAL" if has_fund else "N/A", _evidence_line(scope), "Concurrent same-key requests may race." if has_fund and not ok else "", "Use unique constraint + CAS/lock around operation state." if has_fund and not ok else "")
    if cid == "R5":
        ok = has_durable
        return CriterionResult(cid, name, "PASS" if ok else "PARTIAL" if (has_fund or has_retry) else "N/A", _evidence_line(scope, CallKind.DURABLE_STATE) if ok else _evidence_line(scope), "Retry state machine not visible." if (has_fund or has_retry) and not ok else "", "Persist NEW/PROCESSING/SUCCEEDED/FAILED_FINAL and define retry behavior per state." if (has_fund or has_retry) and not ok else "")
    if cid == "R6":
        ok = has_retry and (has_durable or has_idem)
        return CriterionResult(cid, name, "PASS" if ok else "FAIL" if has_proven_fund and has_retry else "PARTIAL" if has_fund else "N/A", _evidence_line(scope), "Timeout may be treated as failed while external side effect may still complete." if has_fund and not ok else "", "Add probe/reconcile path for in-flight/unknown external state." if has_fund and not ok else "")
    if cid == "R7":
        ok = has_fund and has_idem
        return CriterionResult(cid, name, "PASS" if ok else "FAIL" if has_proven_fund else "PARTIAL" if has_fund else "N/A", _evidence_line(scope, CallKind.EXTERNAL_FUND) if has_fund else _evidence_line(scope), "External side effect not visibly guarded by stable idempotency key." if has_fund and not ok else "", "Guard charge/debit/credit/bank calls with stable operation/partner request ID." if has_fund and not ok else "")
    if cid == "R8":
        ok = has_durable and has_fund
        return CriterionResult(cid, name, "PASS" if ok else "FAIL" if has_proven_fund else "PARTIAL" if has_fund else "N/A", _evidence_line(scope), "External success can become orphaned or duplicated." if has_fund and not ok else "", "Persist operation state before external side effect; terminal update after response with CAS." if has_fund and not ok else "")
    if cid == "R9":
        return CriterionResult(cid, name, "PARTIAL" if has_identity_key else "N/A", _evidence_line(scope), "Response consistency not inferable statically." if has_identity_key else "", "Store first successful response or normalize dedup response status/body." if has_identity_key else "")
    if cid == "R10":
        return CriterionResult(cid, name, "PASS" if has_comp else "PARTIAL" if has_fund else "N/A", _evidence_line(scope, CallKind.COMPENSATION) if has_comp else _evidence_line(scope), "Compensation/reversal path not visible in depth=2 evidence." if has_fund and not has_comp else "", "Document or implement idempotent refund/reversal with separate compensation key." if has_fund and not has_comp else "")
    return CriterionResult(cid, name, "N/A", "", "", "")


def _score(criteria: list[CriterionResult]) -> str:
    applicable = [c for c in criteria if c.status not in {"N/A", "NOT_FOUND"}]
    if not applicable:
        return "—"
    passed = sum(1 for c in applicable if c.status == "PASS")
    return f"{passed}/{len(applicable)}"


def _issues(criteria: list[CriterionResult]) -> list[str]:
    return [f"{c.id}: {c.risk or c.fix or c.status}" for c in criteria if c.status in {"FAIL", "PARTIAL"}]


def assess_targets(targets: list[DiscoveryTarget], methods: list[MethodEvidence], edges: list[CallEdge]) -> list[TargetAssessment]:
    out: list[TargetAssessment] = []
    by_id = {m.id: m for m in methods}
    for t in targets:
        base = by_id.get(t.method_id)
        scope = _scope(t, methods, edges)
        if not scope or not base:
            out.append(TargetAssessment(t.id, t.method_id, t.class_name, t.method, t.file_path, 0, t.priority, t.context, [], "NOT_FOUND", "—", ["Target method not found"], []))
            continue
        # Always render matrix for R1-R10. Criteria not in focus are N/A, so output is stable and comparable.
        criteria: list[CriterionResult] = []
        focus = set(t.focus_criteria or ORDERED_CRITERIA)
        for cid in ORDERED_CRITERIA:
            if cid in focus:
                criteria.append(_criterion(t, scope, cid))
            else:
                criteria.append(CriterionResult(cid, CRITERIA[cid], "N/A", "Not selected by discovery focus criteria", "", ""))
        statuses = [c.status for c in criteria]
        if "FAIL" in statuses:
            overall = "FAIL"
        elif "PARTIAL" in statuses:
            overall = "PARTIAL"
        else:
            overall = "PASS"
        issues = _issues(criteria)
        out.append(TargetAssessment(t.id, t.method_id, t.class_name, t.method, t.file_path, base.start_line, t.priority, t.context, criteria, overall, _score(criteria), issues, issues))
    return out


def severity_for(priority: str, status: str) -> Severity:
    if status == "FAIL":
        if priority == "P0": return Severity.CRITICAL
        if priority == "P1": return Severity.HIGH
        return Severity.MEDIUM
    if status == "PARTIAL":
        if priority == "P0": return Severity.HIGH
        if priority == "P1": return Severity.MEDIUM
        return Severity.LOW
    return Severity.LOW


def findings_from_target_assessments(items: list[TargetAssessment]) -> list[Finding]:
    findings: list[Finding] = []
    for ta in items:
        for c in ta.criteria:
            if c.status not in {"FAIL", "PARTIAL"}:
                continue
            findings.append(Finding(
                rule_id=c.id,
                title=f"{c.id} — {c.name}",
                severity=severity_for(ta.priority, c.status),
                confidence=0.9 if c.status == "FAIL" else 0.7,
                file_path=ta.file_path,
                start_line=ta.start_line or 1,
                end_line=ta.start_line or 1,
                method_id=ta.method_id,
                method_name=f"{ta.class_name + '.' if ta.class_name else ''}{ta.method}",
                evidence=[c.evidence, f"Status: {c.status}", f"Priority: {ta.priority}", f"Context: {ta.context}"],
                reasoning=c.risk or f"{c.id} is {c.status} for this target.",
                remediation=c.fix or "Review and document control evidence.",
                evidence_level=EvidenceLevel.PROVEN if c.status == "FAIL" else EvidenceLevel.PLAUSIBLE,
            ))
    return findings


def filter_findings_to_targets(findings: list[Finding], targets: list[DiscoveryTarget]) -> list[Finding]:
    target_method_ids = {t.method_id for t in targets}
    evidence_ids = {mid for t in targets for mid in (t.evidence_method_ids or [])}
    allowed = target_method_ids | evidence_ids
    return [f for f in findings if f.method_id in allowed]


def target_assessments_to_dict(items: list[TargetAssessment]) -> list[dict[str, Any]]:
    return [asdict(x) for x in items]


def build_audit_summary(project: str, target_assessments: list[TargetAssessment]) -> dict[str, Any]:
    total = len(target_assessments)
    p0_fail = sum(1 for x in target_assessments if x.priority == "P0" and x.overall_status == "FAIL")
    p0_partial = sum(1 for x in target_assessments if x.priority == "P0" and x.overall_status == "PARTIAL")
    return {
        "project": project,
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "total_functions_audited": total,
        "p0_with_fail": p0_fail,
        "p0_with_partial": p0_partial,
    }


def criterion_icon(status: str) -> str:
    return _status_to_icon(status)


def _load_prompt(name: str) -> str:
    from pathlib import Path
    p = Path(__file__).resolve().parent / "prompts" / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _method_snippet(m: MethodEvidence, max_chars: int = 4000) -> dict[str, Any]:
    return {
        "id": m.id,
        "file_path": m.file_path,
        "class_name": m.class_name,
        "method_name": m.method_name,
        "signature": m.signature,
        "start_line": m.start_line,
        "end_line": m.end_line,
        "annotations": m.annotations,
        "calls": m.calls[:80],
        "call_evidence": [ev.model_dump(mode="json") for ev in m.call_evidence[:40]],
        "signals": {
            "entrypoint": m.is_entrypoint,
            "consumer": m.is_consumer,
            "transaction_boundary": m.has_transaction_boundary,
            "idempotency": m.has_idempotency_signal,
            "durable_state": m.has_durable_state_signal,
            "retry": m.has_retry_signal,
            "compensation": m.has_compensation_signal,
            "inbox_dedup": m.has_inbox_dedup_signal,
        },
        "body_excerpt": m.body[:max_chars],
    }


def _assessment_from_llm_item(item: dict[str, Any], target: DiscoveryTarget, base: MethodEvidence) -> TargetAssessment:
    criteria: list[CriterionResult] = []
    results = item.get("criteria") or item.get("rule_results") or []
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(results, dict):
        for k, v in results.items():
            if isinstance(v, dict):
                by_id[k] = v
    elif isinstance(results, list):
        for r in results:
            if isinstance(r, dict) and r.get("id"):
                by_id[str(r["id"])] = r
    for cid in ORDERED_CRITERIA:
        r = by_id.get(cid, {})
        status = str(r.get("status") or "N/A").upper()
        if status not in {"PASS", "FAIL", "PARTIAL", "N/A", "NOT_FOUND"}:
            status = "PARTIAL" if status in {"WARN", "WARNING"} else "N/A"
        criteria.append(CriterionResult(
            id=cid,
            name=CRITERIA[cid],
            status=status,
            evidence=str(r.get("evidence") or r.get("reason") or "Assessed by LLM from scoped evidence"),
            risk=str(r.get("risk") or r.get("issue") or ""),
            fix=str(r.get("fix") or r.get("recommended_fix") or ""),
        ))
    statuses = [c.status for c in criteria]
    overall = str(item.get("overall_status") or ("FAIL" if "FAIL" in statuses else "PARTIAL" if "PARTIAL" in statuses else "PASS"))
    if overall not in {"PASS", "FAIL", "PARTIAL", "NOT_FOUND"}:
        overall = "PARTIAL"
    issues = item.get("issues")
    if not isinstance(issues, list):
        issues = _issues(criteria)
    return TargetAssessment(
        target_id=target.id,
        method_id=target.method_id,
        class_name=base.class_name,
        method=base.method_name,
        file_path=base.file_path,
        start_line=base.start_line,
        priority=str(item.get("priority") or target.priority),
        context=str(item.get("context") or target.context),
        criteria=criteria,
        overall_status=overall,
        score=str(item.get("score") or _score(criteria)),
        issues=[str(x) for x in issues],
        findings=[str(x) for x in (item.get("findings") or issues or [])],
    )


def assess_targets_with_llm(
    targets: list[DiscoveryTarget],
    methods: list[MethodEvidence],
    edges: list[CallEdge],
    project: str,
    llm_client: Any,
    source_root: str | None = None,
    batch_size: int = 4,
) -> list[TargetAssessment]:
    """LLM-guided R1-R10 assessment with deterministic fallback.

    Claude gets only discovered targets + depth evidence, not the whole repo.
    If output is invalid or provider unavailable, fallback rule assessment is used.
    """
    fallback = assess_targets(targets, methods, edges)
    if not getattr(llm_client, "enabled", False) or not targets:
        return fallback
    by_id = {m.id: m for m in methods}
    fallback_by_target = {x.target_id: x for x in fallback}
    assessed: list[TargetAssessment] = []
    base_prompt = _load_prompt("CLAUDE_GO.md") + "\n\n" + _load_prompt("CLAUDE_JAVA.md")
    for start in range(0, len(targets), batch_size):
        batch = targets[start : start + batch_size]
        payload_targets = []
        valid_targets = []
        for t in batch:
            base = by_id.get(t.method_id)
            if not base:
                continue
            ids = [t.method_id] + list(downstream_reachable(t.method_id, edges, t.depth))[:20]
            evidence = [_method_snippet(by_id[i]) for i in ids if i in by_id]
            payload_targets.append({
                "target": {
                    "id": t.id,
                    "method_id": t.method_id,
                    "priority": t.priority,
                    "group": t.group,
                    "context": t.context,
                    "focus_criteria": t.focus_criteria,
                    "notes": t.notes,
                },
                "evidence_methods": evidence,
            })
            valid_targets.append((t, base))
        if not payload_targets:
            continue
        prompt = f"""
{base_prompt}

Project: {project}
You are assessing only the following discovered targets and their depth evidence.
Return ONLY valid JSON with this schema:
{{
  "assessments": [
    {{
      "target_id": "target id",
      "priority": "P0|P1|P2",
      "overall_status": "PASS|PARTIAL|FAIL|NOT_FOUND",
      "score": "10/11",
      "issues": ["R3: ..."],
      "criteria": [
        {{"id":"R1", "status":"PASS|PARTIAL|FAIL|N/A", "evidence":"file:line call/state", "risk":"", "fix":""}}
      ]
    }}
  ]
}}

Assessment rules:
- Use R1-R10 exactly.
- Use PASS only when evidence is visible in the scoped data.
- Use PARTIAL when control exists downstream but target can re-trigger prep/state changes.
- Use FAIL when duplicate/retry/external side effect is unguarded.
- Do not invent code beyond evidence_methods.
- Keep issues concise like: "R3: missing delivery state check".

TARGET_EVIDENCE_JSON:
{json.dumps(payload_targets, ensure_ascii=False, indent=2)}
"""
        try:
            raw = llm_client.generate(prompt, cwd=source_root)
            from .llm import extract_json_object
            parsed = extract_json_object(raw) or {}
            items = parsed.get("assessments") or []
            item_by_id = {str(x.get("target_id")): x for x in items if isinstance(x, dict)}
            for t, base in valid_targets:
                item = item_by_id.get(t.id)
                if item:
                    assessed.append(_assessment_from_llm_item(item, t, base))
                else:
                    assessed.append(fallback_by_target.get(t.id) or assess_targets([t], methods, edges)[0])
        except Exception:
            for t, _ in valid_targets:
                assessed.append(fallback_by_target.get(t.id) or assess_targets([t], methods, edges)[0])
    # preserve any target not covered due errors
    have = {a.target_id for a in assessed}
    for f in fallback:
        if f.target_id not in have:
            assessed.append(f)
    return assessed
