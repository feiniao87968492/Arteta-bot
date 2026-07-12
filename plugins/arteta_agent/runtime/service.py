from typing import Awaitable, Callable

from ..context import ToolContext
from ..executor import execute_tool_call, execute_tool_call_result
from ..registry import get_tool
from ..response.mood import maybe_send_mood_emoji
from .config import AgentRunConfig
from .loop_guard import loop_guard_message
from .runner import AgentRuntimeRunner
from .state import AgentState, FinalizedResponse


ChatModelCall = Callable[..., Awaitable[dict]]
EmojiEnabled = Callable[[str], bool]


def _remember_artifact_markers(markers: list, tool_result) -> None:
    for marker in list(getattr(tool_result, "artifacts", None) or []):
        if marker not in markers:
            markers.append(marker)


def build_runtime_state(
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


async def _runtime_model_call(
    state_messages,
    runtime_state: AgentState,
    chat_model_call: ChatModelCall,
) -> dict:
    return await chat_model_call(
        state_messages,
        runtime_state.metadata["model"],
        runtime_state.metadata["api_key"],
        api_url=runtime_state.metadata["api_url"],
        allowed_permissions=runtime_state.allowed_permissions,
        disabled_tools=runtime_state.disabled_tools,
        temperature=runtime_state.metadata["temperature"],
        request_timeout=runtime_state.metadata["request_timeout"],
    )


async def _runtime_finalizer(
    content: str,
    runtime_state: AgentState,
    emoji_enabled: EmojiEnabled,
) -> FinalizedResponse:
    return await maybe_send_mood_emoji(
        content,
        runtime_state,
        get_tool=get_tool,
        execute_tool_call=execute_tool_call,
        emoji_enabled=emoji_enabled,
    )


def _observe_runtime_tool_result(tool_artifact_markers: list):
    def _observer(tool_result, runtime_state: AgentState) -> None:
        _remember_artifact_markers(tool_artifact_markers, tool_result)

    return _observer


async def run_runtime_loop_from_state(
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
    chat_model_call: ChatModelCall,
    emoji_enabled: EmojiEnabled,
    max_tool_calls: int = 10,
    max_same_tool_call_repeats: int = 2,
    max_total_observation_chars: int = 80000,
    initial_tool_calls=None,
    stop_after_initial_tools: bool = False,
    tool_call_dependencies=None,
) -> str:
    runtime_state = build_runtime_state(
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
        model_call=lambda messages, agent_state: _runtime_model_call(
            messages,
            agent_state,
            chat_model_call,
        ),
        tool_executor=execute_tool_call_result,
        tool_result_observer=_observe_runtime_tool_result(tool_artifact_markers),
        finalizer=lambda content, agent_state: _runtime_finalizer(
            content,
            agent_state,
            emoji_enabled,
        ),
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
            tool_call_dependencies=dict(tool_call_dependencies or {}),
        ),
        initial_tool_calls=initial_tool_calls,
    )
    state[:] = runtime_state.messages
    if result.stop_reason == "max_rounds":
        return "Agent runtime stopped after the maximum model rounds. Please restate the goal more specifically."
    if result.stop_reason == "timeout":
        return loop_guard_message("request timeout")
    return result.content


async def run_loop_from_state(
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
    chat_model_call: ChatModelCall,
    emoji_enabled: EmojiEnabled,
    max_tool_calls: int = 10,
    max_same_tool_call_repeats: int = 2,
    max_total_observation_chars: int = 80000,
) -> str:
    return await run_runtime_loop_from_state(
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
        chat_model_call=chat_model_call,
        emoji_enabled=emoji_enabled,
        max_tool_calls=max_tool_calls,
        max_same_tool_call_repeats=max_same_tool_call_repeats,
        max_total_observation_chars=max_total_observation_chars,
    )
