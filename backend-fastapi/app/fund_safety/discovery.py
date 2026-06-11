from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import re
from typing import Any

from .models import MethodEvidence, CallEdge, CallKind, EvidenceLevel
from .indexer import IndexEntry
from .graph import downstream_reachable
from .scanner import EntrypointKind, detect_entrypoints
from app.config import DISCOVERY_CONFIG

GROUP_RULES = [
    ("reversal", ("refund", "reverse", "reversal", "compensate", "rollback")),
    ("wallet", ("wallet", "debit", "credit", "balance", "withdraw")),
    ("payment-flow", ("payment", "charge", "capture", "pay", "transfer", "payout", "disburse", "bank", "gateway", "partner")),
    ("order", ("order", "confirm", "cancel", "expire")),
    ("event", ("consumer", "kafka", "rabbit", "webhook", "ipn", "callback", "event")),
]

@dataclass
class DiscoveryTarget:
    id: str
    method_id: str
    class_name: str | None
    file_path: str
    method: str
    signature: str
    group: str
    priority: str
    context: str
    focus_criteria: list[str]
    notes: str
    depth: int = 2
    evidence_method_ids: list[str] | None = None


def _group_for(entry: IndexEntry) -> str:
    text = " ".join([entry.file_path, entry.class_name or "", entry.method_name, entry.signature] + entry.call_names + entry.signals).lower()
    for group, hints in GROUP_RULES:
        if any(h in text for h in hints):
            return group
    return "other"


def _focus_criteria(entry: IndexEntry, method: MethodEvidence, reachable: list[MethodEvidence]) -> list[str]:
    scope = [method] + reachable
    criteria = set()
    if method.is_entrypoint or method.is_consumer or any("idempotency" in s for s in entry.signals):
        criteria.update(["R1", "R2", "R3", "R4", "R5", "R9"])
    if any(ev.kind == CallKind.EXTERNAL_FUND for m in scope for ev in m.call_evidence):
        criteria.update(["R6", "R7", "R8", "R10"])
    if any(m.has_retry_signal for m in scope):
        criteria.update(["R5", "R6", "R7"])
    if any(m.is_consumer for m in scope):
        criteria.update(["R3", "R4", "R6"])
    if not criteria:
        criteria.update(["R1", "R3", "R8"])
    return sorted(criteria, key=lambda x: int(x[1:]))


def _context(entry: IndexEntry, method: MethodEvidence, reachable: list[MethodEvidence]) -> str:
    proven_calls = []
    plausible_calls = []
    for m in [method] + reachable:
        for ev in m.call_evidence:
            if ev.kind == CallKind.EXTERNAL_FUND and ev.level == EvidenceLevel.PROVEN:
                proven_calls.append(f"{m.method_name}:{ev.line}:{ev.name}")
            elif ev.kind == CallKind.EXTERNAL_FUND and ev.level == EvidenceLevel.PLAUSIBLE:
                plausible_calls.append(f"{m.method_name}:{ev.line}:{ev.name}")
    parts = [entry.candidate_reason]
    if proven_calls:
        parts.append("confirmed external fund calls: " + "; ".join(proven_calls[:5]))
    elif plausible_calls:
        parts.append("plausible fund calls: " + "; ".join(plausible_calls[:5]))
    if method.is_entrypoint: parts.append("boundary entrypoint")
    if method.is_consumer: parts.append("message/callback consumer")
    if method.has_retry_signal: parts.append("retry/timeout signal")
    return ". ".join(parts)


def _should_exclude_method(method_name: str, exclude_patterns: list[str] | None) -> bool:
    if not exclude_patterns:
        return False
    method_lower = method_name.lower()
    for pattern in exclude_patterns:
        pattern_lower = pattern.lower()
        if pattern_lower.startswith("*") and pattern_lower.endswith("*"):
            if pattern_lower[1:-1] in method_lower:
                return True
        elif pattern_lower.startswith("*"):
            if method_lower.endswith(pattern_lower[1:]):
                return True
        elif pattern_lower.endswith("*"):
            suffix = pattern_lower[:-1]
            if method_lower.startswith(suffix):
                return True
        elif method_lower == pattern_lower:
            return True
    return False


def discover_targets(entries: list[IndexEntry], methods: list[MethodEvidence], edges: list[CallEdge], depth: int = 2, max_targets: int | None = None) -> list[DiscoveryTarget]:
    max_targets = max_targets or int(DISCOVERY_CONFIG.get("max_targets", 80))
    ignore_paths = [str(x).lower() for x in DISCOVERY_CONFIG.get("ignore_path_contains", []) or []]
    exclude_methods = DISCOVERY_CONFIG.get("exclude_methods", []) or []
    by_id = {m.id: m for m in methods}
    seq_by_group: dict[str, int] = {}
    out: list[DiscoveryTarget] = []
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    for entry in sorted(entries, key=lambda e: (priority_rank.get(e.candidate_priority, 9), e.file_path, e.start_line)):
        if any(token in entry.file_path.lower() for token in ignore_paths):
            continue
        m = by_id.get(entry.id)
        if not m:
            continue
        if _should_exclude_method(m.method_name, exclude_methods):
            continue
        reachable_ids = list(downstream_reachable(m.id, edges, depth))
        reachable = [by_id[rid] for rid in reachable_ids if rid in by_id]
        group = _group_for(entry)
        seq_by_group[group] = seq_by_group.get(group, 0) + 1
        prefix = re.sub(r"[^A-Z]", "", group.upper())[:3] or "OTH"
        target_id = f"{prefix}-{seq_by_group[group]:03d}"
        out.append(DiscoveryTarget(
            id=target_id,
            method_id=m.id,
            class_name=m.class_name,
            file_path=m.file_path,
            method=m.method_name,
            signature=m.signature[:240],
            group=group,
            priority=entry.candidate_priority,
            context=_context(entry, m, reachable),
            focus_criteria=_focus_criteria(entry, m, reachable),
            notes="Generated by index-first discovery; review full target method and depth=2 reachable methods.",
            depth=depth,
            evidence_method_ids=[m.id] + reachable_ids[:20],
        ))
        if len(out) >= max_targets:
            break
    return out


def _kind_to_group(kind: EntrypointKind) -> str:
    return {
        EntrypointKind.HTTP_HANDLER:      "http-api",
        EntrypointKind.GRPC_HANDLER:      "grpc-api",
        EntrypointKind.KAFKA_CONSUMER:    "kafka-consumer",
        EntrypointKind.RABBITMQ_CONSUMER: "rabbitmq-consumer",
    }.get(kind, "other")


def _priority_from_scope(
    method: MethodEvidence,
    reachable: list[MethodEvidence],
    kind: EntrypointKind,
) -> str:
    """Assign P0/P1/P2 to an entrypoint based on fund signals in its depth-N scope."""
    scope = [method] + reachable
    has_proven_fund = any(
        ev.kind == CallKind.EXTERNAL_FUND and ev.level == EvidenceLevel.PROVEN
        for m in scope for ev in m.call_evidence
    )
    has_plausible_fund = any(
        ev.kind == CallKind.EXTERNAL_FUND and ev.level == EvidenceLevel.PLAUSIBLE
        for m in scope for ev in m.call_evidence
    )
    has_durable = any(ev.kind == CallKind.DURABLE_STATE for m in scope for ev in m.call_evidence)
    is_consumer = kind in (EntrypointKind.KAFKA_CONSUMER, EntrypointKind.RABBITMQ_CONSUMER)

    if has_proven_fund:
        return "P0"
    if is_consumer or has_plausible_fund:
        return "P1"
    if has_durable:
        return "P2"
    # HTTP/gRPC entrypoints with no fund signal: still include at P1 for
    # API-boundary idempotency review.
    return "P1"


def _focus_criteria_for_entrypoint(
    method: MethodEvidence,
    reachable: list[MethodEvidence],
    kind: EntrypointKind,
) -> list[str]:
    """R1-R10 focus set appropriate for entrypoint-first targets."""
    scope = [method] + reachable
    criteria: set[str] = set()
    # Every API/consumer boundary needs the core idempotency checks.
    criteria.update(["R1", "R2", "R3", "R4", "R5", "R9"])
    if any(ev.kind == CallKind.EXTERNAL_FUND for m in scope for ev in m.call_evidence):
        criteria.update(["R6", "R7", "R8", "R10"])
    if any(m.has_retry_signal for m in scope):
        criteria.update(["R5", "R6", "R7"])
    if kind in (EntrypointKind.KAFKA_CONSUMER, EntrypointKind.RABBITMQ_CONSUMER):
        criteria.update(["R3", "R4", "R6"])
    return sorted(criteria, key=lambda x: int(x[1:]))


def _context_for_entrypoint(
    method: MethodEvidence,
    reachable: list[MethodEvidence],
    kind: EntrypointKind,
) -> str:
    proven_calls, plausible_calls = [], []
    for m in [method] + reachable:
        for ev in m.call_evidence:
            if ev.kind == CallKind.EXTERNAL_FUND and ev.level == EvidenceLevel.PROVEN:
                proven_calls.append(f"{m.method_name}:{ev.line}:{ev.name}")
            elif ev.kind == CallKind.EXTERNAL_FUND and ev.level == EvidenceLevel.PLAUSIBLE:
                plausible_calls.append(f"{m.method_name}:{ev.line}:{ev.name}")
    parts = [f"{kind.value} entrypoint"]
    if proven_calls:
        parts.append("confirmed external fund calls: " + "; ".join(proven_calls[:5]))
    elif plausible_calls:
        parts.append("plausible fund calls: " + "; ".join(plausible_calls[:5]))
    if method.has_retry_signal:
        parts.append("retry/timeout signal")
    if kind in (EntrypointKind.KAFKA_CONSUMER, EntrypointKind.RABBITMQ_CONSUMER):
        parts.append("message/event consumer")
    return ". ".join(parts)


def discover_from_entrypoints(
    entries: list[IndexEntry],
    methods: list[MethodEvidence],
    edges: list[CallEdge],
    depth: int = 2,
    max_targets: int | None = None,
) -> list[DiscoveryTarget]:
    """Entrypoint-first discovery.

    Selects only methods that are confirmed API/consumer boundaries:
    - HTTP handlers  (gin.Context, echo.Context, http.ResponseWriter, …)
    - gRPC handlers  (receiver ends in Server/ServiceServer + context.Context)
    - Kafka consumers  (kafka.Message / sarama.ConsumerMessage parameter)
    - RabbitMQ consumers  (amqp.Delivery / rabbitmq.Delivery parameter)

    Priority is assigned by fund-signal evidence in the depth-N call graph.
    Falls back to discover_targets() if no entrypoints are found.
    """
    max_targets = max_targets or int(DISCOVERY_CONFIG.get("max_targets", 80))
    ignore_paths = [str(x).lower() for x in DISCOVERY_CONFIG.get("ignore_path_contains", []) or []]
    exclude_methods = DISCOVERY_CONFIG.get("exclude_methods", []) or []
    by_id = {m.id: m for m in methods}

    # Detect entrypoints from ALL scanned methods (not just index_entries),
    # because an HTTP handler may not contain fund keywords in its own name.
    raw_entrypoints = detect_entrypoints(methods)

    # Filter + score
    scored: list[tuple[MethodEvidence, EntrypointKind, str]] = []
    for m, kind in raw_entrypoints:
        if any(token in m.file_path.lower() for token in ignore_paths):
            continue
        if _should_exclude_method(m.method_name, exclude_methods):
            continue
        reachable_ids = list(downstream_reachable(m.id, edges, depth))
        reachable = [by_id[rid] for rid in reachable_ids if rid in by_id]
        priority = _priority_from_scope(m, reachable, kind)
        scored.append((m, kind, priority))

    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    scored.sort(key=lambda x: (priority_rank.get(x[2], 9), x[0].file_path, x[0].start_line))

    group_prefix = {
        "http-api": "HTTP",
        "grpc-api": "GRP",
        "kafka-consumer": "KFK",
        "rabbitmq-consumer": "RMQ",
    }
    seq_by_group: dict[str, int] = {}
    out: list[DiscoveryTarget] = []

    for m, kind, priority in scored:
        if len(out) >= max_targets:
            break
        group = _kind_to_group(kind)
        seq_by_group[group] = seq_by_group.get(group, 0) + 1
        target_id = f"{group_prefix.get(group, 'OTH')}-{seq_by_group[group]:03d}"
        reachable_ids = list(downstream_reachable(m.id, edges, depth))
        reachable = [by_id[rid] for rid in reachable_ids if rid in by_id]
        out.append(DiscoveryTarget(
            id=target_id,
            method_id=m.id,
            class_name=m.class_name,
            file_path=m.file_path,
            method=m.method_name,
            signature=m.signature[:240],
            group=group,
            priority=priority,
            context=_context_for_entrypoint(m, reachable, kind),
            focus_criteria=_focus_criteria_for_entrypoint(m, reachable, kind),
            notes=f"Entrypoint-first discovery ({kind.value}). Review this boundary and depth={depth} downstream evidence.",
            depth=depth,
            evidence_method_ids=[m.id] + reachable_ids[:20],
        ))

    return out


def targets_to_dict(targets: list[DiscoveryTarget]) -> list[dict[str, Any]]:
    return [asdict(t) for t in targets]


def render_targets_yaml(project: str, targets: list[DiscoveryTarget]) -> str:
    try:
        import yaml  # type: ignore
        return yaml.safe_dump({
            "project": {"name": project, "description": "Auto-discovered from source index", "base_package": "auto"},
            "defaults": {"criteria": "all", "output_format": "full", "trace_depth": 2},
            "targets": targets_to_dict(targets),
        }, sort_keys=False, allow_unicode=True)
    except Exception:
        return json.dumps({"project": {"name": project}, "defaults": {"trace_depth": 2}, "targets": targets_to_dict(targets)}, indent=2)


def _load_prompt(name: str) -> str:
    p = Path(__file__).resolve().parent / "prompts" / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def discover_targets_with_llm(
    entries: list[IndexEntry],
    methods: list[MethodEvidence],
    edges: list[CallEdge],
    project: str,
    depth: int,
    llm_client: Any,
    source_root: str | None = None,
    max_targets: int = 80,
) -> list[DiscoveryTarget]:
    """Claude/Ollama-guided discovery.

    The LLM does NOT read the whole repository freely. It receives only the compact
    method/API index and must return target method IDs from that index. If parsing
    or provider call fails, the deterministic discovery is used.
    """
    fallback = discover_targets(entries, methods, edges, depth=depth, max_targets=max_targets)
    if not getattr(llm_client, "enabled", False):
        return fallback

    index_payload = []
    for e in entries[:300]:
        index_payload.append({
            "id": e.id,
            "language": e.language.value if hasattr(e.language, "value") else str(e.language),
            "file_path": e.file_path,
            "class_name": e.class_name,
            "method_name": e.method_name,
            "signature": e.signature,
            "priority": e.candidate_priority,
            "reason": e.candidate_reason,
            "signals": e.signals[:20],
            "call_names": e.call_names[:30],
        })
    base_prompt = _load_prompt("CLAUDE_DISCOVERY_GO.md") + "\n\n" + _load_prompt("CLAUDE_DISCOVERY_JAVA.md")
    prompt = f"""
{base_prompt}

You are running inside Fund Safety Platform.
Project: {project}
Trace depth: {depth}

Return ONLY valid JSON with this schema:
{{
  "targets": [
    {{
      "method_id": "exact method id from index",
      "group": "payment-flow|wallet|reversal|order|event|other",
      "priority": "P0|P1|P2",
      "context": "why this target matters",
      "focus_criteria": ["R1", "R2", "R3"],
      "notes": "assessment instruction"
    }}
  ]
}}

Rules:
- Select only method_id values that exist in the index.
- Prefer P0 fund-moving methods and callback/retry methods.
- Be conservative; avoid DTO/model/getter/test methods.
- Limit to {max_targets} targets.

METHOD_INDEX_JSON:
{json.dumps(index_payload, ensure_ascii=False, indent=2)}
"""
    try:
        raw = llm_client.generate(prompt, cwd=source_root)
        from .llm import extract_json_object
        parsed = extract_json_object(raw) or {}
        raw_targets = parsed.get("targets") or []
        by_id = {e.id: e for e in entries}
        by_method = {m.id: m for m in methods}
        out: list[DiscoveryTarget] = []
        seq = 0
        for item in raw_targets:
            mid = str(item.get("method_id", ""))
            e = by_id.get(mid)
            m = by_method.get(mid)
            if not e or not m:
                continue
            seq += 1
            group = str(item.get("group") or _group_for(e))
            prefix = re.sub(r"[^A-Z]", "", group.upper())[:3] or "TGT"
            reachable_ids = list(downstream_reachable(mid, edges, depth))
            focus = item.get("focus_criteria") or _focus_criteria(e, m, [by_method[r] for r in reachable_ids if r in by_method])
            focus = [x for x in focus if isinstance(x, str) and re.match(r"^R(?:[1-9]|10|11)$", x)] or _focus_criteria(e, m, [])
            out.append(DiscoveryTarget(
                id=f"{prefix}-{seq:03d}",
                method_id=mid,
                class_name=m.class_name,
                file_path=m.file_path,
                method=m.method_name,
                signature=m.signature[:240],
                group=group,
                priority=str(item.get("priority") or e.candidate_priority),
                context=str(item.get("context") or e.candidate_reason),
                focus_criteria=sorted(set(focus), key=lambda x: int(x[1:])),
                notes=str(item.get("notes") or "LLM-guided discovery target; review target and depth=2 evidence."),
                depth=depth,
                evidence_method_ids=[mid] + reachable_ids[:20],
            ))
            if len(out) >= max_targets:
                break
        return out or fallback
    except Exception:
        return fallback
