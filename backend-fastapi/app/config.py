from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Config-driven, SQLite-first configuration for Phase 1.
# No pydantic-settings. YAML files are the source of truth; environment
# variables may override secrets/runtime values when needed.
BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BACKEND_DIR / "config"


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without overriding existing vars.

    Values already present in the real environment win; the .env file only
    fills in keys that are not yet set. Must run before any os.getenv() call
    below so secrets like api_key_env entries resolve correctly.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


# Repo-root .env is loaded as a fallback for environment variables.
_load_dotenv(BACKEND_DIR.parent / ".env")


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Config file {path} must contain a YAML object")
    return data


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else BACKEND_DIR / p


APP_CONFIG = _load_yaml("app.yaml")
LLM_CONFIG = _load_yaml("llm.yaml")
DISCOVERY_CONFIG = _load_yaml("discovery.yaml")
ASSESSMENT_CONFIG = _load_yaml("assessment.yaml")
GRAPH_CONFIG = _load_yaml("graph.yaml")
JAVA_CONFIG = _load_yaml("java.yaml")
GOLANG_CONFIG = _load_yaml("golang.yaml")

app_section = APP_CONFIG.get("app", {})
storage_section = APP_CONFIG.get("storage", {})
security_section = APP_CONFIG.get("security", {})

def _cfg(section: dict[str, Any], key: str, default: Any = None) -> Any:
    return section.get(key, default)

APP_NAME = str(_cfg(app_section, "name", "Fund Safety Platform"))
APP_VERSION = str(_cfg(app_section, "version", "1.0.0-phase1"))

DATA_DIR = _path(_cfg(storage_section, "data_dir", "data"))
UPLOAD_DIR = _path(_cfg(storage_section, "upload_dir", "uploads"))
REPORT_DIR = _path(_cfg(storage_section, "report_dir", "uploads"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

_database_url_cfg = str(_cfg(storage_section, "database_url", f"sqlite:///{DATA_DIR / 'fund_safety.db'}"))
if _database_url_cfg.startswith("sqlite:///"):
    sqlite_path = _database_url_cfg.removeprefix("sqlite:///")
    if sqlite_path and not Path(sqlite_path).is_absolute():
        _database_url_cfg = f"sqlite:///{_path(sqlite_path)}"
DATABASE_URL = os.getenv("DATABASE_URL", _database_url_cfg)
SCAN_STORAGE_DIR = _path(os.getenv("SCAN_STORAGE_DIR", str(_cfg(storage_section, "scan_storage_dir", UPLOAD_DIR))))
SCAN_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

JWT_SECRET = os.getenv("JWT_SECRET", str(_cfg(security_section, "jwt_secret", "fund-safety-phase1-demo-secret-change-me-32bytes")))
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", str(_cfg(security_section, "jwt_algorithm", "HS256")))
JWT_EXP_MINUTES = int(os.getenv("JWT_EXP_MINUTES", str(_cfg(security_section, "jwt_exp_minutes", 480))))
SEED_DEMO_USERS = _bool(os.getenv("SEED_DEMO_USERS", _cfg(security_section, "seed_demo_users", True)), True)
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", str(_cfg(storage_section, "max_upload_size_mb", 500))))

# LLM config is loaded from config/llm.yaml. Environment variables override YAML
# for keys/secrets and quick local experimentation.
LLM_ENABLED = _bool(os.getenv("LLM_ENABLED", LLM_CONFIG.get("enabled", False)), False)


def _llm_stage_config(stage: str) -> dict[str, Any]:
    data = LLM_CONFIG.get(stage, {}) or {}
    if not isinstance(data, dict):
        return {}
    return data


DISCOVERY_LLM_CONFIG = _llm_stage_config("discovery")
ASSESSMENT_LLM_CONFIG = _llm_stage_config("assessment")
CHAT_LLM_CONFIG = _llm_stage_config("chat")
LLM_PROVIDERS_CONFIG = LLM_CONFIG.get("providers", {}) or {}
if not isinstance(LLM_PROVIDERS_CONFIG, dict):
    LLM_PROVIDERS_CONFIG = {}

# Backward compatible top-level values. New code should use stage-specific configs.
LLM_PROVIDER = str(os.getenv("LLM_PROVIDER", LLM_CONFIG.get("provider", "mock"))).strip().lower()
LLM_MODEL = str(os.getenv("LLM_MODEL", LLM_CONFIG.get("model", "claude-sonnet-4-5")))

DISCOVERY_PROVIDER = str(os.getenv("DISCOVERY_PROVIDER", DISCOVERY_LLM_CONFIG.get("provider", LLM_PROVIDER))).strip().lower()
DISCOVERY_MODEL = str(os.getenv("DISCOVERY_MODEL", DISCOVERY_LLM_CONFIG.get("model", LLM_MODEL)))
DISCOVERY_DEPTH = int(os.getenv("DISCOVERY_DEPTH", str(DISCOVERY_LLM_CONFIG.get("depth", DISCOVERY_CONFIG.get("depth", 2)))))
DISCOVERY_MAX_TARGETS = int(os.getenv("DISCOVERY_MAX_TARGETS", str(DISCOVERY_LLM_CONFIG.get("max_targets", DISCOVERY_CONFIG.get("max_targets", 80)))))

ASSESSMENT_PROVIDER = str(os.getenv("ASSESSMENT_PROVIDER", ASSESSMENT_LLM_CONFIG.get("provider", LLM_PROVIDER))).strip().lower()
ASSESSMENT_MODEL = str(os.getenv("ASSESSMENT_MODEL", ASSESSMENT_LLM_CONFIG.get("model", LLM_MODEL)))

CHAT_PROVIDER = str(os.getenv("CHAT_PROVIDER", CHAT_LLM_CONFIG.get("provider", ASSESSMENT_PROVIDER))).strip().lower()
CHAT_MODEL = str(os.getenv("CHAT_MODEL", CHAT_LLM_CONFIG.get("model", ASSESSMENT_MODEL)))
ASSESSMENT_BATCH_SIZE = int(os.getenv("ASSESSMENT_BATCH_SIZE", str(ASSESSMENT_LLM_CONFIG.get("batch_size", 4))))
ASSESSMENT_MAX_TARGETS = int(os.getenv("ASSESSMENT_MAX_TARGETS", str(ASSESSMENT_LLM_CONFIG.get("max_targets", ASSESSMENT_CONFIG.get("max_llm_targets", 30)))))

HIGH_RISK_ONLY_LLM = _bool(ASSESSMENT_CONFIG.get("high_risk_only_llm", True), True)
MAX_LLM_TARGETS = int(ASSESSMENT_CONFIG.get("max_llm_targets", 30))
