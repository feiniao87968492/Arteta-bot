from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class AgentRunConfig:
    max_rounds: int = 6
    max_tool_calls: int = 10
    max_same_tool_call_repeats: int = 2
    max_total_observation_chars: int = 80000
    request_timeout_seconds: float = 80.0
    stop_after_initial_tools: bool = False
    max_parallel_tools: int = 3
    tool_call_dependencies: Dict[str, List[str]] = field(default_factory=dict)
