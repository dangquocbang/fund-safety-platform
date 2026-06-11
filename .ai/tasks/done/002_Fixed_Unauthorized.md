# Current Task

## Status: ✅ COMPLETED

The 401 Unauthorized issue has been fixed.

### Solution Summary

**Root cause:** UI uses HttpOnly cookies (cannot be read by JavaScript), but the original `/api/scans/{scan_id}/status` endpoint required Bearer token in Authorization header.

**Fix:**
1. Created `/ui/scans/{scan_id}/status` endpoint that uses cookie-based auth via `_ui_user()`
2. Updated JavaScript polling to call `/ui/scans/{scan_id}/status` with `credentials: "same-origin"`
3. Kept `/api/scans/{scan_id}/status` for programmatic Bearer-token access

### Implementation Details

**Backend Changes (main.py):**
- Added new endpoint `@app.get("/ui/scans/{scan_id}/status")` (line ~232)
- Uses `_ui_user()` for cookie-based authentication
- Respects existing RBAC (`can_view_scan()`)

**Frontend Changes (scan_detail.html):**
- Changed fetch URL from `/api/scans/{scan_id}/status` to `/ui/scans/{scan_id}/status`
- Added `credentials: "same-origin"` to fetch options

### Acceptance Criteria Met

✅ Admin can access `/ui/scans/{scan_id}/status`
✅ Developer can access `/ui/scans/{scan_id}/status`
✅ Progress bar polling no longer returns 401
✅ Unauthorized anonymous user gets 401/303 redirect
✅ python -m compileall app passes

---

No active implementation task.

When starting a new task, update this file with:

- objective
- target files/classes
- requirements
- constraints
- acceptance criteria