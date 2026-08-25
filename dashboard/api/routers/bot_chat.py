from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.audit_service import AuditService
from dashboard.api.config import get_settings
from dashboard.api.services.bot_chat_service import BotChatService

router = APIRouter(prefix="/api/bot-chat", tags=["bot-chat"], dependencies=[Depends(require_auth)])


class BotChatRequest(BaseModel):
    message: str = ""
    group_id: str = "dashboard"
    user_id: str = "dashboard-user"
    nickname: str = "Dashboard 球员"
    images: List[str] = []


@router.post("/messages")
async def send_message(request: BotChatRequest):
    if not request.message.strip() and not request.images:
        raise HTTPException(status_code=400, detail="message or images required")
    result = await BotChatService().reply(
        request.message,
        request.group_id,
        request.user_id,
        request.nickname,
        images=request.images,
    )
    AuditService(get_settings().audit_log_path).record("bot_chat.message", result["group_id"], "ok")
    return ok(result)
