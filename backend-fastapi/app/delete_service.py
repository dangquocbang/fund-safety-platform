from __future__ import annotations
import shutil
from pathlib import Path
from sqlmodel import Session, select
from .db import Project, ScanJob, FindingRecord
from .config import SCAN_STORAGE_DIR, UPLOAD_DIR


def delete_scan_artifacts(scan: ScanJob) -> int:
    """Delete scan artifacts from disk (report + upload). Returns bytes deleted."""
    total_size = 0

    # Delete report directory
    if scan.report_dir:
        try:
            report_path = Path(scan.report_dir)
            if report_path.exists() and report_path.is_dir():
                size = sum(f.stat().st_size for f in report_path.rglob('*') if f.is_file())
                shutil.rmtree(report_path)
                total_size += size
        except Exception:
            pass

    # Delete upload directory (source_path = uploads/UUID/source)
    if scan.source_path:
        try:
            source_path = Path(scan.source_path)
            # Navigate up to uploads/UUID from uploads/UUID/source
            upload_dir = source_path.parent if source_path.name == 'source' else source_path
            if upload_dir.exists() and upload_dir.is_dir():
                size = sum(f.stat().st_size for f in upload_dir.rglob('*') if f.is_file())
                shutil.rmtree(upload_dir)
                total_size += size
        except Exception:
            pass

    return total_size


def delete_scan(scan_id: int, s: Session) -> dict:
    """Delete a scan and all related data. Returns deletion summary."""
    scan = s.get(ScanJob, scan_id)
    if not scan:
        return {"deleted": False, "error": "scan not found"}

    try:
        size_deleted = delete_scan_artifacts(scan)
        finding_count = s.exec(select(FindingRecord).where(FindingRecord.scan_id == scan_id)).all()
        for f in finding_count:
            s.delete(f)
        s.delete(scan)
        s.commit()
        return {
            "deleted": True,
            "scan_id": scan_id,
            "findings_deleted": len(finding_count),
            "bytes_freed": size_deleted,
        }
    except Exception as e:
        s.rollback()
        return {"deleted": False, "error": str(e)}


def delete_project(project_id: int, s: Session) -> dict:
    """Delete a project and all related scans/findings. Returns deletion summary."""
    project = s.get(Project, project_id)
    if not project:
        return {"deleted": False, "error": "project not found"}

    try:
        scans = s.exec(select(ScanJob).where(ScanJob.project_id == project_id)).all()
        total_size = 0
        total_findings = 0

        for scan in scans:
            total_size += delete_scan_artifacts(scan)
            findings = s.exec(select(FindingRecord).where(FindingRecord.scan_id == scan.id)).all()
            total_findings += len(findings)
            for f in findings:
                s.delete(f)
            s.delete(scan)

        s.delete(project)
        s.commit()
        return {
            "deleted": True,
            "project_id": project_id,
            "scans_deleted": len(scans),
            "findings_deleted": total_findings,
            "bytes_freed": total_size,
        }
    except Exception as e:
        s.rollback()
        return {"deleted": False, "error": str(e)}


def purge_all_data(s: Session) -> dict:
    """Delete all projects and scans (nuclear option). Keeps users."""
    try:
        projects = s.exec(select(Project)).all()
        total_scans = 0
        total_findings = 0
        total_size = 0

        for project in projects:
            scans = s.exec(select(ScanJob).where(ScanJob.project_id == project.id)).all()
            total_scans += len(scans)

            for scan in scans:
                total_size += delete_scan_artifacts(scan)
                findings = s.exec(select(FindingRecord).where(FindingRecord.scan_id == scan.id)).all()
                total_findings += len(findings)
                for f in findings:
                    s.delete(f)
                s.delete(scan)

            s.delete(project)

        s.commit()

        # Remove the entire reports tree so no empty subdirectories remain.
        reports_root = SCAN_STORAGE_DIR / "reports"
        if not reports_root.exists():
            # Also check UPLOAD_DIR in case SCAN_STORAGE_DIR differs
            reports_root = UPLOAD_DIR / "reports"
        if reports_root.exists() and reports_root.is_dir():
            try:
                size = sum(f.stat().st_size for f in reports_root.rglob('*') if f.is_file())
                shutil.rmtree(reports_root)
                total_size += size
            except Exception:
                pass

        return {
            "deleted": True,
            "projects_deleted": len(projects),
            "scans_deleted": total_scans,
            "findings_deleted": total_findings,
            "bytes_freed": total_size,
        }
    except Exception as e:
        s.rollback()
        return {"deleted": False, "error": str(e)}


def get_admin_stats(s: Session) -> dict:
    """Get statistics for admin dashboard."""
    projects = s.exec(select(Project)).all()
    scans = s.exec(select(ScanJob)).all()
    findings = s.exec(select(FindingRecord)).all()

    total_size = 0
    for scan in scans:
        if scan.report_dir:
            try:
                path = Path(scan.report_dir)
                if path.exists():
                    total_size += sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
            except Exception:
                pass

    return {
        "project_count": len(projects),
        "scan_count": len(scans),
        "finding_count": len(findings),
        "storage_bytes": total_size,
        "storage_mb": round(total_size / (1024 * 1024), 2),
    }