import sqlite3
import time
from datetime import date, datetime
from typing import List, Tuple

from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


def _get_arteta_daily():
    from plugins import arteta_daily

    return arteta_daily


def _get_arteta_weekly():
    from plugins import arteta_weekly

    return arteta_weekly


def _get_today_group_messages(group_id: str, limit: int = 300):
    arteta_daily = _get_arteta_daily()
    today = date.today()
    start = int(datetime(today.year, today.month, today.day).timestamp())
    end = start + 86400
    safe_limit = max(1, min(int(limit or 300), 1000))
    conn = sqlite3.connect(arteta_daily.DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT nickname, message, timestamp
            FROM daily_messages
            WHERE group_id = ? AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (str(group_id), start, end, safe_limit),
        ).fetchall()
    finally:
        conn.close()
    return rows


def _search_daily_rows(group_id: str, keyword: str = "", limit: int = 20):
    arteta_daily = _get_arteta_daily()
    safe_limit = max(1, min(int(limit or 20), 100))
    conn = sqlite3.connect(arteta_daily.DB_PATH)
    try:
        if keyword:
            rows = conn.execute(
                """
                SELECT nickname, message, timestamp
                FROM daily_messages
                WHERE group_id = ? AND message LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (str(group_id), "%" + str(keyword) + "%", safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT nickname, message, timestamp
                FROM daily_messages
                WHERE group_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (str(group_id), safe_limit),
            ).fetchall()
    finally:
        conn.close()
    return rows


def search_daily_messages(ctx: ToolContext, keyword: str = "", limit: int = 20) -> str:
    rows = _search_daily_rows(ctx.group_id, keyword, limit)
    if not rows:
        return "No matching daily messages."
    return "\n".join("[{0}] {1}: {2}".format(row[2], row[0], row[1]) for row in rows)


async def generate_today_group_summary(ctx: ToolContext, limit: int = 300) -> str:
    messages = _get_today_group_messages(ctx.group_id, limit)
    if not messages:
        return "今天本群暂无可总结的聊天记录。"
    summary = await _get_arteta_daily().generate_summary(messages)
    if not summary:
        return "日报生成失败，可能是模型配置不可用或消息不足。"
    return "[DailySummary: {0} messages at {1}]\n{2}".format(len(messages), int(time.time()), summary)


def _normalize_weekly_articles(articles) -> List[Tuple[str, str]]:
    normalized = []
    for article in articles or []:
        if isinstance(article, dict):
            title = article.get("title") or article.get("headline") or ""
            url = article.get("url") or article.get("link") or ""
        elif isinstance(article, (list, tuple)) and len(article) >= 2:
            title = article[0]
            url = article[1]
        else:
            continue
        if title and url:
            normalized.append((str(title), str(url)))
    return normalized


async def generate_weekly_report(ctx: ToolContext, articles=None) -> str:
    normalized = _normalize_weekly_articles(articles)
    if not normalized:
        return "No weekly report articles provided."
    return await _get_arteta_weekly().generate_weekly_report(normalized)


def register_read_tools() -> None:
    ensure_tool(ToolSpec(
        name="search_daily_messages",
        description="Search stored group daily messages. Read-only.",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Keyword to search in message text"},
                "limit": {"type": "integer", "description": "Maximum rows to return", "default": 20},
            },
            "required": [],
        },
        handler=search_daily_messages,
        permission="safe_read",
        category="summary",
        timeout_seconds=10.0,
    ))


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="generate_today_group_summary",
        description="生成当前群今日聊天总结，只返回总结文本，不主动群发。",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "最多读取多少条今日消息", "default": 300},
            },
            "required": [],
        },
        handler=generate_today_group_summary,
        permission="safe_write",
        category="summary",
        timeout_seconds=80.0,
    ))
    ensure_tool(ToolSpec(
        name="generate_weekly_report",
        description="Generate an Arsenal weekly report from provided article title/url pairs.",
        parameters={
            "type": "object",
            "properties": {
                "articles": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Article title"},
                            "headline": {"type": "string", "description": "Alternative title field"},
                            "url": {"type": "string", "description": "Article URL"},
                            "link": {"type": "string", "description": "Alternative URL field"},
                        },
                        "required": [],
                    },
                    "description": "Articles with title and url fields",
                },
            },
            "required": ["articles"],
        },
        handler=generate_weekly_report,
        permission="safe_write",
        category="summary",
        timeout_seconds=120.0,
    ))
