import json

from plugins.arteta_football_intelligence.config import (
    DEFAULT_SOURCE_CONFIG,
    FootballIntelligenceSettings,
    load_source_config,
    load_settings,
)


def test_load_settings_reads_feature_flags_and_limits():
    env = {
        "ARTETA_FOOTBALL_INTELLIGENCE_ENABLED": "true",
        "ARTETA_FOOTBALL_KNOWLEDGE_FIRST": "1",
        "ARTETA_FOOTBALL_WRITE_THROUGH_ENABLED": "yes",
        "ARTETA_FOOTBALL_SYNC_MAX_CANDIDATES": "42",
        "ARTETA_FOOTBALL_SYNC_FETCH_CONCURRENCY": "2",
        "ARTETA_FOOTBALL_SYNC_RETENTION_DAYS": "120",
        "ARTETA_FOOTBALL_TRANSFER_WINDOW_MODE": "false",
    }

    settings = load_settings(env=env)

    assert isinstance(settings, FootballIntelligenceSettings)
    assert settings.enabled is True
    assert settings.knowledge_first_enabled is True
    assert settings.write_through_enabled is True
    assert settings.max_candidates == 42
    assert settings.fetch_concurrency == 2
    assert settings.retention_days == 120
    assert settings.transfer_window_mode is False


def test_source_config_falls_back_to_safe_defaults_when_missing(tmp_path):
    config = load_source_config(str(tmp_path / "missing.json"))

    assert config.source_groups["official_primary"].source_level == "official"
    assert "arsenal.com" in config.source_groups["official_primary"].domains
    assert [pack.key for pack in config.topic_packs]
    assert config.topic_packs[0].queries


def test_source_config_loads_json_topic_packs(tmp_path):
    path = tmp_path / "sources.json"
    data = dict(DEFAULT_SOURCE_CONFIG)
    data["topic_packs"] = [
        {
            "key": "test_pack",
            "queries": ["Arsenal injuries latest"],
            "event_types": ["injury"],
            "priority": 7,
        }
    ]
    path.write_text(json.dumps(data), encoding="utf-8")

    config = load_source_config(str(path))

    assert config.topic_packs[0].key == "test_pack"
    assert config.topic_packs[0].event_types == ["injury"]
    assert config.topic_packs[0].priority == 7
