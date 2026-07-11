from plugins import arteta_tools
from plugins.arteta_knowledge import query_knowledge

from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


EMPTY_OBJECT_SCHEMA = {"type": "object", "properties": {}, "required": []}


async def get_arsenal_result(ctx: ToolContext) -> str:
    return await arteta_tools._get_arsenal_result()


async def get_pl_table(ctx: ToolContext) -> str:
    return await arteta_tools._get_pl_table()


async def get_arsenal_injuries(ctx: ToolContext) -> str:
    return await arteta_tools._get_arsenal_injuries()


async def search_news(ctx: ToolContext, q: str) -> str:
    return await arteta_tools._search_news(q)


def get_football_knowledge(ctx: ToolContext, topic: str) -> str:
    return query_knowledge(topic, max_chars=3000)


async def get_group_members(ctx: ToolContext, group_id: str = "") -> str:
    return await arteta_tools._get_group_members(group_id or ctx.group_id)


async def get_member_relations(ctx: ToolContext, group_id: str = "", user_id: str = "") -> str:
    return await arteta_tools._get_member_relations(group_id or ctx.group_id, user_id or ctx.user_id)


def register_tools() -> None:
    specs = [
        ToolSpec(
            name="get_arsenal_result",
            description="获取阿森纳最近比赛结果（比分、对手、赛事）。当用户问比赛结果、比分、赢没赢时调用",
            parameters=EMPTY_OBJECT_SCHEMA,
            handler=get_arsenal_result,
            category="football",
        ),
        ToolSpec(
            name="get_pl_table",
            description="获取当前英超积分榜（前几名和后几名排名、积分）。当用户问排名、积分榜、争冠形势时调用",
            parameters=EMPTY_OBJECT_SCHEMA,
            handler=get_pl_table,
            category="football",
        ),
        ToolSpec(
            name="get_arsenal_injuries",
            description="获取阿森纳最新伤病信息。当用户问某球员是否受伤、伤愈复出时间、伤病名单时调用",
            parameters=EMPTY_OBJECT_SCHEMA,
            handler=get_arsenal_injuries,
            category="football",
        ),
        ToolSpec(
            name="search_news",
            description="搜索足球/转会/阿森纳相关最新新闻。当用户问转会传闻、签约、官宣、联赛动态时调用。搜索词请用英文",
            parameters={
                "type": "object",
                "properties": {"q": {"type": "string", "description": "英文搜索关键词"}},
                "required": ["q"],
            },
            handler=search_news,
            category="football",
        ),
        ToolSpec(
            name="get_football_knowledge",
            description="查询阿尔特塔知识库（战术概念、更衣室故事、发布会语录等）。",
            parameters={
                "type": "object",
                "properties": {"topic": {"type": "string", "description": "要查询的主题关键词"}},
                "required": ["topic"],
            },
            handler=get_football_knowledge,
            category="knowledge",
        ),
        ToolSpec(
            name="get_group_members",
            description="获取群内活跃球员名单（近24小时有发言的）。",
            parameters={
                "type": "object",
                "properties": {"group_id": {"type": "string", "description": "群号"}},
                "required": ["group_id"],
            },
            handler=get_group_members,
            category="group",
        ),
        ToolSpec(
            name="get_member_relations",
            description="查询某位球员在群内经常和谁互动（回复/@最多的人）。",
            parameters={
                "type": "object",
                "properties": {
                    "group_id": {"type": "string", "description": "群号"},
                    "user_id": {"type": "string", "description": "要查询的球员QQ号"},
                },
                "required": ["group_id", "user_id"],
            },
            handler=get_member_relations,
            category="group",
        ),
    ]
    for spec in specs:
        ensure_tool(spec)

