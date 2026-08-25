"""Football intelligence domain package.

This package backs the newer local-first football knowledge pipeline while
`plugins.arteta_football_news` remains the public compatibility entrypoint.
"""

from .models import (
    EVENT_TYPES,
    GENERAL_STATUSES,
    SOURCE_LEVELS,
    TRANSFER_STATUSES,
    FootballKnowledgeQuery,
    FootballKnowledgeResult,
    FootballNewsItem,
    FootballSyncRun,
)

__all__ = [
    "EVENT_TYPES",
    "GENERAL_STATUSES",
    "SOURCE_LEVELS",
    "TRANSFER_STATUSES",
    "FootballKnowledgeQuery",
    "FootballKnowledgeResult",
    "FootballNewsItem",
    "FootballSyncRun",
]
