import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Set

from .formatter import ProgressFormatterPolicy, format_progress_event
from .models import (
    PROGRESS_FINAL_SYNTHESIS_HEARTBEAT,
    PROGRESS_FINAL_SYNTHESIS_STARTED,
    PROGRESS_MODEL_ROUND_STARTED,
    PROGRESS_TOOL_BATCH_STARTED,
    PROGRESS_TOOL_BATCH_FINISHED,
    PROGRESS_TOOL_FINISHED,
    AgentProgressEvent,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProgressReporterConfig(object):
    initial_delay_seconds: float = 0.8
    minimum_update_interval_seconds: float = 1.8
    tool_heartbeat_seconds: float = 12.0
    synthesis_heartbeat_seconds: float = 10.0
    model_heartbeat_seconds: float = 15.0
    recall_timeout_seconds: float = 2.0
    maximum_messages: int = 9
    maximum_tool_heartbeats: int = 1
    maximum_synthesis_heartbeats: int = 1
    maximum_model_heartbeats: int = 1


@dataclass(frozen=True)
class ProgressRecallResult(object):
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0


class DebugProgressReporter(object):
    def __init__(
        self,
        send_message: Callable[[str], object],
        recall_message: Optional[Callable[[object], object]] = None,
        config: Optional[ProgressReporterConfig] = None,
        formatter_policy: Optional[ProgressFormatterPolicy] = None,
    ) -> None:
        self.send_message = send_message
        self.recall_message = recall_message
        self.config = config or ProgressReporterConfig()
        self.formatter_policy = formatter_policy or ProgressFormatterPolicy()
        self._closed = False
        self._sent_count = 0
        self._sent_texts: Set[str] = set()
        self._sent_message_ids: List[object] = []
        self._lock = asyncio.Lock()
        self._initial_task = None
        self._pending_initial_event = None
        self._synthesis_task = None
        self._synthesis_heartbeat_count = 0
        self._model_task = None
        self._model_heartbeat_count = 0
        self._tool_task = None
        self._tool_heartbeat_count = 0
        self._last_sent_at = 0.0

    async def handle_event(self, event: AgentProgressEvent) -> None:
        if self._closed:
            return
        if event.kind == PROGRESS_MODEL_ROUND_STARTED:
            self._schedule_model_heartbeat()
        if event.kind == PROGRESS_TOOL_BATCH_STARTED:
            self._cancel_model_heartbeat()
            self._schedule_tool_heartbeat()
        if event.kind in (PROGRESS_TOOL_BATCH_FINISHED, PROGRESS_TOOL_FINISHED):
            self._cancel_tool_heartbeat()
        if event.kind == PROGRESS_FINAL_SYNTHESIS_STARTED:
            self._cancel_model_heartbeat()
            self._schedule_synthesis_heartbeat()
        if self.config.initial_delay_seconds > 0 and self._sent_count == 0:
            self._pending_initial_event = event
            if self._initial_task is None:
                self._initial_task = asyncio.create_task(self._flush_initial_after_delay())
            return
        await self._send_event(event)

    async def close(self) -> None:
        self._closed = True
        for task in (self._initial_task, self._synthesis_task, self._model_task, self._tool_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        async with self._lock:
            return

    async def recall_sent_messages(self) -> ProgressRecallResult:
        if self.recall_message is None:
            return ProgressRecallResult()
        async with self._lock:
            message_ids = list(self._sent_message_ids)
            self._sent_message_ids = []
        attempted = 0
        succeeded = 0
        failed_ids = []
        for message_id in message_ids:
            attempted += 1
            try:
                value = self.recall_message(message_id)
                if inspect.isawaitable(value):
                    timeout = max(0.0, float(self.config.recall_timeout_seconds or 0))
                    if timeout > 0:
                        await asyncio.wait_for(value, timeout=timeout)
                    else:
                        await value
            except Exception:
                failed_ids.append(message_id)
                logger.warning(
                    "Failed to recall agent progress message message_id=%r",
                    message_id,
                    exc_info=True,
                )
                continue
            succeeded += 1
        if failed_ids:
            async with self._lock:
                self._sent_message_ids = failed_ids + self._sent_message_ids
        return ProgressRecallResult(
            attempted=attempted,
            succeeded=succeeded,
            failed=len(failed_ids),
        )

    async def _flush_initial_after_delay(self) -> None:
        try:
            await asyncio.sleep(max(0.0, float(self.config.initial_delay_seconds or 0)))
            event = self._pending_initial_event
            if event is not None and not self._closed:
                await self._send_event(event)
        except asyncio.CancelledError:
            raise

    async def _send_event(self, event: AgentProgressEvent) -> None:
        text = format_progress_event(event, self.formatter_policy)
        if not text:
            return
        await self._send_text(text)

    async def _send_text(self, text: str) -> None:
        if self._closed:
            return
        async with self._lock:
            if self._closed:
                return
            minimum_interval = max(0.0, float(self.config.minimum_update_interval_seconds or 0))
            if self._last_sent_at and minimum_interval > 0:
                loop = asyncio.get_running_loop()
                remaining = minimum_interval - (loop.time() - self._last_sent_at)
                if remaining > 0:
                    await asyncio.sleep(remaining)
                    if self._closed:
                        return
            if self._sent_count >= int(self.config.maximum_messages or 0):
                return
            if text in self._sent_texts:
                return
            self._sent_texts.add(text)
            self._sent_count += 1
            try:
                value = self.send_message(text)
                if inspect.isawaitable(value):
                    value = await value
                self._record_message_id(value)
                self._last_sent_at = asyncio.get_running_loop().time()
            except Exception:
                return

    def _record_message_id(self, send_result) -> None:
        message_id = None
        if isinstance(send_result, dict):
            message_id = send_result.get("message_id")
        else:
            message_id = getattr(send_result, "message_id", None)
        if message_id is None:
            return
        if isinstance(message_id, str) and not message_id.strip():
            return
        self._sent_message_ids.append(message_id)

    def _schedule_synthesis_heartbeat(self) -> None:
        if self._synthesis_task is not None or self._closed:
            return
        if int(self.config.maximum_synthesis_heartbeats or 0) <= 0:
            return
        self._synthesis_task = asyncio.create_task(self._send_synthesis_heartbeat_later())

    async def _send_synthesis_heartbeat_later(self) -> None:
        try:
            await asyncio.sleep(max(0.0, float(self.config.synthesis_heartbeat_seconds or 0)))
            if self._closed:
                return
            if self._synthesis_heartbeat_count >= int(self.config.maximum_synthesis_heartbeats or 0):
                return
            self._synthesis_heartbeat_count += 1
            await self._send_event(AgentProgressEvent(kind=PROGRESS_FINAL_SYNTHESIS_HEARTBEAT))
        except asyncio.CancelledError:
            raise

    def _schedule_model_heartbeat(self) -> None:
        if self._model_task is not None or self._closed:
            return
        if int(self.config.maximum_model_heartbeats or 0) <= 0:
            return
        self._model_task = asyncio.create_task(self._send_model_heartbeat_later())

    async def _send_model_heartbeat_later(self) -> None:
        try:
            await asyncio.sleep(max(0.0, float(self.config.model_heartbeat_seconds or 0)))
            if self._closed:
                return
            if self._model_heartbeat_count >= int(self.config.maximum_model_heartbeats or 0):
                return
            self._model_heartbeat_count += 1
            await self._send_text("[Agent] LLM 通道还在等待响应，我会在返回后继续整理结果。")
        except asyncio.CancelledError:
            raise

    def _cancel_model_heartbeat(self) -> None:
        if self._model_task and not self._model_task.done():
            self._model_task.cancel()
        self._model_task = None

    def _schedule_tool_heartbeat(self) -> None:
        if self._tool_task is not None or self._closed:
            return
        if int(self.config.maximum_tool_heartbeats or 0) <= 0:
            return
        self._tool_task = asyncio.create_task(self._send_tool_heartbeat_later())

    async def _send_tool_heartbeat_later(self) -> None:
        try:
            await asyncio.sleep(max(0.0, float(self.config.tool_heartbeat_seconds or 0)))
            if self._closed:
                return
            if self._tool_heartbeat_count >= int(self.config.maximum_tool_heartbeats or 0):
                return
            self._tool_heartbeat_count += 1
            await self._send_text("[Agent] 工具调用仍在执行，我会在返回后继续整理结果。")
        except asyncio.CancelledError:
            raise

    def _cancel_tool_heartbeat(self) -> None:
        if self._tool_task and not self._tool_task.done():
            self._tool_task.cancel()
        self._tool_task = None
