from __future__ import annotations
from .models import MethodEvidence, CallEdge, KeyFlow
import re
KEY_NAMES = ('requestid','request_id','partnerrequestid','partner_request_id','operationid','operation_id','transid','trans_id','orderid','order_id','paymentref','merchantref','referenceid')
LOSSY_HINTS = ('substring','truncate','md5','sha1','hash','replace','lowercase','uppercase','random','uuid','time','now')

def build_call_graph(methods: list[MethodEvidence]) -> list[CallEdge]:
    by_name={m.method_name.lower():m for m in methods}
    edges=[]
    for m in methods:
        for c in m.calls:
            last=c.split('.')[-1].lower()
            if last in by_name and by_name[last].id != m.id:
                edges.append(CallEdge(source=m.id,target=by_name[last].id,confidence=0.7,reason=f"call {c}"))
    return edges

def infer_key_flow(methods: list[MethodEvidence]) -> list[KeyFlow]:
    flows=[]
    for m in methods:
        for left,right in m.variables.items():
            low_l=left.lower(); low_r=right.lower()
            if any(k in low_l for k in KEY_NAMES) or any(k in low_r for k in KEY_NAMES):
                lossy=any(h in low_r for h in LOSSY_HINTS)
                src='unknown'
                for k in KEY_NAMES:
                    if k in low_r: src=k; break
                flows.append(KeyFlow(method_id=m.id,source_key=src,target_key=left,transformation=right[:120],lossy=lossy,confidence=0.8 if src!='unknown' else 0.45))
    return flows

def downstream_reachable(start: str, edges: list[CallEdge], max_depth:int=2) -> set[str]:
    adj={}
    for e in edges: adj.setdefault(e.source,[]).append(e.target)
    seen=set(); frontier=[(start,0)]
    while frontier:
        n,d=frontier.pop(0)
        if d>=max_depth: continue
        for t in adj.get(n,[]):
            if t not in seen:
                seen.add(t); frontier.append((t,d+1))
    return seen
