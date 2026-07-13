import json
from typing import Awaitable, Callable

from ..context import ToolContext
from ..emoji.catalog import load_emoji_catalog
from ..emoji.classifier import classify_emoji_reaction
from ..emoji.gate import (
    decide_emoji_gate,
    user_explicitly_requested_emoji_text,
)
from ..emoji.history import record_emoji_send
from ..emoji.models import EmojiGateContext, EmojiReactionDecision
from ..runtime.state import AgentState, FinalizedResponse
from .style import detect_response_style_profile


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
    user_text = latest_user_content(messages)
    profile = detect_response_style_profile(user_text)
    gate = decide_emoji_gate(EmojiGateContext(
        user_text=user_text,
        assistant_text="placeholder",
        group_id="",
        profile=profile,
        trace=trace,
        has_assets=True,
    ))
    return gate.should_send


def user_explicitly_requested_emoji(messages) -> bool:
    return user_explicitly_requested_emoji_text(latest_user_content(messages))


def _default_explicit_reaction() -> EmojiReactionDecision:
    return EmojiReactionDecision(
        reaction="approval",
        intensity="medium",
        stance="shared_with_user",
        topic="general",
        confidence=0.85,
        reason_codes=["explicit_request_default"],
    )


def _reaction_args(decision: EmojiReactionDecision) -> dict:
    reason_code = ""
    if decision.reason_codes:
        reason_code = str(decision.reason_codes[0])
    return {
        "reaction": decision.reaction,
        "intensity": decision.intensity,
        "stance": decision.stance,
        "topic": decision.topic,
        "emoji_name": "",
        "reason_code": reason_code,
    }


def _emoji_assets_available() -> bool:
    try:
        from ..tools.qq_actions import EMOJI_DIR

        return bool(load_emoji_catalog(EMOJI_DIR))
    except Exception:
        return False


def _build_gate_context(
    messages,
    assistant_content: str,
    group_id: str = "",
    trace=None,
    emoji_enabled: bool = True,
    tool_disabled: bool = False,
    has_assets: bool = True,
    current_information_required: bool = False,
    route_hint: str = "",
) -> EmojiGateContext:
    user_text = latest_user_content(messages)
    profile = detect_response_style_profile(
        user_text,
        route_hint=route_hint,
        current_information_required=current_information_required,
    )
    return EmojiGateContext(
        user_text=user_text,
        assistant_text=assistant_content,
        group_id=str(group_id or ""),
        profile=profile,
        trace=trace,
        route_hint=route_hint,
        emoji_enabled=emoji_enabled,
        tool_disabled=tool_disabled,
        has_assets=has_assets,
        current_information_required=current_information_required,
    )


def detect_forced_mood_emoji_args(messages, assistant_content: str = "") -> dict:
    context = _build_gate_context(
        messages,
        assistant_content,
        has_assets=True,
    )
    gate = decide_emoji_gate(context)
    if not gate.should_send:
        return {}

    decision = classify_emoji_reaction(
        user_text=context.user_text,
        assistant_text=assistant_content,
        response_mode=str(getattr(context.profile, "mode", "") or ""),
        route_hint=context.route_hint,
    )
    if gate.explicit_request and decision.reaction == "none":
        decision = _default_explicit_reaction()
    if decision.reaction == "none":
        return {}
    if not gate.explicit_request and decision.confidence < 0.75:
        return {}
    return _reaction_args(decision)


async def maybe_send_mood_emoji(
    content: str,
    runtime_state: AgentState,
    get_tool: Callable[[str], object],
    execute_tool_call: Callable[[dict, ToolContext], Awaitable[str]],
    emoji_enabled: Callable[[str], bool],
) -> FinalizedResponse:
    group_id = runtime_state.ctx.group_id
    if (
        not get_tool("send_mood_emoji")
        or state_has_tool_call(runtime_state.messages, "send_mood_emoji")
        or trace_has_tool(runtime_state.trace, "send_mood_emoji")
    ):
        return FinalizedResponse(content, 0)

    tool_disabled = "send_mood_emoji" in set(runtime_state.policy_disabled_tools or set())
    context = _build_gate_context(
        runtime_state.messages,
        content,
        group_id=group_id,
        trace=runtime_state.trace,
        emoji_enabled=emoji_enabled(group_id),
        tool_disabled=tool_disabled,
        has_assets=_emoji_assets_available(),
        current_information_required=runtime_state.requires_current_information,
        route_hint=runtime_state.freshness_mode,
    )
    gate = decide_emoji_gate(context)
    if not gate.should_send:
        return FinalizedResponse(content, 0)

    decision = classify_emoji_reaction(
        user_text=context.user_text,
        assistant_text=content,
        response_mode=str(getattr(context.profile, "mode", "") or ""),
        route_hint=context.route_hint,
    )
    if gate.explicit_request and decision.reaction == "none":
        decision = _default_explicit_reaction()
    if decision.reaction == "none":
        return FinalizedResponse(content, 0)
    if not gate.explicit_request and decision.confidence < 0.75:
        return FinalizedResponse(content, 0)

    emoji_call = {
        "id": "forced-send-mood-emoji-1",
        "type": "function",
        "function": {
            "name": "send_mood_emoji",
            "arguments": json.dumps(_reaction_args(decision), ensure_ascii=False),
        },
    }
    before_pending_count = len((runtime_state.ctx.extra or {}).get("pending_mood_emojis") or [])
    try:
        await execute_tool_call(emoji_call, runtime_state.ctx)
    except Exception:
        return FinalizedResponse(content, 0)

    pending = list((runtime_state.ctx.extra or {}).get("pending_mood_emojis") or [])
    asset_name = ""
    if len(pending) > before_pending_count:
        asset_name = str((pending[-1] or {}).get("name") or "")
    record_emoji_send(
        group_id,
        asset_name,
        decision.reaction,
        automatic=not gate.explicit_request,
    )
    return FinalizedResponse(content, 1)
