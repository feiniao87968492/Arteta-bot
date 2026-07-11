import asyncio
import inspect
from typing import Awaitable, Callable, Iterable, Optional

from ..context import ToolContext
from ..executor import execute_tool_call_result
from ..result import TOOL_STATUS_PERMISSION_REQUIRED, ToolResult
from ..trace import record_round
from .config import AgentRunConfig
from .loop_guard import LoopGuard, loop_guard_message
from .state import (
    AgentRunResult,
    AgentState,
    FinalizedResponse,
    STOP_REASON_FINAL,
    STOP_REASON_INITIAL_TOOLS_COMPLETE,
    STOP_REASON_LOOP_GUARD,
    STOP_REASON_MAX_ROUNDS,
    STOP_REASON_TIMEOUT,
    STOP_REASON_WAITING_CONFIRMATION,
)


ModelCall = Callable[[list, AgentState], Awaitable[dict]]
ToolExecutor = Callable[[dict, ToolContext], Awaitable[ToolResult]]
ToolResultObserver = Callable[[ToolResult, AgentState], object]
Finalizer = Callable[[str, AgentState], object]


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


class AgentRuntimeRunner:
    def __init__(
        self,
        model_call: ModelCall,
        tool_executor: Optional[ToolExecutor] = None,
        tool_result_observer: Optional[ToolResultObserver] = None,
        finalizer: Optional[Finalizer] = None,
    ) -> None:
        self.model_call = model_call
        self.tool_executor = tool_executor or execute_tool_call_result
        self.tool_result_observer = tool_result_observer
        self.finalizer = finalizer

    async def run(
        self,
        state: AgentState,
        config: AgentRunConfig,
        initial_tool_calls: Optional[Iterable[dict]] = None,
    ) -> AgentRunResult:
        timeout = float(config.request_timeout_seconds or 0)
        if timeout > 0:
            try:
                return await asyncio.wait_for(
                    self._run_impl(state, config, initial_tool_calls),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                state.stop_reason = STOP_REASON_TIMEOUT
                return AgentRunResult(
                    "[LoopGuard] Agent runtime stopped: request timeout.",
                    STOP_REASON_TIMEOUT,
                    state,
                )
        return await self._run_impl(state, config, initial_tool_calls)

    async def _run_impl(
        self,
        state: AgentState,
        config: AgentRunConfig,
        initial_tool_calls: Optional[Iterable[dict]] = None,
    ) -> AgentRunResult:
        guard = LoopGuard(config)
        initial_calls = list(initial_tool_calls or [])
        if initial_calls:
            state.append_message({
                "role": "assistant",
                "content": "",
                "tool_calls": initial_calls,
            })
            stopped = await self._execute_tool_calls(state, config, guard, initial_calls)
            if stopped is not None:
                return stopped
            if config.stop_after_initial_tools:
                state.stop_reason = STOP_REASON_INITIAL_TOOLS_COMPLETE
                content = state.tool_results[-1].content if state.tool_results else ""
                return AgentRunResult(content, STOP_REASON_INITIAL_TOOLS_COMPLETE, state)

        for _ in range(config.max_rounds):
            assistant_msg = await self.model_call(state.messages, state)
            state.append_message(assistant_msg)
            tool_calls = assistant_msg.get("tool_calls") or []
            if not tool_calls:
                return await self._finish_final_response(state, assistant_msg)

            stopped = await self._execute_tool_calls(state, config, guard, tool_calls)
            if stopped is not None:
                return stopped

        state.stop_reason = STOP_REASON_MAX_ROUNDS
        return AgentRunResult(
            "Agent runtime stopped after the maximum model rounds. Please restate the goal more specifically.",
            STOP_REASON_MAX_ROUNDS,
            state,
        )

    async def _execute_tool_calls(
        self,
        state: AgentState,
        config: AgentRunConfig,
        guard: LoopGuard,
        tool_calls: Iterable[dict],
    ) -> Optional[AgentRunResult]:
        calls = list(tool_calls or [])
        record_round(state.trace, len(calls))
        for tool_call in calls:
            guard_reason = guard.before_tool_call(tool_call, state.tool_call_count)
            if guard_reason:
                state.stop_reason = STOP_REASON_LOOP_GUARD
                return AgentRunResult(loop_guard_message(guard_reason), STOP_REASON_LOOP_GUARD, state)

            tool_result = await self.tool_executor(tool_call, state.ctx)
            state.add_tool_result(tool_result)
            if self.tool_result_observer:
                await _maybe_await(self.tool_result_observer(tool_result, state))

            if tool_result.status == TOOL_STATUS_PERMISSION_REQUIRED:
                state.stop_reason = STOP_REASON_WAITING_CONFIRMATION
                state.pending_action_id = tool_result.pending_action_id
                return AgentRunResult(tool_result.content, STOP_REASON_WAITING_CONFIRMATION, state)

            state.total_observation_chars += len(str(tool_result.content or ""))
            guard_reason = guard.after_observation(state.total_observation_chars)
            if guard_reason:
                state.stop_reason = STOP_REASON_LOOP_GUARD
                return AgentRunResult(loop_guard_message(guard_reason), STOP_REASON_LOOP_GUARD, state)

            state.append_message({
                "role": "tool",
                "tool_call_id": tool_call.get("id", ""),
                "content": tool_result.content,
            })
        return None

    async def _finish_final_response(self, state: AgentState, assistant_msg: dict) -> AgentRunResult:
        content = (assistant_msg.get("content") or "").strip()
        if self.finalizer:
            finalized = await _maybe_await(self.finalizer(content, state))
        else:
            finalized = FinalizedResponse(content, 0)
        if isinstance(finalized, FinalizedResponse):
            final_content = finalized.content
            final_tool_call_count = finalized.tool_call_count
        else:
            final_content = str(finalized or "")
            final_tool_call_count = 0
        record_round(state.trace, int(final_tool_call_count or 0))
        state.stop_reason = STOP_REASON_FINAL
        return AgentRunResult(
            final_content or "I need more information before I can complete this task.",
            STOP_REASON_FINAL,
            state,
        )
