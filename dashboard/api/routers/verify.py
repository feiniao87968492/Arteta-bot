from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dashboard.api.config import REPO_ROOT, get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.audit_service import AuditService
from dashboard.api.services.verify_service import VerifyService

router = APIRouter(prefix="/api/verify", tags=["verify"], dependencies=[Depends(require_auth)])
service = VerifyService(REPO_ROOT)


class StartVerifyRequest(BaseModel):
    suites: List[str] = ["core"]
    cases: List[str] = []
    online: bool = False
    allow_side_effects: bool = False


@router.post("/runs")
def start_run(request: StartVerifyRequest):
    try:
        run_id = service.start_run(request.suites, request.cases, request.online, request.allow_side_effects)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    AuditService(get_settings().audit_log_path).record("verify.start", run_id, "ok")
    return ok({"run_id": run_id})


@router.get("/runs/{run_id}/events")
def events(run_id: str):
    def event_stream():
        try:
            for line in service.stream_lines(run_id):
                yield "data: " + line.replace("\n", " ") + "\n\n"
        except KeyError as exc:
            yield "data: " + str(exc).replace("\n", " ") + "\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/latest-report")
def latest_report():
    return ok(service.latest_report())
