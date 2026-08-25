from dataclasses import dataclass, field
from typing import Dict, List


TOOL_STATUS_OK = "ok"
TOOL_STATUS_INVALID_ARGUMENTS = "invalid_arguments"
TOOL_STATUS_PERMISSION_REQUIRED = "permission_required"
TOOL_STATUS_DISABLED = "disabled"
TOOL_STATUS_TIMEOUT = "timeout"
TOOL_STATUS_ERROR = "error"
TOOL_STATUS_UNAVAILABLE = "unavailable"


@dataclass
class ToolResult:
    name: str
    permission: str
    status: str
    content: str
    args: Dict[str, object] = field(default_factory=dict)
    pending_action_id: str = ""
    markers: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    duration_ms: int = 0
    error_code: str = ""
    metadata: Dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.content

    @property
    def requires_confirmation(self) -> bool:
        return self.status == TOOL_STATUS_PERMISSION_REQUIRED
