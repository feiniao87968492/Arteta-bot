from plugins.arteta_agent.progress.models import (
    PROGRESS_FINAL_SYNTHESIS_HEARTBEAT,
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


def test_progress_model_constants_cover_runtime_lifecycle():
    assert PROGRESS_RUN_STARTED == "run_started"
    assert PROGRESS_MODEL_ROUND_STARTED == "model_round_started"
    assert PROGRESS_TOOL_BATCH_STARTED == "tool_batch_started"
    assert PROGRESS_TOOL_FINISHED == "tool_finished"
    assert PROGRESS_TOOL_BATCH_FINISHED == "tool_batch_finished"
    assert PROGRESS_WAITING_CONFIRMATION == "waiting_confirmation"
    assert PROGRESS_FINAL_SYNTHESIS_STARTED == "final_synthesis_started"
    assert PROGRESS_FINAL_SYNTHESIS_HEARTBEAT == "final_synthesis_heartbeat"
    assert PROGRESS_RUNTIME_STOPPED == "runtime_stopped"
    assert PROGRESS_FINISHED == "finished"


def test_progress_event_is_sanitized_structural_data_only():
    call = ProgressToolCall(
        call_id="call-1",
        name="grok_search",
        permission="safe_read",
        attempt=1,
        argument_keys=["query", "max_results"],
    )
    event = AgentProgressEvent(
        kind=PROGRESS_TOOL_BATCH_STARTED,
        round_index=1,
        tools=[call],
        metadata={"status": "starting"},
    )

    assert event.tools[0].name == "grok_search"
    assert event.tools[0].argument_keys == ["query", "max_results"]
    assert not hasattr(event, "content")
    assert not hasattr(event, "args")
    assert not hasattr(event, "prompt")
