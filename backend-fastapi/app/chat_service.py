from __future__ import annotations
import re
import json
from typing import Any
from pathlib import Path
from .fund_safety.llm import LLMClient


def extract_question_terms(question: str) -> dict:
    """Extract semantic terms from question."""
    question_lower = question.lower()

    # Extract rule ID (R1-R11) - this is exact (case-insensitive)
    rule_match = re.search(r'\b(r\d+)\b', question_lower)
    rule_id = rule_match.group(1).upper() if rule_match else None

    # Extract capitalized words (potential function names)
    capitalized_words = re.findall(r'[A-Z][a-zA-Z0-9_]*', question)

    # Extract lowercase keywords/verbs
    keywords = re.findall(r'\b(?:why|what|how|tell|about|explain|describe|issue|fail|problem|error|bug)\b', question_lower)

    # Extract common method-related words
    action_verbs = re.findall(r'\b(?:accept|transfer|charge|capture|refund|debit|credit|payout|settle|compensate|retry|idempot)\b', question_lower)

    return {
        "rule_id": rule_id,
        "capitalized_words": capitalized_words,
        "keywords": keywords,
        "action_verbs": action_verbs,
        "question_lower": question_lower,
    }


def find_matching_functions(assessment: dict, question_terms: dict) -> list[dict]:
    """
    Find functions in assessment matching question terms.

    Returns list of candidate functions, ranked by relevance.
    """
    methods = assessment.get("methods", [])
    if not methods:
        return []

    candidates = []

    # Strategy 1: Exact name match (highest priority)
    for word in question_terms.get("capitalized_words", []):
        for method in methods:
            if method.get("method_name", "").lower() == word.lower():
                candidates.append({
                    "method": method,
                    "score": 100,
                    "reason": f"Exact name match: {word}"
                })

    # Strategy 2: Partial name match
    for word in question_terms.get("capitalized_words", []):
        word_lower = word.lower()
        for method in methods:
            method_name = method.get("method_name", "").lower()
            if word_lower in method_name or method_name in word_lower:
                candidates.append({
                    "method": method,
                    "score": 80,
                    "reason": f"Name contains: {word}"
                })

    # Strategy 3: Action verb match (e.g., "accept" -> "AcceptPayment")
    for verb in question_terms.get("action_verbs", []):
        for method in methods:
            method_name = method.get("method_name", "").lower()
            if verb in method_name:
                candidates.append({
                    "method": method,
                    "score": 60,
                    "reason": f"Action verb match: {verb}"
                })

    # Deduplicate by method_id and keep highest score
    seen = {}
    for candidate in candidates:
        method_id = candidate["method"].get("id")
        if method_id not in seen or seen[method_id]["score"] < candidate["score"]:
            seen[method_id] = candidate

    # Return ranked by score, then name length (prefer exact matches)
    return sorted(
        seen.values(),
        key=lambda x: (-x["score"], len(x["method"].get("method_name", "")))
    )


def extract_query_intent(question: str, assessment: dict) -> dict:
    """
    Extract query intent by matching against actual functions in assessment.
    """
    terms = extract_question_terms(question)

    # Find matching functions in assessment
    matching_functions = find_matching_functions(assessment, terms)

    if not matching_functions:
        # No matching function - generic query
        return {
            "function_name": None,
            "function_id": None,
            "rule_id": terms.get("rule_id"),
            "is_specific_query": False,
            "query_type": "generic",
            "confidence": 0,
            "all_candidates": [],
        }

    # Found matching function(s)
    best_match = matching_functions[0]
    function_name = best_match["method"].get("method_name")
    function_id = best_match["method"].get("id")
    rule_id = terms.get("rule_id")

    # Specific query if: function found AND (rule mentioned OR action verb used)
    is_specific = bool(function_name) and (bool(rule_id) or bool(terms.get("action_verbs")))

    return {
        "function_name": function_name,
        "function_id": function_id,
        "rule_id": rule_id,
        "is_specific_query": is_specific,
        "query_type": "function_specific" if is_specific else "function_general",
        "confidence": best_match["score"],
        "match_reason": best_match["reason"],
        "all_candidates": matching_functions[:5],
    }


def find_function_context(assessment: dict, function_name: str, rule_id: str | None = None) -> dict | None:
    """
    Find function details in assessment and extract context for reasoning.
    """
    methods = assessment.get("methods", [])
    target_assessments = assessment.get("target_assessments", [])

    # Find method by name (case-insensitive)
    method = next((m for m in methods if m.get("method_name", "").lower() == function_name.lower()), None)
    if not method:
        return None

    method_id = method.get("id")

    # Find assessment for this method
    ta = next((t for t in target_assessments if t.get("method_id") == method_id), None)
    if not ta:
        return None

    # Extract rule result if specified
    rule_result = None
    if rule_id:
        criteria = ta.get("criteria", [])
        rule_result = next((c for c in criteria if c.get("id") == rule_id), None)

    # Extract evidence
    evidence = []
    for criterion in ta.get("criteria", []):
        if criterion.get("status") in ["FAIL", "PARTIAL"]:
            evidence.append({
                "rule": criterion.get("id"),
                "status": criterion.get("status"),
                "risk": criterion.get("risk"),
                "fix": criterion.get("fix"),
            })

    # Get call relationships
    edges = assessment.get("call_edges", [])
    calls = [e.get("target") for e in edges if e.get("source") == method_id]
    called_by = [e.get("source") for e in edges if e.get("target") == method_id]

    return {
        "method_id": method_id,
        "method_name": method.get("method_name"),
        "class_name": method.get("class_name"),
        "file_path": method.get("file_path"),
        "signature": method.get("signature"),
        "source_code": method.get("body", ""),
        "language": method.get("language"),
        "start_line": method.get("start_line"),
        "end_line": method.get("end_line"),
        "rule_result": rule_result,
        "all_evidence": evidence,
        "calls": calls[:5],
        "called_by": called_by[:5],
        "has_retry_signal": method.get("has_retry_signal", False),
        "has_idempotency_signal": method.get("has_idempotency_signal", False),
        "has_external_fund_signal": method.get("has_external_fund_signal", False),
        "priority": ta.get("priority", "P2"),
        "score": ta.get("score"),
    }


def _format_conversation_history(conversation_history: list | None, max_turns: int = 8) -> str:
    """Render prior turns into a transcript block for multi-turn context."""
    if not conversation_history:
        return ""
    lines = []
    for msg in conversation_history[-max_turns:]:
        role = (msg.get("role") or "").lower()
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        speaker = "User" if role == "user" else "Assistant"
        lines.append(f"{speaker}: {content}")
    if not lines:
        return ""
    return "## Conversation So Far\n" + "\n".join(lines) + "\n"


def reason_about_function(
    function_context: dict,
    original_question: str,
    rule_id: str | None = None,
    llm_client: LLMClient | None = None,
    conversation_history: list | None = None,
) -> str:
    """
    Call LLM to reason about function issue with focused prompt.
    Returns LLM reasoning or fallback text.
    """
    # DEBUG
    print(f"[CHAT DEBUG] llm_client: {llm_client}")
    if llm_client:
        print(f"[CHAT DEBUG] llm_client.config.provider: {llm_client.config.provider}")
        print(f"[CHAT DEBUG] llm_client.enabled: {llm_client.enabled}")

    if not llm_client or not llm_client.enabled:
        print(f"[CHAT DEBUG] Using fallback (llm_client={llm_client}, enabled={llm_client.enabled if llm_client else 'N/A'})")
        return _fallback_function_explanation(function_context, rule_id)

    print(f"[CHAT DEBUG] Using LLM with provider: {llm_client.config.provider}")

    rule_section = ""
    if rule_id and function_context.get("rule_result"):
        rr = function_context["rule_result"]
        rule_section = f"""
## Rule Assessment (R1-R11)

Rule: {rule_id}
Status: {rr.get('status', 'UNKNOWN')}
Risk: {rr.get('risk', 'N/A')}
Fix: {rr.get('fix', 'N/A')}
"""

    evidence_section = ""
    if function_context.get("all_evidence"):
        evidence_lines = [f"- {e['rule']}: {e['status']} - {e['risk']}" for e in function_context["all_evidence"][:5]]
        evidence_section = "## Evidence\n" + "\n".join(evidence_lines)

    code_excerpt = function_context.get("source_code", "")[:1000]

    history_section = _format_conversation_history(conversation_history)

    prompt = f"""You are a Fund Safety Platform AI Assistant. Analyze this function and answer the user's question.

## Function
Name: {function_context.get('method_name')}
Class: {function_context.get('class_name', 'N/A')}
File: {function_context.get('file_path')}:{function_context.get('start_line')}
Priority: {function_context.get('priority')}

## Code (excerpt)
```
{code_excerpt}
```

{rule_section}

{evidence_section}

## Signals Detected
- Retry mechanism: {function_context.get('has_retry_signal')}
- Idempotency markers: {function_context.get('has_idempotency_signal')}
- Fund operations: {function_context.get('has_external_fund_signal')}

{history_section}
## User Question
{original_question}

Provide a detailed explanation addressing the user's question. Include:
1. Why the function has detected issues
2. Code evidence from the function body
3. Specific remediation steps
Keep the response concise but thorough.
"""

    # Let exceptions propagate to the caller so the real error can be shown to
    # the user instead of being masked by a generic deterministic fallback.
    return llm_client.generate(prompt)


def _fallback_function_explanation(function_context: dict, rule_id: str | None = None) -> str:
    """Fallback explanation without LLM."""
    lines = [
        f"## {function_context.get('method_name')}",
        f"Location: {function_context.get('file_path')}:{function_context.get('start_line')}",
        f"Priority: {function_context.get('priority')}",
        "",
    ]

    if rule_id and function_context.get("rule_result"):
        rr = function_context["rule_result"]
        lines.extend([
            f"**{rule_id} Status:** {rr.get('status')}",
            f"**Issue:** {rr.get('risk', 'N/A')}",
            f"**Remediation:** {rr.get('fix', 'N/A')}",
            "",
        ])

    if function_context.get("all_evidence"):
        lines.append("### Issues Found")
        for e in function_context["all_evidence"][:3]:
            lines.append(f"- **{e['rule']} ({e['status']}):** {e['risk']}")
        lines.append("")

    signals = []
    if function_context.get("has_retry_signal"):
        signals.append("retry/timeout")
    if function_context.get("has_idempotency_signal"):
        signals.append("idempotency")
    if function_context.get("has_external_fund_signal"):
        signals.append("external fund")

    if signals:
        lines.append(f"**Signals Detected:** {', '.join(signals)}")

    return "\n".join(lines)


def ask_user_to_clarify(candidates: list[dict]) -> dict:
    """
    When multiple matches, ask user which function they meant.
    """
    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    # Multiple candidates - ask user to clarify
    candidate_names = [c["method"].get("method_name") for c in candidates[:5]]

    return {
        "answer": f"I found multiple matches. Which function did you mean?\n\n" +
                 "\n".join(f"- {name}" for name in candidate_names) +
                 "\n\nPlease clarify with the function name, e.g.: 'Why AcceptPayment fails R5?'",
        "query_type": "clarification_needed",
        "candidates": candidate_names,
        "requires_clarification": True,
        "confidence": 0,
    }


CHAT_SYSTEM_PROMPT = (
    "You are the Fund Safety Platform assistant for ONE specific scanned project. "
    "Your job is to help the user understand THIS project's fund-safety audit: its "
    "functions, the R1-R11 idempotency / fund-safety rules, findings, risks, scores, "
    "and remediation steps. "
    "Ground every answer ONLY in the audit data provided in the prompt — never invent "
    "functions, rules, code, or findings that are not present. If the audit data does "
    "not contain the answer (for example the user names a function that was not "
    "audited), say so plainly and point them to what IS available. "
    "If the user asks anything unrelated to this project or its fund-safety audit "
    "(general knowledge, other software, world facts, casual chit-chat, etc.), politely "
    "decline in one short sentence and remind them you only answer questions relevant "
    "to this project's fund-safety audit. "
    "Always reply in the same language the user wrote in. Be concise and concrete, and "
    "cite function names, rule IDs (R1-R11), and file:line where relevant."
)


def _format_audit_context(assessment: dict, max_targets: int = 25) -> str:
    """Compact, model-friendly summary of the whole audit for chat grounding."""
    project = assessment.get("project") or "this project"
    summary = assessment.get("summary", {}) or {}
    tas = assessment.get("target_assessments", []) or []
    risk_scores = assessment.get("risk_scores", []) or []

    lines = [f"Project: {project}"]
    by_sev = summary.get("by_severity") or {}
    if by_sev:
        lines.append("Findings by severity: " + ", ".join(f"{k}={v}" for k, v in by_sev.items() if v))
    lines.append(f"Audited functions ({len(tas)}):")
    for ta in tas[:max_targets]:
        name = ta.get("method") or ta.get("method_id")
        cls = ta.get("class_name")
        label = f"{cls}.{name}" if cls else name
        loc = f"{ta.get('file_path')}:{ta.get('start_line')}"
        lines.append(
            f"- {label} [{loc}] priority={ta.get('priority')} "
            f"overall={ta.get('overall_status')} score={ta.get('score')}"
        )
        for c in ta.get("criteria", []) or []:
            if c.get("status") in ("FAIL", "PARTIAL"):
                seg = f"    {c.get('id')} {c.get('status')}"
                risk = (c.get("risk") or "").strip()
                fix = (c.get("fix") or "").strip()
                if risk:
                    seg += f": {risk}"
                if fix:
                    seg += f" | fix: {fix}"
                lines.append(seg)
    if len(tas) > max_targets:
        lines.append(f"... and {len(tas) - max_targets} more audited functions")
    if risk_scores:
        lines.append(
            "Service risk scores: "
            + ", ".join(f"{r.get('service')}={r.get('score')}/100" for r in risk_scores[:8])
        )
    return "\n".join(lines)


def answer_with_llm(
    assessment: dict,
    question: str,
    llm_client: LLMClient,
    conversation_history: list | None = None,
    function_context: dict | None = None,
) -> str:
    """LLM-first chat: answer any question grounded in the full audit context."""
    audit_context = _format_audit_context(assessment)
    history_section = _format_conversation_history(conversation_history)

    function_section = ""
    if function_context:
        evidence = function_context.get("all_evidence") or []
        ev_lines = "\n".join(
            f"- {e.get('rule')}: {e.get('status')} - {e.get('risk', '')}" for e in evidence[:6]
        )
        code = (function_context.get("source_code") or "")[:1500]
        function_section = f"""
## Focused Function (the user most likely refers to this)
Name: {function_context.get('method_name')}
Class: {function_context.get('class_name', 'N/A')}
File: {function_context.get('file_path')}:{function_context.get('start_line')}
Priority: {function_context.get('priority')}
Signals: retry={function_context.get('has_retry_signal')}, idempotency={function_context.get('has_idempotency_signal')}, fund={function_context.get('has_external_fund_signal')}
Failing/partial criteria:
{ev_lines or '- (none recorded)'}

Source (excerpt):
```
{code}
```
"""

    prompt = f"""## Fund-Safety Audit Data for This Project
{audit_context}
{function_section}
{history_section}
## User Question
{question}

Answer using ONLY the audit data above. If the question is not about this project or
its fund-safety audit, politely decline as instructed in your system role.
"""
    return llm_client.generate(prompt, system=CHAT_SYSTEM_PROMPT)


def chat_with_reasoning(
    assessment: dict,
    question: str,
    llm_client: LLMClient | None = None,
    conversation_history: list | None = None,
) -> dict:
    """Main chat handler.

    LLM-first: when a provider is enabled, the model answers every question grounded in
    the full audit context (and the focused function when one is clearly referenced),
    and out-of-scope questions are declined via the system prompt. The deterministic
    keyword router below is used only when the LLM is intentionally disabled (mock/off).
    """
    intent = extract_query_intent(question, assessment)

    # --- LLM-first path -----------------------------------------------------
    if llm_client and getattr(llm_client, "enabled", False):
        fn = intent.get("function_name")
        function_context = None
        # Only attach a focused function on a confident exact-name match, so fuzzy
        # partial matches (e.g. "Pháp" → "Pay") don't mislabel out-of-scope answers.
        if fn and intent.get("confidence", 0) >= 100:
            function_context = find_function_context(assessment, fn, intent.get("rule_id"))
        try:
            answer = answer_with_llm(
                assessment, question, llm_client, conversation_history, function_context
            )
        except Exception as exc:
            # Surface the real model error instead of a generic fallback.
            provider = llm_client.config.provider if llm_client and llm_client.config else "unknown"
            print(f"[CHAT ERROR] LLM generate failed (provider={provider}): {exc!r}")
            return {
                "answer": (
                    f"⚠️ Unable to get a response from the AI model "
                    f"(provider: `{provider}`).\n\n"
                    f"**Error:** {exc}\n\n"
                    f"Please check the LLM configuration or try again."
                ),
                "query_type": "error",
                "function_name": fn,
                "rule_id": intent.get("rule_id"),
                "error": str(exc),
                "confidence": 0,
            }
        return {
            "answer": answer,
            "query_type": "function_deep_dive" if function_context else "assistant",
            # Only surface a function chip when we actually focused on one.
            "function_name": function_context.get("method_name") if function_context else None,
            "rule_id": intent.get("rule_id"),
            "evidence": (function_context or {}).get("all_evidence", []),
            "confidence": intent.get("confidence", 0),
        }

    # --- Deterministic fallback (LLM disabled by config) --------------------
    # Case 1: Exact match with rule/keyword → focused deterministic explanation
    if intent["is_specific_query"] and intent["function_name"] and intent["confidence"] >= 100:
        context = find_function_context(assessment, intent["function_name"], intent["rule_id"])
        if context:
            return {
                "answer": _fallback_function_explanation(context, intent["rule_id"]),
                "query_type": "function_deep_dive",
                "function_name": intent["function_name"],
                "rule_id": intent["rule_id"],
                "evidence": context.get("all_evidence", []),
                "confidence": intent["confidence"],
            }

    # Case 2: Exact match but no rule/keyword → ask user for more specifics
    if intent["function_name"] and intent["confidence"] >= 100 and not intent["is_specific_query"]:
        return {
            "answer": f"Found function: **{intent['function_name']}**\n\n" +
                     f"What would you like to know about it?\n\n" +
                     f"Try asking:\n" +
                     f"- 'Why {intent['function_name']} fails R5?'\n" +
                     f"- 'Is {intent['function_name']} idempotent?'\n" +
                     f"- 'Explain {intent['function_name']} retry handling'",
            "query_type": "ask_for_specifics",
            "function_name": intent["function_name"],
            "confidence": intent["confidence"],
        }

    # Case 3: Multiple candidates → ask user to clarify
    if intent.get("all_candidates") and len(intent["all_candidates"]) > 1:
        clarification = ask_user_to_clarify(intent["all_candidates"])
        if clarification and clarification.get("requires_clarification"):
            return clarification

    # Case 4: No match or weak match → generic response
    answer = _pattern_matched_response(assessment, question)
    return {
        "answer": answer,
        "query_type": "generic",
        "function_name": None,
        "rule_id": None,
        "evidence": None,
        "confidence": 0,
    }


def _pattern_matched_response(assessment: dict, question: str) -> str:
    """Fallback pattern-matched response for generic questions."""
    q = question.lower()
    findings = assessment.get("findings", [])
    risk_scores = assessment.get("risk_scores", [])

    def top_findings(n=5):
        order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        return sorted(findings, key=lambda f: (order.get(f.get("severity"), 0), f.get("confidence", 0)), reverse=True)[:n]

    if "risk" in q or "risky" in q or "nguy" in q:
        bullets = [f"- {r.get('service')}: risk score {r.get('score')}/100" for r in risk_scores[:5]]
        return "Top risky services:\n" + "\n".join(bullets) if bullets else "No risk scores generated."
    elif "compensation" in q or "compensate" in q or "hoàn" in q:
        fs = [f for f in findings if "COMPENS" in f.get("rule_id", "").upper()]
        if not fs:
            fs = top_findings(3)
        return "Compensation issues:\n" + "\n".join([f"- {f.get('severity')} {f.get('method_name')}" for f in fs[:5]])
    elif "idempot" in q or "retry" in q:
        fs = [f for f in findings if "R5" in f.get("rule_id", "") or "R3" in f.get("rule_id", "")]
        if not fs:
            fs = top_findings(3)
        return "Idempotency/Retry issues:\n" + "\n".join([f"- {f.get('severity')} {f.get('method_name')}" for f in fs[:5]])
    else:
        fs = top_findings(5)
        return "Top findings:\n" + "\n".join([f"- {f.get('severity')} {f.get('title')} in {f.get('method_name')}" for f in fs])