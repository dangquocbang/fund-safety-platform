# Task 004: Data Filtering Fixed

## Status: ✅ COMPLETED

Option 1 has been implemented - methods are now filtered at Assessment creation time.

## Implementation Details

### Change: runner.py (lines 126-128)

Added filtering logic before creating Assessment object:

```python
# Extract assessed method IDs from discovery targets (which are filtered)
assessed_method_ids = {ta.method_id for ta in discovery_targets}

# Filter methods to only keep those that were actually assessed
filtered_methods = [m for m in methods if m.id in assessed_method_ids]

# Filter edges to only keep calls between assessed methods
filtered_edges = [e for e in edges if e.source in assessed_method_ids and e.target in assessed_method_ids]

assessment = Assessment(
    ...
    methods=filtered_methods,    # Now only assessed methods
    call_edges=filtered_edges,   # Now only assessed call edges
    ...
)
```

### What Changed

**Before:**
```
assessment.json contained ALL methods from index (including init*, get*, set*, XXX_*)
```

**After:**
```
assessment.json contains ONLY assessed methods (filtered by discovery.yaml config)
```

## Data Flow After Fix

```
1. build_index()                      → methods = [ALL]
2. discover_targets() + filter        → discovery_targets = [FILTERED]
3. assess_targets()                   → target_assessments = [FILTERED]
4. Filter methods & edges             → filtered_methods = [FILTERED] ✓ NEW
5. Assessment(methods=filtered_methods)
6. assessment.json                    → Contains only [FILTERED] ✓ FIXED
7. assessment_summary.md              → Uses target_assessments ✓ Already correct
8. Chat endpoint                      → Reads filtered assessment.json ✓ Now clean
```

## Results

✅ **Consistency achieved:**
- No orphaned methods in assessment.json
- All methods in assessment.json are assessed
- Excluded methods (init*, get*, set*, XXX_*) do NOT appear

✅ **Benefits:**
- Smaller assessment.json file size
- Cleaner data for chat/UI queries
- Only relevant methods in knowledge graph
- Consistent with discovery filtering

✅ **No regressions:**
- All fund-related methods still present
- assessment_summary.md unchanged
- Findings still complete
- Call edges still maintain relationships between assessed methods

## Verification

The filtering ensures:
- Methods in assessment.json = Methods in target_assessments
- Excluded methods not in assessment.json
- Fund methods (Transfer, Debit, etc.) in assessment.json
- call_edges only reference assessed methods

## Code Changes

**File:** `backend-fastapi/app/fund_safety/runner.py`
- Line 126: Extract assessed method IDs
- Line 127: Filter methods list
- Line 128: Filter edges list
- Line 136: Use filtered_methods in Assessment
- Line 137: Use filtered_edges in Assessment

## Acceptance Criteria Met

✅ Methods in assessment.json match target_assessments
✅ Excluded methods (init*, get*, set*, XXX_*) removed from assessment.json
✅ All fund-related methods present
✅ assessment_summary.md unchanged
✅ Chat endpoint now only sees filtered methods
✅ assessment.json file size reduced
✅ python -m compileall app passes
✅ No regressions

## Problem Statement (Context)

**Issue discovered:** Discovery filtering was not applied consistently:
- assessment_summary.md (human report) used filtered target_assessments ✓
- assessment.json (machine data) used ALL methods from index ❌

**Root cause:** Assessment object included unfiltered methods field

**Solution:** Filter methods at Assessment creation time to ensure consistency across all artifacts