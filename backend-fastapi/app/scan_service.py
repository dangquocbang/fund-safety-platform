from __future__ import annotations
import json, re, shutil, zipfile
from datetime import datetime
from pathlib import Path
from sqlmodel import Session
from .db import ScanJob, FindingRecord, Project
from .config import SCAN_STORAGE_DIR, LLM_ENABLED, DISCOVERY_DEPTH
from .fund_safety.runner import run_fund_safety_scan



def _slug(value: str | None, fallback: str = "project") -> str:
    value = (value or fallback).strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-._")
    return value or fallback


def _scan_timestamp(job: ScanJob) -> str:
    # created_at is stable for the scan; use it so artifact names are deterministic after retries.
    dt = job.created_at or datetime.utcnow()
    return dt.strftime("%Y%m%dT%H%M%SZ")

def extract_zip(file_path: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(file_path) as z:
        z.extractall(dest)

def _update_progress(s: Session, job: ScanJob, percent: int, stage: str):
    job.progress_percent = percent
    job.progress_stage = stage
    s.add(job)
    s.commit()

def run_scan_job(job_id: int):
    from .db import engine
    with Session(engine) as s:
        job=s.get(ScanJob, job_id)
        if not job: return
        job.status='RUNNING'
        job.started_at=datetime.utcnow()
        _update_progress(s, job, 5, 'Upload received')
        try:
            source=Path(job.source_path)
            project_name = f'job-{job_id}'
            if job.project_id:
                project = s.get(Project, job.project_id)
                if project and project.name:
                    project_name = project.name

            user_id = job.requested_by_user_id or 0
            project_slug = _slug(project_name, f"project-{job.project_id or 0}")
            scan_ts = _scan_timestamp(job)
            artifact_prefix = f"{project_slug}_user-{user_id}_scan-{job_id}_{scan_ts}"

            _update_progress(s, job, 10, 'Extract ZIP')

            # Each scan gets an immutable report directory. Dynamic artifact filenames inside
            # this directory also carry user/project/scan metadata.
            out=SCAN_STORAGE_DIR / "reports" / f"user-{user_id}" / project_slug / f"scan-{job_id}-{scan_ts}"
            out.mkdir(parents=True, exist_ok=True)

            _update_progress(s, job, 25, 'Build index')
            _update_progress(s, job, 45, 'Discovery provider running')
            _update_progress(s, job, 55, 'targets.yml generated')
            _update_progress(s, job, 75, 'Assessment provider running')

            assessment_obj = run_fund_safety_scan(
                source=source,
                out=out,
                project=project_name,
                llm=LLM_ENABLED,
                depth=DISCOVERY_DEPTH,
                artifact_prefix=artifact_prefix,
            )
            assessment = assessment_obj.model_dump(mode='json')
            for f in assessment.get('findings',[]):
                s.add(FindingRecord(scan_id=job_id,rule_id=f['rule_id'],severity=f['severity'],title=f['title'],file_path=f['file_path'],start_line=f['start_line'],method_name=f['method_name'],confidence=f['confidence']))

            _update_progress(s, job, 85, 'assessment.json generated')
            _update_progress(s, job, 95, 'assessment_summary.md generated')

            job.summary_json=json.dumps(assessment.get('summary',{}))
            job.report_dir=str(out)
            job.status='COMPLETED'
            job.finished_at=datetime.utcnow()
            _update_progress(s, job, 100, 'Completed')
        except Exception as e:
            job.status='FAILED'; job.error=str(e); job.finished_at=datetime.utcnow(); s.add(job); s.commit()
