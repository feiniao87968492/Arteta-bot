import hashlib
import re
from datetime import datetime
from typing import List

from .normalize import normalize_url


def canonical_content_fingerprint(title: str, source: str, url: str = "") -> str:
    value = "|".join([
        _normalize_text(title),
        _normalize_text(source),
        normalize_url(url),
    ])
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def build_event_key(
    event_type: str,
    teams: List[str],
    players: List[str],
    competition: str,
    published_at: int,
) -> str:
    event = _slug(event_type or "other")
    date_text = datetime.utcfromtimestamp(int(published_at or 0)).strftime("%Y-%m-%d")
    if event == "transfer":
        date_text = date_text[:7]
    subject = "-".join([_slug(item) for item in (players or teams or ["unknown"])])
    team_key = "-".join([_slug(item) for item in teams or []])
    comp = _normalize_text(competition or "")
    if event == "match_result":
        return "%s|%s|%s|%s" % (event, team_key or subject, comp, date_text)
    parts = [event, subject]
    if team_key:
        parts.append(team_key)
    if comp:
        parts.append(comp)
    parts.append(date_text)
    return "|".join(parts)


def is_duplicate_candidate(existing: dict, candidate: dict) -> bool:
    for key in ("canonical_url", "content_hash", "event_key"):
        left = str(existing.get(key) or "")
        right = str(candidate.get(key) or "")
        if left and right and left == right:
            return True
    return False


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[!！。；;，,：:]+", "", str(value or "").lower())).strip()


def _slug(value: str) -> str:
    return re.sub(r"\s+", "-", _normalize_text(value)).strip("-")
