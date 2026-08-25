from plugins.arteta_football_intelligence.models import (
    EVENT_TYPES,
    SOURCE_LEVELS,
    TRANSFER_STATUSES,
    FootballKnowledgeQuery,
    FootballKnowledgeResult,
    FootballNewsItem,
    FootballSyncRun,
)


def test_football_news_item_defaults_are_python38_dataclasses():
    item = FootballNewsItem(
        news_id="news-1",
        title="Arsenal confirm Saka update",
        summary="Bukayo Saka returned to training.",
        canonical_url="https://www.arsenal.com/news/saka-update",
        source_name="Arsenal",
        source_domain="arsenal.com",
        source_type="official_site",
        source_level="official",
        event_type="training",
        competition="Premier League",
    )

    assert item.status == "reported"
    assert item.confidence == 0.0
    assert item.teams == []
    assert item.players == []
    assert item.evidence_urls == []

    other = FootballNewsItem(
        news_id="news-2",
        title="Other",
        summary="Other",
        canonical_url="https://example.com/other",
        source_name="Example",
        source_domain="example.com",
        source_type="media",
        source_level="unknown",
        event_type="other",
        competition="",
    )
    item.players.append("Bukayo Saka")
    assert other.players == []


def test_domain_constants_cover_plan_values():
    assert "match_result" in EVENT_TYPES
    assert "transfer" in EVENT_TYPES
    assert "injury" in EVENT_TYPES
    assert "press_conference" in EVENT_TYPES
    assert "confirmed" in TRANSFER_STATUSES
    assert "collapsed" in TRANSFER_STATUSES
    assert SOURCE_LEVELS == [
        "official",
        "authoritative_media",
        "trusted_reporter",
        "aggregator",
        "unknown",
    ]


def test_sync_run_and_query_result_defaults():
    run = FootballSyncRun(run_id="run-1", job_type="deep", started_at=100)
    assert run.status == "running"
    assert run.inserted_count == 0
    assert run.error_summary == ""

    query = FootballKnowledgeQuery(query="Saka injury", event_types=["injury"])
    assert query.max_results == 6
    assert query.max_age_seconds == 0

    result = FootballKnowledgeResult(status="miss", last_synced_at=0, newest_item_at=0)
    assert result.requires_web_refresh is False
    assert result.items == []
    assert result.reason_codes == []
