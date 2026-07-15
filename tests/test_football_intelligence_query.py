from pathlib import Path

from plugins.arteta_football_intelligence.models import FootballKnowledgeQuery, FootballNewsItem
from plugins.arteta_football_intelligence.query import query_current_football_knowledge
from plugins.arteta_football_intelligence.storage import FootballNewsSQLiteStore
from plugins.arteta_football_intelligence.vector_index import build_item_chroma_id


def _store_with_item(tmp_path, fetched_at=1780000000, event_type="injury", source_level="official"):
    store = FootballNewsSQLiteStore(str(Path(tmp_path) / "news.db"))
    store.initialize()
    item = FootballNewsItem(
        news_id="news-1",
        title="Arsenal confirm Saka injury update",
        summary="Bukayo Saka returned to training.",
        canonical_url="https://www.arsenal.com/news/saka-update",
        source_name="Arsenal",
        source_domain="arsenal.com",
        source_type="official_site",
        source_level=source_level,
        event_type=event_type,
        competition="Premier League",
        teams=["Arsenal"],
        players=["Bukayo Saka"],
        published_at=fetched_at,
        fetched_at=fetched_at,
        last_verified_at=fetched_at,
        status="confirmed",
        confidence=0.98,
        content_hash="hash-saka",
        evidence_urls=["https://www.arsenal.com/news/saka-update"],
    )
    chroma_id = build_item_chroma_id(item)
    assert store.insert_pending_item(item, chroma_id) is True
    store.mark_index_status(chroma_id, "ready")
    return store


def test_query_returns_fresh_for_recent_reliable_local_item(tmp_path):
    store = _store_with_item(tmp_path)
    result = query_current_football_knowledge(
        store,
        FootballKnowledgeQuery(
            query="萨卡最近伤病怎么样",
            event_types=["injury"],
            players=["Bukayo Saka"],
            max_age_seconds=21600,
            min_source_level="authoritative_media",
        ),
        now=1780000100,
    )

    assert result.status == "fresh"
    assert result.requires_web_refresh is False
    assert result.items[0].title == "Arsenal confirm Saka injury update"
    assert result.reason_codes == []


def test_query_marks_stale_and_requires_web_refresh_for_old_item(tmp_path):
    store = _store_with_item(tmp_path, fetched_at=1780000000 - 10 * 3600)
    result = query_current_football_knowledge(
        store,
        FootballKnowledgeQuery(query="萨卡伤病", event_types=["injury"], players=["Bukayo Saka"], max_age_seconds=21600),
        now=1780000000,
    )

    assert result.status == "stale"
    assert result.requires_web_refresh is True
    assert "stale" in result.reason_codes


def test_query_returns_miss_when_no_matching_item(tmp_path):
    store = _store_with_item(tmp_path, event_type="transfer")
    result = query_current_football_knowledge(
        store,
        FootballKnowledgeQuery(query="萨卡伤病", event_types=["injury"], players=["Bukayo Saka"], max_age_seconds=21600),
        now=1780000100,
    )

    assert result.status == "miss"
    assert result.requires_web_refresh is True
    assert "no_local_match" in result.reason_codes


def test_agent_tool_registers_current_football_knowledge_with_strict_schema():
    from plugins.arteta_agent.registry import clear_registry, get_tool
    from plugins.arteta_agent.tools.football_news import register_tools

    clear_registry()
    register_tools()

    spec = get_tool("query_current_football_knowledge")
    assert spec is not None
    assert spec.permission == "safe_read"
    assert spec.parameters["additionalProperties"] is False
    assert spec.parameters["properties"]["event_types"]["items"]["enum"]
    assert spec.parameters["properties"]["max_results"]["minimum"] == 1
    assert spec.parameters["properties"]["max_results"]["maximum"] == 10
    assert spec.parameters["properties"]["max_age_seconds"]["maximum"] == 604800
