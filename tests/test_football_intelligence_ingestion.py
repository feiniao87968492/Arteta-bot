from pathlib import Path

from plugins.arteta_football_intelligence.config import load_source_config
from plugins.arteta_football_intelligence.entities import load_entity_catalog
from plugins.arteta_football_intelligence.ingestion import FootballIngestionService, candidate_to_item
from plugins.arteta_football_intelligence.sources.base import RawFootballCandidate
from plugins.arteta_football_intelligence.storage import FootballNewsSQLiteStore


class RecordingChromaStore(object):
    def __init__(self, fail=False):
        self.fail = fail
        self.items = []

    def add_item(self, item):
        if self.fail:
            raise RuntimeError("chroma unavailable")
        self.items.append(item)
        return "ok"


def _candidate():
    return RawFootballCandidate(
        title="Arsenal confirm Saka injury update",
        url="https://www.arsenal.com/news/saka-update?utm_source=x",
        source_name="Arsenal",
        source_key="grok_bridge",
        snippet="Bukayo Saka returned to training after injury.",
        published_time="2026-05-23T12:30:00Z",
        event_types=["injury"],
    )


def test_candidate_to_item_normalizes_source_entities_and_classification():
    item = candidate_to_item(
        _candidate(),
        source_config=load_source_config(""),
        entity_catalog=load_entity_catalog(""),
        fetched_at=1780000000,
    )

    assert item.canonical_url == "https://www.arsenal.com/news/saka-update"
    assert item.source_level == "official"
    assert item.event_type == "injury"
    assert item.players == ["Bukayo Saka"]
    assert item.teams == ["Arsenal"]
    assert item.published_at == 1779539400
    assert item.evidence_urls == [item.canonical_url]


def test_ingestion_service_writes_sqlite_ready_after_chroma_success(tmp_path):
    store = FootballNewsSQLiteStore(str(Path(tmp_path) / "news.db"))
    store.initialize()
    chroma = RecordingChromaStore()
    service = FootballIngestionService(store, chroma)
    item = candidate_to_item(_candidate(), load_source_config(""), load_entity_catalog(""), fetched_at=1780000000)

    result = service.ingest_item(item)

    assert result.inserted is True
    assert result.index_status == "ready"
    assert [row["index_status"] for row in store.list_recent_items(days=90, now=1780000100)] == ["ready"]
    assert [value.title for value in chroma.items] == [item.title]


def test_ingestion_service_keeps_sqlite_failed_when_chroma_fails(tmp_path):
    store = FootballNewsSQLiteStore(str(Path(tmp_path) / "news.db"))
    store.initialize()
    service = FootballIngestionService(store, RecordingChromaStore(fail=True))
    item = candidate_to_item(_candidate(), load_source_config(""), load_entity_catalog(""), fetched_at=1780000000)

    result = service.ingest_item(item)

    assert result.inserted is True
    assert result.index_status == "failed"
    assert [row["index_status"] for row in store.list_recent_items(days=90, now=1780000100)] == ["failed"]
