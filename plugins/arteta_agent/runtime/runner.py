import asyncio
import inspect
import json
import logging
import time
from typing import Awaitable, Callable, Iterable, Optional, Set

from ..context import ToolContext
from ..executor import execute_tool_call_result
from ..registry import get_tool
from ..progress.models import (
    PROGRESS_FINAL_SYNTHESIS_STARTED,
    PROGRESS_FINISHED,
    PROGRESS_MODEL_ROUND_STARTED,
    PROGRESS_RUN_STARTED,
    PROGRESS_RUNTIME_STOPPED,
    PROGRESS_TOOL_BATCH_FINISHED,
    PROGRESS_TOOL_BATCH_STARTED,
    PROGRESS_TOOL_FINISHED,
    PROGRESS_WAITING_CONFIRMATION,
    AgentProgressEvent,
    ProgressToolCall,
)
from ..result import (
    TOOL_STATUS_ERROR,
    TOOL_STATUS_INVALID_ARGUMENTS,
    TOOL_STATUS_OK,
    TOOL_STATUS_PERMISSION_REQUIRED,
    TOOL_STATUS_TIMEOUT,
    TOOL_STATUS_UNAVAILABLE,
    ToolResult,
)
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
    STOP_REASON_REQUIRED_CURRENT_INFORMATION_UNAVAILABLE,
    STOP_REASON_TIMEOUT,
    STOP_REASON_WAITING_CONFIRMATION,
)


ModelCall = Callable[[list, AgentState], Awaitable[dict]]
ToolExecutor = Callable[[dict, ToolContext], Awaitable[ToolResult]]
ToolResultObserver = Callable[[ToolResult, AgentState], object]
Finalizer = Callable[[str, AgentState], object]
ProgressObserver = Callable[[AgentProgressEvent, AgentState], object]
LOGGER = logging.getLogger(__name__)


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
        progress_observer: Optional[ProgressObserver] = None,
    ) -> None:
        self.model_call = model_call
        self.tool_executor = tool_executor or execute_tool_call_result
        self.tool_result_observer = tool_result_observer
        self.finalizer = finalizer
        self.progress_observer = progress_observer

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
                await self._emit_progress(AgentProgressEvent(
                    kind=PROGRESS_RUNTIME_STOPPED,
                    status=STOP_REASON_TIMEOUT,
                    metadata={"stop_reason": STOP_REASON_TIMEOUT},
                ), state)
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
        await self._emit_progress(AgentProgressEvent(kind=PROGRESS_RUN_STARTED), state)
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
            await self._emit_progress(AgentProgressEvent(
                kind=PROGRESS_MODEL_ROUND_STARTED,
                round_index=self._progress_round_index(state),
            ), state)
            if state.tool_results:
                state.metadata["progress_final_synthesis_started"] = True
                await self._emit_progress(AgentProgressEvent(
                    kind=PROGRESS_FINAL_SYNTHESIS_STARTED,
                    tools=[self._progress_call_from_result(result) for result in state.tool_results[-3:]],
                    metadata={"scene": self._synthesis_scene(state)},
                ), state)
            assistant_msg = await self.model_call(state.messages, state)
            state.append_message(assistant_msg)
            tool_calls = assistant_msg.get("tool_calls") or []
            if not tool_calls:
                return await self._finish_final_response(state, assistant_msg)

            stopped = await self._execute_tool_calls(state, config, guard, tool_calls)
            if stopped is not None:
                return stopped

        state.stop_reason = STOP_REASON_MAX_ROUNDS
        await self._emit_progress(AgentProgressEvent(
            kind=PROGRESS_RUNTIME_STOPPED,
            status=STOP_REASON_MAX_ROUNDS,
            metadata={"stop_reason": STOP_REASON_MAX_ROUNDS},
        ), state)
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
        index = 0
        completed_call_ids = self._completed_tool_call_ids(state)
        while index < len(calls):
            if self._should_skip_satisfied_current_information_call(calls[index], config, state):
                completed_call_ids.add(str((calls[index] or {}).get("id") or ""))
                index += 1
                continue
            batch = self._parallel_safe_batch(calls, index, config, completed_call_ids)
            await self._emit_progress(AgentProgressEvent(
                kind=PROGRESS_TOOL_BATCH_STARTED,
                tools=[self._progress_call_from_tool_call(tool_call) for tool_call in batch],
            ), state)
            started = time.monotonic()
            if len(batch) > 1:
                for tool_call in batch:
                    guard_reason = guard.before_tool_call(tool_call, state.tool_call_count)
                    if guard_reason:
                        state.stop_reason = STOP_REASON_LOOP_GUARD
                        await self._emit_progress(AgentProgressEvent(
                            kind=PROGRESS_RUNTIME_STOPPED,
                            status=STOP_REASON_LOOP_GUARD,
                            metadata={"stop_reason": STOP_REASON_LOOP_GUARD},
                        ), state)
                        return AgentRunResult(loop_guard_message(guard_reason), STOP_REASON_LOOP_GUARD, state)
                tool_results = await asyncio.gather(*[
                    self.tool_executor(tool_call, state.ctx) for tool_call in batch
                ])
                duration_ms = int((time.monotonic() - started) * 1000)
                for tool_call, tool_result in zip(batch, tool_results):
                    await self._emit_progress(AgentProgressEvent(
                        kind=PROGRESS_TOOL_FINISHED,
                        tools=[self._progress_call_from_result(tool_result, tool_call)],
                        status=self._progress_status(tool_result),
                        duration_ms=int(getattr(tool_result, "duration_ms", 0) or duration_ms),
                        error_code=str(getattr(tool_result, "error_code", "") or ""),
                    ), state)
                    stopped = await self._observe_tool_result(state, config, guard, tool_call, tool_result)
                    completed_call_ids.add(str(tool_call.get("id") or ""))
                    if stopped is not None:
                        return stopped
                await self._emit_progress(AgentProgressEvent(
                    kind=PROGRESS_TOOL_BATCH_FINISHED,
                    tools=[self._progress_call_from_result(result, call) for call, result in zip(batch, tool_results)],
                    status="ok" if all(self._progress_status(result) == "ok" for result in tool_results) else "error",
                    duration_ms=duration_ms,
                    metadata={
                        "success_count": sum(1 for result in tool_results if self._progress_status(result) == "ok"),
                        "failure_count": sum(1 for result in tool_results if self._progress_status(result) != "ok"),
                    },
                ), state)
                index += len(batch)
                continue

            tool_call = calls[index]
            guard_reason = guard.before_tool_call(tool_call, state.tool_call_count)
            if guard_reason:
                state.stop_reason = STOP_REASON_LOOP_GUARD
                await self._emit_progress(AgentProgressEvent(
                    kind=PROGRESS_RUNTIME_STOPPED,
                    status=STOP_REASON_LOOP_GUARD,
                    metadata={"stop_reason": STOP_REASON_LOOP_GUARD},
                ), state)
                return AgentRunResult(loop_guard_message(guard_reason), STOP_REASON_LOOP_GUARD, state)

            tool_result = await self.tool_executor(tool_call, state.ctx)
            duration_ms = int((time.monotonic() - started) * 1000)
            await self._emit_progress(AgentProgressEvent(
                kind=PROGRESS_TOOL_FINISHED,
                tools=[self._progress_call_from_result(tool_result, tool_call)],
                status=self._progress_status(tool_result),
                duration_ms=int(getattr(tool_result, "duration_ms", 0) or duration_ms),
                error_code=str(getattr(tool_result, "error_code", "") or ""),
            ), state)
            stopped = await self._observe_tool_result(state, config, guard, tool_call, tool_result)
            completed_call_ids.add(str(tool_call.get("id") or ""))
            if stopped is not None:
                return stopped
            await self._emit_progress(AgentProgressEvent(
                kind=PROGRESS_TOOL_BATCH_FINISHED,
                tools=[self._progress_call_from_result(tool_result, tool_call)],
                status=self._progress_status(tool_result),
                duration_ms=int(getattr(tool_result, "duration_ms", 0) or duration_ms),
                error_code=str(getattr(tool_result, "error_code", "") or ""),
            ), state)
            index += 1
        return None

    def _completed_tool_call_ids(self, state: AgentState) -> Set[str]:
        completed: Set[str] = set()
        for message in list(state.messages or []):
            if (message or {}).get("role") != "tool":
                continue
            tool_call_id = str((message or {}).get("tool_call_id") or "")
            if tool_call_id:
                completed.add(tool_call_id)
        return completed

    def _parallel_safe_batch(
        self,
        calls: list,
        start_index: int,
        config: AgentRunConfig,
        completed_call_ids: Set[str],
    ) -> list:
        limit = max(1, int(getattr(config, "max_parallel_tools", 1) or 1))
        if limit <= 1:
            return calls[start_index:start_index + 1]
        batch = []
        concurrency_groups: Set[str] = set()
        for tool_call in calls[start_index:start_index + limit]:
            if not self._is_parallel_safe_read_call(tool_call):
                break
            call_id = str((tool_call or {}).get("id") or "")
            dependencies = list((config.tool_call_dependencies or {}).get(call_id, []) or [])
            if any(str(dependency) not in completed_call_ids for dependency in dependencies):
                if batch:
                    break
                return calls[start_index:start_index + 1]
            concurrency_group = self._concurrency_group(tool_call)
            if concurrency_group and concurrency_group in concurrency_groups:
                break
            batch.append(tool_call)
            if concurrency_group:
                concurrency_groups.add(concurrency_group)
        return batch if batch else calls[start_index:start_index + 1]

    def _concurrency_group(self, tool_call: dict) -> str:
        function = (tool_call or {}).get("function") or {}
        spec = get_tool(str(function.get("name") or ""))
        return str(getattr(spec, "concurrency_group", "") or "") if spec else ""

    def _is_parallel_safe_read_call(self, tool_call: dict) -> bool:
        function = (tool_call or {}).get("function") or {}
        spec = get_tool(str(function.get("name") or ""))
        if not spec:
            return False
        return (
            spec.permission == "safe_read"
            and bool(spec.parallel_safe)
            and bool(spec.idempotent)
        )

    async def _observe_tool_result(
        self,
        state: AgentState,
        config: AgentRunConfig,
        guard: LoopGuard,
        tool_call: dict,
        tool_result: ToolResult,
    ) -> Optional[AgentRunResult]:
        state.add_tool_result(tool_result)
        if self.tool_result_observer:
            await _maybe_await(self.tool_result_observer(tool_result, state))

        if tool_result.status == TOOL_STATUS_PERMISSION_REQUIRED:
            state.stop_reason = STOP_REASON_WAITING_CONFIRMATION
            state.pending_action_id = tool_result.pending_action_id
            await self._emit_progress(AgentProgressEvent(
                kind=PROGRESS_WAITING_CONFIRMATION,
                tools=[self._progress_call_from_result(tool_result, tool_call)],
                status=TOOL_STATUS_PERMISSION_REQUIRED,
            ), state)
            return AgentRunResult(tool_result.content, STOP_REASON_WAITING_CONFIRMATION, state)

        if self._is_required_current_information_call(tool_call, config):
            state.required_web_tools_attempted.append(tool_result.name)
            if self._current_information_result_satisfied(tool_result):
                state.current_information_satisfied = True
            elif self._is_local_football_knowledge_result(tool_result):
                state.required_web_failure_code = self._current_information_failure_code(tool_result)
            else:
                state.stop_reason = STOP_REASON_REQUIRED_CURRENT_INFORMATION_UNAVAILABLE
                state.required_web_failure_code = self._current_information_failure_code(tool_result)
                await self._emit_progress(AgentProgressEvent(
                    kind=PROGRESS_RUNTIME_STOPPED,
                    status=STOP_REASON_REQUIRED_CURRENT_INFORMATION_UNAVAILABLE,
                    metadata={"stop_reason": STOP_REASON_REQUIRED_CURRENT_INFORMATION_UNAVAILABLE},
                ), state)
                return AgentRunResult(
                    self._required_current_information_unavailable_message(state),
                    STOP_REASON_REQUIRED_CURRENT_INFORMATION_UNAVAILABLE,
                    state,
                )

        state.total_observation_chars += len(str(tool_result.content or ""))
        guard_reason = guard.after_observation(state.total_observation_chars)
        if guard_reason:
            state.stop_reason = STOP_REASON_LOOP_GUARD
            await self._emit_progress(AgentProgressEvent(
                kind=PROGRESS_RUNTIME_STOPPED,
                status=STOP_REASON_LOOP_GUARD,
                metadata={"stop_reason": STOP_REASON_LOOP_GUARD},
            ), state)
            return AgentRunResult(loop_guard_message(guard_reason), STOP_REASON_LOOP_GUARD, state)

        state.append_message({
            "role": "tool",
            "tool_call_id": tool_call.get("id", ""),
            "content": tool_result.content,
        })
        return None

    def _is_required_current_information_call(self, tool_call: dict, config: AgentRunConfig) -> bool:
        call_id = str((tool_call or {}).get("id") or "")
        return bool(call_id and call_id in set(config.required_current_information_tool_call_ids or []))

    def _should_skip_satisfied_current_information_call(
        self,
        tool_call: dict,
        config: AgentRunConfig,
        state: AgentState,
    ) -> bool:
        if not state.current_information_satisfied:
            return False
        if not self._is_required_current_information_call(tool_call, config):
            return False
        function = (tool_call or {}).get("function") or {}
        return str(function.get("name") or "") != "query_current_football_knowledge"

    def _current_information_result_satisfied(self, tool_result: ToolResult) -> bool:
        if tool_result.status != TOOL_STATUS_OK:
            return False
        if tool_result.status in {
            TOOL_STATUS_ERROR,
            TOOL_STATUS_INVALID_ARGUMENTS,
            TOOL_STATUS_TIMEOUT,
            TOOL_STATUS_UNAVAILABLE,
        }:
            return False
        if self._is_local_football_knowledge_result(tool_result):
            return self._local_football_knowledge_status(tool_result) == "fresh"
        return bool(str(tool_result.content or "").strip())

    def _current_information_failure_code(self, tool_result: ToolResult) -> str:
        if tool_result.status == TOOL_STATUS_OK and not str(tool_result.content or "").strip():
            return "EmptyObservation"
        if self._is_local_football_knowledge_result(tool_result):
            status = self._local_football_knowledge_status(tool_result)
            return "LocalFootballKnowledge{0}".format(status.title() if status else "Unavailable")
        return (
            tool_result.error_code
            or tool_result.status
            or "RequiredCurrentInformationUnavailable"
        )

    def _is_local_football_knowledge_result(self, tool_result: ToolResult) -> bool:
        return str(getattr(tool_result, "name", "") or "") == "query_current_football_knowledge"

    def _local_football_knowledge_status(self, tool_result: ToolResult) -> str:
        try:
            data = json.loads(str(tool_result.content or "{}"))
        except ValueError:
            return ""
        if not isinstance(data, dict):
            return ""
        return str(data.get("status") or "").strip().lower()

    def _required_current_information_unavailable_message(self, state: AgentState) -> str:
        value = str(state.metadata.get("current_info_failure_message") or "").strip()
        if value:
            return value
        return "这个问题依赖当前比赛或新闻信息，但这次联网查询没有获得可靠结果，我现在无法核实。"

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
        if not state.metadata.get("progress_final_synthesis_started"):
            await self._emit_progress(AgentProgressEvent(
                kind=PROGRESS_FINAL_SYNTHESIS_STARTED,
                metadata={"scene": self._synthesis_scene(state)},
            ), state)
        await self._emit_progress(AgentProgressEvent(
            kind=PROGRESS_FINISHED,
            status=STOP_REASON_FINAL,
        ), state)
        return AgentRunResult(
            final_content or "I need more information before I can complete this task.",
            STOP_REASON_FINAL,
            state,
        )

    async def _emit_progress(self, event: AgentProgressEvent, state: AgentState) -> None:
        if not self.progress_observer:
            return
        try:
            await _maybe_await(self.progress_observer(event, state))
        except Exception:
            LOGGER.warning("agent_progress_observer_failed", exc_info=True)

    def _progress_call_from_tool_call(self, tool_call: dict) -> ProgressToolCall:
        function = (tool_call or {}).get("function") or {}
        name = str(function.get("name") or "")
        spec = get_tool(name)
        return ProgressToolCall(
            call_id=str((tool_call or {}).get("id") or ""),
            name=name,
            permission=str(getattr(spec, "permission", "") or ""),
            argument_keys=self._argument_keys(function.get("arguments") or "{}"),
        )

    def _progress_call_from_result(self, result: ToolResult, tool_call: dict = None) -> ProgressToolCall:
        call_id = ""
        if tool_call:
            call_id = str((tool_call or {}).get("id") or "")
        return ProgressToolCall(
            call_id=call_id,
            name=str(getattr(result, "name", "") or ""),
            permission=str(getattr(result, "permission", "") or ""),
        )

    def _argument_keys(self, raw_arguments) -> list:
        try:
            value = json.loads(str(raw_arguments or "{}"))
        except Exception:
            return []
        if not isinstance(value, dict):
            return []
        return sorted(str(key) for key in value.keys())

    def _progress_status(self, result: ToolResult) -> str:
        status = str(getattr(result, "status", "") or "")
        if status == TOOL_STATUS_OK:
            return "ok" if str(getattr(result, "content", "") or "").strip() else "empty"
        if status == TOOL_STATUS_TIMEOUT:
            return "timeout"
        if status == TOOL_STATUS_UNAVAILABLE:
            return "unavailable"
        if status == TOOL_STATUS_PERMISSION_REQUIRED:
            return "permission_required"
        return "error"

    def _synthesis_scene(self, state: AgentState) -> str:
        names = [str(getattr(result, "name", "") or "") for result in list(state.tool_results or [])]
        if any(name in {"solve_math_question", "solve_algorithm_problem", "solve_code_question", "solve_science_question"} for name in names):
            return "math"
        if any(name == "analyze_image" for name in names):
            return "image"
        if any(name in {"grok_search", "web_search", "web_fetch", "verify_recent_claim", "fetch_x_post", "search_news", "search_football_news"} for name in names):
            return "news"
        return ""

    def _progress_round_index(self, state: AgentState) -> int:
        if not isinstance(state.trace, dict):
            return 0
        value = state.trace.get("rounds", 0)
        if isinstance(value, list):
            return len(value)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
