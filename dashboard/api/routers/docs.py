from fastapi import APIRouter, Depends, HTTPException, Query

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.docs_service import DocsService

router = APIRouter(prefix="/api/docs", tags=["docs"], dependencies=[Depends(require_auth)])


def _service() -> DocsService:
    return DocsService(get_settings().docs_roots)


@router.get("/tree")
def tree():
    return ok(_service().tree())


@router.get("/file")
def file(path: str = Query(...)):
    try:
        return ok(_service().read_file(path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/search")
def search(q: str = Query(...)):
    return ok(_service().search(q))
