from urllib.parse import urlparse


SOURCE_BASE_CONFIDENCE = {
    "official": 0.95,
    "authoritative_media": 0.82,
    "trusted_reporter": 0.75,
    "aggregator": 0.45,
    "unknown": 0.25,
}

SOURCE_RANK = {
    "unknown": 0,
    "aggregator": 1,
    "trusted_reporter": 2,
    "authoritative_media": 3,
    "official": 4,
}


def source_level_for_url(url: str, source_config) -> str:
    domain = urlparse(str(url or "")).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    for group in getattr(source_config, "source_groups", {}).values():
        for candidate in list(getattr(group, "domains", []) or []):
            value = str(candidate or "").lower()
            if domain == value or domain.endswith("." + value):
                return str(getattr(group, "source_level", "") or "unknown")
    return "unknown"


def confidence_for_source(
    source_level: str,
    has_body: bool = False,
    has_published_time: bool = False,
    independent_authoritative_sources: int = 0,
    is_single_social_source: bool = False,
    conflicts_with_official: bool = False,
    stale_page: bool = False,
    entity_mismatch: bool = False,
) -> float:
    level = str(source_level or "unknown")
    value = SOURCE_BASE_CONFIDENCE.get(level, SOURCE_BASE_CONFIDENCE["unknown"])
    if has_body:
        value += 0.03
    if has_published_time:
        value += 0.02
    if independent_authoritative_sources >= 2:
        value += 0.08
    if conflicts_with_official:
        value -= 0.30
    if stale_page:
        value -= 0.10
    if entity_mismatch:
        value -= 0.20
    if is_single_social_source:
        value = min(value, 0.45)
    return round(max(0.0, min(1.0, value)), 2)


def compare_source_level(first: str, second: str) -> int:
    return SOURCE_RANK.get(str(first or "unknown"), 0) - SOURCE_RANK.get(str(second or "unknown"), 0)
