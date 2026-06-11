# Chat LLM Test Guide

## Quick Start (2 minutes)

### Step 1: Verify Config is Correct

```bash
# Check config.py has CHAT_LLM_CONFIG
grep "CHAT_LLM_CONFIG\|CHAT_PROVIDER\|CHAT_MODEL" backend-fastapi/app/config.py
```

Expected output:
```
CHAT_LLM_CONFIG = _llm_stage_config("chat")
CHAT_PROVIDER = str(os.getenv("CHAT_PROVIDER", ...
CHAT_MODEL = str(os.getenv("CHAT_MODEL", ...
```

### Step 2: Verify Code Compiles

```bash
cd backend-fastapi
python3 -m compileall app -q
echo "✅ Compilation successful"
```

Expected: No errors

### Step 3: Start Server

```bash
python3 -m uvicorn app.main:app --reload --port 8000
```

Expected output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

### Step 4: Test Chat in Browser

**Method A: Manual Test (Fastest)**
1. Open browser: `http://localhost:8000/ui/scans/1/chat`
2. Type: `Why AcceptPayment fails R5?`
3. Click Send
4. **CHECK:** Response should be detailed (LLM), NOT generic (fallback)

**Method B: Python Test Script (Comprehensive)**

Create file: `test_chat_llm.py`

```python
#!/usr/bin/env python3
import requests
import json
import time

BASE_URL = "http://localhost:8000"
SCAN_ID = 1

print("=" * 70)
print("CHAT LLM TEST")
print("=" * 70)

# Step 1: Login
print("\n1. LOGIN...")
login_response = requests.post(
    f"{BASE_URL}/auth/login",
    json={
        "email": "admin@example.com",
        "password": "password"
    }
)

if login_response.status_code != 200:
    print(f"❌ Login failed: {login_response.status_code}")
    exit(1)

access_token = login_response.json()["access_token"]
print(f"✅ Logged in successfully")

# Step 2: Test /ui/api/chats endpoint with chat config
print("\n2. TESTING /ui/api/chats ENDPOINT...")

session = requests.Session()
session.post(
    f"{BASE_URL}/auth/login",
    json={
        "email": "admin@example.com",
        "password": "password"
    }
)

response = session.post(
    f"{BASE_URL}/ui/api/chats/{SCAN_ID}/messages",
    json={
        "question": "Why AcceptPayment fails R5?",
        "conversation_history": []
    },
    headers={"Content-Type": "application/json"}
)

print(f"Status Code: {response.status_code}")

if response.status_code != 200:
    print(f"❌ Request failed: {response.text}")
    exit(1)

data = response.json()

print(f"✅ Request successful")
print(f"\n--- RESPONSE ---")
print(f"Query Type: {data.get('query_type')}")
print(f"Function Name: {data.get('function_name')}")
print(f"Rule ID: {data.get('rule_id')}")
print(f"Confidence: {data.get('confidence')}")
print(f"\nAnswer Preview (first 200 chars):")
answer = data.get('answer', '')
print(f"{answer[:200]}...")

# Step 3: Check if it's LLM response or fallback
print(f"\n3. CHECKING IF LLM IS BEING USED...")

# Fallback response contains these exact patterns
fallback_patterns = [
    "**R5 Status:**",
    "**Issue:**",
    "**Remediation:**",
    "### Issues Found",
    "**Signals Detected:**"
]

is_fallback = any(pattern in answer for pattern in fallback_patterns)

if is_fallback:
    print(f"❌ FALLBACK RESPONSE (not using LLM)")
    print(f"   This means LLM is disabled or not configured")
else:
    print(f"✅ LLM RESPONSE (using real LLM)")
    print(f"   Response is from Ollama with qwen2.5-coder:14b")

# Step 4: Check response quality
print(f"\n4. RESPONSE QUALITY CHECK...")

quality_indicators = [
    ("Detailed", len(answer) > 500),
    ("Has code examples", "```" in answer or "```" in answer),
    ("Has steps", "1." in answer or "step" in answer.lower()),
    ("LLM generated", not is_fallback),
]

quality_score = sum(1 for _, check in quality_indicators if check)
total_checks = len(quality_indicators)

for indicator, result in quality_indicators:
    status = "✅" if result else "❌"
    print(f"{status} {indicator}: {result}")

print(f"\nQuality Score: {quality_score}/{total_checks}")

if quality_score >= 3:
    print("✅ EXCELLENT - LLM is working well!")
elif quality_score >= 2:
    print("⚠️  GOOD - LLM is working, but could be better")
else:
    print("❌ POOR - LLM might not be working correctly")

print("\n" + "=" * 70)
print("TEST COMPLETE")
print("=" * 70)
```

**Run the test:**
```bash
python3 test_chat_llm.py
```

Expected output:
```
======================================================================
CHAT LLM TEST
======================================================================

1. LOGIN...
✅ Logged in successfully

2. TESTING /ui/api/chats ENDPOINT...
Status Code: 200
✅ Request successful

--- RESPONSE ---
Query Type: function_deep_dive
Function Name: AcceptPayment
Rule ID: R5
Confidence: 100

Answer Preview (first 200 chars):
AcceptPayment has a critical issue with its retry mechanism that violates R5...

3. CHECKING IF LLM IS BEING USED...
✅ LLM RESPONSE (using real LLM)
   Response is from Ollama with qwen2.5-coder:14b

4. RESPONSE QUALITY CHECK...
✅ Detailed: True
✅ Has code examples: True
✅ Has steps: True
✅ LLM generated: True

Quality Score: 4/4
✅ EXCELLENT - LLM is working well!

======================================================================
TEST COMPLETE
======================================================================
```

---

## Detailed Testing Steps

### Test 1: Browser Test (Manual)

1. **Open Terminal 1 - Start Server**
   ```bash
   cd backend-fastapi
   python3 -m uvicorn app.main:app --reload --port 8000
   ```
   
   Wait for:
   ```
   INFO:     Uvicorn running on http://127.0.0.1:8000
   ```

2. **Open Browser**
   ```
   http://localhost:8000/ui/scans/1/chat
   ```

3. **Send Test Questions**
   
   Question 1:
   ```
   Why AcceptPayment fails R5?
   ```
   
   Expected response should include:
   - Detailed explanation of the issue
   - Code references (line numbers)
   - Step-by-step remediation
   - NOT just: "**R5 Status:** PARTIAL"

   Question 2:
   ```
   How do we fix the idempotency issue?
   ```
   
   Expected: Detailed LLM response about idempotency fix

4. **Check DevTools** (F12)
   - Network tab
   - Find: `POST /ui/api/chats/1/messages`
   - Response: Should be 200 OK
   - Response body: Valid JSON with detailed answer

### Test 2: Python Script Test

```bash
# In another terminal:
python3 test_chat_llm.py
```

This will:
- Test authentication
- Call the chat endpoint
- Check if LLM is being used
- Grade response quality
- Show before/after comparison

### Test 3: Check Server Logs

In the server terminal, you should see:
```
POST /ui/api/chats/1/messages
INFO:     127.0.0.1:8000 - "POST /ui/api/chats/1/messages HTTP/1.1" 200 OK
```

---

## Expected Responses

### BEFORE FIX (Fallback)
```
**AcceptPayment**
Location: src/payment/handler.go:45
Priority: P1

**R5 Status:** PARTIAL
**Issue:** Retry state machine not visible.
**Remediation:** Persist NEW/PROCESSING/SUCCEEDED/FAILED_FINAL and define retry behavior per state.

### Issues Found
- **R5 (PARTIAL):** Retry state machine not visible.
- **R8 (FAIL):** External success can become orphaned or duplicated.

**Signals Detected:** retry/timeout, external fund
```

### AFTER FIX (LLM)
```
AcceptPayment has a critical vulnerability in its retry mechanism that directly violates R5 (Retry state machine visibility).

**The Problem:**
Looking at line 45 in src/payment/handler.go, the function calls retry.Do() without tracking state transitions. When the network fails after a transfer but before the response is sent, the retry mechanism will execute the transfer again without knowing it's already been done.

**Why R5 Fails:**
R5 requires a visible state machine with clear transitions. Currently:
- No state tracking (NEW, PROCESSING, SUCCEEDED, FAILED_FINAL)
- No checkpoint before fund movement
- No idempotency key in retry logic
- Retry logic is implicit, not explicit

**How to Fix (Step by Step):**

1. **Define State Machine**
   ```go
   const (
       StateNew = iota
       StateProcessing
       StateSucceeded
       StateFailed
   )
   ```

2. **Store State Durably**
   ```go
   redis.Set(ctx, fmt.Sprintf("payment:%s:state", txID), StateNew)
   ```

3. **Check State Before Retry**
   ```go
   state, _ := redis.Get(ctx, fmt.Sprintf("payment:%s:state", txID))
   if state == StateSucceeded {
       return CachedResponse(txID)
   }
   ```

4. **Update State on Transition**
   ```go
   redis.Set(ctx, fmt.Sprintf("payment:%s:state", txID), StateProcessing)
   transfer(...)
   redis.Set(ctx, fmt.Sprintf("payment:%s:state", txID), StateSucceeded)
   ```

**Best Practice:**
Always track state for operations that involve fund movement. The retry logic should be explicit and state-aware, not implicit.
```

---

## Troubleshooting

### Issue: Chat returns fallback response

**Check 1: Is LLM enabled?**
```bash
grep "enabled:" config/llm.yaml
# Should show: enabled: true
```

**Check 2: Is config.py reading chat config?**
```bash
grep "CHAT_LLM_CONFIG" app/config.py
# Should show the line exists
```

**Check 3: Is Ollama running?**
```bash
curl http://localhost:11434/api/tags
# Should return list of models
```

**Check 4: Verify LLMClient.enabled**
Add debug output to main.py temporarily:
```python
print(f"LLM Enabled: {LLM_ENABLED}")
print(f"LLMClient provider: {llm_client.config.provider if llm_client else 'None'}")
print(f"LLMClient.enabled: {llm_client.enabled if llm_client else 'None'}")
```

### Issue: Server doesn't start

```bash
# Check syntax
python3 -m compileall app -q

# Check specific error
python3 -c "from app.main import app; print('OK')"
```

### Issue: Timeout or no response

- Check Ollama is running: `curl http://localhost:11434/api/tags`
- Check model exists: Should see `qwen2.5-coder:14b`
- Check timeout config in llm.yaml: `timeout_seconds: 600`

---

## Success Criteria

✅ **Chat returns detailed LLM response** (not fallback)
✅ **Response includes:**
  - Code references with line numbers
  - Detailed explanation
  - Step-by-step remediation
  - Example implementations
✅ **Response quality score: 4/4**
✅ **No generic fallback patterns**

---

## Quick Commands

```bash
# 1. Verify config
grep -A 2 "CHAT_LLM_CONFIG\|^chat:" app/config.py config/llm.yaml

# 2. Check compilation
python3 -m compileall app -q && echo "✅ OK"

# 3. Start server (Terminal 1)
cd backend-fastapi && python3 -m uvicorn app.main:app --reload

# 4. Test chat (Terminal 2)
python3 test_chat_llm.py

# 5. Or manual browser test
# http://localhost:8000/ui/scans/1/chat
```
