from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.audit_service import AuditService
from dashboard.api.services.chroma_service import ChromaService
from dashboard.api.services.sqlite_service import SQLiteService

router = APIRouter(prefix="/api/memories", tags=["memories"], dependencies=[Depends(require_auth)])


class DeleteRequest(BaseModel):
    group_id: str
    ids: List[str]
    password: str = ""


def _service() -> ChromaService:
    return ChromaService(get_settings().chroma_dir)


def _sqlite_service() -> SQLiteService:
    return SQLiteService(get_settings().db_path)


def _require_group_memory_access(group_id: str, password: str = "") -> None:
    if not group_id.strip():
        raise HTTPException(status_code=400, detail="group_id is required")
    sqlite_service = _sqlite_service()
    if sqlite_service.group_requires_password(group_id) and not sqlite_service.verify_group_password(group_id, password):
        raise HTTPException(status_code=403, detail="group password required")


def _require_ids_belong_to_group(service: ChromaService, group_id: str, ids: List[str]) -> None:
    rows = service.get_memories_by_ids(ids)
    found_ids = {str(row.get("id", "")) for row in rows}
    if found_ids != set(ids):
        raise HTTPException(status_code=400, detail="memory ids do not belong to group")
    for row in rows:
        metadata = row.get("metadata", {})
        if not isinstance(metadata, dict) or str(metadata.get("group_id", "")) != group_id:
            raise HTTPException(status_code=400, detail="memory ids do not belong to group")


@router.get("/health")
def health():
    return ok(_service().health())


@router.get("")
def list_memories(group_id: str = Query(""), limit: int = Query(100), x_group_password: str = Header("", alias="X-Group-Password")):
    _require_group_memory_access(group_id, x_group_password)
    return ok(_service().list_memories(group_id, limit))


@router.get("/search")
def search(q: str = Query(...), group_id: str = Query(""), limit: int = Query(10), x_group_password: str = Header("", alias="X-Group-Password")):
    _require_group_memory_access(group_id, x_group_password)
    return ok(_service().query(group_id, q, limit))


@router.post("/delete")
def delete(request: DeleteRequest):
    settings = get_settings()
    if settings.readonly:
        raise HTTPException(status_code=403, detail="readonly mode")
    _require_group_memory_access(request.group_id, request.password)
    service = _service()
    _require_ids_belong_to_group(service, request.group_id, request.ids)
    count = service.delete(request.ids)
    AuditService(settings.audit_log_path).record("memory.delete", request.group_id + "/" + ",".join(request.ids), "ok")
    return ok({"deleted": count})
