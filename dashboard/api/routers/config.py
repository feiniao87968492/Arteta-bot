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
