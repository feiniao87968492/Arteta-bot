from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.audit_service import AuditService
from dashboard.api.services.sqlite_service import SQLiteService

router = APIRouter(prefix="/api/groups", tags=["groups"], dependencies=[Depends(require_auth)])


class UpdateProfileRequest(BaseModel):
    profile: Dict[str, Any]
    password: str = ""


class DeleteProfileRequest(BaseModel):
    password: str = ""


class GroupPasswordRequest(BaseModel):
    password: str = ""


class GroupNameRequest(BaseModel):
    group_name: str = ""


class UpdateFavorRequest(BaseModel):
    favor: Optional[int] = None
    delta: Optional[int] = None
    nickname: str = ""
    password: str = ""


def _service() -> SQLiteService:
    return SQLiteService(get_settings().db_path)


def _require_group_access(group_id: str, password: str = "") -> None:
    service = _service()
    if service.group_requires_password(group_id) and not service.verify_group_password(group_id, password):
        raise HTTPException(status_code=403, detail="group password required")


@router.get("")
def list_groups():
    return ok(_service().list_groups())


@router.get("/{group_id}/settings")
def group_settings(group_id: str):
    return ok(_service().get_group_settings(group_id))


@router.post("/{group_id}/settings/name")
def set_group_name(group_id: str, request: GroupNameRequest):
    settings = get_settings()
    if settings.readonly:
        raise HTTPException(status_code=403, detail="readonly mode")
    group_name = request.group_name.strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="group_name is required")
    result = _service().upsert_group_name(group_id, group_name)
    AuditService(settings.audit_log_path).record("group.name.set", group_id, "ok")
    return ok(result)


@router.post("/{group_id}/settings/password")
def set_group_password(group_id: str, request: GroupPasswordRequest):
    settings = get_settings()
    if settings.readonly:
        raise HTTPException(status_code=403, detail="readonly mode")
    password = request.password.strip()
    if not password:
        raise HTTPException(status_code=400, detail="password is required")
    result = _service().set_group_password(group_id, password)
    AuditService(settings.audit_log_path).record("group.password.set", group_id, "ok")
    return ok(result)


@router.delete("/{group_id}/settings/password")
def clear_group_password(group_id: str, request: GroupPasswordRequest):
    settings = get_settings()
    if settings.readonly:
        raise HTTPException(status_code=403, detail="readonly mode")
    _require_group_access(group_id, request.password)
    result = _service().clear_group_password(group_id)
    AuditService(settings.audit_log_path).record("group.password.clear", group_id, "ok")
    return ok(result)


@router.get("/{group_id}/users")
def list_users(group_id: str, x_group_password: str = Header("", alias="X-Group-Password")):
    _require_group_access(group_id, x_group_password)
    return ok(_service().list_users(group_id))


@router.get("/{group_id}/users/{user_id}")
def user_detail(group_id: str, user_id: str, x_group_password: str = Header("", alias="X-Group-Password")):
    _require_group_access(group_id, x_group_password)
    return ok(_service().get_user_detail(group_id, user_id))


@router.post("/{group_id}/users/{user_id}/profile")
def update_user_profile(group_id: str, user_id: str, request: UpdateProfileRequest):
    settings = get_settings()
    if settings.readonly:
        raise HTTPException(status_code=403, detail="readonly mode")
    _require_group_access(group_id, request.password)
    result = _service().update_user_profile(group_id, user_id, request.profile)
    AuditService(settings.audit_log_path).record("profile.update", f"{group_id}/{user_id}", "ok")
    return ok(result)


@router.delete("/{group_id}/users/{user_id}/profile")
def delete_user_profile(group_id: str, user_id: str, request: DeleteProfileRequest = DeleteProfileRequest()):
    settings = get_settings()
    if settings.readonly:
        raise HTTPException(status_code=403, detail="readonly mode")
    _require_group_access(group_id, request.password)
    result = _service().delete_user_profile(group_id, user_id)
    AuditService(settings.audit_log_path).record("profile.delete", f"{group_id}/{user_id}", "ok")
    return ok(result)


@router.post("/{group_id}/users/{user_id}/favor")
def update_user_favor(group_id: str, user_id: str, request: UpdateFavorRequest):
    settings = get_settings()
    if settings.readonly:
        raise HTTPException(status_code=403, detail="readonly mode")
    _require_group_access(group_id, request.password)
    if (request.favor is None) == (request.delta is None):
        raise HTTPException(status_code=400, detail="exactly one of favor or delta must be provided")
    if request.delta is not None and request.delta == 0:
        raise HTTPException(status_code=400, detail="delta must be non-zero")
    nickname = request.nickname.strip() or None
    try:
        result = _service().update_user_favor(
            group_id,
            user_id,
            favor=request.favor,
            delta=request.delta,
            nickname=nickname,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    favor_value = result.get("favorability", 0) if isinstance(result, dict) else 0
    action = "favor.set" if request.favor is not None else "favor.delta"
    AuditService(settings.audit_log_path).record(
        action,
        f"{group_id}/{user_id}",
        f"ok favor={favor_value}",
    )
    return ok(result)
