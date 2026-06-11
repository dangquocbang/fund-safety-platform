from __future__ import annotations
import re
from .models import MethodEvidence, CallEdge, KeyFlow, Finding, KnowledgeNode, KnowledgeEdge

BUSINESS_ENTITY_PATTERNS = {
    'PaymentOrder': ('order', 'paymentorder', 'payment_order'),
    'Transaction': ('transaction', 'trans', 'txn'),
    'Ledger': ('ledger', 'bookkeeping', 'journal'),
    'Settlement': ('settlement', 'settle', 'reconcile', 'reconciliation'),
    'Wallet': ('wallet', 'balance', 'account'),
    'BankPartner': ('bank', 'partner', 'adapter', 'gateway'),
}
FUND_MOVEMENT_PATTERNS = ('debit','credit','transfer','withdraw','capture','charge','refund','payout','disburse')
KEY_CANONICAL = {
    'requestid': 'requestId', 'request_id': 'requestId',
    'partnerrequestid': 'partnerRequestId', 'partner_request_id': 'partnerRequestId',
    'operationid': 'operationId', 'operation_id': 'operationId',
    'transid': 'transId', 'trans_id': 'transId',
    'orderid': 'orderId', 'order_id': 'orderId',
    'paymentref': 'paymentRef', 'merchantref': 'merchantRef', 'referenceid': 'referenceId'
}

def service_name(m: MethodEvidence) -> str:
    if m.class_name:
        return m.class_name
    parts = m.file_path.replace('\\','/').split('/')
    return parts[-1].split('.')[0] if parts else 'UnknownService'

def _add_node(nodes: dict[str, KnowledgeNode], node: KnowledgeNode):
    if node.id not in nodes:
        nodes[node.id] = node

def _add_edge(edges: list[KnowledgeEdge], source: str, target: str, typ: str, confidence: float=0.7, evidence: str|None=None):
    key=(source,target,typ,evidence)
    if not any((e.source,e.target,e.type,e.evidence)==key for e in edges):
        edges.append(KnowledgeEdge(source=source,target=target,type=typ,confidence=confidence,evidence=evidence))

def build_knowledge_graph(methods: list[MethodEvidence], call_edges: list[CallEdge], key_flows: list[KeyFlow], findings: list[Finding]) -> tuple[list[KnowledgeNode], list[KnowledgeEdge]]:
    nodes: dict[str, KnowledgeNode] = {}
    edges: list[KnowledgeEdge] = []
    by_method={m.id:m for m in methods}

    for m in methods:
        svc=service_name(m)
        sid=f'service:{svc}'
        mid=f'method:{m.id}'
        _add_node(nodes, KnowledgeNode(id=sid,label=svc,type='Service',properties={'language':m.language.value}))
        _add_node(nodes, KnowledgeNode(id=mid,label=m.method_name,type='Method',properties={'file':m.file_path,'line':m.start_line,'entrypoint':m.is_entrypoint}))
        _add_edge(edges,sid,mid,'OWNS_METHOD',0.95,f'{m.file_path}:{m.start_line}')

        low=(m.class_name or '' + ' ' + m.method_name + ' ' + m.body).lower()
        for entity, hints in BUSINESS_ENTITY_PATTERNS.items():
            if any(h in low for h in hints):
                eid=f'entity:{entity}'
                _add_node(nodes, KnowledgeNode(id=eid,label=entity,type='BusinessEntity'))
                _add_edge(edges,mid,eid,'TOUCHES_ENTITY',0.7,f'{m.file_path}:{m.start_line}')
        for ev in getattr(m, 'call_evidence', []):
            if ev.kind == 'EXTERNAL_FUND' and ev.level in {'PROVEN', 'PLAUSIBLE'}:
                fid=f'fund:{m.id}:{ev.line}'
                label='Confirmed external fund movement' if ev.level == 'PROVEN' else 'Plausible fund movement'
                _add_node(nodes, KnowledgeNode(id=fid,label=label,type='FundMovement',properties={'method':m.method_name,'call':ev.name,'line':ev.line,'level':ev.level}))
                _add_edge(edges,mid,fid,'MUTATES_FUND',ev.confidence,f'{m.file_path}:{ev.line} {ev.raw or ev.name}')
        if m.has_compensation_signal:
            cid=f'compensation:{m.id}'
            _add_node(nodes, KnowledgeNode(id=cid,label='Compensation path',type='Compensation'))
            _add_edge(edges,mid,cid,'COMPENSATES',0.75,f'{m.file_path}:{m.start_line}')
        if m.has_idempotency_signal:
            iid=f'control:idempotency:{m.id}'
            _add_node(nodes, KnowledgeNode(id=iid,label='Idempotency control',type='Control'))
            _add_edge(edges,mid,iid,'HAS_CONTROL',0.8,f'{m.file_path}:{m.start_line}')

    for ce in call_edges:
        if ce.source in by_method and ce.target in by_method:
            _add_edge(edges,f'method:{ce.source}',f'method:{ce.target}','CALLS',ce.confidence,ce.reason)

    for kf in key_flows:
        src = KEY_CANONICAL.get(kf.source_key.lower().replace('-','_'), kf.source_key) if kf.source_key != 'unknown' else 'unknownKey'
        tgt_raw = re.sub(r'[^a-zA-Z0-9_]', '', kf.target_key)
        tgt = KEY_CANONICAL.get(tgt_raw.lower(), tgt_raw or 'derivedKey')
        src_id=f'key:{src}'; tgt_id=f'key:{tgt}'
        _add_node(nodes, KnowledgeNode(id=src_id,label=src,type='OperationKey'))
        _add_node(nodes, KnowledgeNode(id=tgt_id,label=tgt,type='OperationKey'))
        rel='LOSSY_TRANSFORM' if kf.lossy else 'SAME_INTENT_OR_DERIVED'
        _add_edge(edges,src_id,tgt_id,rel,kf.confidence,kf.transformation)
        _add_edge(edges,f'method:{kf.method_id}',tgt_id,'USES_KEY',kf.confidence,kf.transformation)

    for f in findings:
        fid=f'finding:{f.rule_id}:{f.method_id}:{f.start_line}'
        _add_node(nodes, KnowledgeNode(id=fid,label=f.title,type='Finding',properties={'severity':f.severity.value,'confidence':f.confidence}))
        _add_edge(edges,f'method:{f.method_id}',fid,'HAS_FINDING',0.95,f'{f.file_path}:{f.start_line}')

    return list(nodes.values()), edges
