from dataclasses import dataclass
from typing import Optional

from .classification import classify_event
from .clustering import build_story_cluster_id
from .dedupe import canonical_content_fingerprint
from .entities import extract_entities
from .models import FootballNewsItem
from .normalize import normalize_published_time, normalize_url
from .source_ranking import confidence_for_source, source_level_for_url
from .vector_index import build_item_chroma_id


@dataclass
class IngestionResult:
    inserted: bool
    duplicate: bool = False
    index_status: str = ""
    chroma_id: str = ""
    error_summary: str = ""


def candidate_to_item(candidate, source_config, entity_catalog, fetched_at: int) -> FootballNewsItem:
    canonical_url = normalize_url(getattr(candidate, "url", ""))
    title = str(getattr(candidate, "title", "") or "")
    summary = str(getattr(candidate, "snippet", "") or "")
    classification = classify_event(title, summary)
    entities = extract_entities("%s %s" % (title, summary), entity_catalog)
    published_at, reason_codes = normalize_published_time(getattr(candidate, "published_time", ""), fetched_at)
    source_level = source_level_for_url(canonical_url, source_config)
    confidence = confidence_for_source(
        source_level,
        has_body=bool(summary),
        has_published_time="published_time_inferred" not in reason_codes,
    )
    content_hash = canonical_content_fingerprint(title, getattr(candidate, "source_name", ""), canonical_url)
    story_cluster_id = build_story_cluster_id(
        classification.event_type,
        entities.teams,
        entities.players,
        entities.competitions[0] if entities.competitions else "",
        published_at or fetched_at,
    )
    return FootballNewsItem(
        news_id=content_hash,
        title=title,
        summary=summary,
        canonical_url=canonical_url,
        source_name=str(getattr(candidate, "source_name", "") or ""),
        source_domain=str(getattr(candidate, "source_name", "") or ""),
        source_type="media",
        source_level=source_level,
        event_type=classification.event_type,
        competition=entities.competitions[0] if entities.competitions else "",
        teams=entities.teams,
        players=entities.players,
        coaches=[],
        published_at=published_at,
        fetched_at=int(fetched_at),
        last_verified_at=int(fetched_at),
        expires_at=0,
        status=classification.status,
        confidence=confidence,
        story_cluster_id=story_cluster_id,
        content_hash=content_hash,
        evidence_urls=[canonical_url] if canonical_url else [],
    )


class FootballIngestionService(object):
    def __init__(self, sqlite_store, chroma_store):
        self.sqlite_store = sqlite_store
        self.chroma_store = chroma_store

    def ingest_item(self, item: FootballNewsItem) -> IngestionResult:
        chroma_id = build_item_chroma_id(item)
        inserted = self.sqlite_store.insert_pending_item(item, chroma_id)
        if not inserted:
            return IngestionResult(inserted=False, duplicate=True, chroma_id=chroma_id)
        try:
            self.chroma_store.add_item(item)
        except Exception as exc:
            self.sqlite_store.mark_index_status(chroma_id, "failed")
            return IngestionResult(
                inserted=True,
                index_status="failed",
                chroma_id=chroma_id,
                error_summary="%s: %s" % (type(exc).__name__, exc),
            )
        self.sqlite_store.mark_index_status(chroma_id, "ready")
        return IngestionResult(inserted=True, index_status="ready", chroma_id=chroma_id)
