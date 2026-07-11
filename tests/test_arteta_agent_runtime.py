import asyncio
import json

from plugins.arteta_agent.context import ToolContext
from plugins.arteta_agent.result import TOOL_STATUS_OK, TOOL_STATUS_PERMISSION_REQUIRED, ToolResult


def make_context(**kwargs):
    data = {
        "bot": None,
        "event": None,
        "user_id": "user-1",
        "group_id": "group-1",
        "nickname": "player",
        "raw_message": "please read and verify",
        "is_group": True,
        "is_admin": False,
        "extra": {},
    }
    data.update(kwargs)
    return ToolContext(**data)


def test_loop_guard_signature_normalizes_argument_key_order():
    from plugins.arteta_agent.runtime.loop_guard import tool_call_signature

    first = {
        "id": "call-1",
        "function": {
            "name": "sample_read",
            "arguments": json.dumps({"b": 2, "a": 1}),
        },
    }
    second = {
        "id": "call-2",
        "function": {
            "name": "sample_read",
            "arguments": json.dumps({"a": 1, "b": 2}),
        },
    }

    assert tool_call_signature(first) == tool_call_signature(second)


def test_runtime_runner_executes_initial_and_model_tool_calls_through_same_executor():
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    executed = []
    model_calls = []

    initial_tool_call = {
        "id": "forced-read-document-1",
        "type": "function",
        "function": {
            "name": "read_document",
            "arguments": json.dumps({"document_index": 0}),
        },
    }

    async def fake_execute(tool_call, ctx):
        name = tool_call["function"]["name"]
        executed.append(name)
        content = {
            "read_document": "document says this needs web verification",
            "web_search": "verified web result",
        }[name]
        return ToolResult(
            name=name,
            permission="safe_read",
            status=TOOL_STATUS_OK,
            content=content,
        )

    async def fake_model(messages, runtime_state):
        model_calls.append(list(messages))
        if len(model_calls) == 1:
            assert messages[-1]["role"] == "tool"
            assert messages[-1]["tool_call_id"] == "forced-read-document-1"
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-web-1",
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "arguments": json.dumps({"query": "source check"}),
                    },
                }],
            }
        assert messages[-1]["role"] == "tool"
        assert messages[-1]["tool_call_id"] == "call-web-1"
        return {"role": "assistant", "content": "final answer"}

    state = AgentState(
        messages=[{"role": "user", "content": "read this PDF and verify it"}],
        ctx=make_context(),
        allowed_permissions={"safe_read"},
        disabled_tools=set(),
        policy_disabled_tools=set(),
        trace=None,
    )
    runner = AgentRuntimeRunner(
        model_call=fake_model,
        tool_executor=fake_execute,
    )

    result = asyncio.run(runner.run(
        state,
        AgentRunConfig(max_rounds=3),
        initial_tool_calls=[initial_tool_call],
    ))

    assert result.content == "final answer"
    assert result.stop_reason == "final"
    assert executed == ["read_document", "web_search"]
    assert [message["role"] for message in state.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]


def test_runtime_runner_stops_immediately_when_initial_tool_requires_confirmation():
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    async def fake_execute(tool_call, ctx):
        return ToolResult(
            name="send_group_message",
            permission="confirm_write",
            status=TOOL_STATUS_PERMISSION_REQUIRED,
            content="[PermissionRequired] confirm PendingAction: action-1",
            pending_action_id="action-1",
        )

    async def fake_model(messages, runtime_state):
        raise AssertionError("permission-required initial tool must stop before model call")

    state = AgentState(
        messages=[{"role": "user", "content": "send this"}],
        ctx=make_context(),
        allowed_permissions={"safe_read", "confirm_write"},
    )
    runner = AgentRuntimeRunner(model_call=fake_model, tool_executor=fake_execute)

    result = asyncio.run(runner.run(
        state,
        AgentRunConfig(max_rounds=3),
        initial_tool_calls=[{
            "id": "forced-send-1",
            "type": "function",
            "function": {"name": "send_group_message", "arguments": "{}"},
        }],
    ))

    assert result.stop_reason == "waiting_confirmation"
    assert result.content.startswith("[PermissionRequired]")
    assert state.pending_action_id == "action-1"
    assert len(state.tool_results) == 1


def test_runtime_runner_can_return_after_initial_tool_calls_without_model_call():
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    executed = []

    async def fake_execute(tool_call, ctx):
        name = tool_call["function"]["name"]
        executed.append(name)
        return ToolResult(
            name=name,
            permission="safe_write",
            status=TOOL_STATUS_OK,
            content="updated preference",
        )

    async def fake_model(messages, runtime_state):
        raise AssertionError("direct forced tool mode must not call the model")

    state = AgentState(
        messages=[{"role": "user", "content": "make trace title red"}],
        ctx=make_context(),
        allowed_permissions={"safe_read", "safe_write"},
    )
    runner = AgentRuntimeRunner(model_call=fake_model, tool_executor=fake_execute)

    result = asyncio.run(runner.run(
        state,
        AgentRunConfig(max_rounds=3, stop_after_initial_tools=True),
        initial_tool_calls=[{
            "id": "forced-update-ui-1",
            "type": "function",
            "function": {"name": "update_ui_preference", "arguments": "{}"},
        }],
    ))

    assert result.stop_reason == "initial_tools_complete"
    assert result.content == "updated preference"
    assert executed == ["update_ui_preference"]
    assert state.messages[-1]["role"] == "tool"


def test_runtime_runner_enforces_total_request_timeout():
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    async def slow_model(messages, runtime_state):
        await asyncio.sleep(0.05)
        return {"role": "assistant", "content": "too late"}

    state = AgentState(
        messages=[{"role": "user", "content": "slow"}],
        ctx=make_context(),
        allowed_permissions={"safe_read"},
    )
    runner = AgentRuntimeRunner(model_call=slow_model)

    result = asyncio.run(runner.run(
        state,
        AgentRunConfig(max_rounds=3, request_timeout_seconds=0.001),
    ))

    assert result.stop_reason == "timeout"
    assert "request timeout" in result.content
