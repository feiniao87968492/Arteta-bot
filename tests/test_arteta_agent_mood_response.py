import asyncio
import json
import pytest

from plugins.arteta_agent.context import ToolContext
from plugins.arteta_agent.response.mood import maybe_send_mood_emoji
from plugins.arteta_agent.response import mood as mood_module
from plugins.arteta_agent.runtime.state import AgentState, FinalizedResponse
from plugins.arteta_agent.emoji.history import reset_emoji_history_for_tests


def make_runtime_state(messages, trace=None, policy_disabled_tools=None, group_id="group-1"):
    return AgentState(
        messages=list(messages),
        ctx=ToolContext(
            bot=None,
            event=None,
            user_id="user-1",
            group_id=group_id,
            nickname="tester",
            raw_message="",
            is_group=True,
            is_admin=False,
        ),
        policy_disabled_tools=set(policy_disabled_tools or set()),
        trace=trace,
    )


@pytest.fixture(autouse=True)
def reset_mood_emoji_state(monkeypatch):
    reset_emoji_history_for_tests()
    monkeypatch.setattr(mood_module, "_emoji_assets_available", lambda: True)


def test_mood_finalizer_sends_reaction_emoji_when_reply_skips_tool():
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
    args = json.loads(calls[0][0]["function"]["arguments"])
    assert args["reaction"] == "frustrated"
    assert "mood" not in args
    assert calls[0][1] == "group-1"


def test_mood_finalizer_does_not_send_positive_neutral_for_plain_reply():
    calls = []
    state = make_runtime_state([
        {"role": "user", "content": "塔子在吗"},
    ], group_id="plain-group")

    async def execute_tool_call(tool_call, ctx):
        calls.append(tool_call)
        return "emoji sent"

    result = asyncio.run(maybe_send_mood_emoji(
        "在。",
        state,
        get_tool=lambda name: object() if name == "send_mood_emoji" else None,
        execute_tool_call=execute_tool_call,
        emoji_enabled=lambda group_id: True,
    ))

    assert result == FinalizedResponse("在。", 0)
    assert calls == []


def test_mood_finalizer_sends_positive_emoji_for_explicit_request():
    calls = []
    state = make_runtime_state([
        {"role": "user", "content": "发个开心表情"},
    ], group_id="explicit-emoji-group")

    async def execute_tool_call(tool_call, ctx):
        calls.append(tool_call)
        return "emoji sent"

    result = asyncio.run(maybe_send_mood_emoji(
        "今天气氛不错。",
        state,
        get_tool=lambda name: object() if name == "send_mood_emoji" else None,
        execute_tool_call=execute_tool_call,
        emoji_enabled=lambda group_id: True,
    ))

    assert result == FinalizedResponse("今天气氛不错。", 1)
    assert calls[0]["function"]["name"] == "send_mood_emoji"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["reaction"] == "approval"
    assert "mood" not in args


def test_mood_finalizer_cooldown_skips_auto_emoji_but_not_explicit_request():
    reset_emoji_history_for_tests()
    calls = []
    group_id = "cooldown-group"

    async def execute_tool_call(tool_call, ctx):
        calls.append(tool_call)
        return "emoji sent"

    for index in range(2):
        state = make_runtime_state([
            {"role": "user", "content": "赢了！太爽了！"},
        ], group_id=group_id)
        result = asyncio.run(maybe_send_mood_emoji(
            "这就是我们要的能量。",
            state,
            get_tool=lambda name: object(),
            execute_tool_call=execute_tool_call,
            emoji_enabled=lambda group_id: True,
        ))
        assert result.tool_call_count == 1, index

    state = make_runtime_state([
        {"role": "user", "content": "赢了！太爽了！"},
    ], group_id=group_id)
    result = asyncio.run(maybe_send_mood_emoji(
        "继续保持。",
        state,
        get_tool=lambda name: object(),
        execute_tool_call=execute_tool_call,
        emoji_enabled=lambda group_id: True,
    ))
    assert result == FinalizedResponse("继续保持。", 0)

    explicit_state = make_runtime_state([
        {"role": "user", "content": "赢了！发个表情庆祝一下"},
    ], group_id=group_id)
    explicit_result = asyncio.run(maybe_send_mood_emoji(
        "可以，庆祝一下。",
        explicit_state,
        get_tool=lambda name: object(),
        execute_tool_call=execute_tool_call,
        emoji_enabled=lambda group_id: True,
    ))
    assert explicit_result == FinalizedResponse("可以，庆祝一下。", 1)


def test_mood_finalizer_emoji_failure_does_not_affect_main_reply():
    state = make_runtime_state([
        {"role": "user", "content": "发个开心表情"},
    ], group_id="emoji-failure-group")

    async def execute_tool_call(tool_call, ctx):
        raise RuntimeError("emoji failed")

    result = asyncio.run(maybe_send_mood_emoji(
        "可以。",
        state,
        get_tool=lambda name: object(),
        execute_tool_call=execute_tool_call,
        emoji_enabled=lambda group_id: True,
    ))

    assert result == FinalizedResponse("可以。", 0)


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


def test_planner_no_longer_keeps_unreachable_inline_mood_loop():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "def _should_allow_forced_mood_emoji" not in source
    assert "def detect_forced_mood_emoji_args" not in source
    assert "tool_call_count = 0" not in source
    assert "forced-send-mood-emoji-1" not in source


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
