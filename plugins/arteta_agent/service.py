from dataclasses import dataclass, field
from typing import List, Optional, Set

from .context import ToolContext
from .planning.execution import (
    initial_tool_calls_from_plan,
    should_execute_initial_plan,
)
from .planning.plan_builder import build_plan
from .policy.service import consume_policy_turn_if_needed, should_consume_policy_turn
from .policy.service import mood_emoji_enabled
from .registry import get_tool
from .response.composer import compose_final_response, compose_trace_response
from .runtime.confirmation import (
    detect_pending_action_confirmation_id,
    execute_explicit_pending_action_confirmation,
)
from .runtime.service import run_loop_from_state, run_runtime_loop_from_state
from .routing.contextual_tools import detect_contextual_tool_exclusions
from .routing.heuristic_router import route_message
from .tool_policy import get_disabled_tools


@dataclass
class PreparedAgentRun:
    state: List[dict]
    trace: Optional[dict]
    disabled_tools: Set[str]
    consume_policy_turn: bool
    artifact_markers: List[str] = field(default_factory=list)


@dataclass
class AgentRequest:
    messages: List[dict]
    ctx: ToolContext
    model: str
    api_key: str
    api_url: str
    max_rounds: int
    trace: Optional[dict]
    temperature: float
    request_timeout: float
    max_tool_calls: int
    max_same_tool_call_repeats: int
    max_total_observation_chars: int
    chat_model_call: object


def prepare_agent_run(
    messages,
    ctx: ToolContext,
    trace,
    disabled_tools,
) -> PreparedAgentRun:
    state = list(messages)
    if trace is None:
        trace = (getattr(ctx, "extra", {}) or {}).get("agent_trace")
    if trace is not None:
        ctx.extra = dict(ctx.extra or {})
        ctx.extra["agent_trace"] = trace
        trace.setdefault("group_id", ctx.group_id)
    disabled = set(disabled_tools or set())
    return PreparedAgentRun(
        state=state,
        trace=trace,
        disabled_tools=disabled,
        consume_policy_turn=should_consume_policy_turn(ctx.group_id, disabled),
    )


def finish_agent_run(value: str, ctx: ToolContext, prepared: PreparedAgentRun) -> str:
    consume_policy_turn_if_needed(ctx.group_id, prepared.consume_policy_turn)
    return compose_final_response(
        value,
        artifacts=prepared.artifact_markers,
        trace=prepared.trace,
    )


async def run_agent_request(request: AgentRequest) -> str:
    allowed = {"safe_read", "safe_write", "confirm_write", "admin_action"}
    ctx = request.ctx
    disabled_tools = get_disabled_tools(ctx.group_id)
    prepared = prepare_agent_run(request.messages, ctx, request.trace, disabled_tools)
    state = prepared.state
    trace = prepared.trace
    disabled_tools = prepared.disabled_tools

    confirmed_action_id = detect_pending_action_confirmation_id(state)
    if confirmed_action_id:
        return await execute_explicit_pending_action_confirmation(confirmed_action_id, ctx, trace)

    schema_excluded_tools = set(disabled_tools) | detect_contextual_tool_exclusions(state, ctx)

    route_decision = route_message(state, ctx)
    is_tool_available = lambda name: get_tool(name) is not None
    initial_plan = build_plan(
        route_decision,
        ctx,
        disabled_tools=disabled_tools,
        is_tool_available=is_tool_available,
    )
    planned_initial_calls = initial_tool_calls_from_plan(initial_plan, disabled_tools, is_tool_available)
    if planned_initial_calls and should_execute_initial_plan(initial_plan, disabled_tools, is_tool_available):
        initial_result = await run_runtime_loop_from_state(
            state,
            ctx,
            request.model,
            request.api_key,
            request.api_url,
            allowed,
            schema_excluded_tools,
            disabled_tools,
            request.max_rounds,
            trace,
            request.temperature,
            request.request_timeout,
            prepared.artifact_markers,
            max_tool_calls=request.max_tool_calls,
            max_same_tool_call_repeats=request.max_same_tool_call_repeats,
            max_total_observation_chars=request.max_total_observation_chars,
            initial_tool_calls=planned_initial_calls,
            stop_after_initial_tools=bool(
                initial_plan.constraints.get("direct_trace_response")
                or initial_plan.constraints.get("direct_tool_response")
            ),
            chat_model_call=request.chat_model_call,
            emoji_enabled=mood_emoji_enabled,
        )
        if initial_plan.constraints.get("direct_trace_response"):
            return finish_agent_run(compose_trace_response(trace), ctx, prepared)
        return finish_agent_run(initial_result, ctx, prepared)

    return finish_agent_run(await run_loop_from_state(
        state,
        ctx,
        request.model,
        request.api_key,
        request.api_url,
        allowed,
        schema_excluded_tools,
        disabled_tools,
        request.max_rounds,
        trace,
        request.temperature,
        request.request_timeout,
        prepared.artifact_markers,
        max_tool_calls=request.max_tool_calls,
        max_same_tool_call_repeats=request.max_same_tool_call_repeats,
        max_total_observation_chars=request.max_total_observation_chars,
        chat_model_call=request.chat_model_call,
        emoji_enabled=mood_emoji_enabled,
    ), ctx, prepared)
