from dataclasses import dataclass, field
from typing import Dict, List


PROGRESS_RUN_STARTED = "run_started"
PROGRESS_MODEL_ROUND_STARTED = "model_round_started"
PROGRESS_TOOL_BATCH_STARTED = "tool_batch_started"
PROGRESS_TOOL_FINISHED = "tool_finished"
PROGRESS_TOOL_BATCH_FINISHED = "tool_batch_finished"
PROGRESS_WAITING_CONFIRMATION = "waiting_confirmation"
PROGRESS_FINAL_SYNTHESIS_STARTED = "final_synthesis_started"
PROGRESS_FINAL_SYNTHESIS_HEARTBEAT = "final_synthesis_heartbeat"
PROGRESS_RUNTIME_STOPPED = "runtime_stopped"
PROGRESS_FINISHED = "finished"


@dataclass(frozen=True)
class ToolProgressSpec(object):
    service_type: str
    action_purpose: str
    visibility: str = "normal"
    synthesis_hint: str = ""


@dataclass(frozen=True)
class ProgressToolCall(object):
    call_id: str
    name: str
    permission: str = ""
    attempt: int = 1
    argument_keys: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentProgressEvent(object):
    kind: str
    round_index: int = 0
    tools: List[ProgressToolCall] = field(default_factory=list)
    status: str = ""
    duration_ms: int = 0
    error_code: str = ""
    metadata: Dict[str, object] = field(default_factory=dict)
