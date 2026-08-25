from plugins.arteta_football_intelligence.config import load_source_config
from plugins.arteta_football_intelligence.source_ranking import (
    confidence_for_source,
    source_level_for_url,
)


def test_source_level_for_url_uses_configured_domain_groups():
    config = load_source_config("")

    assert source_level_for_url("https://www.arsenal.com/news/team-update", config) == "official"
    assert source_level_for_url("https://www.bbc.com/sport/football/arsenal", config) == "authoritative_media"
    assert source_level_for_url("https://random-blog.example/arsenal", config) == "unknown"


def test_confidence_for_source_applies_local_adjustments_and_caps():
    assert confidence_for_source("official", has_body=True, has_published_time=True) == 1.0
    assert confidence_for_source("aggregator", has_body=False, has_published_time=False) == 0.45
    assert confidence_for_source("trusted_reporter", is_single_social_source=True) <= 0.45
    assert confidence_for_source("authoritative_media", conflicts_with_official=True) < 0.82
