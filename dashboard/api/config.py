import os
from dataclasses import dataclass
from typing import List


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
DEV_SECRET_KEY = "dev-dashboard-insecure-secret"


@dataclass
class DashboardSettings:
    host: str
    port: int
    admin_password: str
    secret_key: str
    allowed_origins: List[str]
    env_file: str
    readonly: bool
    public: bool
    db_path: str
    chroma_dir: str
    logs_dir: str
    docs_roots: List[str]
    audit_log_path: str
    sync_status_path: str
    web_dist: str
    prompts_file: str


ENV_WHITELIST = [
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_URL",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_TEMPERATURE",
    "FOOTBALL_API_TOKEN",
    "ALGO_API_KEY",
    "ALGO_API_URL",
    "ALGO_MODEL",
    "IMAGE_API_KEY",
    "IMAGE_API_URL",
    "IMAGE_MODEL",
    "VISION_API_KEY",
    "VISION_API_URL",
    "VISION_MODEL",
    "VISION_TIMEOUT",
    "ARTETA_GROKSEARCH_API_URL",
    "ARTETA_GROKSEARCH_API_KEY",
    "ARTETA_GROKSEARCH_MODEL",
    "ARTETA_GROKSEARCH_TIMEOUT",
    "ARTETA_X_FETCH_API_URL",
    "ARTETA_X_FETCH_API_KEY",
]


def _split_origins(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).lower() == "true"


def get_settings() -> DashboardSettings:
    env_file = os.environ.get("DASHBOARD_ENV_FILE", os.path.join(REPO_ROOT, ".env"))
    return DashboardSettings(
        host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("DASHBOARD_PORT", "8765")),
        admin_password=os.environ.get("DASHBOARD_ADMIN_PASSWORD", ""),
        secret_key=os.environ.get("DASHBOARD_SECRET_KEY", ""),
        allowed_origins=_split_origins(os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "http://localhost:5173")),
        env_file=env_file,
        readonly=_env_bool("DASHBOARD_READONLY"),
        public=_env_bool("DASHBOARD_PUBLIC"),
        db_path=os.environ.get("ARTETA_DB_PATH", os.path.join(REPO_ROOT, "arsenal_data.db")),
        chroma_dir=os.environ.get("ARTETA_CHROMA_DIR", os.path.join(REPO_ROOT, "chroma_db")),
        logs_dir=os.environ.get("DASHBOARD_LOGS_DIR", os.path.join(REPO_ROOT, "logs")),
        docs_roots=[os.path.join(REPO_ROOT, "Docs"), os.path.join(REPO_ROOT, "knowledge_base")],
        audit_log_path=os.path.join(REPO_ROOT, "logs", "dashboard_audit.log"),
        sync_status_path=os.environ.get("DASHBOARD_SYNC_STATUS_PATH", os.path.join(REPO_ROOT, "data", "ecs_sync_status.json")),
        web_dist=os.environ.get("DASHBOARD_WEB_DIST", os.path.join(REPO_ROOT, "dashboard", "web", "dist")),
        prompts_file=os.environ.get("ARTETA_PROMPTS_FILE", os.path.join(REPO_ROOT, "config", "prompts.json")),
    )


def validate_public_settings(settings: DashboardSettings) -> None:
    if settings.public and not settings.secret_key:
        raise RuntimeError("DASHBOARD_SECRET_KEY is required when DASHBOARD_PUBLIC=true")
    if settings.public and settings.secret_key == DEV_SECRET_KEY:
        raise RuntimeError("DASHBOARD_SECRET_KEY must not use the development fallback when DASHBOARD_PUBLIC=true")
