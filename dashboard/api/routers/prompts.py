from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dashboard.api.config import get_settings
from dashboard.api.schemas import fail, ok
from dashboard.api.security import require_auth
from dashboard.api.services.audit_service import AuditService
from dashboard.api.services.prompt_service import PromptService

router = APIRouter(prefix="/api/prompts", tags=["prompts"], dependencies=[Depends(require_auth)])


class PromptEntryRequest(BaseModel):
    key: str = ""
    title: str = ""
    category: str = ""
    content: str = ""
    variables: List[str] = []
    enabled: bool = True


class PromptUpdateRequest(BaseModel):
    title: str = ""
    category: str = ""
    content: str = ""
    variables: List[str] = []
    enabled: bool = True


def _service():
    # type: () -> PromptService
    return PromptService(get_settings().prompts_file)


def _ensure_writable():
    # type: () -> None
    if get_settings().readonly:
        raise HTTPException(status_code=403, detail="readonly mode")


def _request_data(request):
    # type: (BaseModel) -> dict
    if hasattr(request, "model_dump"):
        return request.model_dump(exclude_unset=True)
    return request.dict(exclude_unset=True)


@router.get("")
def list_prompts():
    return ok(_service().list_entries())


@router.post("")
def create_prompt(request: PromptEntryRequest):
    # type: (...) -> dict
    _ensure_writable()
    settings = get_settings()
    audit = AuditService(settings.audit_log_path)
    try:
        entry = _service().create_entry(_request_data(request))
    except ValueError as exc:
        audit.record("prompts.create", request.key, "rejected")
        return JSONResponse(status_code=400, content=fail("bad_request", str(exc)))
    audit.record("prompts.create", entry["key"], "ok")
    return ok(entry)


@router.put("/{key}")
def update_prompt(key: str, request: PromptUpdateRequest):
    # type: (...) -> dict
    _ensure_writable()
    settings = get_settings()
    audit = AuditService(settings.audit_log_path)
    try:
        entry = _service().update_entry(key, _request_data(request))
    except ValueError as exc:
        audit.record("prompts.update", key, "rejected")
        return JSONResponse(status_code=400, content=fail("bad_request", str(exc)))
    audit.record("prompts.update", key, "ok")
    return ok(entry)


@router.post("/{key}/restore")
def restore_prompt(key):
    # type: (str) -> dict
    _ensure_writable()
    settings = get_settings()
    audit = AuditService(settings.audit_log_path)
    try:
        entry = _service().restore_entry(key)
    except ValueError as exc:
        audit.record("prompts.restore", key, "rejected")
        return JSONResponse(status_code=400, content=fail("bad_request", str(exc)))
    audit.record("prompts.restore", key, "ok")
    return ok(entry)


@router.delete("/{key}")
def delete_prompt(key):
    # type: (str) -> dict
    _ensure_writable()
    settings = get_settings()
    audit = AuditService(settings.audit_log_path)
    try:
        _service().delete_entry(key)
    except ValueError as exc:
        audit.record("prompts.delete", key, "rejected")
        return JSONResponse(status_code=400, content=fail("bad_request", str(exc)))
    audit.record("prompts.delete", key, "ok")
    return ok({"key": key})
