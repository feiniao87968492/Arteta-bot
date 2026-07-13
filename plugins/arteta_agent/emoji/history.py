import time
from dataclasses import dataclass
from typing import Dict, List, Optional


MAX_HISTORY_PER_GROUP = 20
AUTO_COOLDOWN_STREAK = 2


@dataclass(frozen=True)
class EmojiHistoryRecord(object):
    asset_name: str
    reaction: str
    automatic: bool
    timestamp: float


_EMOJI_HISTORY = {}  # type: Dict[str, List[EmojiHistoryRecord]]


def reset_emoji_history_for_tests() -> None:
    _EMOJI_HISTORY.clear()


def get_emoji_history(group_id: str) -> List[EmojiHistoryRecord]:
    return list(_EMOJI_HISTORY.get(str(group_id or ""), []))


def record_emoji_send(
    group_id: str,
    asset_name: str,
    reaction: str,
    automatic: bool = True,
    timestamp: Optional[float] = None,
) -> None:
    key = str(group_id or "")
    history = list(_EMOJI_HISTORY.get(key, []))
    history.append(EmojiHistoryRecord(
        asset_name=str(asset_name or ""),
        reaction=str(reaction or "none"),
        automatic=bool(automatic),
        timestamp=float(time.time() if timestamp is None else timestamp),
    ))
    _EMOJI_HISTORY[key] = history[-MAX_HISTORY_PER_GROUP:]


def automatic_cooldown_active(group_id: str) -> bool:
    history = get_emoji_history(group_id)
    if len(history) < AUTO_COOLDOWN_STREAK:
        return False
    recent = history[-AUTO_COOLDOWN_STREAK:]
    return all(item.automatic for item in recent)

