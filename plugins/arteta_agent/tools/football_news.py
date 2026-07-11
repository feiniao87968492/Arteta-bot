from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


def _get_arteta_tools():
    from plugins import arteta_tools

    return arteta_tools


async def search_football_news(ctx: ToolContext, query: str, category: str = "", days: int = 14) -> str:
    return await _get_arteta_tools()._search_football_news(query, category=category or None, days=days)


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="search_football_news",
        description="查询本地足球新闻向量库，适合最近、最新、联赛、欧冠、中超等足球新闻问题。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "新闻检索问题"},
                "category": {
                    "type": "string",
                    "enum": [
                        "premier_league",
                        "champions_league",
                        "laliga",
                        "serie_a",
                        "bundesliga",
                        "ligue1",
                        "chinese_super_league",
                    ],
                    "description": "可选联赛分类",
                },
                "days": {"type": "integer", "description": "检索最近多少天的新闻", "default": 14},
            },
            "required": ["query"],
        },
        handler=search_football_news,
        category="football_news",
    ))
