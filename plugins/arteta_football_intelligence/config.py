import copy
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional


DEFAULT_SOURCE_CONFIG = {
    "source_groups": {
        "official_primary": {
            "domains": ["arsenal.com", "premierleague.com", "uefa.com", "fifa.com"],
            "source_level": "official",
        },
        "authoritative_media_a": {
            "domains": ["bbc.com", "bbc.co.uk", "skysports.com", "espn.com", "reuters.com"],
            "source_level": "authoritative_media",
        },
    },
    "topic_packs": [
        {
            "key": "arsenal_priority",
            "queries": [
                "Arsenal latest official news injuries transfers contracts",
                "Arsenal match press conference training player update",
            ],
            "event_types": ["injury", "transfer", "contract", "press_conference", "training", "match_result"],
            "priority": 100,
        },
        {
            "key": "major_matches",
            "queries": [
                "major European football match results scorers lineups latest",
                "Premier League Champions League latest match results",
            ],
            "event_types": ["match_result", "lineup", "match_event"],
            "priority": 90,
        },
        {
            "key": "transfers",
            "queries": [
                "football transfer news official confirmed latest",
                "Premier League European transfer negotiations latest",
            ],
            "event_types": ["transfer", "contract"],
            "priority": 90,
        },
        {
            "key": "player_updates",
            "queries": ["football player injury suspension training return latest"],
            "event_types": ["injury", "suspension", "training"],
            "priority": 80,
        },
    ],
}


@dataclass
class SourceGroup:
    domains: List[str] = field(default_factory=list)
    source_level: str = "unknown"


@dataclass
class TopicPack:
    key: str
    queries: List[str] = field(default_factory=list)
    event_types: List[str] = field(default_factory=list)
    priority: int = 0


@dataclass
class SourceConfig:
    source_groups: Dict[str, SourceGroup] = field(default_factory=dict)
    topic_packs: List[TopicPack] = field(default_factory=list)


@dataclass
class FootballIntelligenceSettings:
    enabled: bool = False
    knowledge_first_enabled: bool = False
    write_through_enabled: bool = False
    deep_sync_cron: str = "15 6 * * *"
    incremental_sync_cron: str = "15 18 * * *"
    timezone: str = "Asia/Shanghai"
    max_candidates: int = 160
    fetch_concurrency: int = 3
    retention_days: int = 120
    source_config_path: str = "config/football_intelligence_sources.json"
    entity_config_path: str = "config/football_entities.json"
    transfer_window_mode: bool = False


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _int_value(env: Mapping[str, str], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(env.get(key, default)).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def load_settings(env: Optional[Mapping[str, str]] = None) -> FootballIntelligenceSettings:
    values = env if env is not None else os.environ
    return FootballIntelligenceSettings(
        enabled=_truthy(values.get("ARTETA_FOOTBALL_INTELLIGENCE_ENABLED", "false")),
        knowledge_first_enabled=_truthy(values.get("ARTETA_FOOTBALL_KNOWLEDGE_FIRST", "false")),
        write_through_enabled=_truthy(values.get("ARTETA_FOOTBALL_WRITE_THROUGH_ENABLED", "false")),
        deep_sync_cron=str(values.get("ARTETA_FOOTBALL_DEEP_SYNC_CRON", "15 6 * * *")),
        incremental_sync_cron=str(values.get("ARTETA_FOOTBALL_INCREMENTAL_SYNC_CRON", "15 18 * * *")),
        timezone=str(values.get("ARTETA_FOOTBALL_SYNC_TIMEZONE", "Asia/Shanghai")),
        max_candidates=_int_value(values, "ARTETA_FOOTBALL_SYNC_MAX_CANDIDATES", 160, 1, 1000),
        fetch_concurrency=_int_value(values, "ARTETA_FOOTBALL_SYNC_FETCH_CONCURRENCY", 3, 1, 10),
        retention_days=_int_value(values, "ARTETA_FOOTBALL_SYNC_RETENTION_DAYS", 120, 1, 3650),
        source_config_path=str(values.get("ARTETA_FOOTBALL_SOURCE_CONFIG", "config/football_intelligence_sources.json")),
        entity_config_path=str(values.get("ARTETA_FOOTBALL_ENTITY_CONFIG", "config/football_entities.json")),
        transfer_window_mode=_truthy(values.get("ARTETA_FOOTBALL_TRANSFER_WINDOW_MODE", "false")),
    )


def _load_json(path: Optional[str]) -> dict:
    if not path:
        return copy.deepcopy(DEFAULT_SOURCE_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else copy.deepcopy(DEFAULT_SOURCE_CONFIG)
    except Exception:
        return copy.deepcopy(DEFAULT_SOURCE_CONFIG)


def load_source_config(path: Optional[str] = None) -> SourceConfig:
    raw = _load_json(path)
    groups = {}
    for key, value in dict(raw.get("source_groups") or {}).items():
        if not isinstance(value, dict):
            continue
        domains = [str(item).strip().lower() for item in list(value.get("domains") or []) if str(item).strip()]
        groups[str(key)] = SourceGroup(
            domains=domains,
            source_level=str(value.get("source_level") or "unknown"),
        )

    packs = []
    for value in list(raw.get("topic_packs") or []):
        if not isinstance(value, dict):
            continue
        key = str(value.get("key") or "").strip()
        if not key:
            continue
        packs.append(TopicPack(
            key=key,
            queries=[str(item).strip() for item in list(value.get("queries") or []) if str(item).strip()],
            event_types=[str(item).strip() for item in list(value.get("event_types") or []) if str(item).strip()],
            priority=int(value.get("priority") or 0),
        ))

    if not groups or not packs:
        return load_source_config_from_dict(DEFAULT_SOURCE_CONFIG)
    return SourceConfig(source_groups=groups, topic_packs=packs)


def load_source_config_from_dict(raw: dict) -> SourceConfig:
    groups = {}
    for key, value in dict(raw.get("source_groups") or {}).items():
        groups[str(key)] = SourceGroup(
            domains=[str(item).strip().lower() for item in list(value.get("domains") or []) if str(item).strip()],
            source_level=str(value.get("source_level") or "unknown"),
        )
    packs = []
    for value in list(raw.get("topic_packs") or []):
        packs.append(TopicPack(
            key=str(value.get("key") or ""),
            queries=[str(item).strip() for item in list(value.get("queries") or []) if str(item).strip()],
            event_types=[str(item).strip() for item in list(value.get("event_types") or []) if str(item).strip()],
            priority=int(value.get("priority") or 0),
        ))
    return SourceConfig(source_groups=groups, topic_packs=packs)
