import hashlib
from datetime import datetime
from typing import List

from .dedupe import build_event_key
from .source_ranking import compare_source_level


TRANSFER_STATUS_ORDER = [
    "rumor",
    "reported",
    "contacted",
    "bid_submitted",
    "negotiating",
    "advanced",
    "agreement_reached",
    "confirmed",
]


def build_story_cluster_id(
    event_type: str,
    teams: List[str],
    players: List[str],
    competition: str,
    published_at: int,
) -> str:
    month_at = datetime.utcfromtimestamp(int(published_at or 0)).strftime("%Y-%m-01")
    key = build_event_key(event_type, teams, players, competition, int(datetime.strptime(month_at, "%Y-%m-%d").timestamp()))
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return "football_story_%s" % digest


def choose_transfer_status(
    current_status: str,
    new_status: str,
    current_source_level: str = "unknown",
    new_source_level: str = "unknown",
) -> str:
    current = str(current_status or "reported")
    new = str(new_status or "reported")
    if new in ("denied", "collapsed", "superseded"):
        if compare_source_level(new_source_level, current_source_level) >= 0 or new_source_level == "official":
            return new
        return current
    if current == "confirmed" and new != "confirmed":
        return current
    if new == "confirmed":
        if compare_source_level(new_source_level, current_source_level) >= 0 or current != "confirmed":
            return new
    if _status_rank(new) > _status_rank(current):
        return new
    return current


def _status_rank(status: str) -> int:
    try:
        return TRANSFER_STATUS_ORDER.index(status)
    except ValueError:
        return 0
