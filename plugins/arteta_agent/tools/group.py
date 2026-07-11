from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


def _get_arteta_chat():
    from plugins import arteta_chat

    return arteta_chat


def find_recent_messages_by_alias(ctx: ToolContext, query: str = "", limit: int = 3) -> str:
    query_text = str(query or ctx.raw_message or "").strip()
    rows = _get_arteta_chat().find_recent_messages_by_alias(ctx.group_id, query_text, limit=limit)
    if not rows:
        return "暂无按别名命中的最近发言。"
    lines = []
    for item in rows:
        lines.append(
            "- {timestamp} {nickname}（别名：{alias}，QQ：{user_id}）说：{message}".format(
                timestamp=item.get("timestamp", ""),
                nickname=item.get("nickname", ""),
                alias=item.get("alias", ""),
                user_id=item.get("user_id", ""),
                message=item.get("message", ""),
            )
        )
    return "\n".join(lines)


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="find_recent_messages_by_alias",
        description="按昵称、别名或画像中的外号匹配群成员，并读取其最近一条发言。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "包含昵称或别名的用户问题"},
                "limit": {"type": "integer", "description": "最多匹配人数", "default": 3},
            },
            "required": [],
        },
        handler=find_recent_messages_by_alias,
        category="group",
    ))
