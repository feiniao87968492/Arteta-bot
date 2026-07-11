import json

from . import behavior_policy
from .context import ToolContext
from .executor import execute_tool_call, execute_tool_call_result
from .planning.plan_builder import build_plan
from .providers.chat_completion import (
    DEFAULT_CHAT_API_URL,
    call_llm_with_tools as provider_call_llm_with_tools,
)
from .providers.openai_compatible import (
    ProviderResponseError,
    parse_chat_response,
)
from .registry import get_tool
from .response.composer import compose_final_response, compose_trace_response
from .response.mood import (
    maybe_send_mood_emoji,
)
from .runtime.config import AgentRunConfig
from .runtime.confirmation import (
    detect_pending_action_confirmation_id,
    execute_explicit_pending_action_confirmation,
    latest_user_content,
)
from .runtime.loop_guard import loop_guard_message
from .runtime.runner import AgentRuntimeRunner
from .runtime.state import AgentState, FinalizedResponse
from .routing.contextual_tools import detect_contextual_tool_exclusions
from .routing.heuristic_router import route_message
from .tool_policy import (
    consume_group_policy_turn,
    get_disabled_tools,
)


def _parse_chat_response(resp, api_url: str):
    return parse_chat_response(resp, api_url)


def _latest_user_content(messages) -> str:
    return latest_user_content(messages)


def _has_expiring_behavior_policies(group_id: str) -> bool:
    return any(
        "ttl_turns" in item
        for item in behavior_policy.list_group_policies(group_id).values()
    )


def _mood_emoji_enabled(group_id: str) -> bool:
    policy = behavior_policy.get_group_policy(group_id, "emoji.enabled")
    if not policy:
        return True
    return policy.get("value") is not False


async def call_llm_with_tools(messages, model: str, api_key: str, api_url: str = DEFAULT_CHAT_API_URL, allowed_permissions=None, disabled_tools=None, temperature: float = 0.9, request_timeout: float = 80.0):
    return await provider_call_llm_with_tools(
        messages=messages,
        model=model,
        api_key=api_key,
        api_url=api_url,
        allowed_permissions=allowed_permissions,
        disabled_tools=disabled_tools,
        temperature=temperature,
        request_timeout=request_timeout,
    )


async def _call_llm_with_policy(state, model: str, api_key: str, api_url: str, allowed_permissions, disabled_tools, temperature: float, request_timeout: float = 80.0):
    return await call_llm_with_tools(
        state,
        model,
        api_key,
        api_url=api_url,
        allowed_permissions=allowed_permissions,
        disabled_tools=disabled_tools,
        temperature=temperature,
        request_timeout=request_timeout,
    )


def _remember_artifact_markers(markers: list, tool_result) -> None:
    for marker in list(getattr(tool_result, "artifacts", None) or []):
        if marker not in markers:
            markers.append(marker)


def _loop_guard_message(reason: str) -> str:
    return loop_guard_message(reason)


async def _run_runtime_loop_from_state(
    state,
    ctx: ToolContext,
    model: str,
    api_key: str,
    api_url: str,
    allowed_permissions,
    disabled_tools,
    policy_disabled_tools,
    max_rounds: int,
    trace,
    temperature: float,
    request_timeout: float,
    tool_artifact_markers: list,
    max_tool_calls: int = 10,
    max_same_tool_call_repeats: int = 2,
    max_total_observation_chars: int = 80000,
    initial_tool_calls=None,
    stop_after_initial_tools: bool = False,
) -> str:
    runtime_state = _build_runtime_state(
        state,
        ctx,
        model,
        api_key,
        api_url,
        allowed_permissions,
        disabled_tools,
        policy_disabled_tools,
        trace,
        temperature,
        request_timeout,
    )
    runner = AgentRuntimeRunner(
        model_call=_runtime_model_call,
        tool_executor=execute_tool_call_result,
        tool_result_observer=_observe_runtime_tool_result(tool_artifact_markers),
        finalizer=_runtime_finalizer,
    )
    result = await runner.run(
        runtime_state,
        AgentRunConfig(
            max_rounds=max_rounds,
            max_tool_calls=max_tool_calls,
            max_same_tool_call_repeats=max_same_tool_call_repeats,
            max_total_observation_chars=max_total_observation_chars,
            request_timeout_seconds=request_timeout,
            stop_after_initial_tools=stop_after_initial_tools,
        ),
        initial_tool_calls=initial_tool_calls,
    )
    state[:] = runtime_state.messages
    if result.stop_reason == "max_rounds":
        return "Agent runtime stopped after the maximum model rounds. Please restate the goal more specifically."
    if result.stop_reason == "timeout":
        return _loop_guard_message("request timeout")
    return result.content


async def _runtime_model_call(state_messages, runtime_state: AgentState) -> dict:
    return await _call_llm_with_policy(
        state_messages,
        runtime_state.metadata["model"],
        runtime_state.metadata["api_key"],
        runtime_state.metadata["api_url"],
        runtime_state.allowed_permissions,
        runtime_state.disabled_tools,
        runtime_state.metadata["temperature"],
        runtime_state.metadata["request_timeout"],
    )


async def _runtime_finalizer(content: str, runtime_state: AgentState) -> FinalizedResponse:
    return await maybe_send_mood_emoji(
        content,
        runtime_state,
        get_tool=get_tool,
        execute_tool_call=execute_tool_call,
        emoji_enabled=_mood_emoji_enabled,
    )


def _observe_runtime_tool_result(tool_artifact_markers: list):
    def _observer(tool_result, runtime_state: AgentState) -> None:
        _remember_artifact_markers(tool_artifact_markers, tool_result)
    return _observer


def _build_runtime_state(
    state,
    ctx: ToolContext,
    model: str,
    api_key: str,
    api_url: str,
    allowed_permissions,
    disabled_tools,
    policy_disabled_tools,
    trace,
    temperature: float,
    request_timeout: float,
) -> AgentState:
    return AgentState(
        messages=list(state),
        ctx=ctx,
        allowed_permissions=set(allowed_permissions or set()),
        disabled_tools=set(disabled_tools or set()),
        policy_disabled_tools=set(policy_disabled_tools or set()),
        trace=trace,
        request_id=str(getattr(ctx, "request_id", "") or ""),
        metadata={
            "model": model,
            "api_key": api_key,
            "api_url": api_url,
            "temperature": temperature,
            "request_timeout": request_timeout,
        },
    )


def _tool_call_from_planned(index: int, planned) -> dict:
    return {
        "id": "planned-{0}-{1}".format(str(planned.name).replace("_", "-"), index),
        "type": "function",
        "function": {
            "name": planned.name,
            "arguments": json.dumps(planned.arguments or {}, ensure_ascii=False),
        },
    }


def _available_planned_calls(plan, disabled_tools) -> list:
    available = []
    for planned in plan.required_tools:
        if planned.name in set(disabled_tools or set()):
            continue
        if not get_tool(planned.name):
            continue
        available.append(planned)
    return available


def _initial_tool_calls_from_plan(plan, disabled_tools) -> list:
    calls = []
    for planned in _available_planned_calls(plan, disabled_tools):
        calls.append(_tool_call_from_planned(len(calls) + 1, planned))
    return calls


def _should_execute_initial_plan(plan, disabled_tools) -> bool:
    available_required = _available_planned_calls(plan, disabled_tools)
    if len(available_required) > 1:
        return True
    if len(available_required) == 1:
        return bool(
            plan.constraints.get("direct_trace_response")
            or plan.constraints.get("execute_single_required_tool")
        )
    return False


async def _run_loop_from_state(
    state,
    ctx: ToolContext,
    model: str,
    api_key: str,
    api_url: str,
    allowed_permissions,
    disabled_tools,
    policy_disabled_tools,
    max_rounds: int,
    trace,
    temperature: float,
    request_timeout: float,
    tool_artifact_markers: list,
    max_tool_calls: int = 10,
    max_same_tool_call_repeats: int = 2,
    max_total_observation_chars: int = 80000,
) -> str:
    return await _run_runtime_loop_from_state(
        state,
        ctx,
        model,
        api_key,
        api_url,
        allowed_permissions,
        disabled_tools,
        policy_disabled_tools,
        max_rounds,
        trace,
        temperature,
        request_timeout,
        tool_artifact_markers,
        max_tool_calls=max_tool_calls,
        max_same_tool_call_repeats=max_same_tool_call_repeats,
        max_total_observation_chars=max_total_observation_chars,
    )


async def run_agent_loop(messages, ctx: ToolContext, model: str, api_key: str, api_url: str = DEFAULT_CHAT_API_URL, max_rounds: int = 6, trace=None, temperature: float = 0.9, request_timeout: float = 80.0, max_tool_calls: int = 10, max_same_tool_call_repeats: int = 2, max_total_observation_chars: int = 80000):
    # Agent loop entrypoint used by arteta_chat.py when
    # ARTETA_USE_AGENT_REGISTRY=true. It alternates LLM planning and
    # permission-checked tool execution until the model returns final text.
    allowed = {"safe_read", "safe_write", "confirm_write", "admin_action"}
    state = list(messages)
    if trace is None:
        trace = (getattr(ctx, "extra", {}) or {}).get("agent_trace")
    if trace is not None:
        # Store trace in ToolContext.extra so planner, executor, and tools share
        # one sanitized execution timeline without changing every tool handler.
        ctx.extra = dict(ctx.extra or {})
        ctx.extra["agent_trace"] = trace
        trace.setdefault("group_id", ctx.group_id)

    confirmed_action_id = detect_pending_action_confirmation_id(state)
    if confirmed_action_id:
        return await execute_explicit_pending_action_confirmation(confirmed_action_id, ctx, trace)

    disabled_tools = get_disabled_tools(ctx.group_id)
    schema_excluded_tools = set(disabled_tools) | detect_contextual_tool_exclusions(state, ctx)
    should_consume_policy_turn = bool(disabled_tools) or _has_expiring_behavior_policies(ctx.group_id)
    tool_artifact_markers = []

    def finish(value: str) -> str:
        if should_consume_policy_turn:
            consume_group_policy_turn(ctx.group_id)
        return compose_final_response(value, artifacts=tool_artifact_markers, trace=trace)

    route_decision = route_message(state, ctx)
    initial_plan = build_plan(
        route_decision,
        ctx,
        disabled_tools=disabled_tools,
        is_tool_available=lambda name: get_tool(name) is not None,
    )
    planned_initial_calls = _initial_tool_calls_from_plan(initial_plan, disabled_tools)
    if planned_initial_calls and _should_execute_initial_plan(initial_plan, disabled_tools):
        initial_result = await _run_runtime_loop_from_state(
            state,
            ctx,
            model,
            api_key,
            api_url,
            allowed,
            schema_excluded_tools,
            disabled_tools,
            max_rounds,
            trace,
            temperature,
            request_timeout,
            tool_artifact_markers,
            max_tool_calls=max_tool_calls,
            max_same_tool_call_repeats=max_same_tool_call_repeats,
            max_total_observation_chars=max_total_observation_chars,
            initial_tool_calls=planned_initial_calls,
            stop_after_initial_tools=bool(
                initial_plan.constraints.get("direct_trace_response")
                or initial_plan.constraints.get("direct_tool_response")
            ),
        )
        if initial_plan.constraints.get("direct_trace_response"):
            return finish(compose_trace_response(trace))
        return finish(initial_result)

    return finish(await _run_loop_from_state(
        state,
        ctx,
        model,
        api_key,
        api_url,
        allowed,
        schema_excluded_tools,
        disabled_tools,
        max_rounds,
        trace,
        temperature,
        request_timeout,
        tool_artifact_markers,
        max_tool_calls=max_tool_calls,
        max_same_tool_call_repeats=max_same_tool_call_repeats,
        max_total_observation_chars=max_total_observation_chars,
    ))
