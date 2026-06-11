from __future__ import annotations

import html as html_lib
import json
import re
from pathlib import Path
from typing import Any

from .models import Assessment

ORDERED_CRITERIA = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10"]
STATUS_ICON = {"PASS": "✅", "FAIL": "❌", "PARTIAL": "⚠️", "N/A": "—", "NOT_FOUND": "NOT_FOUND"}

# Canonical logical artifact keys. The scan folder is already unique
# (reports/user-<id>/<project>/scan-<id>-<timestamp>/), so the summary
# has exactly one canonical Markdown artifact and HTML is rendered at request time.
ASSESSMENT_SUMMARY_KEY = "assessment_summary"
ARTIFACT_MANIFEST = "artifact_manifest.json"


def _safe_filename_part(value: str | None, fallback: str = "unknown") -> str:
    value = (value or fallback).strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-._")
    return value or fallback


def _artifact_filename(prefix: str | None, suffix: str, ext: str) -> str:
    safe_prefix = _safe_filename_part(prefix, "scan")
    return f"{safe_prefix}_{suffix}.{ext}"


def write_reports(a: Assessment, out: str | Path, artifact_prefix: str | None = None) -> dict[str, Any]:
    """Write scan artifacts and return an artifact manifest.

    Clean Phase 1 contract:
    - `assessment.json` is the machine-readable source for UI/chat.
    - one canonical `*_assessment_summary.md` is the human-readable assessment.
    - `artifact_manifest.json` points to canonical artifacts.
    - HTML is NOT persisted; FastAPI renders Markdown to HTML on demand.

    This avoids duplicated files such as `summary.html` and
    `idempotency_audit_summary.html` in every scan folder.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    summary_md_name = _artifact_filename(artifact_prefix, ASSESSMENT_SUMMARY_KEY, "md")
    summary_markdown = idempotency_audit_summary_markdown(a)

    artifacts = {
        "assessment_json": "assessment.json",
        "assessment_summary_md": summary_md_name,
        "targets_yml": "targets.yml",
        "index_txt": "index.txt",
        "findings_md": "findings.md",
        "knowledge_graph_json": "knowledge_graph.json",
        "risk_scores_json": "risk_scores.json",
        "target_assessments_json": "target_assessments.json",
    }

    manifest = {
        "artifact_prefix": artifact_prefix,
        "project": a.project,
        "created_at": a.summary.get("audit_summary", {}).get("date"),
        "canonical": {
            "assessment_summary_md": summary_md_name,
        },
        "rendered_routes": {
            "assessment_summary_html": "GET /ui/scans/{scan_id}/assessment-report",
        },
        "files": artifacts,
    }

    (out / "assessment.json").write_text(a.model_dump_json(indent=2), encoding="utf-8")
    (out / summary_md_name).write_text(summary_markdown, encoding="utf-8")

    (out / "findings.md").write_text(markdown(a), encoding="utf-8")
    (out / "knowledge_graph.json").write_text(
        json.dumps({"nodes": [n.model_dump() for n in a.knowledge_nodes], "edges": [e.model_dump() for e in a.knowledge_edges]}, indent=2),
        encoding="utf-8",
    )
    (out / "risk_scores.json").write_text(json.dumps([r.model_dump() for r in a.risk_scores], indent=2), encoding="utf-8")
    (out / "target_assessments.json").write_text(json.dumps(a.target_assessments, indent=2), encoding="utf-8")
    (out / ARTIFACT_MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _crit_map(ta: dict) -> dict[str, dict]:
    return {c.get("id"): c for c in ta.get("criteria", [])}


def _issues_text(ta: dict) -> str:
    issues = ta.get("issues") or []
    if not issues:
        return "—"
    return "; ".join(str(x) for x in issues[:3])


def _method_label(ta: dict) -> str:
    cls = ta.get("class_name")
    method = ta.get("method")
    if cls:
        return f"{cls}.{method}"
    return str(method)


def _rule_sort_key(rule: str) -> int:
    return int(rule[1:]) if rule.startswith("R") and rule[1:].isdigit() else 99


def idempotency_audit_summary_markdown(a: Assessment) -> str:
    audit = a.summary.get("audit_summary") or {}
    total = audit.get("total_functions_audited", len(a.target_assessments))
    p0_fail = audit.get("p0_with_fail", 0)
    p0_partial = audit.get("p0_with_partial", 0)
    date = audit.get("date", "")

    lines: list[str] = [
        "# Idempotency & Retry-Safety Audit — Summary",
        "",
        f"**Project:** {a.project}",
        f"**Date:** {date}",
        f"**Total functions audited:** {total}",
        f"**P0 with FAIL:** {p0_fail}",
        f"**P0 with PARTIAL:** {p0_partial}",
        "",
        "---",
        "",
        "## Result matrix",
        "",
        "| # | Function | Pri | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 | R9 | R10 | Score | Issues |",
        "|---|----------|-----|----|----|----|----|----|----|----|----|----|----|-------|--------|",
    ]
    for idx, ta in enumerate(a.target_assessments, start=1):
        cm = _crit_map(ta)
        cells = []
        for cid in ORDERED_CRITERIA:
            status = cm.get(cid, {}).get("status", "N/A")
            cells.append(STATUS_ICON.get(status, status))
        lines.append(
            f"| {idx} | `{_method_label(ta)}` | {ta.get('priority','')} | "
            + " | ".join(cells)
            + f" | {ta.get('score','—')} | {_issues_text(ta)} |"
        )

    fail_by_rule: dict[str, list[str]] = {}
    partial_by_rule: dict[str, list[str]] = {}
    fix_rows: list[tuple[int, str, str, str]] = []

    def fix_priority(pri: str, status: str) -> int:
        base = {"P0": 0, "P1": 10, "P2": 20}.get(pri, 30)
        return base + (0 if status == "FAIL" else 5)

    for ta in a.target_assessments:
        for c in ta.get("criteria", []):
            status = c.get("status")
            if status not in {"FAIL", "PARTIAL"}:
                continue
            rule = c.get("id") or "R?"
            message = c.get("risk") or c.get("fix") or status
            row = f"- `{_method_label(ta)}`: {message}"
            if status == "FAIL":
                fail_by_rule.setdefault(rule, []).append(row)
            else:
                partial_by_rule.setdefault(rule, []).append(row)
            if c.get("fix"):
                fix_rows.append((fix_priority(ta.get("priority", "P2"), status), _method_label(ta), rule, c.get("fix")))

    lines += ["", "---", "", "## FAIL details", ""]
    if not fail_by_rule:
        lines.append("No FAIL findings.")
    else:
        for rule in sorted(fail_by_rule, key=_rule_sort_key):
            name = next((c.get("name") for ta in a.target_assessments for c in ta.get("criteria", []) if c.get("id") == rule), rule)
            lines += [f"### {rule} — {name}"]
            lines += fail_by_rule[rule]
            lines.append("")

    lines += ["", "---", "", "## PARTIAL details", ""]
    if not partial_by_rule:
        lines.append("No PARTIAL findings.")
    else:
        for rule in sorted(partial_by_rule, key=_rule_sort_key):
            name = next((c.get("name") for ta in a.target_assessments for c in ta.get("criteria", []) if c.get("id") == rule), rule)
            lines += [f"### {rule} — {name}"]
            lines += partial_by_rule[rule]
            lines.append("")

    lines += ["", "---", "", "## Recommended fix priority", "", "| Priority | Function | R# | Action |", "|----------|----------|----|--------|"]
    for idx, (_, fn, rule, action) in enumerate(sorted(fix_rows)[:20], start=1):
        lines.append(f"| {idx} | `{fn}` | {rule} | {action} |")
    if not fix_rows:
        lines.append("| — | — | — | No recommended fixes. |")
    return "\n".join(lines) + "\n"


def _markdown_to_html(md: str) -> str:
    """Render markdown to HTML.

    Prefer Python-Markdown when installed; fallback to a safe <pre> block so the
    report remains viewable without extra runtime dependencies.
    """
    try:
        import markdown as markdown_lib  # type: ignore

        return markdown_lib.markdown(md, extensions=["tables", "fenced_code", "toc"])
    except Exception:
        return f"<pre>{html_lib.escape(md)}</pre>"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", text.strip()).strip("-").lower()
    return s or "project"


def render_assessment_summary_html(
    project: str,
    summary_markdown: str,
    source_name: str = "assessment_summary.md",
    scan_id: int | None = None,
) -> str:
    """Render canonical Markdown assessment summary into HTML at request time."""
    body = _markdown_to_html(summary_markdown)
    safe_project = html_lib.escape(project or "project")
    scan_nav = f'<a href="/ui/scans/{scan_id}">Scan #{scan_id}</a>' if scan_id else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Assessment Summary — {safe_project}</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <header class="topbar">
    <div>
      <a class="brand" href="/ui/dashboard">Zalopay Fund Safety Agent</a>
      <span class="badge">Claw (a) thon</span>
    </div>
    <nav>
      <a href="/ui/dashboard">Dashboard</a>
      {scan_nav}
      <a href="/logout">Logout</a>
    </nav>
  </header>
  <main class="container">
    <div class="hero compact">
      <h1>Assessment Summary</h1>
      <p class="muted">Project: {safe_project}</p>
    </div>
    <div class="panel table-scroll">
      {body}
    </div>
  </main>
</body>
</html>"""


# Compatibility shim for older code paths. New code should call
# render_assessment_summary_html(project, markdown, source_name).
def assessment_summary_html(a: Assessment, summary_markdown: str) -> str:
    return render_assessment_summary_html(a.project, summary_markdown)


def markdown(a: Assessment) -> str:
    lines = [
        f"# Fund Safety Assessment — {a.project}",
        "",
        "Pipeline: `build_index → discovery depth=2 → targets.yml → R1-R10 assessment → scoped findings`",
        "",
        f"Indexed candidate methods: `{len(a.index_entries)}`",
        f"Discovery targets: `{len(a.discovery_targets)}`",
        f"Total findings from R1-R10: `{len(a.findings)}`",
        "",
        "## Audit Summary",
        "",
        f"- Total functions audited: `{a.summary.get('total_functions_audited')}`",
        f"- P0 with FAIL: `{a.summary.get('p0_with_fail')}`",
        f"- P0 with PARTIAL: `{a.summary.get('p0_with_partial')}`",
        "",
        "## Service Risk Scores",
        "",
    ]
    for r in a.risk_scores:
        lines += [f"- **{r.service}**: `{r.score}/100` — {r.finding_count} findings; drivers: {', '.join(r.drivers) or 'none'}"]
    lines += ["", "## Discovery Targets", ""]
    for t in a.discovery_targets[:120]:
        lines += [
            f"- **{t.get('id')}** `{t.get('class_name')}.{t.get('method')}` — {t.get('priority')} / {t.get('group')}",
            f"  - Context: {t.get('context')}",
            f"  - Focus: {', '.join(t.get('focus_criteria') or [])}",
        ]
    lines += ["", "## R1-R10 Target Assessment", ""]
    for ta in a.target_assessments[:80]:
        lines += [
            f"### {ta.get('overall_status')} {ta.get('target_id')}: `{_method_label(ta)}`",
            f"Priority: `{ta.get('priority')}` | Score: `{ta.get('score')}`",
            f"Context: {ta.get('context')}",
            "",
        ]
        for c in ta.get("criteria", []):
            lines += [f"- **{c.get('id')} {c.get('name')}**: `{c.get('status')}`", f"  - Evidence: {c.get('evidence')}"]
            if c.get("risk"):
                lines.append(f"  - Risk: {c.get('risk')}")
            if c.get("fix"):
                lines.append(f"  - Fix: {c.get('fix')}")
        lines.append("")
    lines += ["", "## Findings", ""]
    for f in a.findings:
        lines += [
            f"### {f.severity} {f.rule_id}: {f.title}",
            f"- File: `{f.file_path}:{f.start_line}`",
            f"- Method: `{f.method_name}`",
            f"- Confidence: `{f.confidence}`",
            f"- Evidence level: `{f.evidence_level}`",
            f"- Reasoning: {f.reasoning}",
            "- Evidence:",
            *[f"  - {e}" for e in f.evidence],
            f"- Remediation: {f.remediation}",
            "",
        ]
    return "\n".join(lines)


# Deprecated compatibility shim. Prefer render_assessment_summary_html(...).
def html(a: Assessment) -> str:
    return render_assessment_summary_html(a.project, idempotency_audit_summary_markdown(a))
