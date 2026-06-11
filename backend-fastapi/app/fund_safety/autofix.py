from .models import Finding

def suggest_patch(f: Finding) -> str:
    if f.rule_id == 'FS-001':
        return f"""--- a/{f.file_path}\n+++ b/{f.file_path}\n@@\n+// TODO(fund-safety): create or load Operation by idempotency_key before executing fund side effects.\n+// Required pattern:\n+// 1. operation = operationRepository.createIfAbsent(operationId, PROCESSING)\n+// 2. if operation is terminal: return cached result\n+// 3. execute exactly one external side effect\n+// 4. persist terminal state with CAS/version guard\n"""
    if f.rule_id == 'FS-004':
        return f"""--- a/{f.file_path}\n+++ b/{f.file_path}\n@@\n+// TODO(fund-safety): add inbox dedup barrier keyed by message_id or business operation_id.\n+// Do not call fund-moving dependencies before inbox insert succeeds.\n"""
    return f"""--- a/{f.file_path}\n+++ b/{f.file_path}\n@@\n+// TODO(fund-safety): review {f.rule_id}: {f.title}\n+// Recommendation: {f.remediation}\n"""
