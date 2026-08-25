import sqlite3

from plugins.arteta_football_intelligence.schema import (
    FOOTBALL_NEWS_NEW_COLUMNS,
    MIGRATION_VERSION,
    ensure_football_intelligence_schema,
)


def _columns(conn, table_name):
    return {row[1] for row in conn.execute("PRAGMA table_info(%s)" % table_name)}


def _indexes(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_football_news_%'"
    ).fetchall()
    return {row[0] for row in rows}


def test_schema_initializes_empty_database_with_legacy_and_new_columns(tmp_path):
    db_path = tmp_path / "news.db"
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_football_intelligence_schema(conn)

        columns = _columns(conn, "football_news_items")
        assert {"id", "chroma_id", "url", "title", "source", "category", "content_hash"}.issubset(columns)
        for name, _ddl in FOOTBALL_NEWS_NEW_COLUMNS:
            assert name in columns

        assert _columns(conn, "football_story_clusters")
        assert _columns(conn, "football_sync_runs")
        assert _columns(conn, "football_sync_cursors")
        assert _columns(conn, "football_ingestion_failures")
        versions = conn.execute("SELECT version FROM football_schema_migrations").fetchall()
        assert (MIGRATION_VERSION,) in versions
    finally:
        conn.close()


def test_schema_migrates_legacy_table_idempotently(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE football_news_items (
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
        conn.execute(
            """
            INSERT INTO football_news_items
            (chroma_id, url, title, source, category, summary, published_at, fetched_at, content_hash)
            VALUES ('old-chroma', 'https://example.com/a', 'Old item', 'Legacy', 'premier_league', 'summary', 100, 200, 'hash-a')
            """
        )
        conn.commit()

        ensure_football_intelligence_schema(conn)
        ensure_football_intelligence_schema(conn)

        row = conn.execute("SELECT title, event_type, source_level, index_status FROM football_news_items").fetchone()
        assert row == ("Old item", "other", "unknown", "pending")
        assert "idx_football_news_event_time" in _indexes(conn)
        assert "idx_football_news_source_level" in _indexes(conn)
        migration_rows = conn.execute(
            "SELECT COUNT(*) FROM football_schema_migrations WHERE version = ?",
            (MIGRATION_VERSION,),
        ).fetchone()[0]
        assert migration_rows == 1
    finally:
        conn.close()
