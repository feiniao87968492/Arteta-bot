import calendar
import re
from datetime import datetime
from typing import List, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "ref", "spm", "from"}


def normalize_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return ""
    netloc = parsed.netloc.lower()
    if not netloc:
        return ""
    path = parsed.path or ""
    if path != "/":
        path = path.rstrip("/")
    query_items = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_QUERY_KEYS or any(lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_items.append((key, item_value))
    query = urlencode(query_items, doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def normalize_published_time(value: object, fetched_at: int) -> Tuple[int, List[str]]:
    reasons = []
    timestamp = _parse_timestamp(value)
    if timestamp <= 0:
        reasons.append("published_time_inferred")
        return int(fetched_at or 0), reasons
    if timestamp > int(fetched_at or 0) + 600:
        reasons.append("published_time_in_future")
        return 0, reasons
    return timestamp, reasons


def _parse_timestamp(value: object) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return 0
    if re.fullmatch(r"\d{10}", text):
        return int(text)
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                return calendar.timegm(parsed.utctimetuple())
            return calendar.timegm(parsed.timetuple())
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return calendar.timegm(datetime.strptime(text, fmt).timetuple())
        except ValueError:
            continue
    return 0
