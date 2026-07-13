import json
from typing import Callable, Awaitable

from ..context import ToolContext
from ..runtime.state import AgentState, FinalizedResponse


_MOOD_EMOJI_HISTORY = {}
_MOOD_EMOJI_COOLDOWN_WINDOW = 3


def latest_user_content(messages) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def state_has_tool_call(messages, tool_name: str) -> bool:
    for msg in messages or []:
        for tool_call in msg.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            if function.get("name") == tool_name:
                return True
    return False


def trace_has_tool(trace, tool_name: str) -> bool:
    if not trace:
        return False
    return any(item.get("name") == tool_name for item in trace.get("tools") or [])


def trace_has_any_tool(trace, tool_names) -> bool:
    if not trace:
        return False
    names = set(tool_names or [])
    return any(item.get("name") in names for item in trace.get("tools") or [])


def should_allow_forced_mood_emoji(messages, trace) -> bool:
    # Policy/trace/debug answers are operational diagnostics, not emotional
    # chat replies. Auto-emoji here makes the agent appear to ignore policy.
    if trace_has_any_tool(trace, {
        "show_behavior_policy",
        "update_behavior_policy",
        "show_agent_trace",
    }):
        return False
    text = latest_user_content(messages)
    if any(marker in text for marker in ("行为策略", "当前策略", "策略", "trace", "调度", "调用了什么工具")):
        return False
    if any(marker in text for marker in ("最新", "官宣", "伤情", "伤病", "转会", "积分榜", "核实", "来源", "报错", "权限")):
        return False
    return True


def user_explicitly_requested_emoji(messages) -> bool:
    text = latest_user_content(messages).replace(" ", "").lower()
    return any(marker in text for marker in (
        "发表情",
        "发个表情",
        "来个表情",
        "开心表情",
        "庆祝一下",
        "发图",
    ))


def _recent_auto_emoji_saturated(group_id: str) -> bool:
    history = list(_MOOD_EMOJI_HISTORY.get(str(group_id or ""), []))
    if len(history) < _MOOD_EMOJI_COOLDOWN_WINDOW:
        return False
    return all(history[-_MOOD_EMOJI_COOLDOWN_WINDOW:])


def _record_mood_emoji_result(group_id: str, sent: bool) -> None:
    key = str(group_id or "")
    history = list(_MOOD_EMOJI_HISTORY.get(key, []))
    history.append(bool(sent))
    _MOOD_EMOJI_HISTORY[key] = history[-_MOOD_EMOJI_COOLDOWN_WINDOW:]


def detect_forced_mood_emoji_args(messages, assistant_content: str = "") -> dict:
    user_text = latest_user_content(messages).strip()
    if not user_text:
        return {}
    content = (assistant_content or "").strip()
    if not content or content == "[NO_REPLY]" or content.startswith("[PermissionRequired]"):
        return {}
    compact = (user_text + "\n" + (assistant_content or "")).replace(" ", "").lower()
    if any(marker in compact for marker in ("不要发表情", "别发表情", "不用表情", "不要发图", "别发图")):
        return {}
    explicit_emoji = user_explicitly_requested_emoji(messages)

    negative_markers = (
        "sb",
        "傻逼",
        "傻b",
        "傻叉",
        "你是傻",
        "废物",
        "垃圾",
        "滚",
        "烂",
        "stupid",
        "idiot",
        "fuck",
        "痛苦",
        "难过",
        "哭",
        "崩溃",
        "遗憾",
        "输麻",
        "淘汰了",
        "被淘汰",
    )

    if any(marker in compact for marker in negative_markers):
        return {
            "mood": "negative",
            "emoji_name": "",
            "reason": "检测到消极情绪，补发表情。",
        }
    positive_markers = (
        "赢了",
        "庆祝",
        "太爽",
        "爽了",
        "开心",
        "笑死",
        "起飞",
        "牛逼",
    )
    if explicit_emoji or any(marker in compact for marker in positive_markers):
        return {
            "mood": "positive_neutral",
            "emoji_name": "",
            "reason": "检测到显式请求或强烈积极情绪，补发表情。",
        }
    return {}


async def maybe_send_mood_emoji(
    content: str,
    runtime_state: AgentState,
    get_tool: Callable[[str], object],
    execute_tool_call: Callable[[dict, ToolContext], Awaitable[str]],
    emoji_enabled: Callable[[str], bool],
) -> FinalizedResponse:
    forced_emoji_args = detect_forced_mood_emoji_args(runtime_state.messages, content)
    group_id = runtime_state.ctx.group_id
    explicit_emoji = user_explicitly_requested_emoji(runtime_state.messages)
    if forced_emoji_args and not explicit_emoji and _recent_auto_emoji_saturated(group_id):
        _record_mood_emoji_result(group_id, False)
        return FinalizedResponse(content, 0)
    if (
        forced_emoji_args
        and get_tool("send_mood_emoji")
        and should_allow_forced_mood_emoji(runtime_state.messages, runtime_state.trace)
        and emoji_enabled(runtime_state.ctx.group_id)
        and "send_mood_emoji" not in set(runtime_state.policy_disabled_tools or set())
        and not state_has_tool_call(runtime_state.messages, "send_mood_emoji")
        and not trace_has_tool(runtime_state.trace, "send_mood_emoji")
    ):
        emoji_call = {
            "id": "forced-send-mood-emoji-1",
            "type": "function",
            "function": {
                "name": "send_mood_emoji",
                "arguments": json.dumps(forced_emoji_args, ensure_ascii=False),
            },
        }
        try:
            await execute_tool_call(emoji_call, runtime_state.ctx)
        except Exception:
            _record_mood_emoji_result(group_id, False)
            return FinalizedResponse(content, 0)
        _record_mood_emoji_result(group_id, True)
        return FinalizedResponse(content, 1)
    _record_mood_emoji_result(group_id, False)
    return FinalizedResponse(content, 0)
