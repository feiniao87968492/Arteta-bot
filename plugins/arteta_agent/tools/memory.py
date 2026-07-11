from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


def _get_arteta_chat():
    from plugins import arteta_chat

    return arteta_chat


def _get_arteta_memory():
    from plugins import arteta_memory

    return arteta_memory


async def query_group_memory(ctx: ToolContext, query: str = "") -> str:
    query_text = str(query or ctx.raw_message or "").strip()
    memories = _get_arteta_memory().memory_store.query_memories(ctx.group_id, query_text)
    if not memories:
        return "暂无相关群记忆。"
    return "\n\n".join(memories)


async def get_recent_group_context(ctx: ToolContext, limit: int = 15) -> str:
    arteta_chat = _get_arteta_chat()
    rows = await arteta_chat.get_recent_group_messages(ctx.group_id, limit)
    context = arteta_chat.format_recent_group_context(rows)
    return context or "暂无最近群聊上下文。"


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="query_group_memory",
        description="按语义检索当前群的长期对话记忆。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题，默认使用用户原始消息"},
            },
            "required": [],
        },
        handler=query_group_memory,
        category="memory",
    ))
    ensure_tool(ToolSpec(
        name="get_recent_group_context",
        description="读取当前群最近聊天上下文，用于理解刚才、他们、那件事等近距离指代。",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "最多读取多少条最近消息", "default": 15},
            },
            "required": [],
        },
        handler=get_recent_group_context,
        category="memory",
    ))
