import asyncio

from plugins.arteta_agent.context import ToolContext
from plugins.arteta_agent.response.mood import maybe_send_mood_emoji
from plugins.arteta_agent.runtime.state import AgentState, FinalizedResponse


def make_runtime_state(messages, trace=None, policy_disabled_tools=None):
    return AgentState(
        messages=list(messages),
        ctx=ToolContext(
            bot=None,
            event=None,
            user_id="user-1",
            group_id="group-1",
            nickname="tester",
            raw_message="",
            is_group=True,
            is_admin=False,
        ),
        policy_disabled_tools=set(policy_disabled_tools or set()),
        trace=trace,
    )


def test_mood_finalizer_sends_negative_emoji_when_reply_skips_tool():
    calls = []
    state = make_runtime_state([
        {"role": "user", "content": "塔子你是sb吗"},
    ])

    async def execute_tool_call(tool_call, ctx):
        calls.append((tool_call, ctx.group_id))
        return "emoji sent"

    result = asyncio.run(maybe_send_mood_emoji(
        "保持尊重。",
        state,
        get_tool=lambda name: object() if name == "send_mood_emoji" else None,
        execute_tool_call=execute_tool_call,
        emoji_enabled=lambda group_id: True,
    ))

    assert result == FinalizedResponse("保持尊重。", 1)
    assert calls[0][0]["function"]["name"] == "send_mood_emoji"
    assert '"mood": "negative"' in calls[0][0]["function"]["arguments"]
    assert calls[0][1] == "group-1"


def test_mood_finalizer_skips_operational_trace_or_policy_turns():
    calls = []
    state = make_runtime_state(
        [{"role": "user", "content": "看看当前策略"}],
        trace={"tools": [{"name": "show_behavior_policy"}]},
    )

    async def execute_tool_call(tool_call, ctx):
        calls.append(tool_call)
        return "emoji sent"

    result = asyncio.run(maybe_send_mood_emoji(
        "当前没有策略。",
        state,
        get_tool=lambda name: object(),
        execute_tool_call=execute_tool_call,
        emoji_enabled=lambda group_id: True,
    ))

    assert result == FinalizedResponse("当前没有策略。", 0)
    assert calls == []


def test_mood_finalizer_respects_disabled_or_existing_emoji_call():
    calls = []
    state = make_runtime_state(
        [
            {"role": "user", "content": "塔子在吗"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-existing",
                    "function": {"name": "send_mood_emoji", "arguments": "{}"},
                }],
            },
        ],
        policy_disabled_tools={"send_mood_emoji"},
    )

    async def execute_tool_call(tool_call, ctx):
        calls.append(tool_call)
        return "emoji sent"

    result = asyncio.run(maybe_send_mood_emoji(
        "在。",
        state,
        get_tool=lambda name: object(),
        execute_tool_call=execute_tool_call,
        emoji_enabled=lambda group_id: True,
    ))

    assert result == FinalizedResponse("在。", 0)
    assert calls == []
