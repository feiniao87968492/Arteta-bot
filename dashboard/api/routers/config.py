import subprocess

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard.api.config import ENV_WHITELIST, get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.audit_service import AuditService
from dashboard.api.services.env_service import EnvService

router = APIRouter(prefix="/api/config", tags=["config"], dependencies=[Depends(require_auth)])


class UpdateConfigRequest(BaseModel):
    name: str
    value: str


def _env_service() -> EnvService:
    return EnvService(get_settings().env_file, ENV_WHITELIST)


@router.get("/keys")
def keys():
    return ok(_env_service().list_masked())


@router.get("/keys/{name}/test")
def test_key(name: str):
    audit = AuditService(get_settings().audit_log_path)
    try:
        result = _env_service().check_effective(name)
    except ValueError as exc:
        audit.record("config.test", name, "rejected")
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record("config.test", name, "ok" if result["effective"] else "mismatch")
    return ok(result)


@router.post("/restart-bot")
def restart_bot():
    settings = get_settings()
    audit = AuditService(settings.audit_log_path)
    if settings.readonly:
        audit.record("bot.restart", "arteta_bot", "readonly")
        raise HTTPException(status_code=403, detail="readonly mode")

    command = ["supervisorctl", "restart", "arteta_bot"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        audit.record("bot.restart", "arteta_bot", "timeout")
        raise HTTPException(status_code=504, detail="bot restart timed out")
    except OSError as exc:
        audit.record("bot.restart", "arteta_bot", "failed")
        raise HTTPException(status_code=500, detail=str(exc))

    status = "ok" if result.returncode == 0 else "failed"
    audit.record("bot.restart", "arteta_bot", status)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=(result.stderr or result.stdout or "restart failed").strip())
    return ok({
        "service": "arteta_bot",
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    })


@router.post("/keys")
def update_key(request: UpdateConfigRequest):
    settings = get_settings()
    if settings.readonly:
        raise HTTPException(status_code=403, detail="readonly mode")
    audit = AuditService(settings.audit_log_path)
    try:
        _env_service().update(request.name, request.value)
    except ValueError as exc:
        audit.record("config.update", request.name, "rejected")
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record("config.update", request.name, "ok")
    return ok({"name": request.name})
