from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from ..context import ToolContext
from ..result import ToolResult


STOP_REASON_FINAL = "final"
STOP_REASON_LOOP_GUARD = "loop_guard"
STOP_REASON_WAITING_CONFIRMATION = "waiting_confirmation"
STOP_REASON_INITIAL_TOOLS_COMPLETE = "initial_tools_complete"
STOP_REASON_MAX_ROUNDS = "max_rounds"
STOP_REASON_TIMEOUT = "timeout"
STOP_REASON_REQUIRED_CURRENT_INFORMATION_UNAVAILABLE = "required_current_information_unavailable"


@dataclass
class AgentState:
    messages: List[dict]
    ctx: ToolContext
    allowed_permissions: Set[str] = field(default_factory=set)
    disabled_tools: Set[str] = field(default_factory=set)
    policy_disabled_tools: Set[str] = field(default_factory=set)
    trace: Optional[dict] = None
    request_id: str = ""
    tool_call_count: int = 0
    total_observation_chars: int = 0
    stop_reason: str = ""
    pending_action_id: str = ""
    tool_results: List[ToolResult] = field(default_factory=list)
    metadata: Dict[str, object] = field(default_factory=dict)
    requires_current_information: bool = False
    current_information_satisfied: bool = False
    freshness_mode: str = "none"
    freshness_reason_codes: List[str] = field(default_factory=list)
    required_web_tools_attempted: List[str] = field(default_factory=list)
    required_web_failure_code: str = ""

    def append_message(self, message: dict) -> None:
        self.messages.append(message)

    def add_tool_result(self, result: ToolResult) -> None:
        self.tool_results.append(result)
        self.tool_call_count += 1


@dataclass
class AgentRunResult:
    content: str
    stop_reason: str
    state: AgentState


@dataclass
class FinalizedResponse:
    content: str
    tool_call_count: int = 0
