from typing import List

from .history import automatic_cooldown_active
from .models import EmojiGateContext, EmojiGateDecision


EXPLICIT_EMOJI_REQUEST_MARKERS = (
    "发表情",
    "发个表情",
    "来个表情",
    "用表情回应",
    "开心表情",
    "发个开心的",
    "庆祝一下",
    "发图",
)

EMOJI_BAN_MARKERS = (
    "不要发表情",
    "别发表情",
    "不用表情",
    "不要发图",
    "别发图",
)

TECHNICAL_MARKERS = (
    "数学",
    "物理",
    "算法",
    "代码",
    "公式",
    "证明",
    "这题怎么解",
)

CURRENT_NEWS_MARKERS = (
    "最新",
    "核实",
    "来源",
    "靠谱吗",
    "转会",
    "伤病",
    "伤情",
    "积分榜",
)

OPERATIONAL_TRACE_TOOLS = (
    "show_behavior_policy",
    "update_behavior_policy",
    "show_agent_trace",
)

HIGH_SIGNAL_MARKERS = (
    "绝杀",
    "赢了",
    "起飞",
    "太爽",
    "笑死",
    "梗图",
    "节目效果",
    "离谱",
    "难绷",
    "红温",
    "气死",
    "被绝平",
    "淘汰",
    "重伤",
    "官宣",
)


def _compact(text: str) -> str:
    return str(text or "").replace(" ", "").lower()


def user_explicitly_requested_emoji_text(text: str) -> bool:
    compact = _compact(text)
    return any(marker in compact for marker in EXPLICIT_EMOJI_REQUEST_MARKERS)


def user_explicitly_disabled_emoji_text(text: str) -> bool:
    compact = _compact(text)
    return any(marker in compact for marker in EMOJI_BAN_MARKERS)


def _trace_has_tool(trace, names) -> bool:
    if not trace:
        return False
    wanted = set(names or [])
    return any((item or {}).get("name") in wanted for item in trace.get("tools") or [])


def _trace_has_send_emoji(trace) -> bool:
    return _trace_has_tool(trace, {"send_mood_emoji"})


def _has_any(text: str, markers) -> bool:
    compact = _compact(text)
    return any(marker in compact for marker in markers)


def _deny(reason: str, explicit_request: bool = False) -> EmojiGateDecision:
    return EmojiGateDecision(False, 0.0, [reason], explicit_request=explicit_request)


def decide_emoji_gate(context: EmojiGateContext) -> EmojiGateDecision:
    user_text = str(context.user_text or "")
    assistant_text = str(context.assistant_text or "")
    explicit_request = user_explicitly_requested_emoji_text(user_text)

    if user_explicitly_disabled_emoji_text(user_text):
        return _deny("user_disabled_emoji", explicit_request=False)
    if not assistant_text.strip() or assistant_text.strip() == "[NO_REPLY]":
        return _deny("no_reply", explicit_request=explicit_request)
    if assistant_text.lstrip().startswith("[PermissionRequired]"):
        return _deny("permission_required", explicit_request=explicit_request)
    if not context.has_assets:
        return _deny("no_assets", explicit_request=explicit_request)
    if not context.emoji_enabled:
        return _deny("emoji_policy_disabled", explicit_request=explicit_request)
    if context.tool_disabled:
        return _deny("emoji_tool_disabled", explicit_request=explicit_request)
    if _trace_has_send_emoji(context.trace):
        return _deny("emoji_already_called", explicit_request=explicit_request)

    if explicit_request:
        return EmojiGateDecision(True, 1.0, ["explicit_request"], explicit_request=True)

    if _trace_has_tool(context.trace, OPERATIONAL_TRACE_TOOLS):
        return _deny("operational_trace")
    if _has_any(user_text, ("行为策略", "当前策略", "策略", "trace", "调度", "调用了什么工具")):
        return _deny("operational_request")
    if context.current_information_required or _has_any(user_text, CURRENT_NEWS_MARKERS):
        return _deny("current_news_or_fact_check")
    if _has_any(user_text, TECHNICAL_MARKERS):
        return _deny("technical_or_math")

    profile = context.profile
    profile_mode = str(getattr(profile, "mode", "") or "")
    profile_allows = bool(getattr(profile, "allow_mood_emoji", False))
    reason_codes = []  # type: List[str]
    if _has_any(user_text + "\n" + assistant_text, HIGH_SIGNAL_MARKERS):
        reason_codes.append("high_social_signal")
    if profile_mode == "meme":
        reason_codes.append("meme_mode")

    if not reason_codes:
        return _deny("low_signal")
    if not profile_allows and profile_mode != "meme":
        return _deny("style_disallows_auto")
    if automatic_cooldown_active(context.group_id):
        return _deny("auto_cooldown")

    confidence = 0.85 if "high_social_signal" in reason_codes else 0.75
    return EmojiGateDecision(True, confidence, reason_codes, explicit_request=False)
