import json
from typing import List

from ..context import ToolContext
from .contextual_tools import detect_memory_preference_args
from .contextual_tools import detect_ui_preference_args
from .models import Intent, PlannedToolCall, RouteDecision


LOCAL_MEMORY_MARKERS = ("之前", "刚才", "上次", "昨天", "你之前", "你刚才")
CURRENT_FACT_MARKERS = ("最新", "最近", "现在", "结果", "赛果", "比分", "伤病", "转会")
FOOTBALL_MARKERS = ("阿森纳", "arsenal", "比赛", "英超", "欧冠", "球队")
DOCUMENT_MARKERS = ("pdf", "PDF", "文档", "文件", "附件", "报告")
DOCUMENT_INTENT_MARKERS = (
    "文档",
    "pdf",
    "docx",
    "文件",
    "读取",
    "总结",
    "分析",
    "看看",
    "提取",
    "讲了什么",
)
DETECTED_URL_DOCUMENT_INTENT_MARKERS = (
    "文档",
    "pdf",
    "docx",
    "文件",
    "读取",
    "附件",
    "报告",
)
LINK_INTENT_MARKERS = (
    "链接",
    "网址",
    "网页",
    "http://",
    "https://",
    "总结",
    "分析",
    "看看",
    "快照",
    "截取",
    "讲了什么",
)
MATH_INTENT_MARKERS = ("求解", "计算", "解方程", "证明")

TRACE_MARKERS = (
    "trace",
    "agent trace",
    "tool trace",
    "调用了什么工具",
    "调用什么工具",
    "工具调用",
    "为什么这样回复",
    "为什么这么回",
    "可视化调试",
)

CURRENT_FACT_ASCII_MARKERS = (
    "latest",
    "recent",
    "news",
    "transfer",
    "injury",
    "fixture",
    "score",
    "result",
    "official",
)
FOOTBALL_ASCII_MARKERS = (
    "arsenal",
    "football",
    "premier league",
    "champions league",
    "club",
    "team",
    "match",
    "game",
)

RECENT_MATCH_MARKERS = (
    "recent match",
    "latest match",
    "last match",
    "previous match",
    "最近一场",
    "最近的一场",
    "上一场",
    "上场",
    "近期",
)
MATCH_CONTEXT_MARKERS = (
    "match",
    "game",
    "fixture",
    "比赛",
    "对阵",
    "交手",
    "踢",
)
TEAM_PAIR_MARKERS = (
    " vs ",
    " v ",
    " versus ",
    " against ",
    "和",
    "与",
    "跟",
    "对",
    "对阵",
)
LOCAL_CURRENT_VERIFICATION_MARKERS = (
    "现在查",
    "查最新",
    "最新",
    "最近",
    "新闻",
    "消息",
    "动态",
    "官宣",
    "官方",
    "来源",
    "核实",
    "查证",
    "转会",
    "伤病",
    "赛程",
    "赛果",
    "结果",
    "search",
    "verify",
    "source",
    "news",
    "latest",
    "recent",
)


def _latest_user_content(messages) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def _append_tool_once(tools: List[PlannedToolCall], call: PlannedToolCall) -> None:
    for item in tools:
        if item.name == call.name and json.dumps(item.arguments, ensure_ascii=False, sort_keys=True) == json.dumps(call.arguments, ensure_ascii=False, sort_keys=True):
            return
    tools.append(call)


def _has_any(text: str, markers) -> bool:
    lowered = text.lower()
    return any(str(marker).lower() in lowered for marker in markers)


def _looks_like_math(text: str) -> bool:
    compact = text.replace(" ", "")
    if _has_any(text, MATH_INTENT_MARKERS) and any(token in compact for token in ("=", "^", "+", "*", "/", "x", "X")):
        return True
    return False


def _looks_like_recent_public_match_question(text: str) -> bool:
    lowered = str(text or "").lower()
    return (
        any(marker in lowered for marker in RECENT_MATCH_MARKERS)
        and any(marker in lowered for marker in MATCH_CONTEXT_MARKERS)
        and any(marker in lowered for marker in TEAM_PAIR_MARKERS)
    )


def _public_current_fact_query(text: str) -> str:
    lowered = text.lower()
    query = text
    if "阿森纳" in text and "arsenal" not in lowered:
        query = "{0} Arsenal".format(query)
    if "转会" in text and "transfer" not in lowered:
        query = "{0} transfer news".format(query)
    return query


def _allows_public_fact_with_local_memory(text: str) -> bool:
    if not _has_any(text, LOCAL_MEMORY_MARKERS):
        return True
    return _has_any(text, LOCAL_CURRENT_VERIFICATION_MARKERS)


def _document_tool_args(text: str, extra: dict):
    if extra.get("document_urls") and (not text or _has_any(text, DOCUMENT_INTENT_MARKERS)):
        return {}
    if extra.get("detected_urls") and _has_any(text, DETECTED_URL_DOCUMENT_INTENT_MARKERS):
        urls = list(extra.get("detected_urls") or [])
        if urls:
            return {"url": str(urls[0])}
    return None


def route_message(messages, ctx: ToolContext = None) -> RouteDecision:
    text = _latest_user_content(messages).strip()
    decision = RouteDecision()
    extra = getattr(ctx, "extra", {}) or {} if ctx is not None else {}
    if not text and not extra.get("document_urls") and not extra.get("detected_urls"):
        return decision

    ui_args = detect_ui_preference_args(messages)
    if ui_args:
        decision.intents.append(Intent("ui_preference", 0.9, "explicit UI preference request"))
        decision.constraints["execute_single_required_tool"] = True
        decision.constraints["direct_tool_response"] = True
        _append_tool_once(decision.required_tools, PlannedToolCall(
            name="update_ui_preference",
            arguments=ui_args,
            reason="update controlled UI preference",
            forced=True,
        ))

    memory_args = detect_memory_preference_args(messages)
    if memory_args and not ui_args:
        decision.intents.append(Intent("memory_preference", 0.9, "explicit future/preference marker"))
        _append_tool_once(decision.required_tools, PlannedToolCall(
            name="remember_user_preference",
            arguments=memory_args,
            reason="remember explicit user preference",
            forced=True,
        ))

    if _has_any(text, TRACE_MARKERS):
        decision.intents.append(Intent("agent_trace", 0.95, "explicit trace/debug request"))
        decision.constraints["direct_trace_response"] = True
        _append_tool_once(decision.required_tools, PlannedToolCall(
            name="show_agent_trace",
            arguments={},
            reason="show sanitized agent trace",
            forced=True,
        ))

    document_args = _document_tool_args(text, extra)
    if document_args is not None:
        decision.intents.append(Intent("document_read", 0.95, "document context present"))
        _append_tool_once(decision.required_tools, PlannedToolCall(
            name="read_document",
            arguments=document_args,
            reason="document context present",
            forced=True,
        ))

    has_document_read = any(intent.name == "document_read" for intent in decision.intents)
    if not has_document_read and extra.get("detected_urls") and (not text or _has_any(text, LINK_INTENT_MARKERS)):
        decision.intents.append(Intent("link_analysis", 0.9, "link context present with analysis intent"))
        _append_tool_once(decision.required_tools, PlannedToolCall(
            name="analyze_links",
            arguments={},
            reason="analyze detected link context",
            forced=True,
        ))

    if _has_any(text, LOCAL_MEMORY_MARKERS):
        decision.intents.append(Intent("group_memory", 0.75, "local memory reference"))
        _append_tool_once(decision.required_tools, PlannedToolCall(
            name="query_group_memory",
            arguments={"query": text},
            reason="retrieve referenced local memory",
            forced=True,
        ))

    is_recent_match_question = _looks_like_recent_public_match_question(text)
    if (
        _allows_public_fact_with_local_memory(text)
        and
        (
            _has_any(text, CURRENT_FACT_MARKERS)
            or _has_any(text, CURRENT_FACT_ASCII_MARKERS)
            or is_recent_match_question
        )
        and (
            _has_any(text, FOOTBALL_MARKERS)
            or _has_any(text, FOOTBALL_ASCII_MARKERS)
            or is_recent_match_question
        )
    ):
        decision.intents.append(Intent("public_current_fact", 0.85, "current football fact"))
        _append_tool_once(decision.required_tools, PlannedToolCall(
            name="grok_search",
            arguments={"query": _public_current_fact_query(text), "freshness": "recent", "max_results": 5},
            reason="verify current public football fact",
            forced=True,
        ))

    if _looks_like_math(text):
        decision.intents.append(Intent("math", 0.95, "explicit math notation and solve intent"))
        _append_tool_once(decision.required_tools, PlannedToolCall(
            name="solve_math_question",
            arguments={"question": text},
            reason="explicit math solve intent",
            forced=True,
        ))

    return decision
