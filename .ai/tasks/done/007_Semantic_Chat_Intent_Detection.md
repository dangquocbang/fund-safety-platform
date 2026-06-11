# Task 007: Semantic Chat Intent Detection

## Status: ✅ COMPLETED

Implemented semantic function matching for chat queries using assessment.json as the source of truth instead of fragile regex patterns.

## Implementation Summary

### Changes to `backend-fastapi/app/chat_service.py`

#### 1. New Function: `extract_question_terms(question: str) -> dict`
Extracts semantic terms from natural language questions:
- **rule_id**: Exact match for R1-R11 rule IDs (case-insensitive regex)
- **capitalized_words**: Potential function names extracted from capitalized words
- **action_verbs**: Common method-related action words (accept, transfer, charge, refund, etc.)
- **keywords**: Query intent words (why, what, how, explain, fail, error, etc.)

#### 2. New Function: `find_matching_functions(assessment: dict, question_terms: dict) -> list[dict]`
Searches assessment.methods with three-tier ranking:
- **Tier 1 (score 100)**: Exact name match - function_name.lower() == word.lower()
- **Tier 2 (score 80)**: Partial name match - word in method_name or vice versa
- **Tier 3 (score 60)**: Action verb match - verb found in method_name
- Returns deduplicated candidates sorted by score (highest first)

#### 3. New Function: `ask_user_to_clarify(candidates: list[dict]) -> dict`
Generates clarification prompt when multiple function candidates found:
- Shows top 5 function names
- Asks user to specify which function they meant
- Returns structured response with `requires_clarification: True`
- Example: "I found multiple matches. Which function did you mean?\n- AcceptPayment\n- ProcessPayment\n- CapturePayment\n\nPlease clarify with the function name..."

#### 4. Updated Function: `extract_query_intent(question: str, assessment: dict) -> dict`
Now semantic matching instead of regex-guessing:
- Takes assessment parameter to look up actual functions
- Uses `extract_question_terms()` to parse question
- Uses `find_matching_functions()` to find candidates
- Returns:
  - `function_name`: Best match function name (or None)
  - `function_id`: Function ID from assessment
  - `rule_id`: Extracted rule ID (R1-R11)
  - `is_specific_query`: True if function found + (rule OR action_verb)
  - `query_type`: "function_specific", "function_general", or "generic"
  - `confidence`: Match confidence (100, 80, 60, or 0)
  - `match_reason`: Why this function was selected
  - `all_candidates`: Top 5 matching functions for disambiguation

#### 5. Updated Function: `chat_with_reasoning(assessment: dict, question: str, llm_client: LLMClient | None = None) -> dict`
Smart routing with four paths:

**Case 1: Exact match + rule/keyword → function_deep_dive**
```
Q: "Why AcceptPayment fails R5?"
→ confidence >= 100, is_specific_query = True
→ Extract function context
→ Call LLM for detailed reasoning
→ Return: {"query_type": "function_deep_dive", "function_name": "AcceptPayment", "rule_id": "R5"}
```

**Case 2: Exact match only → ask_for_specifics**
```
Q: "Tell me about AcceptPayment"
→ confidence >= 100, is_specific_query = False
→ Suggest follow-up questions
→ Return: {"query_type": "ask_for_specifics", "function_name": "AcceptPayment"}
```

**Case 3: Multiple candidates → clarification_needed**
```
Q: "Why does Payment operation fail?"
→ Multiple candidates found (AcceptPayment, ProcessPayment, CapturePayment)
→ Call ask_user_to_clarify()
→ Return: {"query_type": "clarification_needed", "candidates": [...], "requires_clarification": True}
```

**Case 4: No match → generic response**
```
Q: "What are the risky services?"
→ No function found
→ Use pattern-based fallback
→ Return: {"query_type": "generic", "answer": "Top findings: ..."}
```

## Key Features

✅ **Truth from assessment** - Uses actual functions in assessment.json, not guessing
✅ **Semantic matching** - Understands "accept" → AcceptPayment, "Payment" → matches PaymentService methods
✅ **Flexible phrasing** - Works with "why", "tell me", "explain", "What is", etc.
✅ **No fragile regex** - Relies on data-driven matching
✅ **Smart disambiguation** - Asks user to clarify when ambiguous (multiple candidates)
✅ **Ranking** - Exact (100) > Partial (80) > Verb (60) matches
✅ **Confidence scoring** - Response includes match confidence level
✅ **Fallback chain** - Gracefully handles LLM unavailability

## Example Flows

### Flow 1: Exact Match + Rule → Deep Dive ✓
```
User: "Why AcceptPayment fails R5: Retry state machine not visible?"
→ extract_question_terms() finds ["AcceptPayment"], rule "R5"
→ find_matching_functions() returns AcceptPayment (score: 100)
→ is_specific_query = True (has rule)
→ Route to function_deep_dive
→ LLM analyzes specific issue with code evidence
```

### Flow 2: Exact Match Only → Ask for Specifics
```
User: "Tell me about AcceptPayment"
→ extract_question_terms() finds ["AcceptPayment"], no rule
→ find_matching_functions() returns AcceptPayment (score: 100)
→ is_specific_query = False (no rule or verb)
→ Route to ask_for_specifics
→ Suggest follow-ups: "Why AcceptPayment fails R5?", "Is AcceptPayment idempotent?"
```

### Flow 3: Ambiguous → Ask User to Clarify
```
User: "Why does Payment operation fail?"
→ extract_question_terms() finds ["Payment"], no rule
→ find_matching_functions() finds 3 candidates: AcceptPayment (80), ProcessPayment (80), CapturePayment (80)
→ Multiple candidates, confidence < 100
→ Route to clarification_needed
→ "I found multiple matches. Which did you mean?\n- AcceptPayment\n- ProcessPayment\n- CapturePayment"
```

### Flow 4: Action Verb + Rule → Deep Dive ✓
```
User: "Why does accept operation fail retry? (R5)"
→ extract_question_terms() finds verb "accept", rule "R5"
→ find_matching_functions() finds AcceptPayment (score: 60 - verb match)
→ is_specific_query = True (has rule + verb)
→ Route to function_deep_dive
→ LLM analyzes with lower confidence but still helpful
```

### Flow 5: No Match → Generic Response
```
User: "What are the risky services?"
→ extract_question_terms() finds no functions, rules, or verbs
→ find_matching_functions() returns []
→ Route to generic response
→ Return pattern-matched top findings
```

## Test Results

All semantic matching flows tested and passing:
- ✅ Flow 1: Exact match + rule → function_specific, confidence 100
- ✅ Flow 2: Exact match only → function_general, confidence 100
- ✅ Flow 3: Multiple candidates → shows 3 partial matches
- ✅ Flow 4: Action verb + rule → function_specific, confidence 60
- ✅ Flow 5: No match → generic, confidence 0
- ✅ Ranking: Exact (100) > Partial (80) > Verb (60)

## Code Quality

✅ `python3 -m compileall app -q` passes
✅ No breaking changes to existing functions
✅ Backward compatible - assessment parameter added as required
✅ Main.py already correctly passes assessment to chat_with_reasoning()
✅ All response types include confidence scoring

## Integration

**No changes required to main.py** - The `/chat` endpoint already:
1. Loads assessment.json from scan report directory
2. Passes it to `chat_with_reasoning(assessment, question, llm_client)`
3. Returns the enhanced response with query_type, confidence, etc.

## User Feedback Addressed

✅ "từ câu hỏi phải biết được họ đang muốn hỏi function nào, bằng cách xác định naming theo ngữ nghĩa và tra cứu vào assessment function" 
- Implemented semantic matching against assessment.json functions, not regex guessing

✅ "nếu không 'Exact match' thì phải hỏi lại người dùng để xác định cụ thể function đó"
- Implemented ask_user_to_clarify() for ambiguous cases
- Four routing paths ensure proper disambiguation

## Benefits Over Previous Implementation

**Before:**
- Regex patterns fragile and incomplete
- Missed valid function names
- No source of truth
- Generic responses for specific questions
- No disambiguation for ambiguous queries

**After:**
- Looks up functions in assessment.json (source of truth)
- Three-tier semantic matching (exact, partial, verb)
- Explicit confidence scoring
- Smart routing: deep-dive, ask-for-specifics, clarify, or generic
- User gets helpful prompts when confused
- Scales automatically with assessment.methods

## Files Changed

- `backend-fastapi/app/chat_service.py` (256+ lines → 330+ lines)
  - Added: extract_question_terms(), find_matching_functions(), ask_user_to_clarify()
  - Updated: extract_query_intent(), chat_with_reasoning()
  - Fixed: Rule ID extraction to be case-insensitive (r\d+ pattern)

## Acceptance Criteria Met

✅ Exact match cases work correctly
✅ Exact match without specifics prompts for more info
✅ Ambiguous cases ask user to clarify
✅ Weak/partial matches handled gracefully
✅ Generic queries fall back to pattern matching
✅ Ranking: exact (100) > partial (80) > verb (60)
✅ Confidence score in every response
✅ User-friendly messages with next steps
✅ No silent failures - clarifies when unsure
✅ python3 -m compileall app passes

## Future Enhancements

- Cache function reasoning results to avoid duplicate LLM calls
- Add conversation context tracking (follow-up questions on same function)
- Support more action verbs based on actual function names
- Add Vietnamese semantic support (current Vietnamese keywords in prompt, not code)
- Suggest autofix patches when LLM identifies issues
- Export function analysis to report
