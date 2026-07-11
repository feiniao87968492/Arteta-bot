import asyncio
import json
import time

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


def test_runtime_runner_executes_parallel_safe_read_tools_concurrently_in_order():
    from plugins.arteta_agent.registry import ToolSpec, clear_registry, register_tool
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    clear_registry()
    register_tool(ToolSpec(
        "read_a",
        "read a",
        {"type": "object", "properties": {}},
        lambda ctx: "a",
        permission="safe_read",
        parallel_safe=True,
        idempotent=True,
    ))
    register_tool(ToolSpec(
        "read_b",
        "read b",
        {"type": "object", "properties": {}},
        lambda ctx: "b",
        permission="safe_read",
        parallel_safe=True,
        idempotent=True,
    ))
    starts = {}

    async def fake_execute(tool_call, ctx):
        name = tool_call["function"]["name"]
        starts[name] = time.monotonic()
        await asyncio.sleep(0.05)
        return ToolResult(
            name=name,
            permission="safe_read",
            status=TOOL_STATUS_OK,
            content="{0}-result".format(name),
        )

    async def fake_model(messages, runtime_state):
        if not runtime_state.tool_results:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-read-a",
                        "type": "function",
                        "function": {"name": "read_a", "arguments": "{}"},
                    },
                    {
                        "id": "call-read-b",
                        "type": "function",
                        "function": {"name": "read_b", "arguments": "{}"},
                    },
                ],
            }
        return {"role": "assistant", "content": "done"}

    state = AgentState(
        messages=[{"role": "user", "content": "read both"}],
        ctx=make_context(),
        allowed_permissions={"safe_read"},
    )
    runner = AgentRuntimeRunner(model_call=fake_model, tool_executor=fake_execute)

    started = time.monotonic()
    result = asyncio.run(runner.run(
        state,
        AgentRunConfig(max_rounds=3, max_parallel_tools=3),
    ))
    elapsed = time.monotonic() - started

    assert result.content == "done"
    assert elapsed < 0.09
    assert abs(starts["read_a"] - starts["read_b"]) < 0.025
    assert [item.name for item in state.tool_results] == ["read_a", "read_b"]
    assert [message.get("tool_call_id") for message in state.messages if message["role"] == "tool"] == [
        "call-read-a",
        "call-read-b",
    ]


def test_runtime_runner_does_not_parallelize_write_tools():
    from plugins.arteta_agent.registry import ToolSpec, clear_registry, register_tool
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    clear_registry()
    register_tool(ToolSpec(
        "read_a",
        "read a",
        {"type": "object", "properties": {}},
        lambda ctx: "a",
        permission="safe_read",
        parallel_safe=True,
        idempotent=True,
    ))
    register_tool(ToolSpec(
        "write_a",
        "write a",
        {"type": "object", "properties": {}},
        lambda ctx: "w",
        permission="safe_write",
        parallel_safe=True,
        idempotent=True,
    ))
    started = {}
    finished = {}

    async def fake_execute(tool_call, ctx):
        name = tool_call["function"]["name"]
        started[name] = time.monotonic()
        await asyncio.sleep(0.03)
        finished[name] = time.monotonic()
        return ToolResult(name=name, permission="safe_read" if name == "read_a" else "safe_write", status=TOOL_STATUS_OK, content=name)

    async def fake_model(messages, runtime_state):
        if not runtime_state.tool_results:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call-read-a", "type": "function", "function": {"name": "read_a", "arguments": "{}"}},
                    {"id": "call-write-a", "type": "function", "function": {"name": "write_a", "arguments": "{}"}},
                ],
            }
        return {"role": "assistant", "content": "done"}

    state = AgentState(messages=[{"role": "user", "content": "mixed"}], ctx=make_context(), allowed_permissions={"safe_read", "safe_write"})
    runner = AgentRuntimeRunner(model_call=fake_model, tool_executor=fake_execute)

    result = asyncio.run(runner.run(state, AgentRunConfig(max_rounds=3, max_parallel_tools=3)))

    assert result.content == "done"
    assert started["write_a"] >= finished["read_a"]


def test_runtime_runner_parallel_read_failure_does_not_cancel_other_results():
    from plugins.arteta_agent.registry import ToolSpec, clear_registry, register_tool
    from plugins.arteta_agent.result import TOOL_STATUS_ERROR
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    clear_registry()
    for name in ("read_fail", "read_ok"):
        register_tool(ToolSpec(
            name,
            name,
            {"type": "object", "properties": {}},
            lambda ctx: name,
            permission="safe_read",
            parallel_safe=True,
            idempotent=True,
        ))

    async def fake_execute(tool_call, ctx):
        name = tool_call["function"]["name"]
        await asyncio.sleep(0.01)
        if name == "read_fail":
            return ToolResult(name=name, permission="safe_read", status=TOOL_STATUS_ERROR, content="[ToolError] failed")
        return ToolResult(name=name, permission="safe_read", status=TOOL_STATUS_OK, content="ok")

    async def fake_model(messages, runtime_state):
        if not runtime_state.tool_results:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call-fail", "type": "function", "function": {"name": "read_fail", "arguments": "{}"}},
                    {"id": "call-ok", "type": "function", "function": {"name": "read_ok", "arguments": "{}"}},
                ],
            }
        return {"role": "assistant", "content": "done"}

    state = AgentState(messages=[{"role": "user", "content": "read both"}], ctx=make_context(), allowed_permissions={"safe_read"})
    runner = AgentRuntimeRunner(model_call=fake_model, tool_executor=fake_execute)

    result = asyncio.run(runner.run(state, AgentRunConfig(max_rounds=3, max_parallel_tools=3)))

    assert result.content == "done"
    assert [item.name for item in state.tool_results] == ["read_fail", "read_ok"]
    assert [message.get("tool_call_id") for message in state.messages if message["role"] == "tool"] == [
        "call-fail",
        "call-ok",
    ]


def test_runtime_runner_parallel_tool_limit_is_enforced():
    from plugins.arteta_agent.registry import ToolSpec, clear_registry, register_tool
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    clear_registry()
    for name in ("read_1", "read_2", "read_3"):
        register_tool(ToolSpec(
            name,
            name,
            {"type": "object", "properties": {}},
            lambda ctx: name,
            permission="safe_read",
            parallel_safe=True,
            idempotent=True,
        ))

    starts = {}
    finishes = {}

    async def fake_execute(tool_call, ctx):
        name = tool_call["function"]["name"]
        starts[name] = time.monotonic()
        await asyncio.sleep(0.03)
        finishes[name] = time.monotonic()
        return ToolResult(name=name, permission="safe_read", status=TOOL_STATUS_OK, content=name)

    async def fake_model(messages, runtime_state):
        if not runtime_state.tool_results:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call-1", "type": "function", "function": {"name": "read_1", "arguments": "{}"}},
                    {"id": "call-2", "type": "function", "function": {"name": "read_2", "arguments": "{}"}},
                    {"id": "call-3", "type": "function", "function": {"name": "read_3", "arguments": "{}"}},
                ],
            }
        return {"role": "assistant", "content": "done"}

    state = AgentState(messages=[{"role": "user", "content": "read three"}], ctx=make_context(), allowed_permissions={"safe_read"})
    runner = AgentRuntimeRunner(model_call=fake_model, tool_executor=fake_execute)

    result = asyncio.run(runner.run(state, AgentRunConfig(max_rounds=3, max_parallel_tools=2)))

    assert result.content == "done"
    assert abs(starts["read_1"] - starts["read_2"]) < 0.025
    assert starts["read_3"] >= finishes["read_1"]


def test_runtime_confirmation_module_owns_explicit_pending_confirmation_helpers():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "def detect_pending_action_confirmation_id" not in source
    assert "def _execute_explicit_pending_action_confirmation" not in source
    assert "record_pending_confirmation_failure" not in source
    assert "store_from_context" not in source


def test_runtime_service_owns_planner_runtime_wiring():
    from pathlib import Path

    from plugins.arteta_agent.runtime import service

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert hasattr(service, "run_runtime_loop_from_state")
    assert "def _run_runtime_loop_from_state" not in source
    assert "def _run_loop_from_state" not in source
    assert "def _build_runtime_state" not in source
    assert "def _runtime_model_call" not in source
    assert "def _runtime_finalizer" not in source
    assert "def _observe_runtime_tool_result" not in source
    assert "AgentRuntimeRunner(" not in source


def test_agent_service_owns_trace_and_final_response_wiring():
    from pathlib import Path

    from plugins.arteta_agent import service

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert hasattr(service, "prepare_agent_run")
    assert hasattr(service, "finish_agent_run")
    assert "ctx.extra[\"agent_trace\"]" not in source
    assert "trace.setdefault(\"group_id\"" not in source
    assert "compose_final_response(" not in source
    assert "consume_policy_turn_if_needed(" not in source


def test_planner_delegates_agent_loop_orchestration_to_service():
    from pathlib import Path

    from plugins.arteta_agent import service

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert hasattr(service, "run_legacy_agent_loop")
    assert "from .planning." not in source
    assert "from .routing." not in source
    assert "run_runtime_loop_from_state" not in source
    assert "route_message(" not in source
    assert "build_plan(" not in source
    assert "initial_tool_calls_from_plan(" not in source
    assert "detect_contextual_tool_exclusions(" not in source
    assert "return await run_agent_request(" in source


def test_planner_uses_structured_agent_request_for_service_entrypoint():
    from pathlib import Path

    from plugins.arteta_agent import service

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert hasattr(service, "AgentRequest")
    assert hasattr(service, "run_agent_request")
    assert "AgentRequest(" in source
    assert "return await run_agent_request(" in source
    assert "run_legacy_agent_loop(" not in source
