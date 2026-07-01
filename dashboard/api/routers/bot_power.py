from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.audit_service import AuditService
from plugins.arteta_power import get_state, set_state

router = APIRouter(prefix="/api/bot-power", tags=["bot-power"], dependencies=[Depends(require_auth)])


class UpdatePowerRequest(BaseModel):
    enabled: bool
    reason: str = ""


@router.get("")
def read_power():
    return ok(get_state())


@router.post("")
def update_power(request: UpdatePowerRequest):
    settings = get_settings()
    if settings.readonly:
        raise HTTPException(status_code=403, detail="readonly mode")
    state = set_state(request.enabled, actor="dashboard", reason=request.reason)
    AuditService(settings.audit_log_path).record(
        "bot_power.update",
        "on" if state["enabled"] else "off",
        "ok",
    )
    return ok(state)
