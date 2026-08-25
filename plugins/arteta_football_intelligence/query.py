import json
import time
from typing import List

from .freshness_policy import max_age_for_event_type
from .models import FootballKnowledgeQuery, FootballKnowledgeResult, FootballNewsItem
from .source_ranking import compare_source_level


QUERY_STATUSES = {"fresh", "stale", "miss", "conflict", "unavailable"}


def query_current_football_knowledge(
    sqlite_store,
    query: FootballKnowledgeQuery,
    now: int = None,
) -> FootballKnowledgeResult:
    current = int(now or time.time())
    max_age = int(query.max_age_seconds or _default_query_max_age(query))
    rows = sqlite_store.list_recent_items(days=3650, now=current)
    candidates = [_row_to_item(row) for row in rows]
    candidates = [_item for _item in candidates if _matches_query(_item, query)]
    if not candidates:
        return FootballKnowledgeResult(
            status="miss",
            last_synced_at=_latest_sync_time(sqlite_store),
            newest_item_at=0,
            items=[],
            requires_web_refresh=True,
            reason_codes=["no_local_match"],
        )
    if query.min_source_level:
        qualified = [
            item for item in candidates
            if compare_source_level(item.source_level, query.min_source_level) >= 0
        ]
        if not qualified:
            newest = max(int(item.last_verified_at or item.fetched_at or item.published_at or 0) for item in candidates)
            return FootballKnowledgeResult(
                status="stale",
                last_synced_at=_latest_sync_time(sqlite_store),
                newest_item_at=newest,
                items=candidates[:query.max_results],
                requires_web_refresh=True,
                reason_codes=["insufficient_source"],
            )
        candidates = qualified
    candidates.sort(key=lambda item: int(item.last_verified_at or item.fetched_at or item.published_at or 0), reverse=True)
    newest = int(candidates[0].last_verified_at or candidates[0].fetched_at or candidates[0].published_at or 0)
    if _has_conflict(candidates):
        return FootballKnowledgeResult(
            status="conflict",
            last_synced_at=_latest_sync_time(sqlite_store),
            newest_item_at=newest,
            items=candidates[:query.max_results],
            conflicts=["conflicting_status"],
            requires_web_refresh=True,
            reason_codes=["conflict"],
        )
    if max_age > 0 and newest < current - max_age:
        return FootballKnowledgeResult(
            status="stale",
            last_synced_at=_latest_sync_time(sqlite_store),
            newest_item_at=newest,
            items=candidates[:query.max_results],
            requires_web_refresh=True,
            reason_codes=["stale"],
        )
    return FootballKnowledgeResult(
        status="fresh",
        last_synced_at=_latest_sync_time(sqlite_store),
        newest_item_at=newest,
        items=candidates[:query.max_results],
        requires_web_refresh=False,
        reason_codes=[],
    )


def result_to_json(result: FootballKnowledgeResult) -> str:
    return json.dumps({
        "status": result.status,
        "last_synced_at": result.last_synced_at,
        "newest_item_at": result.newest_item_at,
        "requires_web_refresh": result.requires_web_refresh,
        "reason_codes": list(result.reason_codes or []),
        "conflicts": list(result.conflicts or []),
        "items": [_item_to_dict(item) for item in result.items],
    }, ensure_ascii=False)


def _default_query_max_age(query: FootballKnowledgeQuery) -> int:
    if query.event_types:
        return max_age_for_event_type(query.event_types[0])
    return max_age_for_event_type("other")


def _latest_sync_time(sqlite_store) -> int:
    latest = sqlite_store.latest_sync_run() if hasattr(sqlite_store, "latest_sync_run") else {}
    return int((latest or {}).get("finished_at") or (latest or {}).get("started_at") or 0)


def _matches_query(item: FootballNewsItem, query: FootballKnowledgeQuery) -> bool:
    if query.event_types and item.event_type not in set(query.event_types):
        return False
    if query.teams and not set(query.teams).intersection(set(item.teams)):
        return False
    if query.players and not set(query.players).intersection(set(item.players)):
        return False
    if query.competitions and item.competition not in set(query.competitions):
        return False
    text = "%s %s %s %s %s" % (
        item.title,
        item.summary,
        " ".join(item.teams),
        " ".join(item.players),
        item.competition,
    )
    tokens = [token for token in str(query.query or "").lower().split() if len(token) > 2]
    if not tokens:
        return True
    haystack = text.lower()
    return any(token in haystack for token in tokens) or bool(query.event_types or query.teams or query.players)


def _has_conflict(items: List[FootballNewsItem]) -> bool:
    statuses = set(item.status for item in items if item.status)
    return bool("denied" in statuses and ("confirmed" in statuses or "reported" in statuses))


def _row_to_item(row: dict) -> FootballNewsItem:
    return FootballNewsItem(
        news_id=str(row.get("content_hash") or row.get("id") or ""),
        title=str(row.get("title") or ""),
        summary=str(row.get("summary") or ""),
        canonical_url=str(row.get("canonical_url") or row.get("url") or ""),
        source_name=str(row.get("source") or ""),
        source_domain=str(row.get("source_domain") or ""),
        source_type=str(row.get("source_type") or "media"),
        source_level=str(row.get("source_level") or "unknown"),
        event_type=str(row.get("event_type") or "other"),
        competition=str(row.get("competition") or ""),
        teams=_json_list(row.get("teams_json")),
        players=_json_list(row.get("players_json")),
        coaches=_json_list(row.get("coaches_json")),
        published_at=int(row.get("published_at") or 0),
        fetched_at=int(row.get("fetched_at") or 0),
        last_verified_at=int(row.get("last_verified_at") or row.get("fetched_at") or 0),
        expires_at=int(row.get("expires_at") or 0),
        status=str(row.get("status") or "reported"),
        confidence=float(row.get("confidence") or 0.0),
        story_cluster_id=str(row.get("story_cluster_id") or ""),
        content_hash=str(row.get("content_hash") or ""),
        evidence_urls=_json_list(row.get("evidence_urls_json")) or [str(row.get("url") or "")],
    )


def _json_list(value) -> List[str]:
    try:
        data = json.loads(str(value or "[]"))
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item)]


def _item_to_dict(item: FootballNewsItem) -> dict:
    return {
        "title": item.title,
        "summary": item.summary,
        "source_name": item.source_name,
        "source_level": item.source_level,
        "published_at": item.published_at,
        "last_verified_at": item.last_verified_at,
        "status": item.status,
        "url": item.canonical_url,
    }
