import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from dashboard.api.config import ENV_WHITELIST, REPO_ROOT, get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.chroma_service import ChromaService
from dashboard.api.services.env_service import EnvService
from dashboard.api.services.logs_service import LogsService
from dashboard.api.services.sqlite_service import SQLiteService
from dashboard.api.services.verify_service import VerifyService
from plugins.arteta_power import get_state as get_power_state

router = APIRouter(prefix="/api/overview", tags=["overview"], dependencies=[Depends(require_auth)])


def _parse_time(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sync_status(path: str):
    if not os.path.exists(path):
        return {"available": False, "stale": True, "last_success_at": "", "last_error": "", "remote_db": "", "local_db": "", "bytes": 0, "duration_ms": 0, "interval_seconds": 0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, ValueError) as exc:
        return {"available": False, "stale": True, "last_success_at": "", "last_error": str(exc), "remote_db": "", "local_db": "", "bytes": 0, "duration_ms": 0, "interval_seconds": 0}

    interval = int(status.get("interval_seconds") or 0)
    last_success = status.get("last_success_at") or ""
    parsed = _parse_time(last_success)
    stale = True
    if parsed and interval > 0:
        stale = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() > interval * 3
    return {
        "available": True,
        "stale": stale,
        "last_success_at": last_success,
        "last_error": status.get("last_error") or "",
        "remote_db": status.get("remote_db") or "",
        "local_db": status.get("local_db") or "",
        "bytes": status.get("bytes") or 0,
        "duration_ms": status.get("duration_ms") or 0,
        "interval_seconds": interval,
    }


@router.get("")
def overview():
    settings = get_settings()
    groups = SQLiteService(settings.db_path).list_groups()
    logs = LogsService(settings.logs_dir).list_logs()
    keys = EnvService(settings.env_file, ENV_WHITELIST).list_masked()
    report = VerifyService(REPO_ROOT).latest_report()

    return ok(
        {
            "paths": {
                "db": {"path": settings.db_path, "exists": os.path.exists(settings.db_path)},
                "chroma": {"path": settings.chroma_dir, "exists": os.path.isdir(settings.chroma_dir)},
                "logs": {"path": settings.logs_dir, "exists": os.path.isdir(settings.logs_dir)},
                "env": {"path": settings.env_file, "exists": os.path.exists(settings.env_file)},
            },
            "groups": {"count": len(groups), "items": groups[:5]},
            "chroma": ChromaService(settings.chroma_dir).health(),
            "logs": {"count": len(logs), "items": logs[:5]},
            "config": {"keys": keys},
            "latest_report": report,
            "readonly": settings.readonly,
            "sync": _sync_status(settings.sync_status_path),
            "bot_power": get_power_state(),
        }
    )
