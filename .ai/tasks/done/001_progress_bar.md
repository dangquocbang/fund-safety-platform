# Current Task

## Objective

Implement scan progress tracking and progress bar UI.

## Background

Current flow:

Upload ZIP
→ build_index
→ discovery
→ targets.yml
→ assessment
→ assessment.json
→ assessment_summary.md
→ report

Currently users see no progress while scan is running.

## Requirements

### Backend

Add scan progress tracking.

Scan status:

* PENDING
* RUNNING
* COMPLETED
* FAILED

Add fields:

* progress_percent
* progress_stage
* error_message
* started_at
* completed_at

Create API:

GET /api/scans/{scan_id}/status

Example:

{
"scan_id": 123,
"status": "RUNNING",
"progress_percent": 45,
"progress_stage": "Discovery provider running"
}

Progress stages:

5% Upload received

10% ZIP extracted

25% build_index

45% discovery running

55% targets.yml generated

75% assessment running

85% assessment.json generated

95% assessment_summary.md generated

100% completed

Use FastAPI BackgroundTasks.

Do not introduce Celery.

Do not introduce Redis.

### UI

Create page:

/ui/scans/{scan_id}/progress

Show:

* project name
* scan status
* current stage
* progress bar

Poll:

/api/scans/{scan_id}/status

every 2 seconds.

When completed:

Show button:

Open Fund Safety Assessment Report

Link:

/ui/scans/{scan_id}/assessment-report

### Constraints

Respect:

AGENTS.md

.ai/memory/project_state.md

.ai/memory/architecture.md

Do not change the core pipeline.

Do not expose internal artifacts.

Do not generate summary.html.

Do not generate assessment_summary.html.

### Acceptance Criteria

* Upload ZIP immediately redirects to progress page
* Progress updates automatically
* Progress reaches 100%
* Assessment report still works
* compileall passes
