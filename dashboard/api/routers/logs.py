from fastapi import APIRouter, Depends, HTTPException, Query

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.logs_service import LogsService

router = APIRouter(prefix="/api/logs", tags=["logs"], dependencies=[Depends(require_auth)])


def _service() -> LogsService:
    return LogsService(get_settings().logs_dir)


@router.get("")
def list_logs():
    return ok(_service().list_logs())


@router.get("/tail")
def tail(name: str = Query("arteta_bot.log"), limit: int = Query(200)):
    try:
        return ok({"name": name, "lines": _service().tail(name, limit)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
