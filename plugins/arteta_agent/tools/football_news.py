from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


def _get_arteta_tools():
    from plugins import arteta_tools

    return arteta_tools


async def search_football_news(ctx: ToolContext, query: str, category: str = "", days: int = 14) -> str:
    return await _get_arteta_tools()._search_football_news(query, category=category or None, days=days)


async def query_current_football_knowledge(
    ctx: ToolContext,
    query: str,
    event_types=None,
    teams=None,
    players=None,
    competitions=None,
    max_age_seconds: int = 0,
    min_source_level: str = "",
    max_results: int = 6,
) -> str:
    from plugins.arteta_football_news import DB_PATH, FootballNewsSQLiteStore
    from plugins.arteta_football_intelligence.models import FootballKnowledgeQuery
    from plugins.arteta_football_intelligence.query import query_current_football_knowledge as query_service
    from plugins.arteta_football_intelligence.query import result_to_json

    store = FootballNewsSQLiteStore(DB_PATH)
    store.initialize()
    result = query_service(
        store,
        FootballKnowledgeQuery(
            query=str(query or ""),
            event_types=list(event_types or []),
            teams=list(teams or []),
            players=list(players or []),
            competitions=list(competitions or []),
            max_age_seconds=int(max_age_seconds or 0),
            min_source_level=str(min_source_level or ""),
            max_results=max(1, min(int(max_results or 6), 10)),
        ),
    )
    return result_to_json(result)


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="query_current_football_knowledge",
        description="先查询本地当前足球情报库，返回 fresh/stale/miss/conflict/unavailable 结构化状态；仅 fresh 可直接作为当前事实依据。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "当前足球事实问题", "maxLength": 300},
                "event_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "match_result",
                            "fixture",
                            "lineup",
                            "match_event",
                            "transfer",
                            "contract",
                            "injury",
                            "suspension",
                            "training",
                            "press_conference",
                            "manager_change",
                            "player_form",
                            "club_announcement",
                            "disciplinary",
                            "rumor",
                            "other",
                        ],
                    },
                    "maxItems": 5,
                    "description": "事件类型过滤",
                },
                "teams": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 80},
                    "maxItems": 6,
                },
                "players": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 80},
                    "maxItems": 6,
                },
                "competitions": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 80},
                    "maxItems": 4,
                },
                "max_age_seconds": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 604800,
                    "default": 0,
                },
                "min_source_level": {
                    "type": "string",
                    "enum": ["", "official", "authoritative_media", "trusted_reporter", "aggregator", "unknown"],
                    "default": "",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 6,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=query_current_football_knowledge,
        category="football_news",
        parallel_safe=True,
        idempotent=True,
    ))
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
