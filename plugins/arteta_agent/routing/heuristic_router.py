import json
from typing import List

from ..context import ToolContext
from .models import Intent, PlannedToolCall, RouteDecision


LOCAL_MEMORY_MARKERS = ("之前", "刚才", "上次", "昨天", "你之前", "你刚才")
CURRENT_FACT_MARKERS = ("最新", "最近", "现在", "结果", "赛果", "比分", "伤病", "转会")
FOOTBALL_MARKERS = ("阿森纳", "arsenal", "比赛", "英超", "欧冠", "球队")
MEMORY_PREFERENCE_MARKERS = ("记住", "以后", "下次")
DOCUMENT_MARKERS = ("pdf", "PDF", "文档", "文件", "附件", "报告")
MATH_INTENT_MARKERS = ("求解", "计算", "解方程", "证明")


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


def route_message(messages, ctx: ToolContext = None) -> RouteDecision:
    text = _latest_user_content(messages).strip()
    decision = RouteDecision()
    if not text:
        return decision

    extra = getattr(ctx, "extra", {}) or {} if ctx is not None else {}

    if _has_any(text, MEMORY_PREFERENCE_MARKERS):
        decision.intents.append(Intent("memory_preference", 0.9, "explicit future/preference marker"))
        _append_tool_once(decision.required_tools, PlannedToolCall(
            name="remember_user_preference",
            arguments={"memory": text},
            reason="remember explicit user preference",
            forced=True,
        ))

    if extra.get("document_urls") or _has_any(text, DOCUMENT_MARKERS):
        if extra.get("document_urls"):
            decision.intents.append(Intent("document_read", 0.95, "document context present"))
            _append_tool_once(decision.required_tools, PlannedToolCall(
                name="read_document",
                arguments={},
                reason="document context present",
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

    if _has_any(text, CURRENT_FACT_MARKERS) and _has_any(text, FOOTBALL_MARKERS):
        decision.intents.append(Intent("public_current_fact", 0.85, "current football fact"))
        _append_tool_once(decision.required_tools, PlannedToolCall(
            name="grok_search",
            arguments={"query": text, "freshness": "recent", "max_results": 5},
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

