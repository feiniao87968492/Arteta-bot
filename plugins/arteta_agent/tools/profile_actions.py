from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


def _get_arteta_chat():
    from plugins import arteta_chat

    return arteta_chat


async def update_user_profile_by_llm(ctx: ToolContext, user_id: str = "", group_id: str = "", nickname: str = "") -> str:
    target_user = str(user_id or ctx.user_id)
    target_group = str(group_id or ctx.group_id)
    target_nick = str(nickname or ctx.nickname or target_user)
    level = str((ctx.extra or {}).get("level", ""))
    favorability = int((ctx.extra or {}).get("favorability", 0))
    await _get_arteta_chat().update_user_profile(target_user, target_group, target_nick, level, favorability)
    return "已触发 {0} 在群 {1} 的档案更新。".format(target_user, target_group)


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="update_user_profile_by_llm",
        description="用现有 LLM 画像流程更新当前用户或指定用户档案。会改变档案状态，必须用户确认后执行。",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "目标 QQ 号，默认当前用户"},
                "group_id": {"type": "string", "description": "目标群号，默认当前群"},
                "nickname": {"type": "string", "description": "目标昵称，默认当前昵称"},
            },
            "required": [],
        },
        handler=update_user_profile_by_llm,
        permission="confirm_write",
        category="profile",
        timeout_seconds=80.0,
    ))
