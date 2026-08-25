from dataclasses import dataclass, field
from typing import Dict, List, Set

from ..routing.models import PlannedToolCall


@dataclass
class AgentPlan:
    required_tools: List[PlannedToolCall] = field(default_factory=list)
    excluded_tools: Set[str] = field(default_factory=set)
    constraints: Dict[str, object] = field(default_factory=dict)
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
