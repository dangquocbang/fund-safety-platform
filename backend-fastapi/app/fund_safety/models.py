from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

class Severity(str, Enum):
    LOW="LOW"; MEDIUM="MEDIUM"; HIGH="HIGH"; CRITICAL="CRITICAL"

class Language(str, Enum):
    JAVA="java"; GO="go"; UNKNOWN="unknown"

class EvidenceLevel(str, Enum):
    PROVEN="PROVEN"        # concrete side-effect call evidence
    PLAUSIBLE="PLAUSIBLE"  # executable call, but receiver/context is not definitive
    WEAK="WEAK"            # keyword/text only; never creates high-risk finding by itself

class CallKind(str, Enum):
    EXTERNAL_FUND="EXTERNAL_FUND"
    DURABLE_STATE="DURABLE_STATE"
    IDEMPOTENCY_CONTROL="IDEMPOTENCY_CONTROL"
    RETRY_CONTROL="RETRY_CONTROL"
    COMPENSATION="COMPENSATION"
    INBOX_DEDUP="INBOX_DEDUP"
    INTERNAL_CALL="INTERNAL_CALL"
    UNKNOWN="UNKNOWN"

class CallEvidence(BaseModel):
    name: str
    receiver: str | None = None
    method: str
    line: int
    kind: CallKind = CallKind.UNKNOWN
    level: EvidenceLevel = EvidenceLevel.WEAK
    confidence: float = 0.3
    reason: str = ""
    raw: str | None = None

class MethodEvidence(BaseModel):
    id: str
    language: Language
    file_path: str
    class_name: str | None = None
    method_name: str
    signature: str
    start_line: int
    end_line: int
    body: str
    calls: list[str] = Field(default_factory=list)
    call_evidence: list[CallEvidence] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)
    annotations: list[str] = Field(default_factory=list)
    is_executable_logic: bool = True
    is_entrypoint: bool = False
    is_consumer: bool = False
    has_transaction_boundary: bool = False
    has_idempotency_signal: bool = False
    has_durable_state_signal: bool = False
    has_external_fund_signal: bool = False
    has_retry_signal: bool = False
    has_compensation_signal: bool = False
    has_inbox_dedup_signal: bool = False

class CallEdge(BaseModel):
    source: str
    target: str
    confidence: float = 0.5
    reason: str = "name-match"

class KeyFlow(BaseModel):
    method_id: str
    source_key: str
    target_key: str
    transformation: str
    lossy: bool = False
    confidence: float = 0.5

class Finding(BaseModel):
    rule_id: str
    title: str
    severity: Severity
    confidence: float
    file_path: str
    start_line: int
    end_line: int
    method_id: str
    method_name: str
    evidence: list[str]
    reasoning: str
    remediation: str
    evidence_level: EvidenceLevel = EvidenceLevel.PLAUSIBLE
    llm_review: dict[str, Any] | None = None
    autofix_patch: str | None = None

class KnowledgeNode(BaseModel):
    id: str
    label: str
    type: str
    properties: dict[str, Any] = Field(default_factory=dict)

class KnowledgeEdge(BaseModel):
    source: str
    target: str
    type: str
    confidence: float = 0.7
    evidence: str | None = None

class ServiceRiskScore(BaseModel):
    service: str
    score: int
    finding_count: int
    critical_count: int
    high_count: int
    drivers: list[str] = Field(default_factory=list)

class Assessment(BaseModel):
    project: str
    summary: dict[str, Any]
    index_entries: list[dict[str, Any]] = Field(default_factory=list)
    discovery_targets: list[dict[str, Any]] = Field(default_factory=list)
    target_assessments: list[dict[str, Any]] = Field(default_factory=list)
    methods: list[MethodEvidence]
    call_edges: list[CallEdge]
    key_flows: list[KeyFlow]
    findings: list[Finding]
    knowledge_nodes: list[KnowledgeNode] = Field(default_factory=list)
    knowledge_edges: list[KnowledgeEdge] = Field(default_factory=list)
    risk_scores: list[ServiceRiskScore] = Field(default_factory=list)
