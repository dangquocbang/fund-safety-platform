from __future__ import annotations

from pydantic import BaseModel

from app.config import ASSESSMENT_CONFIG, DISCOVERY_CONFIG, JAVA_CONFIG, GOLANG_CONFIG


def _flatten_language_keywords(config: dict, key: str) -> list[str]:
    values: list[str] = []
    for item in config.get(key, []) or []:
        if isinstance(item, str):
            values.append(item)
    return values


class ScanPolicy(BaseModel):
    # These are not used to create final findings directly. They are discovery
    # hints for index-first target selection and evidence scoping.
    fund_keywords: list[str]
    idempotency_keywords: list[str]
    idempotency_control_keywords: list[str]
    durable_keywords: list[str]
    retry_keywords: list[str]
    compensation_keywords: list[str]
    inbox_keywords: list[str]
    high_risk_only_llm: bool = True
    max_llm_findings: int = 30


def load_scan_policy() -> ScanPolicy:
    java_fund = _flatten_language_keywords(JAVA_CONFIG, "fund_methods")
    go_fund = _flatten_language_keywords(GOLANG_CONFIG, "fund_methods")
    discovery_include = DISCOVERY_CONFIG.get("include_name_contains", []) or []
    fund_keywords = sorted({*(x.lower() for x in java_fund), *(x.lower() for x in go_fund), *(str(x).lower() for x in discovery_include)})

    return ScanPolicy(
        fund_keywords=fund_keywords or ["bank", "wallet", "ledger", "transfer", "debit", "credit", "charge", "refund", "payout", "settle"],
        idempotency_keywords=["requestid", "request_id", "operationid", "operation_id", "idempotency_key", "idempotencykey"],
        idempotency_control_keywords=["idempot", "dedup", "unique", "lock", "processedmessage", "operationstore", "insertifabsent", "createifabsent"],
        durable_keywords=["save", "insert", "update", "persist", "createoperation", "upsert", "repository", "dao"],
        retry_keywords=["retry", "resend", "attempt", "timeout", "backoff"],
        compensation_keywords=["compensat", "reverse", "reversal", "refund", "rollback", "creditback"],
        inbox_keywords=["inbox", "dedup", "processedmessage", "consumerrecord", "offset", "unique"],
        high_risk_only_llm=bool(ASSESSMENT_CONFIG.get("high_risk_only_llm", True)),
        max_llm_findings=int(ASSESSMENT_CONFIG.get("max_llm_targets", 30)),
    )


DEFAULT_POLICY = load_scan_policy()
