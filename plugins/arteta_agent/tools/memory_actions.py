from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool
from ..ui_preferences import detect_phrase_style_preference, set_phrase_preference


def _get_arteta_chat():
    from plugins import arteta_chat

    return arteta_chat


def _get_arteta_memory():
    from plugins import arteta_memory

    return arteta_memory


def clear_group_memory(ctx: ToolContext, group_id: str = "") -> str:
    target_group = str(group_id or ctx.group_id)
    return _get_arteta_chat().clear_group_memory_for_group(target_group)


def remember_user_preference(ctx: ToolContext, memory: str) -> str:
    text = str(memory or "").strip()
    if not text:
        return "没有可写入的长期记忆。"
    _get_arteta_memory().memory_store.add_memory(
        ctx.group_id,
        ctx.user_id,
        text,
        "用户明确要求长期记住：{0}".format(text),
        nickname=ctx.nickname or ctx.user_id,
        aliases=[],
    )
    phrase_style = detect_phrase_style_preference(text)
    if phrase_style:
        set_phrase_preference(ctx.group_id, **phrase_style)
        return "已写入长期记忆：{0}\n已同步回复样式：{1}".format(text, phrase_style["phrase"])
    return "已写入长期记忆：{0}".format(text)


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="clear_group_memory",
        description="清空当前群或指定群的长期对话记忆。会删除状态，必须用户确认后执行。",
        parameters={
            "type": "object",
            "properties": {
                "group_id": {"type": "string", "description": "目标群号，默认当前群"},
            },
            "required": [],
        },
        handler=clear_group_memory,
        permission="confirm_write",
        category="memory",
        timeout_seconds=30.0,
    ))
    ensure_tool(ToolSpec(
        name="remember_user_preference",
        description="把用户明确要求以后、下次、记住的偏好或规则立即写入当前群当前用户的长期记忆。",
        parameters={
            "type": "object",
            "properties": {
                "memory": {"type": "string", "description": "需要长期记住的用户偏好或规则"},
            },
            "required": ["memory"],
        },
        handler=remember_user_preference,
        permission="safe_write",
        category="memory",
        timeout_seconds=10.0,
    ))
