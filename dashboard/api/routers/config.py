import subprocess
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_verified_auth
from dashboard.api.services.audit_service import AuditService
from dashboard.api.services.env_service import EnvService
from dashboard.api.services.provider_config_service import (
    ProviderConfigError,
    ProviderConfigService,
)

router = APIRouter(prefix="/api/config", tags=["config"])


class ProviderCandidateRequest(BaseModel):
    values: Dict[str, str]


class ProviderApplyRequest(BaseModel):
    values: Dict[str, str]
    receipt: str


_provider_services = {}  # type: Dict[str, ProviderConfigService]


def _provider_service() -> ProviderConfigService:
    env_file = get_settings().env_file
    service = _provider_services.get(env_file)
    if service is None:
        service = ProviderConfigService(EnvService(env_file, []))
        _provider_services[env_file] = service
    return service


@router.get("/providers")
def providers(auth: Dict[str, str] = Depends(require_verified_auth)):
    return ok(_provider_service().list_providers())


@router.post("/providers/{provider_id}/validate")
async def validate_provider(
    provider_id: str,
    request: ProviderCandidateRequest,
    auth: Dict[str, str] = Depends(require_verified_auth),
):
    settings = get_settings()
    audit = AuditService(settings.audit_log_path)
    actor = str(auth.get("sub") or "admin")
    try:
        result = await _provider_service().verify(provider_id, request.values, actor=actor)
    except ProviderConfigError as exc:
        audit.record("provider.validate", provider_id, exc.code)
        raise HTTPException(status_code=400, detail=exc.message)
    audit.record("provider.validate", provider_id, "ok")
    return ok(result)


@router.post("/providers/{provider_id}/apply")
def apply_provider(
    provider_id: str,
    request: ProviderApplyRequest,
    auth: Dict[str, str] = Depends(require_verified_auth),
):
    settings = get_settings()
    audit = AuditService(settings.audit_log_path)
    actor = str(auth.get("sub") or "admin")
    if settings.readonly:
        audit.record("provider.apply", provider_id, "readonly")
        raise HTTPException(status_code=403, detail="readonly mode")

    def restart():
        try:
            return subprocess.run(
                ["supervisorctl", "restart", "arteta_bot"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            class TimeoutResult:
                returncode = 1
                stdout = ""
                stderr = "restart timed out"
            return TimeoutResult()
        except OSError as exc:
            class ErrorResult:
                returncode = 1
                stdout = ""
                stderr = str(exc)
            return ErrorResult()

    try:
        result = _provider_service().apply(
            provider_id,
            request.values,
            request.receipt,
            actor=actor,
            restart=restart,
        )
    except ProviderConfigError as exc:
        audit.record("provider.apply", provider_id, exc.code)
        raise HTTPException(status_code=400, detail=exc.message)
    status = "ok" if result.get("active") else "restart_failed"
    audit.record("provider.apply", provider_id, status)
    return ok(result)
