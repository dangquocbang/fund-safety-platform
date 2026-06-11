from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, create_engine, Session
from .config import DATABASE_URL

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    full_name: str
    role: str = Field(default='developer', index=True)  # admin, architect, developer, viewer
    password_hash: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    repo_url: str | None = None
    language: str = 'auto'
    fund_critical: bool = True
    owner_user_id: int | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ScanJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int | None = None
    requested_by_user_id: int | None = Field(default=None, index=True)
    status: str = 'PENDING'
    progress_percent: int = 0
    progress_stage: str = ''
    source_path: str | None = None
    report_dir: str | None = None
    summary_json: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

class FindingRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    scan_id: int = Field(index=True)
    rule_id: str
    severity: str = Field(index=True)
    title: str
    file_path: str
    start_line: int
    method_name: str
    confidence: float
    status: str = 'OPEN'  # OPEN, ACCEPTED, FALSE_POSITIVE, RISK_ACCEPTED, FIX_REQUESTED
    reviewer_user_id: int | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)

def init_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as s:
        yield s
