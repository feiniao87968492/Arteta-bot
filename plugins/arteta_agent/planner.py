from .context import ToolContext
from .planning.execution import (
    initial_tool_calls_from_plan,
    should_execute_initial_plan,
)
from .planning.plan_builder import build_plan
from .policy.service import mood_emoji_enabled
from .providers.chat_completion import (
    DEFAULT_CHAT_API_URL,
    call_llm_with_tools as provider_call_llm_with_tools,
)
from .providers.openai_compatible import (
    ProviderResponseError,
    parse_chat_response,
)
from .registry import get_tool
from .response.composer import compose_trace_response
from .runtime.confirmation import (
    detect_pending_action_confirmation_id,
    execute_explicit_pending_action_confirmation,
    latest_user_content,
)
from .runtime.service import run_loop_from_state, run_runtime_loop_from_state
from .routing.contextual_tools import detect_contextual_tool_exclusions
from .routing.heuristic_router import route_message
from .service import finish_agent_run, prepare_agent_run
from .tool_policy import (
    get_disabled_tools,
)


def _parse_chat_response(resp, api_url: str):
    return parse_chat_response(resp, api_url)


def _latest_user_content(messages) -> str:
    return latest_user_content(messages)


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


async def run_agent_loop(messages, ctx: ToolContext, model: str, api_key: str, api_url: str = DEFAULT_CHAT_API_URL, max_rounds: int = 6, trace=None, temperature: float = 0.9, request_timeout: float = 80.0, max_tool_calls: int = 10, max_same_tool_call_repeats: int = 2, max_total_observation_chars: int = 80000):
    # Agent loop entrypoint used by arteta_chat.py when
    # ARTETA_USE_AGENT_REGISTRY=true. It alternates LLM planning and
    # permission-checked tool execution until the model returns final text.
    allowed = {"safe_read", "safe_write", "confirm_write", "admin_action"}
    disabled_tools = get_disabled_tools(ctx.group_id)
    prepared = prepare_agent_run(messages, ctx, trace, disabled_tools)
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
            prepared.artifact_markers,
            max_tool_calls=max_tool_calls,
            max_same_tool_call_repeats=max_same_tool_call_repeats,
            max_total_observation_chars=max_total_observation_chars,
            initial_tool_calls=planned_initial_calls,
            stop_after_initial_tools=bool(
                initial_plan.constraints.get("direct_trace_response")
                or initial_plan.constraints.get("direct_tool_response")
            ),
            chat_model_call=call_llm_with_tools,
            emoji_enabled=mood_emoji_enabled,
        )
        if initial_plan.constraints.get("direct_trace_response"):
            return finish_agent_run(compose_trace_response(trace), ctx, prepared)
        return finish_agent_run(initial_result, ctx, prepared)

    return finish_agent_run(await run_loop_from_state(
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
        prepared.artifact_markers,
        max_tool_calls=max_tool_calls,
        max_same_tool_call_repeats=max_same_tool_call_repeats,
        max_total_observation_chars=max_total_observation_chars,
        chat_model_call=call_llm_with_tools,
        emoji_enabled=mood_emoji_enabled,
    ), ctx, prepared)
