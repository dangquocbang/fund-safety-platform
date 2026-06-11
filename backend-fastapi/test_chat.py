#!/usr/bin/env python3
"""Test chat LLM integration."""
import requests
import json
import time
import sys

BASE_URL = "http://localhost:8000"
SCAN_ID = 1

def main():
    print("=" * 70)
    print("CHAT LLM INTEGRATION TEST")
    print("=" * 70)

    # Step 1: Login
    print("\n[1/4] Logging in...")
    session = requests.Session()
    login_resp = session.post(
        f"{BASE_URL}/auth/login",
        json={
            "email": "admin@example.com",
            "password": "password"
        }
    )

    if login_resp.status_code != 200:
        print(f"❌ Login failed: {login_resp.status_code}")
        print(f"   {login_resp.text}")
        return False

    print("✅ Logged in")

    # Step 2: Send chat question
    print("\n[2/4] Sending chat question...")
    chat_resp = session.post(
        f"{BASE_URL}/ui/api/chats/{SCAN_ID}/messages",
        json={
            "question": "Why AcceptPayment fails R5?",
            "conversation_history": []
        },
        headers={"Content-Type": "application/json"}
    )

    if chat_resp.status_code != 200:
        print(f"❌ Chat request failed: {chat_resp.status_code}")
        print(f"   {chat_resp.text}")
        return False

    print("✅ Got response")
    data = chat_resp.json()

    # Step 3: Analyze response
    print("\n[3/4] Analyzing response...")
    answer = data.get("answer", "")
    query_type = data.get("query_type", "unknown")
    function_name = data.get("function_name", "N/A")
    rule_id = data.get("rule_id", "N/A")

    print(f"   Query Type: {query_type}")
    print(f"   Function: {function_name}")
    print(f"   Rule ID: {rule_id}")
    print(f"   Response Length: {len(answer)} chars")

    # Check if it's fallback
    fallback_markers = [
        "**R5 Status:**",
        "**Issue:**",
        "**Remediation:**",
        "### Issues Found",
    ]
    is_fallback = any(marker in answer for marker in fallback_markers)

    if is_fallback:
        print("   Type: FALLBACK (generic pattern-matched)")
    else:
        print("   Type: LLM (detailed explanation)")

    # Step 4: Grade quality
    print("\n[4/4] Quality assessment...")
    checks = [
        ("Detailed response (>400 chars)", len(answer) > 400),
        ("Has code markers or examples", "```" in answer or "code" in answer.lower()),
        ("Has step-by-step guidance", any(f"{i}." in answer for i in range(1, 6))),
        ("Is LLM response (not fallback)", not is_fallback),
    ]

    passed = sum(1 for _, result in checks if result)
    total = len(checks)

    for desc, result in checks:
        status = "✅" if result else "❌"
        print(f"{status} {desc}")

    print(f"\nQuality Score: {passed}/{total}")

    if passed == total:
        print("✅ EXCELLENT - LLM is working perfectly!")
        return True
    elif passed >= 3:
        print("⚠️  GOOD - LLM is mostly working")
        return True
    else:
        print("❌ FAILED - LLM is not responding properly")
        print("\n📋 First 300 chars of response:")
        print(answer[:300])
        return False

    print("=" * 70)

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)