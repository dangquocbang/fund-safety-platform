from __future__ import annotations
from collections import defaultdict
from .models import MethodEvidence, Finding, ServiceRiskScore, Severity
from .knowledge import service_name

WEIGHTS = {
    'IDEMPOTENCY': 30,
    'COMPENSATION': 25,
    'RETRY': 15,
    'CONSUMER': 15,
    'ORDERING': 15,
    'LOSSY_KEY': 20,
    'DEFAULT': 10,
}

def _driver(rule_id: str) -> tuple[str,int]:
    r=rule_id.upper()
    if 'IDEMPOT' in r: return ('Missing idempotency', WEIGHTS['IDEMPOTENCY'])
    if 'COMPENS' in r: return ('Missing compensation', WEIGHTS['COMPENSATION'])
    if 'RETRY' in r: return ('Retry safety risk', WEIGHTS['RETRY'])
    if 'CONSUMER' in r or 'INBOX' in r or 'REPLAY' in r: return ('Consumer replay risk', WEIGHTS['CONSUMER'])
    if 'ORDER' in r or 'DURABLE' in r: return ('Unsafe side-effect ordering', WEIGHTS['ORDERING'])
    if 'LOSSY' in r or 'KEY' in r: return ('Lossy key transformation', WEIGHTS['LOSSY_KEY'])
    return ('Fund safety finding', WEIGHTS['DEFAULT'])

def compute_service_risk_scores(methods: list[MethodEvidence], findings: list[Finding]) -> list[ServiceRiskScore]:
    by_method={m.id:m for m in methods}
    score=defaultdict(int); count=defaultdict(int); crit=defaultdict(int); high=defaultdict(int); drivers=defaultdict(list)
    services={service_name(m) for m in methods}
    for f in findings:
        m=by_method.get(f.method_id)
        svc=service_name(m) if m else 'UnknownService'
        label, base=_driver(f.rule_id)
        sev_mult={Severity.CRITICAL:1.4,Severity.HIGH:1.0,Severity.MEDIUM:0.55,Severity.LOW:0.25}[f.severity]
        score[svc]+=int(base*sev_mult*f.confidence)
        count[svc]+=1
        if f.severity==Severity.CRITICAL: crit[svc]+=1
        if f.severity==Severity.HIGH: high[svc]+=1
        if label not in drivers[svc]: drivers[svc].append(label)
    out=[]
    for svc in sorted(services | set(score.keys())):
        out.append(ServiceRiskScore(service=svc,score=min(100,score[svc]),finding_count=count[svc],critical_count=crit[svc],high_count=high[svc],drivers=drivers[svc][:5]))
    return sorted(out, key=lambda x:x.score, reverse=True)
