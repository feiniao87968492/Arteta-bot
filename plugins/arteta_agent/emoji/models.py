from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


ALLOWED_REACTIONS = (
    "celebration",
    "approval",
    "amused",
    "teasing",
    "surprised",
    "speechless",
    "thinking",
    "skeptical",
    "encouraging",
    "comforting",
    "frustrated",
    "sad",
    "none",
)
ALLOWED_INTENSITIES = ("low", "medium", "high")
ALLOWED_STANCES = ("shared_with_user", "toward_user", "toward_event", "toward_claim")
ALLOWED_TOPICS = (
    "general",
    "football",
    "football_news",
    "news",
    "meme",
    "technical",
    "injury",
    "transfer",
    "match",
)
ALLOWED_AVOID_CONTEXTS = (
    "serious_injury",
    "bereavement",
    "technical",
    "permission",
    "trace",
    "current_news",
    "safety",
)


def _normalize_value(value: str, allowed: Tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    if text in allowed:
        return text
    return default


def normalize_reaction(value: str, default: str = "none") -> str:
    return _normalize_value(value, ALLOWED_REACTIONS, default)


def normalize_intensity(value: str, default: str = "medium") -> str:
    return _normalize_value(value, ALLOWED_INTENSITIES, default)


def normalize_stance(value: str, default: str = "shared_with_user") -> str:
    return _normalize_value(value, ALLOWED_STANCES, default)


def normalize_topic(value: str, default: str = "general") -> str:
    return _normalize_value(value, ALLOWED_TOPICS, default)


def normalize_avoid_context(value: str, default: str = "") -> str:
    return _normalize_value(value, ALLOWED_AVOID_CONTEXTS, default)


def _normalize_list(values, normalizer, fallback: str = "") -> List[str]:
    result = []
    for value in values or []:
        normalized = normalizer(value)
        if normalized and normalized not in result:
            result.append(normalized)
    if not result and fallback:
        result.append(fallback)
    return result


@dataclass(frozen=True)
class EmojiGateDecision(object):
    should_send: bool
    confidence: float = 0.0
    reason_codes: List[str] = field(default_factory=list)
    explicit_request: bool = False


@dataclass(frozen=True)
class EmojiReactionDecision(object):
    reaction: str = "none"
    intensity: str = "medium"
    stance: str = "shared_with_user"
    topic: str = "general"
    confidence: float = 0.0
    reason_codes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reaction", normalize_reaction(self.reaction))
        object.__setattr__(self, "intensity", normalize_intensity(self.intensity))
        object.__setattr__(self, "stance", normalize_stance(self.stance))
        object.__setattr__(self, "topic", normalize_topic(self.topic))
        object.__setattr__(self, "confidence", max(0.0, min(float(self.confidence or 0.0), 1.0)))
        object.__setattr__(self, "reason_codes", [str(item) for item in self.reason_codes or [] if str(item or "").strip()])


@dataclass(frozen=True)
class EmojiAsset(object):
    name: str
    path: str
    relative_path: str
    reactions: List[str] = field(default_factory=list)
    intensities: List[str] = field(default_factory=list)
    stances: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    avoid_contexts: List[str] = field(default_factory=list)
    weight: float = 1.0
    reviewed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name or ""))
        object.__setattr__(self, "path", str(self.path or ""))
        object.__setattr__(self, "relative_path", str(self.relative_path or ""))
        object.__setattr__(self, "reactions", _normalize_list(self.reactions, normalize_reaction, "approval"))
        object.__setattr__(self, "intensities", _normalize_list(self.intensities, normalize_intensity, "medium"))
        object.__setattr__(self, "stances", _normalize_list(self.stances, normalize_stance, "shared_with_user"))
        object.__setattr__(self, "topics", _normalize_list(self.topics, normalize_topic, "general"))
        object.__setattr__(self, "avoid_contexts", _normalize_list(self.avoid_contexts, normalize_avoid_context))
        object.__setattr__(self, "weight", max(0.0, float(self.weight or 0.0)))


@dataclass(frozen=True)
class EmojiGateContext(object):
    user_text: str
    assistant_text: str
    group_id: str
    profile: Optional[Any] = None
    trace: Optional[Dict[str, Any]] = None
    route_hint: str = ""
    emoji_enabled: bool = True
    tool_disabled: bool = False
    has_assets: bool = True
    current_information_required: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

