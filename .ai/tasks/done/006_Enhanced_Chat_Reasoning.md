# Task 006: Enhanced Chat Reasoning

## Status: ✅ COMPLETED

Enhanced chat feature with function-level reasoning has been implemented.

## Implementation Summary

### 1. New File: chat_service.py (145 lines)

**Functions:**

1. **`extract_query_intent(question: str)`**
   - Extracts function name, rule ID, keywords from natural language
   - Supports English + Vietnamese
   - Returns: function_name, rule_id, is_specific_query

2. **`find_function_context(assessment, function_name, rule_id)`**
   - Locates function in assessment.json
   - Extracts: source code, R1-R11 results, evidence, call graph
   - Returns complete context for reasoning

3. **`reason_about_function(context, question, rule_id, llm_client)`**
   - Calls Claude/Junie/Ollama with focused prompt
   - Returns LLM reasoning or fallback explanation
   - Max 500 tokens for concise response

4. **`chat_with_reasoning(assessment, question, llm_client)`**
   - Main chat handler with smart routing
   - Routes to function deep-dive OR pattern-based fallback
   - Returns: answer, query_type, function_name, rule_id, evidence

### 2. New File: CHAT_FUNCTION_REASONING.md

System prompt for LLM reasoning:
- R1-R11 rule definitions
- Analysis guidelines
- Common issues (R3, R5, R8)
- Response format with examples

### 3. Updated: main.py

**Changes:**
- Added imports: `chat_service`, `LLMClient`
- Made `/chat` endpoint async
- Replaced old pattern-matching with `chat_with_reasoning()`
- Added response fields: query_type, function_name, rule_id

## Flow Comparison

### Before (Pattern Matching)
```
Question: "Why AcceptPayment fails R5?"
→ Keyword matching on "fail", "R5"
→ Return generic: "Retry issues: HIGH Transfer at..."
```

### After (Function Reasoning)
```
Question: "Why AcceptPayment fails R5?"
→ Extract: func=AcceptPayment, rule=R5
→ Find function + assessment details
→ Call LLM with focused prompt
→ Return detailed explanation with code evidence
```

## Example Responses

### Specific Function Query
```
User: "Tại sao AcceptPayment bị R5: Retry state machine not visible?"

Response (LLM-generated):
"AcceptPayment lacks idempotency in its retry mechanism.

Line 45: retry.Do(func() { transfer(...) })
The transfer is inside the retry loop without state tracking.

If network fails after transfer but before response,
retry will execute transfer again. No idempotency key exists.

Fix:
1. Extract request ID from message header
2. Check if already processed (store request_id → tx_id)
3. On retry, verify transfer already completed
4. Return cached response if duplicate detected"
```

### Generic Question (Fallback)
```
User: "What are the risky methods?"

Response (Pattern-matched):
"Top findings:
- CRITICAL: Debit lacks idempotency in...
- HIGH: Transfer missing request ID propagation...
- HIGH: Payout lacks state machine visibility..."
```

## Architecture

**Smart Routing:**
```
Is specific query (function + rule)?
  ├─ YES → LLM function-level reasoning
  │  └─ Extract context → Call LLM → Return detailed explanation
  └─ NO → Pattern-based response
     └─ Keyword matching → Return standard answer
```

**Context for LLM:**
- Function name, signature, file location
- Source code (excerpt up to 1000 chars)
- R1-R11 assessment results
- Evidence (why it fails)
- Call graph (related functions)
- Signals (retry, idempotency, fund operations)

## Features

✅ **Natural language understanding**
- Extracts function names from English/Vietnamese questions
- Detects rule IDs (R1-R11)
- Identifies specific vs generic queries

✅ **Function-level context**
- Complete code + assessment details
- Related methods (call graph)
- All detected signals + evidence

✅ **LLM reasoning**
- Detailed explanations of issues
- Code analysis with line references
- Practical remediation steps
- Works with Claude/Junie/Ollama

✅ **Graceful fallback**
- Works without LLM enabled
- Pattern matching for generic questions
- No latency overhead for simple queries

✅ **Response enrichment**
- query_type: "function_deep_dive" or "generic"
- function_name, rule_id in response
- Evidence list attached

## Testing

### Test Case 1: Function-Specific Query
```bash
POST /chat
{
  "scan_id": 123,
  "question": "Why does AcceptPayment fail R5?"
}

Response:
{
  "answer": "AcceptPayment lacks idempotency in retry...",
  "query_type": "function_deep_dive",
  "function_name": "AcceptPayment",
  "rule_id": "R5",
  "evidence": [...]
}
```

### Test Case 2: Generic Question
```bash
POST /chat
{
  "scan_id": 123,
  "question": "What are the risky methods?"
}

Response:
{
  "answer": "Top findings: CRITICAL Debit...",
  "query_type": "generic",
  "function_name": null,
  "rule_id": null
}
```

### Test Case 3: Function Not Found
```bash
POST /chat
{
  "scan_id": 123,
  "question": "Why does NonExistentFunc fail?"
}

Response:
{
  "answer": "Top findings: [generic fallback]",
  "query_type": "generic"
}
```

## Code Changes

**Files:**
1. `backend-fastapi/app/chat_service.py` (new, 145 lines)
2. `backend-fastapi/app/fund_safety/prompts/CHAT_FUNCTION_REASONING.md` (new)
3. `backend-fastapi/app/main.py` (updated `/chat` endpoint)

**Key updates in main.py:**
- Line ~17: Added imports
- Line ~359: Made endpoint async
- Line ~367-390: Replaced old chat implementation

## Acceptance Criteria Met

✅ Extract function name + rule from natural language
✅ Handle English + Vietnamese questions
✅ Find function details in assessment.json
✅ Call LLM with focused prompt + function context
✅ Return detailed explanation with code evidence
✅ Fallback to pattern-based for generic questions
✅ Handle function not found gracefully
✅ Works with Claude/Junie/Ollama
✅ Response includes query_type, function_name, rule_id
✅ python -m compileall app passes

## Future Enhancements

- Cache function reasoning results
- Multi-turn conversation (follow-up questions)
- Show code snippets with syntax highlighting
- Suggest fixes from autofix_patch field
- Export reasoning to report
- Support more languages (Chinese, Vietnamese)

## Problem Statement (Context)

**Issue:** Chat feature used keyword pattern matching → generic responses

**Desired:** Function-level deep reasoning
- Extract function name from question
- Call LLM to analyze specific function issue
- Return detailed explanation with code evidence

**Solution:** Intelligent query routing
- Detect specific function queries
- Extract context from assessment
- Call LLM for detailed reasoning
- Fallback to pattern matching for generic questions