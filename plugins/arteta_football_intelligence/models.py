from dataclasses import dataclass, field
from typing import List


EVENT_TYPES = [
    "match_result",
    "fixture",
    "lineup",
    "match_event",
    "transfer",
    "contract",
    "injury",
    "suspension",
    "training",
    "press_conference",
    "manager_change",
    "player_form",
    "club_announcement",
    "disciplinary",
    "rumor",
    "other",
]

GENERAL_STATUSES = [
    "reported",
    "confirmed",
    "denied",
    "superseded",
    "expired",
]

TRANSFER_STATUSES = [
    "rumor",
    "reported",
    "contacted",
    "bid_submitted",
    "negotiating",
    "advanced",
    "agreement_reached",
    "confirmed",
    "denied",
    "collapsed",
    "superseded",
]

SOURCE_LEVELS = [
    "official",
    "authoritative_media",
    "trusted_reporter",
    "aggregator",
    "unknown",
]


@dataclass
class FootballNewsItem:
    news_id: str
    title: str
    summary: str
    canonical_url: str
    source_name: str
    source_domain: str
    source_type: str
    source_level: str
    event_type: str
    competition: str
    teams: List[str] = field(default_factory=list)
    players: List[str] = field(default_factory=list)
    coaches: List[str] = field(default_factory=list)
    published_at: int = 0
    fetched_at: int = 0
    last_verified_at: int = 0
    expires_at: int = 0
    status: str = "reported"
    confidence: float = 0.0
    story_cluster_id: str = ""
    content_hash: str = ""
    evidence_urls: List[str] = field(default_factory=list)


@dataclass
class FootballSyncRun:
    run_id: str
    job_type: str
    started_at: int
    finished_at: int = 0
    status: str = "running"
    query_count: int = 0
    fetched_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    duplicate_count: int = 0
    failed_source_count: int = 0
    error_summary: str = ""


@dataclass
class FootballKnowledgeQuery:
    query: str
    event_types: List[str] = field(default_factory=list)
    teams: List[str] = field(default_factory=list)
    players: List[str] = field(default_factory=list)
    competitions: List[str] = field(default_factory=list)
    max_age_seconds: int = 0
    min_source_level: str = ""
    max_results: int = 6


@dataclass
class FootballKnowledgeResult:
    status: str
    last_synced_at: int
    newest_item_at: int
    items: List[FootballNewsItem] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    requires_web_refresh: bool = False
    reason_codes: List[str] = field(default_factory=list)
