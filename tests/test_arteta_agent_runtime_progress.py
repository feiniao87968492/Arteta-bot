import asyncio
import json

from plugins.arteta_agent.context import ToolContext
from plugins.arteta_agent.result import TOOL_STATUS_OK, TOOL_STATUS_PERMISSION_REQUIRED, ToolResult
from plugins.arteta_agent.runtime.config import AgentRunConfig
from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
from plugins.arteta_agent.runtime.state import AgentState


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


def _tool_call(call_id, name, args=None):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args or {"query": "secret value"}),
        },
    }


def test_runtime_emits_structured_progress_without_mutating_messages():
    events = []

    async def fake_execute(tool_call, ctx):
        return ToolResult(
            name=tool_call["function"]["name"],
            permission="safe_read",
            status=TOOL_STATUS_OK,
            content="raw tool result that must not appear in progress",
            duration_ms=1234,
        )

    async def fake_model(messages, runtime_state):
        if not runtime_state.tool_results:
            return {"role": "assistant", "content": "", "tool_calls": [_tool_call("call-1", "grok_search")]}
        return {"role": "assistant", "content": "final answer"}

    async def observer(event, state):
        events.append(event)

    state = AgentState(messages=[{"role": "user", "content": "查一下"}], ctx=make_context(), allowed_permissions={"safe_read"})
    runner = AgentRuntimeRunner(model_call=fake_model, tool_executor=fake_execute, progress_observer=observer)

    result = asyncio.run(runner.run(state, AgentRunConfig(max_rounds=3)))

    assert result.content == "final answer"
    assert [event.kind for event in events] == [
        "run_started",
        "model_round_started",
        "tool_batch_started",
        "tool_finished",
        "tool_batch_finished",
        "model_round_started",
        "final_synthesis_started",
        "finished",
    ]
    assert events[2].tools[0].name == "grok_search"
    assert events[2].tools[0].argument_keys == ["query"]
    assert "raw tool result" not in repr(events)
    assert [message["role"] for message in state.messages] == ["user", "assistant", "tool", "assistant"]


def test_runtime_progress_observer_failure_does_not_break_main_result():
    async def fake_model(messages, runtime_state):
        return {"role": "assistant", "content": "ok"}

    async def broken_observer(event, state):
        raise RuntimeError("observer failed")

    state = AgentState(messages=[{"role": "user", "content": "hi"}], ctx=make_context(), allowed_permissions={"safe_read"})
    runner = AgentRuntimeRunner(model_call=fake_model, progress_observer=broken_observer)

    result = asyncio.run(runner.run(state, AgentRunConfig(max_rounds=1)))

    assert result.content == "ok"
    assert result.stop_reason == "final"


def test_runtime_progress_reports_waiting_confirmation_and_timeout():
    confirmation_events = []

    async def permission_execute(tool_call, ctx):
        return ToolResult(
            name="mute_member",
            permission="admin_action",
            status=TOOL_STATUS_PERMISSION_REQUIRED,
            content="[PermissionRequired] mute_member PendingAction: action-1",
            pending_action_id="action-1",
        )

    async def no_model(messages, runtime_state):
        raise AssertionError("should not call model")

    state = AgentState(messages=[{"role": "user", "content": "mute"}], ctx=make_context(), allowed_permissions={"admin_action"})
    runner = AgentRuntimeRunner(
        model_call=no_model,
        tool_executor=permission_execute,
        progress_observer=lambda event, runtime_state: confirmation_events.append(event),
    )

    result = asyncio.run(runner.run(
        state,
        AgentRunConfig(max_rounds=1),
        initial_tool_calls=[_tool_call("mute", "mute_member")],
    ))

    assert result.stop_reason == "waiting_confirmation"
    assert "waiting_confirmation" in [event.kind for event in confirmation_events]

    timeout_events = []

    async def slow_model(messages, runtime_state):
        await asyncio.sleep(0.05)
        return {"role": "assistant", "content": "late"}

    timeout_state = AgentState(messages=[{"role": "user", "content": "slow"}], ctx=make_context(), allowed_permissions={"safe_read"})
    timeout_runner = AgentRuntimeRunner(
        model_call=slow_model,
        progress_observer=lambda event, runtime_state: timeout_events.append(event),
    )

    timeout_result = asyncio.run(timeout_runner.run(
        timeout_state,
        AgentRunConfig(max_rounds=1, request_timeout_seconds=0.001),
    ))

    assert timeout_result.stop_reason == "timeout"
    assert "runtime_stopped" in [event.kind for event in timeout_events]
