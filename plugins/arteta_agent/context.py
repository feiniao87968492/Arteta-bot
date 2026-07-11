from dataclasses import dataclass, field
from typing import Any, Dict, Optional

try:
    from nonebot.adapters.onebot.v11 import Bot, MessageEvent
except Exception:  # pragma: no cover - keeps pure unit tests independent of NoneBot.
    Bot = Any
    MessageEvent = Any


@dataclass
class ToolContext:
    bot: Optional[Bot]
    event: Optional[MessageEvent]
    user_id: str
    group_id: str
    nickname: str = ""
    raw_message: str = ""
    reply_text: str = ""
    image_analysis: str = ""
    is_group: bool = True
    is_admin: bool = False
    request_id: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
