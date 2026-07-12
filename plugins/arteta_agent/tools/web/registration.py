"""Tool registration for Web access tools."""

from ...registry import ToolSpec, ensure_tool


def register_tools() -> None:
    """Register all Web access tools with the Arteta agent registry."""
    from . import handlers

    web_timeout = handlers._groksearch_timeout() + 2.0

    ensure_tool(ToolSpec(
        name="grok_search",
        description="GrokSearch 独立搜索工具，优先用于最新新闻、X/Twitter/社媒内容、转会、伤病、官宣和需要强实时性的事实查询；不会回退到普通网页搜索，结果仍需按来源强度谨慎判断。",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 500, "description": "GrokSearch 搜索关键词，查 X/Twitter 时可加入 site:x.com 或账号名"},
                "freshness": {"type": "string", "enum": ["day", "week", "month", "year", "recent", "all"], "description": "时间范围，默认 recent"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 8, "description": "返回条数，1-8"},
            },
            "required": ["query"],
        },
        handler=handlers.grok_search,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
        parallel_safe=True,
        concurrency_group="web_http",
        idempotent=True,
    ))

    ensure_tool(ToolSpec(
        name="web_search",
        description="互联网搜索工具，用于发现真实来源线索。适合最新新闻、2024 年以后事实、陌生实体、需要联网核实时调用；搜索结果不是最终证据，回答前应继续用 web_fetch 或 verify_recent_claim 核实来源。",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 500, "description": "搜索关键词，尽量包含实体、日期、关键词"},
                "freshness": {"type": "string", "enum": ["day", "week", "month", "year", "recent", "all"], "description": "时间范围，默认 recent"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 8, "description": "返回条数，1-8"},
            },
            "required": ["query"],
        },
        handler=handlers.web_search,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
        parallel_safe=True,
        concurrency_group="web_http",
        idempotent=True,
    ))

    ensure_tool(ToolSpec(
        name="fetch_x_post",
        description="读取 x.com/twitter.com status 原帖正文。用于核实 X/Twitter 原帖、记者原帖、俱乐部社媒官宣；比通用 web_fetch 更适合 X 链接，失败时会明确要求截图或原文。",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string", "minLength": 8, "maxLength": 2048, "description": "x.com/twitter.com 的 status 链接"},
            },
            "required": ["url"],
        },
        handler=handlers.fetch_x_post,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
        parallel_safe=True,
        concurrency_group="web_http",
        idempotent=True,
    ))

    ensure_tool(ToolSpec(
        name="web_fetch",
        description="抓取并提取指定 http/https 网页的标题、链接、发布时间和正文摘录，用于核实 web_search 找到的来源；x.com/twitter.com status 链接应优先用 fetch_x_post。",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string", "minLength": 8, "maxLength": 2048, "description": "要抓取的 http/https URL"},
                "max_chars": {"type": "integer", "minimum": 300, "maximum": 4000, "description": "正文摘录最大长度，300-4000"},
            },
            "required": ["url"],
        },
        handler=handlers.web_fetch,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
        parallel_safe=True,
        concurrency_group="web_http",
        idempotent=True,
    ))

    ensure_tool(ToolSpec(
        name="verify_recent_claim",
        description="核实近期/最新/2024 年以后事实陈述。会搜索来源并优先抓取官方或一手来源；用于降低 AI 幻觉，回答时应引用返回的来源。",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "claim": {"type": "string", "minLength": 1, "maxLength": 1000, "description": "需要核实的说法或问题"},
                "preferred_sources": {"type": "string", "maxLength": 300, "description": "可选，偏好的官方/权威来源关键词，如 Arsenal official"},
                "max_results": {"type": "integer", "minimum": 2, "maximum": 8, "description": "搜索条数，2-8"},
            },
            "required": ["claim"],
        },
        handler=handlers.verify_recent_claim,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
        parallel_safe=True,
        concurrency_group="web_http",
        idempotent=True,
    ))
