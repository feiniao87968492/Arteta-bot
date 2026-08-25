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
class ConversationEntities:
    players: List[str] = field(default_factory=list)
    teams: List[str] = field(default_factory=list)
    competitions: List[str] = field(default_factory=list)
    active_match: str = ""
    active_topic: str = ""
    replied_message: str = ""
    source_urls: List[str] = field(default_factory=list)


@dataclass
class FreshnessDecision:
    mode: str = "none"
    domain: str = ""
    intent: str = ""
    confidence: float = 0.0
    freshness_window: str = ""
    preferred_web_tools: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
    resolved_entities: List[str] = field(default_factory=list)
    query_hint: str = ""


@dataclass
class RouteDecision:
    intents: List[Intent] = field(default_factory=list)
    required_tools: List[PlannedToolCall] = field(default_factory=list)
    excluded_tools: Set[str] = field(default_factory=set)
    allowed_categories: Set[str] = field(default_factory=set)
    constraints: Dict[str, object] = field(default_factory=dict)
    freshness: FreshnessDecision = field(default_factory=FreshnessDecision)
