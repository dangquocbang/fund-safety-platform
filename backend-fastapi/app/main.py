from __future__ import annotations
import json, uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Depends, BackgroundTasks, HTTPException, Header, Query, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .auth import current_user, require_min_role, require_role, verify_password, create_access_token, seed_demo_users, hash_password, user_from_token
from .db import init_db, get_session, Project, ScanJob, FindingRecord, User
from .scan_service import extract_zip, run_scan_job
from .delete_service import delete_scan, delete_project, purge_all_data, get_admin_stats
from .chat_service import chat_with_reasoning
from .fund_safety.report import render_assessment_summary_html
from .fund_safety.llm import LLMClient
from .config import DATABASE_URL, SCAN_STORAGE_DIR, SEED_DEMO_USERS, MAX_UPLOAD_SIZE_MB, BACKEND_DIR, APP_NAME, APP_VERSION, LLM_PROVIDER, LLM_ENABLED, DISCOVERY_DEPTH

app = FastAPI(title=APP_NAME, version=APP_VERSION)
templates = Jinja2Templates(directory=str(BACKEND_DIR / "app" / "templates"))
app.mount("/static", StaticFiles(directory=str(BACKEND_DIR / "app" / "static")), name="static")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class LoginRequest(BaseModel):
    email: str
    password: str

class UserCreate(BaseModel):
    email: str
    full_name: str
    role: str
    password: str

class ProjectCreate(BaseModel):
    name: str
    repo_url: Optional[str] = None
    language: str = "auto"
    fund_critical: bool = True

class FindingReview(BaseModel):
    status: str
    note: str | None = None

class ChatRequest(BaseModel):
    scan_id: int
    question: str

class ChatMessage(BaseModel):
    question: str
    conversation_history: list = []

@app.on_event("startup")
def startup():
    init_db()
    if SEED_DEMO_USERS:
        with next(get_session()) as s:
            seed_demo_users(s)

@app.get("/health")
def health():
    return {"status": "ok", "edition": APP_VERSION, "database": DATABASE_URL, "llm_provider": LLM_PROVIDER, "llm_enabled": LLM_ENABLED, "discovery_depth": DISCOVERY_DEPTH}


def public_user(user: User):
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role}


def can_view_project(user: User, project: Project) -> bool:
    return user.role in {"admin", "architect", "viewer"} or project.owner_user_id == user.id


def can_view_scan(user: User, scan: ScanJob, s: Session) -> bool:
    if user.role in {"admin", "architect", "viewer"}:
        return True
    if scan.requested_by_user_id == user.id:
        return True
    if scan.project_id:
        p = s.get(Project, scan.project_id)
        return bool(p and p.owner_user_id == user.id)
    return False

@app.post("/auth/login")
def login(body: LoginRequest, s: Session = Depends(get_session)):
    user = s.exec(select(User).where(User.email == body.email)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid email or password")
    return {"access_token": create_access_token(user), "token_type": "bearer", "user": public_user(user)}

@app.get("/me")
def me(user: User = Depends(current_user)):
    return public_user(user)

@app.get("/users")
def list_users(user: User = Depends(require_role("admin")), s: Session = Depends(get_session)):
    return [public_user(u) for u in s.exec(select(User).order_by(User.created_at.desc())).all()]

@app.post("/users")
def create_user(body: UserCreate, user: User = Depends(require_role("admin")), s: Session = Depends(get_session)):
    if body.role not in {"admin", "architect", "developer", "viewer"}:
        raise HTTPException(400, "invalid role")
    if s.exec(select(User).where(User.email == body.email)).first():
        raise HTTPException(409, "email already exists")
    u = User(email=body.email, full_name=body.full_name, role=body.role, password_hash=hash_password(body.password))
    s.add(u); s.commit(); s.refresh(u)
    return public_user(u)

@app.post("/projects")
def create_project(p: ProjectCreate, user: User = Depends(require_min_role("developer")), s: Session = Depends(get_session)):
    obj = Project(**p.model_dump(), owner_user_id=user.id)
    s.add(obj); s.commit(); s.refresh(obj)
    return obj

@app.get("/projects")
def list_projects(user: User = Depends(current_user), s: Session = Depends(get_session)):
    items = s.exec(select(Project).order_by(Project.created_at.desc())).all()
    if user.role in {"admin", "architect", "viewer"}:
        return items
    return [p for p in items if p.owner_user_id == user.id]

@app.get("/projects/{project_id}")
def project_detail(project_id: int, user: User = Depends(current_user), s: Session = Depends(get_session)):
    p = s.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    if not can_view_project(user, p):
        raise HTTPException(403, "not allowed")
    scans = s.exec(select(ScanJob).where(ScanJob.project_id == project_id).order_by(ScanJob.created_at.desc())).all()
    return {"project": p, "scans": scans}

@app.get("/projects/{project_id}/scans")
def project_scans(project_id: int, user: User = Depends(current_user), s: Session = Depends(get_session)):
    p = s.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    if not can_view_project(user, p):
        raise HTTPException(403, "not allowed")
    return s.exec(select(ScanJob).where(ScanJob.project_id == project_id).order_by(ScanJob.created_at.desc())).all()

@app.get("/projects/{project_id}/risk-trend")
def project_risk_trend(project_id: int, user: User = Depends(current_user), s: Session = Depends(get_session)):
    p = s.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    if not can_view_project(user, p):
        raise HTTPException(403, "not allowed")
    scans = s.exec(select(ScanJob).where(ScanJob.project_id == project_id).order_by(ScanJob.created_at.asc())).all()
    trend = []
    for scan in scans:
        if scan.status != "COMPLETED" or not scan.report_dir:
            continue
        score = None
        try:
            path = Path(scan.report_dir) / "risk_scores.json"
            if path.exists():
                risks = json.loads(path.read_text())
                if risks:
                    score = max(int(r.get("score", 0)) for r in risks)
        except Exception:
            score = None
        summary = {}
        if scan.summary_json:
            try:
                summary = json.loads(scan.summary_json)
            except Exception:
                summary = {}
        trend.append({
            "scan_id": scan.id,
            "created_at": scan.created_at.isoformat(),
            "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
            "max_risk_score": score,
            "finding_count": summary.get("finding_count"),
            "critical_count": summary.get("by_severity", {}).get("CRITICAL") if isinstance(summary.get("by_severity"), dict) else None,
        })
    return trend

@app.post("/projects/{project_id}/scans/upload")
async def upload_project_scan(project_id: int, background: BackgroundTasks, file: UploadFile = File(...), user: User = Depends(require_min_role("developer")), s: Session = Depends(get_session)):
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(400, "only .zip source upload is supported")
    p = s.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    if user.role == "developer" and p.owner_user_id != user.id:
        raise HTTPException(403, "developer can only scan own project")
    base = SCAN_STORAGE_DIR / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    zip_path = base / file.filename
    zip_path.write_bytes(await file.read())
    source = base / "source"
    extract_zip(zip_path, source)
    job = ScanJob(project_id=project_id, requested_by_user_id=user.id, source_path=str(source), status="PENDING")
    s.add(job); s.commit(); s.refresh(job)
    background.add_task(run_scan_job, job.id)
    return {"job_id": job.id, "project_id": project_id, "status": job.status}

@app.post("/scans/upload")
async def legacy_upload_scan(background: BackgroundTasks, project_id: int | None = None, file: UploadFile = File(...), user: User = Depends(require_min_role("developer")), s: Session = Depends(get_session)):
    if not project_id:
        raise HTTPException(400, "project_id is required in real-source edition. Create a project first, then upload source ZIP to that project.")
    return await upload_project_scan(project_id, background, file, user, s)

@app.get("/scans")
def scans(user: User = Depends(current_user), s: Session = Depends(get_session)):
    items = s.exec(select(ScanJob).order_by(ScanJob.created_at.desc()).limit(100)).all()
    if user.role in {"admin", "architect", "viewer"}:
        return items
    return [j for j in items if can_view_scan(user, j, s)]

@app.get("/scans/{scan_id}")
def scan(scan_id: int, user: User = Depends(current_user), s: Session = Depends(get_session)):
    job = s.get(ScanJob, scan_id)
    if not job:
        raise HTTPException(404, "not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")
    findings = s.exec(select(FindingRecord).where(FindingRecord.scan_id == scan_id)).all()
    return {"job": job, "findings": findings}

@app.get("/api/scans/{scan_id}/status")
def scan_status(scan_id: int, user: User = Depends(current_user), s: Session = Depends(get_session)):
    job = s.get(ScanJob, scan_id)
    if not job:
        raise HTTPException(404, "not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")
    return {
        "scan_id": job.id,
        "status": job.status,
        "progress_percent": job.progress_percent,
        "progress_stage": job.progress_stage,
        "error_message": job.error,
    }

@app.get("/ui/scans/{scan_id}/status")
def ui_scan_status(scan_id: int, request: Request, s: Session = Depends(get_session)):
    user = _ui_user(request, s)
    if not user:
        raise HTTPException(401, "unauthorized")
    job = s.get(ScanJob, scan_id)
    if not job:
        raise HTTPException(404, "not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")
    return {
        "scan_id": job.id,
        "status": job.status,
        "progress_percent": job.progress_percent,
        "progress_stage": job.progress_stage,
        "error_message": job.error,
    }

@app.post("/findings/{finding_id}/review")
def review_finding(finding_id: int, body: FindingReview, user: User = Depends(require_min_role("architect")), s: Session = Depends(get_session)):
    allowed = {"OPEN", "ACCEPTED", "FALSE_POSITIVE", "RISK_ACCEPTED", "FIX_REQUESTED"}
    if body.status not in allowed:
        raise HTTPException(400, f"invalid status, allowed={sorted(allowed)}")
    finding = s.get(FindingRecord, finding_id)
    if not finding:
        raise HTTPException(404, "finding not found")
    finding.status = body.status
    finding.review_note = body.note
    finding.reviewer_user_id = user.id
    finding.reviewed_at = datetime.utcnow()
    s.add(finding); s.commit(); s.refresh(finding)
    return finding

@app.delete("/api/scans/{scan_id}")
def api_delete_scan(scan_id: int, user: User = Depends(require_role("admin")), s: Session = Depends(get_session)):
    result = delete_scan(scan_id, s)
    if not result.get("deleted"):
        raise HTTPException(404, result.get("error", "failed to delete scan"))
    return result

@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: int, user: User = Depends(require_role("admin")), s: Session = Depends(get_session)):
    result = delete_project(project_id, s)
    if not result.get("deleted"):
        raise HTTPException(404, result.get("error", "failed to delete project"))
    return result

@app.delete("/api/admin/purge-all")
def api_purge_all(user: User = Depends(require_role("admin")), s: Session = Depends(get_session)):
    result = purge_all_data(s)
    if not result.get("deleted"):
        raise HTTPException(500, result.get("error", "failed to purge data"))
    return result

@app.get("/api/admin/stats")
def api_admin_stats(user: User = Depends(require_role("admin")), s: Session = Depends(get_session)):
    return get_admin_stats(s)

@app.get("/dashboard/risk")
def risk_dashboard(user: User = Depends(current_user), s: Session = Depends(get_session)):
    visible_projects = list_projects(user, s)
    project_ids = {p.id for p in visible_projects}
    all_scans = s.exec(select(ScanJob).order_by(ScanJob.created_at.desc()).limit(200)).all()
    visible_scans = [scan for scan in all_scans if user.role in {"admin", "architect", "viewer"} or scan.project_id in project_ids or scan.requested_by_user_id == user.id]
    scan_ids = {scan.id for scan in visible_scans}
    all_findings = s.exec(select(FindingRecord)).all()
    findings = [f for f in all_findings if f.scan_id in scan_ids]
    by_sev = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    open_count = sum(1 for f in findings if f.status == "OPEN")
    return {"project_count": len(visible_projects), "scan_count": len(visible_scans), "finding_count": len(findings), "open_count": open_count, "by_severity": by_sev}

@app.get("/scans/{scan_id}/report/{name}")
def report(scan_id: int, name: str, token: str | None = Query(default=None), authorization: str | None = Header(default=None), s: Session = Depends(get_session)):
    raw_token = token or (authorization.replace("Bearer ", "") if authorization and authorization.startswith("Bearer ") else None)
    if not raw_token:
        raise HTTPException(401, "missing token")
    user = user_from_token(raw_token, s)
    job = s.get(ScanJob, scan_id)
    if not job or not job.report_dir:
        raise HTTPException(404, "not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")
    base = Path(job.report_dir)
    if Path(name).name != name:
        raise HTTPException(400, "invalid report")
    manifest = _load_json_file(base / "artifact_manifest.json", {})
    allowed = {"assessment.json", "findings.md", "knowledge_graph.json", "risk_scores.json", "target_assessments.json", "targets.yml", "index.txt", "artifact_manifest.json"}
    if isinstance(manifest, dict):
        for section in ("files", "canonical", "aliases"):
            values = manifest.get(section, {})
            if isinstance(values, dict):
                allowed.update(str(v) for v in values.values() if v)
    if name not in allowed:
        raise HTTPException(400, "invalid report")
    path = base / name
    if not path.exists():
        raise HTTPException(404, "report not found")
    return FileResponse(path)

@app.get("/scans/{scan_id}/knowledge-graph")
def knowledge_graph(scan_id: int, user: User = Depends(current_user), s: Session = Depends(get_session)):
    job = s.get(ScanJob, scan_id)
    if not job or not job.report_dir:
        raise HTTPException(404, "scan report not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")
    path = Path(job.report_dir) / "knowledge_graph.json"
    if not path.exists():
        raise HTTPException(404, "knowledge graph not generated")
    return json.loads(path.read_text())

@app.get("/scans/{scan_id}/risk-scores")
def scan_risk_scores(scan_id: int, user: User = Depends(current_user), s: Session = Depends(get_session)):
    job = s.get(ScanJob, scan_id)
    if not job or not job.report_dir:
        raise HTTPException(404, "scan report not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")
    path = Path(job.report_dir) / "risk_scores.json"
    if not path.exists():
        raise HTTPException(404, "risk scores not generated")
    return json.loads(path.read_text())

@app.post("/chat")
def chat(body: ChatRequest, user: User = Depends(current_user), s: Session = Depends(get_session)):
    job = s.get(ScanJob, body.scan_id)
    if not job or not job.report_dir:
        raise HTTPException(404, "scan report not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")
    assessment_path = Path(job.report_dir) / "assessment.json"
    if not assessment_path.exists():
        raise HTTPException(404, "assessment not found")

    assessment = json.loads(assessment_path.read_text())

    # Get LLM client for chat reasoning (uses dedicated chat config)
    llm_client = LLMClient.for_stage("chat") if LLM_ENABLED else None

    # Use enhanced chat with function-level reasoning
    result = chat_with_reasoning(assessment, body.question, llm_client)

    # Extract supporting findings
    findings = assessment.get("findings", [])
    def top_findings(n=5):
        order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        return sorted(findings, key=lambda f: (order.get(f.get("severity"), 0), f.get("confidence", 0)), reverse=True)[:n]

    graph = {"nodes": assessment.get("knowledge_nodes", []), "edges": assessment.get("knowledge_edges", [])}

    return {
        "answer": result["answer"],
        "query_type": result["query_type"],
        "function_name": result.get("function_name"),
        "rule_id": result.get("rule_id"),
        "supporting_findings": top_findings(5),
        "graph_summary": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"])},
    }

# ---------------------------
# Python-only GUI routes
# ---------------------------

def _token_from_cookie(request: Request) -> str | None:
    return request.cookies.get("fundsafe_token")


def _ui_user(request: Request, s: Session) -> User | None:
    token = _token_from_cookie(request)
    if not token:
        return None
    try:
        return user_from_token(token, s)
    except Exception:
        return None


def _require_ui_user(request: Request, s: Session) -> User:
    user = _ui_user(request, s)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _load_json_file(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        return default
    return default


def _scan_artifacts(job: ScanJob) -> dict:
    if not job.report_dir:
        return {}
    base = Path(job.report_dir)
    manifest = _load_json_file(base / "artifact_manifest.json", {})
    canonical = manifest.get("canonical", {}) if isinstance(manifest, dict) else {}
    files = manifest.get("files", {}) if isinstance(manifest, dict) else {}

    summary_md_name = canonical.get("assessment_summary_md") or files.get("assessment_summary_md") or "assessment_summary.md"

    return {
        "manifest": manifest,
        "assessment": _load_json_file(base / "assessment.json", {}),
        "risk_scores": _load_json_file(base / "risk_scores.json", []),
        "knowledge_graph": _load_json_file(base / "knowledge_graph.json", {"nodes": [], "edges": []}),
        "target_assessments": _load_json_file(base / "target_assessments.json", []),
        "summary_md_name": summary_md_name,
        "summary_md_path": base / summary_md_name,
        "assessment_report_route": f"/ui/scans/{job.id}/assessment-report",
        "targets_path": base / "targets.yml",
        "index_path": base / "index.txt",
    }


@app.get("/", response_class=HTMLResponse)
def ui_home(request: Request, s: Session = Depends(get_session)):
    user = _ui_user(request, s)
    if not user:
        return _redirect("/login")
    return _redirect("/ui/dashboard")


@app.get("/login", response_class=HTMLResponse)
def ui_login_page(request: Request, s: Session = Depends(get_session)):
    if _ui_user(request, s):
        return _redirect("/ui/dashboard")
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": None})


@app.post("/login")
def ui_login(request: Request, email: str = Form(...), password: str = Form(...), s: Session = Depends(get_session)):
    user = s.exec(select(User).where(User.email == email)).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request, "login.html", {"request": request, "error": "Invalid email or password"}, status_code=401)
    response = _redirect("/ui/dashboard")
    response.set_cookie("fundsafe_token", create_access_token(user), httponly=True, samesite="lax", max_age=60 * 60 * 8)
    return response


@app.get("/logout")
def ui_logout():
    response = _redirect("/login")
    response.delete_cookie("fundsafe_token")
    return response


@app.get("/ui/dashboard", response_class=HTMLResponse)
def ui_dashboard(request: Request, s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    visible_projects = list_projects(user, s)
    dashboard = risk_dashboard(user, s)
    scans_all = s.exec(select(ScanJob).order_by(ScanJob.created_at.desc()).limit(20)).all()
    scans_visible = [j for j in scans_all if can_view_scan(user, j, s)]
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request,
        "user": user,
        "projects": visible_projects,
        "dashboard": dashboard,
        "scans": scans_visible,
    })


@app.post("/ui/projects")
def ui_create_project(
    request: Request,
    name: str = Form(...),
    language: str = Form("auto"),
    repo_url: str = Form(""),
    fund_critical: str | None = Form(None),
    s: Session = Depends(get_session),
):
    user = _require_ui_user(request, s)
    if user.role not in {"admin", "architect", "developer"}:
        raise HTTPException(403, "not allowed")
    obj = Project(name=name.strip(), language=language, repo_url=repo_url or None, fund_critical=bool(fund_critical), owner_user_id=user.id)
    s.add(obj); s.commit(); s.refresh(obj)
    return _redirect(f"/ui/projects/{obj.id}")


@app.get("/ui/projects/{project_id}", response_class=HTMLResponse)
def ui_project_detail(project_id: int, request: Request, s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    p = s.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    if not can_view_project(user, p):
        raise HTTPException(403, "not allowed")
    scans = s.exec(select(ScanJob).where(ScanJob.project_id == project_id).order_by(ScanJob.created_at.desc())).all()
    return templates.TemplateResponse(request, "project_detail.html", {
        "request": request,
        "user": user,
        "project": p,
        "scans": scans,
    })


@app.post("/ui/projects/{project_id}/scan")
async def ui_upload_scan(project_id: int, request: Request, background: BackgroundTasks, file: UploadFile = File(...), s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    if user.role not in {"admin", "architect", "developer"}:
        raise HTTPException(403, "not allowed")
    # Reuse API implementation to keep upload behavior consistent.
    result = await upload_project_scan(project_id, background, file, user, s)
    return _redirect(f"/ui/scans/{result['job_id']}")


@app.get("/ui/scans/{scan_id}", response_class=HTMLResponse)
def ui_scan_detail(scan_id: int, request: Request, s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    job = s.get(ScanJob, scan_id)
    if not job:
        raise HTTPException(404, "scan not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")
    project = s.get(Project, job.project_id) if job.project_id else None
    findings = s.exec(select(FindingRecord).where(FindingRecord.scan_id == scan_id)).all()
    artifacts = _scan_artifacts(job)
    assessment = artifacts.get("assessment") or {}
    matrix = assessment.get("assessment_matrix") or assessment.get("matrix") or []
    summary = assessment.get("assessment_summary") or assessment.get("summary") or {}
    fail_details = assessment.get("fail_details") or []
    partial_details = assessment.get("partial_details") or []
    fix_priority = assessment.get("recommended_fixes") or assessment.get("fix_priority") or []
    graph = artifacts.get("knowledge_graph") or {"nodes": [], "edges": []}
    return templates.TemplateResponse(request, "scan_detail.html", {
        "request": request,
        "user": user,
        "job": job,
        "project": project,
        "findings": findings,
        "summary": summary,
        "matrix": matrix,
        "fail_details": fail_details,
        "partial_details": partial_details,
        "fix_priority": fix_priority,
        "risk_scores": artifacts.get("risk_scores", []),
        "graph": graph,
        "artifacts": artifacts,
    })


@app.post("/ui/findings/{finding_id}/review")
def ui_review_finding(finding_id: int, request: Request, status: str = Form(...), note: str = Form(""), s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    if user.role not in {"admin", "architect"}:
        raise HTTPException(403, "architect role required")
    finding = s.get(FindingRecord, finding_id)
    if not finding:
        raise HTTPException(404, "finding not found")
    review_finding(finding_id, FindingReview(status=status, note=note or None), user, s)
    return _redirect(f"/ui/scans/{finding.scan_id}")


@app.post("/ui/chat", response_class=HTMLResponse)
def ui_chat(request: Request, scan_id: int = Form(...), question: str = Form(...), s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    response = chat(ChatRequest(scan_id=scan_id, question=question), user, s)
    return templates.TemplateResponse(request, "chat_answer.html", {"request": request, "answer": response["answer"], "supporting_findings": response.get("supporting_findings", [])})

@app.get("/ui/scans/{scan_id}/chat", response_class=HTMLResponse)
def ui_chat_page(scan_id: int, request: Request, s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    job = s.get(ScanJob, scan_id)
    if not job or not job.report_dir:
        raise HTTPException(404, "scan not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")

    assessment_path = Path(job.report_dir) / "assessment.json"
    if not assessment_path.exists():
        raise HTTPException(404, "assessment not found")

    assessment = json.loads(assessment_path.read_text())
    project = s.get(Project, job.project_id) if job.project_id else None
    project_name = project.name if project else "Unknown Project"

    # Get example methods for quick start (pick first 5)
    example_methods = assessment.get("methods", [])[:5]

    return templates.TemplateResponse(
        request,
        "chat_page.html",
        {
            "request": request,
            "scan_id": scan_id,
            "project_name": project_name,
            "assessment": assessment,
            "example_methods": example_methods,
        },
    )

@app.post("/api/chats/{scan_id}/messages")
def api_chat_message(
    scan_id: int,
    body: ChatMessage,
    user: User = Depends(current_user),
    s: Session = Depends(get_session),
):
    job = s.get(ScanJob, scan_id)
    if not job or not job.report_dir:
        raise HTTPException(404, "scan not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")

    assessment_path = Path(job.report_dir) / "assessment.json"
    if not assessment_path.exists():
        raise HTTPException(404, "assessment not found")

    assessment = json.loads(assessment_path.read_text())

    # Get LLM client for function reasoning
    llm_client = LLMClient.for_stage("assessment") if LLM_ENABLED else None

    # Use enhanced chat with function-level reasoning
    result = chat_with_reasoning(assessment, body.question, llm_client)

    return {
        "answer": result["answer"],
        "content": result["answer"],
        "query_type": result["query_type"],
        "function_name": result.get("function_name"),
        "rule_id": result.get("rule_id"),
        "confidence": result.get("confidence", 0),
        "requires_clarification": result.get("requires_clarification", False),
        "candidates": result.get("candidates", []),
    }

@app.post("/ui/api/chats/{scan_id}/messages")
def ui_api_chat_message(
    scan_id: int,
    body: ChatMessage,
    request: Request,
    s: Session = Depends(get_session),
):
    # Cookie-based authentication for web UI
    user = _require_ui_user(request, s)

    # Load and validate scan
    job = s.get(ScanJob, scan_id)
    if not job or not job.report_dir:
        raise HTTPException(404, "scan not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")

    # Load assessment
    assessment_path = Path(job.report_dir) / "assessment.json"
    if not assessment_path.exists():
        raise HTTPException(404, "assessment not found")

    assessment = json.loads(assessment_path.read_text())

    # Get LLM client for chat reasoning (uses dedicated chat config)
    llm_client = LLMClient.for_stage("chat") if LLM_ENABLED else None

    # Use enhanced chat with function-level reasoning
    result = chat_with_reasoning(assessment, body.question, llm_client)

    return {
        "answer": result["answer"],
        "content": result["answer"],
        "query_type": result["query_type"],
        "function_name": result.get("function_name"),
        "rule_id": result.get("rule_id"),
        "confidence": result.get("confidence", 0),
        "requires_clarification": result.get("requires_clarification", False),
        "candidates": result.get("candidates", []),
    }

@app.get("/ui/scans/{scan_id}/assessment-report", response_class=HTMLResponse)
def ui_assessment_report(scan_id: int, request: Request, s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    job = s.get(ScanJob, scan_id)
    if not job or not job.report_dir:
        raise HTTPException(404, "not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")
    project = s.get(Project, job.project_id) if job.project_id else None
    artifacts = _scan_artifacts(job)
    summary_md_name = artifacts.get("summary_md_name") or "assessment_summary.md"
    summary_md_path = Path(job.report_dir) / summary_md_name
    if not summary_md_path.exists():
        raise HTTPException(404, "assessment summary markdown not found")
    markdown_text = summary_md_path.read_text(encoding="utf-8")
    project_name = project.name if project else f"scan-{scan_id}"
    return HTMLResponse(render_assessment_summary_html(project_name, markdown_text, summary_md_name, scan_id=scan_id))


@app.get("/ui/scans/{scan_id}/download/{name}")
def ui_download_report(scan_id: int, name: str, request: Request, s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    job = s.get(ScanJob, scan_id)
    if not job or not job.report_dir:
        raise HTTPException(404, "not found")
    if not can_view_scan(user, job, s):
        raise HTTPException(403, "not allowed")
    base = Path(job.report_dir)
    if Path(name).name != name:
        raise HTTPException(400, "invalid report")
    manifest = _load_json_file(base / "artifact_manifest.json", {})
    allowed = {"assessment.json", "findings.md", "knowledge_graph.json", "risk_scores.json", "target_assessments.json", "targets.yml", "index.txt", "artifact_manifest.json"}
    if isinstance(manifest, dict):
        for section in ("files", "canonical", "aliases"):
            values = manifest.get(section, {})
            if isinstance(values, dict):
                allowed.update(str(v) for v in values.values() if v)
    if name not in allowed:
        raise HTTPException(400, "invalid report")
    path = base / name
    if not path.exists():
        raise HTTPException(404, "report not found")
    return FileResponse(path)

@app.get("/ui/admin/dashboard", response_class=HTMLResponse)
def ui_admin_dashboard(request: Request, s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    if user.role != "admin":
        raise HTTPException(403, "admin only")
    stats = get_admin_stats(s)
    projects = s.exec(select(Project).order_by(Project.created_at.desc())).all()
    scans = s.exec(select(ScanJob).order_by(ScanJob.created_at.desc()).limit(50)).all()
    return templates.TemplateResponse(request, "admin_dashboard.html", {
        "request": request,
        "user": user,
        "stats": stats,
        "projects": projects,
        "scans": scans,
    })

@app.post("/ui/admin/delete-project/{project_id}")
def ui_delete_project(project_id: int, request: Request, s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    if user.role != "admin":
        raise HTTPException(403, "admin only")
    result = delete_project(project_id, s)
    return _redirect("/ui/admin/dashboard")

@app.post("/ui/admin/delete-scan/{scan_id}")
def ui_delete_scan(scan_id: int, request: Request, s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    if user.role != "admin":
        raise HTTPException(403, "admin only")
    result = delete_scan(scan_id, s)
    return _redirect("/ui/admin/dashboard")

@app.post("/ui/admin/purge-all")
def ui_purge_all(request: Request, s: Session = Depends(get_session)):
    user = _require_ui_user(request, s)
    if user.role != "admin":
        raise HTTPException(403, "admin only")
    result = purge_all_data(s)
    return _redirect("/ui/admin/dashboard")
