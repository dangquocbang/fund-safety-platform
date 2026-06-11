# Chat Functionality Test Guide

## Setup & Prerequisites

### 1. Check Backend Configuration

**LLM Provider:**
```bash
grep "provider:" backend-fastapi/config/llm.yaml | head -3
```

Expected output:
```
provider: ollama          # for discovery
provider: ollama          # for assessment
```

**LLM Enabled:**
```bash
grep "enabled:" backend-fastapi/config/llm.yaml | head -1
```

Expected output:
```
enabled: true
```

### 2. Verify Database

```bash
ls -lh data/fund_safety.db
```

Should show database file exists (~500KB).

### 3. Check Code Fix is in Place

```bash
grep -n "credentials.*same-origin" backend-fastapi/app/static/js/chat.js
```

Expected output:
```
97:                credentials: "same-origin",
```

✅ If all three checks pass, ready to test.

---

## Test 1: Start Backend Server

```bash
cd backend-fastapi

# Option A: Using Python directly
python3 -m uvicorn app.main:app --reload --port 8000

# Option B: Using docker
docker build -t fund-safety .
docker run -p 8000:8000 fund-safety
```

**Expected Output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

✅ Server started successfully.

---

## Test 2: Verify Authentication Works

```bash
# Test login endpoint
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@example.com",
    "password": "password"
  }'
```

**Expected Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "email": "admin@example.com",
    "full_name": "Admin User",
    "role": "admin"
  }
}
```

✅ Authentication working.

---

## Test 3: Check Existing Scans (Get Sample Scan ID)

```bash
# Query database for scans
python3 << 'EOF'
import sqlite3
conn = sqlite3.connect('data/fund_safety.db')
cursor = conn.cursor()
cursor.execute('SELECT id, status, project_id FROM scans LIMIT 5')
rows = cursor.fetchall()
for row in rows:
    print(f"Scan ID: {row[0]}, Status: {row[1]}, Project: {row[2]}")
conn.close()
EOF
```

**Expected Output:**
```
Scan ID: 1, Status: COMPLETED, Project: 1
Scan ID: 2, Status: COMPLETED, Project: 1
...
```

Note the **first completed scan ID** (we'll use it for testing).

---

## Test 4: Test Chat Endpoint (Programmatic)

Create test script: `test_chat.py`

```python
#!/usr/bin/env python3
import requests
import json
from pathlib import Path

BASE_URL = "http://localhost:8000"
SCAN_ID = 1  # Adjust based on your scan

# Step 1: Login
print("=" * 60)
print("Step 1: Login")
print("=" * 60)

login_response = requests.post(
    f"{BASE_URL}/auth/login",
    json={
        "email": "admin@example.com",
        "password": "password"
    }
)

if login_response.status_code != 200:
    print(f"❌ Login failed: {login_response.status_code}")
    print(login_response.text)
    exit(1)

login_data = login_response.json()
access_token = login_data["access_token"]
print(f"✅ Login successful")
print(f"   Token: {access_token[:50]}...")

# Step 2: Test /api/chats endpoint (Bearer token auth)
print("\n" + "=" * 60)
print("Step 2: Test /api/chats (Bearer Token Auth)")
print("=" * 60)

api_response = requests.post(
    f"{BASE_URL}/api/chats/{SCAN_ID}/messages",
    json={
        "question": "Why does AcceptPayment fail?",
        "conversation_history": []
    },
    headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
)

print(f"Status Code: {api_response.status_code}")
if api_response.status_code == 200:
    print("✅ /api/chats endpoint works with Bearer token")
    response_data = api_response.json()
    print(f"   Query Type: {response_data.get('query_type')}")
    print(f"   Confidence: {response_data.get('confidence')}")
    print(f"   Answer: {response_data.get('answer', '')[:100]}...")
else:
    print(f"❌ Failed: {api_response.status_code}")
    print(api_response.text)

# Step 3: Test /ui/api/chats endpoint (Cookie auth)
print("\n" + "=" * 60)
print("Step 3: Test /ui/api/chats (Cookie Auth)")
print("=" * 60)

# Create session to maintain cookies
session = requests.Session()

# Login to get cookies
login_response = session.post(
    f"{BASE_URL}/auth/login",
    json={
        "email": "admin@example.com",
        "password": "password"
    }
)

print(f"Login Status: {login_response.status_code}")
if login_response.status_code == 200:
    print("✅ Logged in (cookies should be set)")
    
    # Now test /ui/api/chats endpoint with cookies
    ui_response = session.post(
        f"{BASE_URL}/ui/api/chats/{SCAN_ID}/messages",
        json={
            "question": "Why does Transfer fail R8?",
            "conversation_history": []
        },
        headers={"Content-Type": "application/json"}
    )
    
    print(f"Status Code: {ui_response.status_code}")
    
    if ui_response.status_code == 200:
        print("✅ /ui/api/chats endpoint works with cookies")
        response_data = ui_response.json()
        print(f"   Query Type: {response_data.get('query_type')}")
        print(f"   Confidence: {response_data.get('confidence')}")
        print(f"   Function: {response_data.get('function_name')}")
        print(f"   Rule: {response_data.get('rule_id')}")
        print(f"   Answer: {response_data.get('answer', '')[:100]}...")
    else:
        print(f"❌ Failed: {ui_response.status_code}")
        print(ui_response.text)
else:
    print(f"❌ Login failed: {login_response.status_code}")

# Step 4: Test conversation history
print("\n" + "=" * 60)
print("Step 4: Test Multi-turn Conversation")
print("=" * 60)

session = requests.Session()
session.post(
    f"{BASE_URL}/auth/login",
    json={
        "email": "admin@example.com",
        "password": "password"
    }
)

# First question
q1_response = session.post(
    f"{BASE_URL}/ui/api/chats/{SCAN_ID}/messages",
    json={
        "question": "Why AcceptPayment fails?",
        "conversation_history": []
    },
    headers={"Content-Type": "application/json"}
)

if q1_response.status_code == 200:
    print("✅ First question successful")
    first_answer = q1_response.json()
    print(f"   Answer: {first_answer.get('answer', '')[:80]}...")
    
    # Follow-up question with history
    q2_response = session.post(
        f"{BASE_URL}/ui/api/chats/{SCAN_ID}/messages",
        json={
            "question": "How do we fix it?",
            "conversation_history": [
                {
                    "role": "user",
                    "content": "Why AcceptPayment fails?"
                },
                {
                    "role": "assistant",
                    "content": first_answer.get('answer', '')
                }
            ]
        },
        headers={"Content-Type": "application/json"}
    )
    
    if q2_response.status_code == 200:
        print("✅ Follow-up question successful")
        second_answer = q2_response.json()
        print(f"   Answer: {second_answer.get('answer', '')[:80]}...")
    else:
        print(f"❌ Follow-up failed: {q2_response.status_code}")
else:
    print(f"❌ First question failed: {q1_response.status_code}")

print("\n" + "=" * 60)
print("ALL TESTS COMPLETED")
print("=" * 60)
```

**Run the test:**
```bash
python3 test_chat.py
```

**Expected Output:**
```
============================================================
Step 1: Login
============================================================
✅ Login successful
   Token: eyJ0eXAiOiJKV1QiLCJhbGc...

============================================================
Step 2: Test /api/chats (Bearer Token Auth)
============================================================
Status Code: 200
✅ /api/chats endpoint works with Bearer token
   Query Type: function_deep_dive
   Confidence: 100
   Answer: AcceptPayment lacks idempotency in its retry...

============================================================
Step 3: Test /ui/api/chats (Cookie Auth)
============================================================
Login Status: 200
✅ Logged in (cookies should be set)
Status Code: 200
✅ /ui/api/chats endpoint works with cookies
   Query Type: function_deep_dive
   Confidence: 100
   Function: Transfer
   Rule: R8
   Answer: Transfer function lacks proper idempotency...

============================================================
Step 4: Test Multi-turn Conversation
============================================================
✅ First question successful
   Answer: AcceptPayment lacks idempotency because...
✅ Follow-up question successful
   Answer: To fix the idempotency issue, you should...

============================================================
ALL TESTS COMPLETED
============================================================
```

---

## Test 5: Manual Browser Testing

### Test 5a: Open Chat Page

1. Open browser: `http://localhost:8000/ui/scans/1/chat`
2. Should see:
   ```
   ✅ Dark navbar with logo and links
   ✅ "Fund Safety Chat" header
   ✅ Welcome message
   ✅ Example questions listed
   ✅ Input box at bottom
   ```

### Test 5b: Send Chat Message

1. Type in input box: `"Why AcceptPayment fails R5?"`
2. Click "Send" or press Enter
3. Should see:
   ```
   ✅ Loading indicator (three dots)
   ✅ Message appears on right (blue)
   ✅ AI response appears on left (white)
   ✅ Response includes: function name, rule, confidence
   ✅ No error messages
   ```

### Test 5c: Follow-up Question

1. Type: `"How do we fix it?"`
2. Click "Send"
3. Should see:
   ```
   ✅ Second user message on right
   ✅ Second AI response on left
   ✅ All previous messages still visible
   ✅ Chat scrolls to show latest
   ✅ No 401 errors
   ```

### Test 5d: DevTools Network Verification

1. Open DevTools (F12)
2. Go to "Network" tab
3. Send a chat message
4. Find: `POST /ui/api/chats/1/messages`
5. Click on it
6. Check "Request Headers" tab
7. Should see:
   ```
   ✅ Cookie: funcsafe_token=eyJ... (PRESENT)
   ✅ Content-Type: application/json
   ✅ Accept: */*
   ```

8. Check "Response" tab
9. Should see:
   ```
   ✅ Status: 200 OK (NOT 401)
   ✅ Valid JSON response
   ✅ answer: "..."
   ✅ query_type: "function_deep_dive" (or other valid type)
   ✅ confidence: 100
   ```

---

## Test 6: Error Cases

### Test 6a: Invalid Scan ID

```bash
curl -X POST http://localhost:8000/ui/api/chats/9999/messages \
  -H "Content-Type: application/json" \
  -d '{"question": "test"}' \
  -b "funcsafe_token=..."
```

**Expected Response:**
```json
{"detail": "scan not found"}
```

Status: **404 Not Found** ✅

### Test 6b: No Authentication

```bash
curl -X POST http://localhost:8000/ui/api/chats/1/messages \
  -H "Content-Type: application/json" \
  -d '{"question": "test"}'
```

**Expected Response:**
```
Redirect to login page or 401 Unauthorized
```

Status: **303 or 401** ✅

### Test 6c: Empty Question

```bash
curl -X POST http://localhost:8000/ui/api/chats/1/messages \
  -H "Content-Type: application/json" \
  -d '{"question": ""}' \
  -b "funcsafe_token=..."
```

**Expected Response:**
```json
{"detail": "question cannot be empty"}
```

Status: **400 Bad Request** ✅

---

## Verification Checklist

### Code Level ✅
- [x] `credentials: "same-origin"` in chat.js:97
- [x] Code compiles: `python3 -m compileall app`
- [x] Both endpoints exist:
  - `/api/chats/{scan_id}/messages` (Bearer token)
  - `/ui/api/chats/{scan_id}/messages` (Cookies)

### API Level ✅
- [ ] `/api/chats` endpoint responds 200 with Bearer token
- [ ] `/ui/api/chats` endpoint responds 200 with cookies
- [ ] Multi-turn conversation works
- [ ] Invalid scan returns 404
- [ ] No auth returns 401/303

### Browser Level ✅
- [ ] Chat page loads at `/ui/scans/1/chat`
- [ ] UI displays correctly
- [ ] Message sends without 401 error
- [ ] Response displays in chat
- [ ] DevTools shows Cookie header in request
- [ ] DevTools shows 200 OK response

### LLM Level ✅
- [ ] LLM provider is configured (ollama)
- [ ] Chat gets LLM response (not mock)
- [ ] Response includes semantic matching results

---

## Expected Results Summary

| Test | Before Fix | After Fix | ✅ Status |
|------|-----------|-----------|----------|
| `/api/chats` with token | 200 OK | 200 OK | ✅ |
| `/ui/api/chats` with cookie | ❌ 401 | ✅ 200 OK | ✅ FIXED |
| Browser DevTools Cookie | ❌ Missing | ✅ Present | ✅ FIXED |
| Chat message displays | ❌ No | ✅ Yes | ✅ FIXED |
| Multi-turn works | ❌ No | ✅ Yes | ✅ WORKS |

---

## Troubleshooting

### Issue: Still Getting 401 Unauthorized

**Check 1: Verify credentials in fetch**
```bash
grep -A 3 "fetch.*ui/api/chats" backend-fastapi/app/static/js/chat.js
```
Must see: `credentials: "same-origin",`

**Check 2: Verify cookies in browser**
- Open DevTools
- Application → Cookies
- Should see `funcsafe_token` cookie

**Check 3: Clear browser cache**
```
Ctrl+Shift+Delete (or Cmd+Shift+Delete on Mac)
```

**Check 4: Hard refresh**
```
Ctrl+Shift+R (or Cmd+Shift+R on Mac)
```

### Issue: Chat Returns No Response

**Check 1: LLM status**
```bash
echo $ASSESSMENT_PROVIDER
# Should be: ollama, claude_code, junie, or anthropic_api
# NOT: mock
```

**Check 2: Ollama is running**
```bash
curl http://localhost:11434/api/tags
```
Should return list of available models.

**Check 3: Check server logs**
```
Server console should show: "Using LLM Provider: ollama"
```

### Issue: Chat Endpoint Returns 404

**Check 1: Endpoint exists**
```bash
grep "def ui_api_chat_message" backend-fastapi/app/main.py
```

**Check 2: Scan exists**
```bash
python3 << 'EOF'
import sqlite3
conn = sqlite3.connect('data/fund_safety.db')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM scans WHERE status = "COMPLETED"')
print(f"Completed scans: {cursor.fetchone()[0]}")
conn.close()
EOF
```

---

## Summary

✅ **Code Fix Verified:** `credentials: "same-origin"` in chat.js
✅ **Compilation Verified:** Code compiles without errors  
✅ **Both Endpoints:** API (token) + UI (cookie) endpoints ready

**Next Step:** Run `test_chat.py` to verify full functionality
