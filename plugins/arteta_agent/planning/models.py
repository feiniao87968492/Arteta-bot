from dataclasses import dataclass, field
from typing import List, Set

from ..routing.models import PlannedToolCall


@dataclass
class AgentPlan:
    required_tools: List[PlannedToolCall] = field(default_factory=list)
    excluded_tools: Set[str] = field(default_factory=set)

