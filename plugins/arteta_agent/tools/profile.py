import json

from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


def _get_arteta_chat():
    from plugins import arteta_chat

    return arteta_chat


def _format_profile(profile: dict) -> str:
    if not profile or not profile.get("current_nickname"):
        return "暂无该球员档案。"
    payload = {
        "user_id": profile.get("user_id", ""),
        "nickname": profile.get("current_nickname", ""),
        "level": profile.get("level", ""),
        "favorability": profile.get("favorability", 0),
        "message_count": profile.get("message_count", 0),
        "personality_profile": profile.get("personality_profile", {}),
        "recent_messages": profile.get("recent_messages", [])[:5],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def get_user_profile(ctx: ToolContext, user_id: str, group_id: str = "") -> str:
    profile = await _get_arteta_chat().get_user_profile(str(user_id), str(group_id or ctx.group_id))
    return _format_profile(profile)


async def get_current_user_profile(ctx: ToolContext) -> str:
    profile = await _get_arteta_chat().get_user_profile(ctx.user_id, ctx.group_id)
    return _format_profile(profile)


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="get_user_profile",
        description="读取指定群成员档案，包括昵称、定位、信任度、画像和最近发言。",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "目标 QQ 号"},
                "group_id": {"type": "string", "description": "群号，默认当前群"},
            },
            "required": ["user_id"],
        },
        handler=get_user_profile,
        category="profile",
    ))
    ensure_tool(ToolSpec(
        name="get_current_user_profile",
        description="读取当前提问者在本群的档案。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_current_user_profile,
        category="profile",
    ))
