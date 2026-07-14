import asyncio
import logging

from plugins.arteta_agent.progress.models import (
    PROGRESS_FINAL_SYNTHESIS_STARTED,
    PROGRESS_TOOL_BATCH_FINISHED,
    PROGRESS_TOOL_BATCH_STARTED,
    AgentProgressEvent,
    ProgressToolCall,
)
from plugins.arteta_agent.progress.reporter import DebugProgressReporter, ProgressReporterConfig


def test_reporter_suppresses_fast_requests_before_initial_delay():
    sent = []
    reporter = DebugProgressReporter(
        send_message=lambda text: sent.append(text),
        config=ProgressReporterConfig(initial_delay_seconds=0.05, minimum_update_interval_seconds=0.0),
    )

    async def scenario():
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_STARTED, tools=[ProgressToolCall("c1", "grok_search")]))
        await reporter.close()
        await asyncio.sleep(0.06)

    asyncio.run(scenario())

    assert sent == []


def test_reporter_prioritizes_action_dedupes_and_limits_messages():
    sent = []
    reporter = DebugProgressReporter(
        send_message=lambda text: sent.append(text),
        config=ProgressReporterConfig(
            initial_delay_seconds=0.0,
            minimum_update_interval_seconds=0.0,
            maximum_messages=2,
        ),
    )

    async def scenario():
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_STARTED, tools=[ProgressToolCall("c1", "grok_search")]))
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_STARTED, tools=[ProgressToolCall("c1", "grok_search")]))
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_FINISHED, tools=[ProgressToolCall("c1", "grok_search")], status="ok"))
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_FINAL_SYNTHESIS_STARTED))
        await reporter.close()

    asyncio.run(scenario())

    assert sent == [
        "[Action] 我将调用 grok_search 实时检索服务，检索最新新闻、官宣、记者原帖和 X/Twitter 实时线索。",
        "[Observation] grok_search 调用完成（0.0 秒），已返回可用结果。",
    ]


def test_reporter_sends_synthesis_heartbeat_once_and_stops_after_close():
    sent = []
    reporter = DebugProgressReporter(
        send_message=lambda text: sent.append(text),
        config=ProgressReporterConfig(
            initial_delay_seconds=0.0,
            minimum_update_interval_seconds=0.0,
            synthesis_heartbeat_seconds=0.02,
        ),
    )

    async def scenario():
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_FINAL_SYNTHESIS_STARTED))
        await asyncio.sleep(0.05)
        await reporter.close()
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_FINAL_SYNTHESIS_STARTED))
        await asyncio.sleep(0.03)

    asyncio.run(scenario())

    assert sent.count("[Agent] 详细回答仍在生成，我正在整理结构、论据和排版。") == 1
    assert sent[-1] == "[Agent] 详细回答仍在生成，我正在整理结构、论据和排版。"


def test_reporter_sends_tool_heartbeat_once_and_cancels_on_tool_finish():
    sent = []
    reporter = DebugProgressReporter(
        send_message=lambda text: sent.append(text),
        config=ProgressReporterConfig(
            initial_delay_seconds=0.0,
            minimum_update_interval_seconds=0.0,
            tool_heartbeat_seconds=0.02,
            maximum_tool_heartbeats=1,
        ),
    )

    async def scenario():
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_STARTED, tools=[ProgressToolCall("c1", "grok_search")]))
        await asyncio.sleep(0.05)
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_FINISHED, tools=[ProgressToolCall("c1", "grok_search")], status="ok"))
        await asyncio.sleep(0.03)
        await reporter.close()

    asyncio.run(scenario())

    assert sent.count("[Agent] 工具调用仍在执行，我会在返回后继续整理结果。") == 1


def test_reporter_cancels_tool_heartbeat_when_tool_finishes_quickly():
    sent = []
    reporter = DebugProgressReporter(
        send_message=lambda text: sent.append(text),
        config=ProgressReporterConfig(
            initial_delay_seconds=0.0,
            minimum_update_interval_seconds=0.0,
            tool_heartbeat_seconds=0.04,
            maximum_tool_heartbeats=1,
        ),
    )

    async def scenario():
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_STARTED, tools=[ProgressToolCall("c1", "grok_search")]))
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_FINISHED, tools=[ProgressToolCall("c1", "grok_search")], status="ok"))
        await asyncio.sleep(0.06)
        await reporter.close()

    asyncio.run(scenario())

    assert "[Agent] 工具调用仍在执行，我会在返回后继续整理结果。" not in sent


def test_reporter_respects_minimum_update_interval():
    sent = []
    reporter = DebugProgressReporter(
        send_message=lambda text: sent.append((text, asyncio.get_event_loop().time())),
        config=ProgressReporterConfig(
            initial_delay_seconds=0.0,
            minimum_update_interval_seconds=0.06,
            maximum_messages=3,
        ),
    )

    async def scenario():
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_STARTED, tools=[ProgressToolCall("c1", "grok_search")]))
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_FINISHED, tools=[ProgressToolCall("c1", "grok_search")], status="ok"))
        await reporter.close()

    asyncio.run(scenario())

    assert len(sent) == 2
    assert sent[1][1] - sent[0][1] >= 0.04


def test_reporter_close_during_minimum_interval_prevents_pending_send():
    sent = []
    reporter = DebugProgressReporter(
        send_message=lambda text: sent.append(text),
        config=ProgressReporterConfig(
            initial_delay_seconds=0.0,
            minimum_update_interval_seconds=0.08,
            maximum_messages=3,
        ),
    )

    async def scenario():
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_STARTED, tools=[ProgressToolCall("c1", "grok_search")]))
        pending = asyncio.create_task(reporter.handle_event(AgentProgressEvent(
            kind=PROGRESS_TOOL_BATCH_FINISHED,
            tools=[ProgressToolCall("c1", "grok_search")],
            status="ok",
        )))
        await asyncio.sleep(0.01)
        await reporter.close()
        await pending

    asyncio.run(scenario())

    assert len(sent) == 1
    assert sent[0].startswith("[Action]")


def test_reporter_send_errors_are_swallowed():
    calls = []

    def broken_send(text):
        calls.append(text)
        raise RuntimeError("send failed")

    reporter = DebugProgressReporter(
        send_message=broken_send,
        config=ProgressReporterConfig(initial_delay_seconds=0.0, minimum_update_interval_seconds=0.0),
    )

    async def scenario():
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_STARTED, tools=[ProgressToolCall("c1", "grok_search")]))
        await reporter.close()

    asyncio.run(scenario())

    assert len(calls) == 1


def test_reporter_records_message_ids_and_recalls_them_once():
    sent = []
    recalled = []

    async def send_message(text):
        message_id = 1000 + len(sent)
        sent.append((message_id, text))
        return {"message_id": message_id}

    async def recall_message(message_id):
        recalled.append(message_id)

    reporter = DebugProgressReporter(
        send_message=send_message,
        recall_message=recall_message,
        config=ProgressReporterConfig(initial_delay_seconds=0.0, minimum_update_interval_seconds=0.0),
    )

    async def scenario():
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_STARTED, tools=[ProgressToolCall("c1", "grok_search")]))
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_FINISHED, tools=[ProgressToolCall("c1", "grok_search")], status="ok"))
        await reporter.recall_sent_messages()
        await reporter.recall_sent_messages()

    asyncio.run(scenario())

    assert [item[0] for item in sent] == [1000, 1001]
    assert recalled == [1000, 1001]


def test_reporter_recall_errors_are_counted_logged_and_retried(caplog):
    calls = []

    async def recall_message(message_id):
        calls.append(message_id)
        if len(calls) == 1:
            raise RuntimeError("delete failed")

    reporter = DebugProgressReporter(
        send_message=lambda text: {"message_id": 3003},
        recall_message=recall_message,
        config=ProgressReporterConfig(initial_delay_seconds=0.0, minimum_update_interval_seconds=0.0),
    )

    async def scenario():
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_STARTED, tools=[ProgressToolCall("c1", "grok_search")]))
        first_result = await reporter.recall_sent_messages()
        second_result = await reporter.recall_sent_messages()
        return first_result, second_result

    caplog.set_level(logging.WARNING, logger="plugins.arteta_agent.progress.reporter")

    first, second = asyncio.run(scenario())

    assert (first.attempted, first.succeeded, first.failed) == (1, 0, 1)
    assert (second.attempted, second.succeeded, second.failed) == (1, 1, 0)
    assert calls == [3003, 3003]
    assert "Failed to recall agent progress message" in caplog.text


def test_reporter_extracts_message_id_from_object_response_and_swallows_recall_errors():
    class SendResult(object):
        message_id = "2002"

    recalled = []

    async def recall_message(message_id):
        recalled.append(message_id)
        raise RuntimeError("delete failed")

    reporter = DebugProgressReporter(
        send_message=lambda text: SendResult(),
        recall_message=recall_message,
        config=ProgressReporterConfig(initial_delay_seconds=0.0, minimum_update_interval_seconds=0.0),
    )

    async def scenario():
        await reporter.handle_event(AgentProgressEvent(kind=PROGRESS_TOOL_BATCH_STARTED, tools=[ProgressToolCall("c1", "grok_search")]))
        await reporter.recall_sent_messages()

    asyncio.run(scenario())

    assert recalled == ["2002"]
