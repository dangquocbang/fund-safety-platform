from __future__ import annotations
import hashlib, re
from enum import Enum
from pathlib import Path
from .models import MethodEvidence, Language, CallEvidence, CallKind, EvidenceLevel
from .config import ScanPolicy, DEFAULT_POLICY

JAVA_METHOD_RE = re.compile(r"(?P<anno>(?:\s*@\w+(?:\([^)]*\))?\s*)*)(?:public|private|protected|static|final|synchronized|\s)+[\w<>\[\], ?]+\s+(?P<name>\w+)\s*\((?P<args>[^)]*)\)\s*\{", re.M)
GO_FUNC_RE = re.compile(r"func\s+(?:\((?P<recv>[^)]*)\)\s*)?(?P<name>\w+)\s*\((?P<args>[^)]*)\)(?:\s*\([^)]*\)|\s*[\w\*\.\[\]]+)?\s*\{", re.M)
CALL_RE = re.compile(r"(?P<call>[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s*\(")
ASSIGN_RE = re.compile(r"(?P<left>[A-Za-z_][\w]*)\s*(?::=|=)\s*(?P<right>[^;\n]+)")
CLASS_RE = re.compile(r"\b(?:class|interface|enum)\s+(?P<name>[A-Za-z_][\w]*)")

ENTRYPOINT_HINTS=("@PostMapping","@GetMapping","@PutMapping","@DeleteMapping","@RequestMapping","@GrpcService","func Handler","http.Handle","gin.Context")
CONSUMER_HINTS=("@KafkaListener","ConsumerRecord","consume(","Subscribe","ReadMessage","Poll(","@RabbitListener")

# ── Entrypoint-first discovery constants ─────────────────────────────────────

class EntrypointKind(str, Enum):
    HTTP_HANDLER      = "http_handler"
    GRPC_HANDLER      = "grpc_handler"
    KAFKA_CONSUMER    = "kafka_consumer"
    RABBITMQ_CONSUMER = "rabbitmq_consumer"

# Go: parameter type hints that identify HTTP handlers
HTTP_PARAM_HINTS_GO = (
    "*gin.Context", "gin.Context",
    "echo.Context",
    "http.ResponseWriter",
    "*fiber.Ctx", "fiber.Ctx",
)

# Go: receiver type suffixes that identify gRPC service implementations
GRPC_RECEIVER_SUFFIXES = ("Server", "GrpcService", "ServiceServer")

# Go: patterns in the return type that identify HTTP handler factory methods
# e.g. func (api *T) createOrder() gin.HandlerFunc { return func(c *gin.Context) {...} }
HTTP_HANDLER_RETURN_GO = (
    "gin.HandlerFunc",
    "echo.HandlerFunc",
    "http.HandlerFunc",
    "fiber.Handler",
)

# File path suffixes that indicate auto-generated gRPC stubs (skip these)
GRPC_GENERATED_FILE_SUFFIXES = ("_grpc.pb.go", ".pb.go")

# Go: parameter type hints that identify Kafka consumers
KAFKA_PARAM_HINTS_GO = (
    "kafka.Message", "*kafka.Message",
    "sarama.ConsumerMessage", "*sarama.ConsumerMessage",
    "confluent_kafka.Message", "*confluent_kafka.Message",
)

# Go: parameter type hints that identify RabbitMQ consumers
RABBITMQ_PARAM_HINTS_GO = (
    "amqp.Delivery",
    "rabbitmq.Delivery",
)

# Java: annotation strings (lowercased) for each entrypoint kind
HTTP_ANNOTATIONS_JAVA = frozenset({
    "@postmapping", "@getmapping", "@putmapping",
    "@deletemapping", "@requestmapping", "@patchmapping",
})
GRPC_ANNOTATIONS_JAVA = frozenset({"@grpcservice", "@grpcmethod"})
KAFKA_ANNOTATIONS_JAVA = frozenset({"@kafkalistener"})
RABBITMQ_ANNOTATIONS_JAVA = frozenset({"@rabbitlistener"})

# Regex to extract the receiver type from a Go method signature
# e.g. "func (s *PaymentServer) Charge(...)" → "PaymentServer"
_GO_RECV_RE = re.compile(r"^func\s+\(\s*\w*\s*(\*?\w+)\s*\)")

# Kafka producer method names — these take kafka.Message as output arg, not consumers
KAFKA_PRODUCER_NAMES = frozenset({"produce", "sendmessage", "publish", "send", "write", "publishmessage"})
TRANSACTION_HINTS=("@Transactional","BeginTx","db.Transaction","WithTransaction","transactionTemplate")
SKIP_DIR_HINTS=("/target/","/vendor/","/build/","/.git/","/node_modules/","/dist/")
TEST_HINTS=("/test/","/tests/","test.java","_test.go","mock","fixture")
MODEL_FILE_HINTS=("dto","request","response","entity","model","vo","constant","config","properties")
TRIVIAL_METHODS=("get","set","tostring","hashcode","equals","builder","valueof")

FUND_VERBS={"debit","credit","transfer","withdraw","capture","charge","refund","payout","disburse","settle","settlement","void","reverse","reversal","postentry","book","hold","release"}
EXTERNAL_RECEIVER_HINTS={"client","adapter","gateway","connector","proxy","partner","bank","wallet","ledger","payment","processor","acquirer","issuer","core","external","api"}
DURABLE_METHOD_HINTS={"save","insert","update","upsert","persist","create","createifabsent","mark","lock","trylock","commit","cas","compareandswap"}
DURABLE_RECEIVER_HINTS={"repository","repo","dao","mapper","store","db","database","operationstore","outbox"}
IDEM_HINTS={"idempot","dedup","unique","lock","processedmessage","operationstore","insertifabsent","createifabsent"}
KEY_IDENTITY_HINTS={"operationid","operation_id","requestid","request_id","partnerrequestid","partner_request_id","idempotencykey","idempotency_key"}
RETRY_HINTS={"retry","resend","attempt","backoff","timeout","recover"}
COMP_HINTS={"compensat","reverse","reversal","refund","rollback","creditback"}
INBOX_HINTS={"inbox","dedup","processedmessage","messageid","message_id","consumerrecord","offset","unique"}

def _find_matching_brace(text: str, open_idx: int) -> int:
    depth=0
    for i in range(open_idx, len(text)):
        if text[i]=='{': depth+=1
        elif text[i]=='}':
            depth-=1
            if depth==0: return i
    return len(text)-1

def _line_no(text: str, idx: int) -> int:
    return text.count('\n',0,idx)+1

def _method_id(path: Path, name: str, start: int) -> str:
    return hashlib.sha1(f"{path}:{name}:{start}".encode()).hexdigest()[:12]

def _class_name_before(text: str, idx: int) -> str | None:
    before=text[:idx]
    matches=list(CLASS_RE.finditer(before))
    return matches[-1].group('name') if matches else None

def _line_at(text: str, idx: int) -> str:
    s=text.rfind('\n',0,idx)+1
    e=text.find('\n',idx)
    if e < 0: e=len(text)
    return text[s:e].strip()

def _split_call(call: str) -> tuple[str|None,str]:
    parts=call.split('.')
    if len(parts) == 1:
        return None, parts[0]
    return '.'.join(parts[:-1]), parts[-1]

def _contains_any(text: str, words: set[str] | tuple[str, ...] | list[str]) -> bool:
    low=text.lower()
    return any(w.lower() in low for w in words)

def _classify_call(call: str, line: int, raw: str) -> CallEvidence:
    receiver, method = _split_call(call)
    low_call=call.lower(); low_recv=(receiver or '').lower(); low_method=method.lower(); low_raw=raw.lower()
    receiver_has_external=any(h in low_recv for h in EXTERNAL_RECEIVER_HINTS)
    method_has_fund=any(v in low_method for v in FUND_VERBS)
    raw_has_fund=any(v in low_raw for v in FUND_VERBS)

    # PROVEN: concrete receiver + fund-moving verb. This is the only evidence that can create critical/high side-effect findings.
    if receiver_has_external and method_has_fund:
        return CallEvidence(name=call, receiver=receiver, method=method, line=line, kind=CallKind.EXTERNAL_FUND, level=EvidenceLevel.PROVEN, confidence=0.93, reason="receiver looks like external fund dependency and method is a money-movement verb", raw=raw)

    # PLAUSIBLE: fund verb appears in executable call, but receiver is not clearly external.
    if method_has_fund and receiver:
        return CallEvidence(name=call, receiver=receiver, method=method, line=line, kind=CallKind.EXTERNAL_FUND, level=EvidenceLevel.PLAUSIBLE, confidence=0.62, reason="method name is fund-related but receiver is not confirmed external", raw=raw)

    if any(h in low_recv for h in DURABLE_RECEIVER_HINTS) and any(h in low_method for h in DURABLE_METHOD_HINTS):
        return CallEvidence(name=call, receiver=receiver, method=method, line=line, kind=CallKind.DURABLE_STATE, level=EvidenceLevel.PROVEN, confidence=0.9, reason="repository/dao/store durable write call", raw=raw)
    if any(h in low_call or h in low_raw for h in IDEM_HINTS):
        return CallEvidence(name=call, receiver=receiver, method=method, line=line, kind=CallKind.IDEMPOTENCY_CONTROL, level=EvidenceLevel.PLAUSIBLE, confidence=0.75, reason="idempotency/dedup/operation key control signal", raw=raw)
    if any(h in low_call or h in low_raw for h in RETRY_HINTS):
        return CallEvidence(name=call, receiver=receiver, method=method, line=line, kind=CallKind.RETRY_CONTROL, level=EvidenceLevel.PLAUSIBLE, confidence=0.7, reason="retry/timeout control signal", raw=raw)
    if any(h in low_call or h in low_raw for h in COMP_HINTS):
        return CallEvidence(name=call, receiver=receiver, method=method, line=line, kind=CallKind.COMPENSATION, level=EvidenceLevel.PLAUSIBLE, confidence=0.72, reason="compensation/reversal/refund signal", raw=raw)
    if any(h in low_call or h in low_raw for h in INBOX_HINTS):
        return CallEvidence(name=call, receiver=receiver, method=method, line=line, kind=CallKind.INBOX_DEDUP, level=EvidenceLevel.PLAUSIBLE, confidence=0.72, reason="consumer inbox/dedup barrier signal", raw=raw)
    return CallEvidence(name=call, receiver=receiver, method=method, line=line, kind=CallKind.INTERNAL_CALL if receiver else CallKind.UNKNOWN, level=EvidenceLevel.WEAK, confidence=0.25, reason="ordinary call", raw=raw)

def _extract_call_evidence(body: str, base_line: int) -> list[CallEvidence]:
    out=[]
    for m in CALL_RE.finditer(body):
        call=m.group('call')
        if call in {'if','for','while','switch','return','new','catch','throw','else','try','synchronized'}:
            continue
        line=base_line + body.count('\n',0,m.start())
        raw=_line_at(body, m.start())
        out.append(_classify_call(call, line, raw))
    # de-duplicate by call+line
    seen=set(); dedup=[]
    for ev in out:
        key=(ev.name,ev.line)
        if key not in seen:
            seen.add(key); dedup.append(ev)
    return dedup

def _extract_variables(body: str) -> dict[str,str]:
    d={}
    for m in ASSIGN_RE.finditer(body):
        d[m.group('left')] = m.group('right').strip()[:180]
    return d

def _is_executable(path: Path, method_name: str, body: str, calls: list[CallEvidence]) -> bool:
    low_path=str(path).replace('\\','/').lower()
    low_name=method_name.lower()
    if any(h in low_path for h in TEST_HINTS):
        return False
    if any(h in low_path for h in MODEL_FILE_HINTS) and len(calls) <= 1:
        return False
    if any(low_name.startswith(t) for t in TRIVIAL_METHODS) and len(calls) <= 1:
        return False
    # No executable call and no assignment means usually DTO/getter/simple model.
    if not calls and ':=' not in body and '=' not in body:
        return False
    return True

def _signals(body_and_context: str, call_evidence: list[CallEvidence], policy: ScanPolicy):
    low=body_and_context.lower()
    return {
      'has_idempotency_signal': any(k in low for k in policy.idempotency_keywords),
      'has_durable_state_signal': any(ev.kind == CallKind.DURABLE_STATE for ev in call_evidence),
      'has_external_fund_signal': any(ev.kind == CallKind.EXTERNAL_FUND and ev.level in {EvidenceLevel.PROVEN, EvidenceLevel.PLAUSIBLE} for ev in call_evidence),
      'has_retry_signal': any(ev.kind == CallKind.RETRY_CONTROL for ev in call_evidence) or any(k in low for k in policy.retry_keywords),
      'has_compensation_signal': any(ev.kind == CallKind.COMPENSATION for ev in call_evidence) or any(k in low for k in policy.compensation_keywords),
      'has_inbox_dedup_signal': any(ev.kind == CallKind.INBOX_DEDUP for ev in call_evidence) or any(k in low for k in policy.inbox_keywords),
    }

def scan_file(path: Path, root: Path, policy: ScanPolicy=DEFAULT_POLICY) -> list[MethodEvidence]:
    text=path.read_text(errors='ignore')
    rel=str(path.relative_to(root))
    lang=Language.JAVA if path.suffix=='.java' else Language.GO if path.suffix=='.go' else Language.UNKNOWN
    regex=JAVA_METHOD_RE if lang==Language.JAVA else GO_FUNC_RE if lang==Language.GO else None
    if not regex: return []
    out=[]
    for m in regex.finditer(text):
        open_idx=text.find('{', m.end()-1)
        if open_idx < 0: continue
        close_idx=_find_matching_brace(text, open_idx)
        body=text[open_idx:close_idx+1]
        name=m.group('name')
        start=_line_no(text, m.start())
        end=_line_no(text, close_idx)
        before=text[max(0,m.start()-320):m.start()]
        annos=re.findall(r"@\w+(?:\([^)]*\))?", before)
        sig=text[m.start():open_idx+1].strip()
        call_evidence=_extract_call_evidence(body, start)
        calls=sorted({ev.name for ev in call_evidence})
        is_exec=_is_executable(path, name, body, call_evidence)
        context=body+before+sig
        s=_signals(context, call_evidence, policy)
        out.append(MethodEvidence(
            id=_method_id(path,name,start), language=lang, file_path=rel,
            class_name=_class_name_before(text, m.start()), method_name=name, signature=sig, start_line=start, end_line=end, body=body[:8000],
            calls=calls, call_evidence=call_evidence, variables=_extract_variables(body), annotations=annos,
            is_executable_logic=is_exec,
            is_entrypoint=any(h.lower() in context.lower() for h in ENTRYPOINT_HINTS),
            is_consumer=any(h.lower() in context.lower() for h in CONSUMER_HINTS),
            has_transaction_boundary=any(h.lower() in context.lower() for h in TRANSACTION_HINTS),
            **s
        ))
    return out

def scan_repo(source: str | Path, policy: ScanPolicy=DEFAULT_POLICY) -> list[MethodEvidence]:
    root=Path(source).resolve()
    methods=[]
    for p in root.rglob('*'):
        normalized=str(p).replace('\\','/').lower()
        if p.is_file() and p.suffix in {'.java','.go'} and not any(x in normalized for x in SKIP_DIR_HINTS):
            methods.extend(scan_file(p, root, policy))
    return methods


def _go_receiver_type(sig: str) -> str:
    """Extract receiver struct name (without *) from a Go method signature."""
    m = _GO_RECV_RE.match(sig.strip())
    return (m.group(1) or "").lstrip("*") if m else ""


def _go_params_range(sig: str) -> tuple[int, int] | None:
    """
    Return (start, end) indices of the parameter section within sig, where
    end is the index of the closing ')'. Handles nested brackets correctly.

    'func (recv) Name(PARAMS) ReturnType {'  →  (start_of_PARAMS, idx_of_closing_paren)
    """
    m = re.search(r"\bfunc\s+(?:\([^)]*\)\s*)?\w+\s*\(", sig)
    if not m:
        return None
    start = m.end()
    depth = 1
    for i in range(start, len(sig)):
        ch = sig[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return (start, i)
    return None


def _go_params_section(sig: str) -> str:
    r = _go_params_range(sig)
    return sig[r[0]:r[1]] if r else ""


def _go_return_section(sig: str) -> str:
    """Extract the return type section of a Go function signature."""
    r = _go_params_range(sig)
    if not r:
        return ""
    _, params_close = r
    after = sig[params_close + 1:].strip()
    brace = after.rfind("{")
    return after[:brace].strip() if brace >= 0 else after.strip()


def _go_is_void(sig: str) -> bool:
    """
    Return True if the Go function has no return type (void).

    Works by finding the closing ')' of the parameter list and checking that
    only whitespace (and the opening '{') follows — no return type.
    """
    r = _go_params_range(sig)
    if not r:
        return False
    _, params_close = r
    # Everything after the params closing ')' and before '{'
    after = sig[params_close + 1:].strip().rstrip("{").strip()
    return after == ""


def _go_is_sole_context_param(params: str, context_type: str) -> bool:
    """
    Return True if the Go parameter list contains context_type as the only
    meaningful parameter (i.e. no extra typed params).

    Real gin handlers:  func (x *T) Handle(c *gin.Context)        → True
    Helper functions:   func (x *T) bind(c *gin.Context, req any) → False
    """
    if context_type not in params:
        return False
    parts = [p.strip() for p in params.split(",") if p.strip()]
    extra = [p for p in parts if context_type not in p]
    return len(extra) == 0


def _detect_entrypoint_kind(method: MethodEvidence) -> EntrypointKind | None:
    """
    Determine whether a method is an HTTP/gRPC handler or Kafka/RabbitMQ consumer.

    Detection is signature-based (parameter types, annotations). For Go HTTP
    handlers we require gin.Context to be the SOLE parameter — helper functions
    that accept gin.Context plus additional params are excluded.
    """
    sig = method.signature
    lang = method.language

    if lang == Language.JAVA:
        annotations_lower = " ".join(method.annotations).lower()
        if any(a in annotations_lower for a in HTTP_ANNOTATIONS_JAVA):
            return EntrypointKind.HTTP_HANDLER
        if any(a in annotations_lower for a in GRPC_ANNOTATIONS_JAVA):
            return EntrypointKind.GRPC_HANDLER
        if any(a in annotations_lower for a in KAFKA_ANNOTATIONS_JAVA):
            return EntrypointKind.KAFKA_CONSUMER
        if any(a in annotations_lower for a in RABBITMQ_ANNOTATIONS_JAVA):
            return EntrypointKind.RABBITMQ_CONSUMER
        return None

    if lang == Language.GO:
        params = _go_params_section(sig)
        ret = _go_return_section(sig)

        # HTTP (pattern 1): framework context type is the SOLE parameter AND
        # the function is void (gin.HandlerFunc = func(*Context), no return).
        is_void = _go_is_void(sig)
        for ctx_type in ("gin.Context", "echo.Context", "fiber.Ctx"):
            if _go_is_sole_context_param(params, ctx_type) and is_void:
                return EntrypointKind.HTTP_HANDLER

        # HTTP (pattern 2): factory methods that return gin/echo/http HandlerFunc.
        # e.g. func (api *T) createOrder() gin.HandlerFunc { return func(c *gin.Context) {...} }
        if any(h in ret for h in HTTP_HANDLER_RETURN_GO):
            return EntrypointKind.HTTP_HANDLER

        # stdlib HTTP: both ResponseWriter and Request as parameters
        if "http.ResponseWriter" in params and "*http.Request" in params:
            return EntrypointKind.HTTP_HANDLER

        # Kafka consumer: message type in params AND method is not a producer
        if method.method_name.lower() not in KAFKA_PRODUCER_NAMES:
            if any(h in params for h in KAFKA_PARAM_HINTS_GO):
                return EntrypointKind.KAFKA_CONSUMER

        # RabbitMQ consumer: delivery type in PARAMS section (not return type)
        if any(h in params for h in RABBITMQ_PARAM_HINTS_GO):
            return EntrypointKind.RABBITMQ_CONSUMER

        # gRPC service implementation (two sub-patterns):
        recv = _go_receiver_type(sig)
        is_pb_file = any(method.file_path.endswith(s) for s in GRPC_GENERATED_FILE_SUFFIXES)
        is_client_recv = recv.endswith("Client")

        if not is_pb_file and not is_client_recv and method.method_name[:1].isupper():
            # Pattern A: receiver ends in "Server"/"ServiceServer"
            is_grpc_recv = recv and any(recv.endswith(s) for s in GRPC_RECEIVER_SUFFIXES)
            # Pattern B: signature explicitly uses *pb. types (protobuf-generated types).
            # Requires *pb. in params OR *pb. in return — avoids matching internal methods
            # that happen to take/return custom XxxRequest/XxxResponse structs.
            is_grpc_sig = (
                "context.Context" in params
                and ("*pb." in params or "*pb." in ret)
                and "error" in ret
            )
            if (is_grpc_recv or is_grpc_sig) and "context.Context" in params:
                return EntrypointKind.GRPC_HANDLER

    return None


def detect_entrypoints(methods: list[MethodEvidence]) -> list[tuple[MethodEvidence, EntrypointKind]]:
    """
    Return (method, kind) for every method that is an HTTP/gRPC handler or
    Kafka/RabbitMQ consumer. Test files and non-executable methods are skipped.
    """
    result: list[tuple[MethodEvidence, EntrypointKind]] = []
    for m in methods:
        if not m.is_executable_logic:
            continue
        low_path = m.file_path.lower()
        if any(h in low_path for h in TEST_HINTS):
            continue
        kind = _detect_entrypoint_kind(m)
        if kind is not None:
            result.append((m, kind))
    return result
