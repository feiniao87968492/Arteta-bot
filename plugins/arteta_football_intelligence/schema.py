import sqlite3
import time
from typing import Iterable, Set, Tuple


MIGRATION_VERSION = "football_intelligence_v1"

FOOTBALL_NEWS_NEW_COLUMNS = [
    ("canonical_url", "TEXT DEFAULT ''"),
    ("source_domain", "TEXT DEFAULT ''"),
    ("source_type", "TEXT DEFAULT 'media'"),
    ("source_level", "TEXT DEFAULT 'unknown'"),
    ("event_type", "TEXT DEFAULT 'other'"),
    ("competition", "TEXT DEFAULT ''"),
    ("teams_json", "TEXT DEFAULT '[]'"),
    ("players_json", "TEXT DEFAULT '[]'"),
    ("coaches_json", "TEXT DEFAULT '[]'"),
    ("status", "TEXT DEFAULT 'reported'"),
    ("confidence", "REAL DEFAULT 0.0"),
    ("story_cluster_id", "TEXT DEFAULT ''"),
    ("last_verified_at", "INTEGER DEFAULT 0"),
    ("expires_at", "INTEGER DEFAULT 0"),
    ("evidence_urls_json", "TEXT DEFAULT '[]'"),
    ("updated_at", "INTEGER DEFAULT 0"),
    ("index_status", "TEXT DEFAULT 'pending'"),
]


def _table_columns(conn: sqlite3.Connection, table_name: str) -> Set[str]:
    return set(row[1] for row in conn.execute("PRAGMA table_info(%s)" % table_name).fetchall())


def _create_base_news_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS football_news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chroma_id TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            category TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            published_at INTEGER NOT NULL,
            fetched_at INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            UNIQUE(url)
        )
        """
    )


def _create_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS football_schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at INTEGER NOT NULL
        )
        """
    )


def _create_story_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS football_story_clusters (
            story_cluster_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            competition TEXT DEFAULT '',
            current_status TEXT DEFAULT 'reported',
            current_summary TEXT DEFAULT '',
            confidence REAL DEFAULT 0.0,
            source_level TEXT DEFAULT 'unknown',
            latest_news_id TEXT DEFAULT '',
            first_seen_at INTEGER NOT NULL,
            last_verified_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )


def _create_sync_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS football_sync_runs (
            run_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            finished_at INTEGER DEFAULT 0,
            status TEXT NOT NULL,
            query_count INTEGER DEFAULT 0,
            fetched_count INTEGER DEFAULT 0,
            inserted_count INTEGER DEFAULT 0,
            updated_count INTEGER DEFAULT 0,
            duplicate_count INTEGER DEFAULT 0,
            failed_source_count INTEGER DEFAULT 0,
            error_summary TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS football_sync_cursors (
            source_key TEXT PRIMARY KEY,
            last_success_at INTEGER NOT NULL,
            last_published_at INTEGER DEFAULT 0,
            continuation_token TEXT DEFAULT '',
            updated_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS football_ingestion_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT DEFAULT '',
            source_key TEXT DEFAULT '',
            url TEXT DEFAULT '',
            reason_code TEXT NOT NULL,
            error_summary TEXT DEFAULT '',
            created_at INTEGER NOT NULL
        )
        """
    )


def _add_missing_columns(conn: sqlite3.Connection, columns: Iterable[Tuple[str, str]]) -> None:
    existing = _table_columns(conn, "football_news_items")
    for name, ddl in columns:
        if name in existing:
            continue
        conn.execute("ALTER TABLE football_news_items ADD COLUMN %s %s" % (name, ddl))
        existing.add(name)


def _create_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_football_news_fetched_at ON football_news_items(fetched_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_football_news_category ON football_news_items(category)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_football_news_content_hash ON football_news_items(content_hash)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_football_news_event_time "
        "ON football_news_items(event_type, published_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_football_news_story "
        "ON football_news_items(story_cluster_id, published_at DESC)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_football_news_verified ON football_news_items(last_verified_at DESC)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_football_news_source_level "
        "ON football_news_items(source_level, published_at DESC)"
    )


def ensure_football_intelligence_schema(conn: sqlite3.Connection) -> None:
    _create_base_news_table(conn)
    _create_migration_table(conn)
    _add_missing_columns(conn, FOOTBALL_NEWS_NEW_COLUMNS)
    _create_story_table(conn)
    _create_sync_tables(conn)
    _create_indexes(conn)
    conn.execute(
        "INSERT OR IGNORE INTO football_schema_migrations(version, applied_at) VALUES (?, ?)",
        (MIGRATION_VERSION, int(time.time())),
    )
    conn.commit()


def migrate_database(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        ensure_football_intelligence_schema(conn)
    finally:
        conn.close()
