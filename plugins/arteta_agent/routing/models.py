from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass(frozen=True)
class PlannedToolCall:
    name: str
    arguments: Dict[str, object] = field(default_factory=dict)
    reason: str = ""
    forced: bool = False


@dataclass(frozen=True)
class Intent:
    name: str
    confidence: float = 1.0
    reason: str = ""


@dataclass
class RouteDecision:
    intents: List[Intent] = field(default_factory=list)
    required_tools: List[PlannedToolCall] = field(default_factory=list)
    excluded_tools: Set[str] = field(default_factory=set)
    allowed_categories: Set[str] = field(default_factory=set)
    constraints: Dict[str, object] = field(default_factory=dict)

