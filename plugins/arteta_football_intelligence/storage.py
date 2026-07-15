import hashlib
import html
import os
import re
import sqlite3
import time
from typing import Dict, List, Optional

from .models import FootballSyncRun
from .schema import ensure_football_intelligence_schema


def normalize_title(title: str) -> str:
    text = html.unescape(title or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("　", " ")
    text = re.sub(r"[！!。；;，,：:]+", "", text)
    text = re.sub(r"[—–−]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_content_hash(title: str, source: str) -> str:
    normalized = "%s|%s" % (normalize_title(title), str(source or "").strip())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _with_hash(item):
    if hasattr(item, "with_hash"):
        return item.with_hash()
    if getattr(item, "content_hash", ""):
        return item
    item.content_hash = build_content_hash(
        str(getattr(item, "title", "") or ""),
        str(getattr(item, "source", "") or getattr(item, "source_name", "") or ""),
    )
    return item


class FootballNewsSQLiteStore(object):
    def __init__(self, db_path: str):
        self.db_path = db_path

    def initialize(self) -> None:
        parent = os.path.dirname(self.db_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        conn = sqlite3.connect(self.db_path)
        try:
            ensure_football_intelligence_schema(conn)
        finally:
            conn.close()

    def insert_item(self, item, chroma_id: str) -> bool:
        return self._insert_item_with_status(item, chroma_id, "ready")

    def insert_pending_item(self, item, chroma_id: str) -> bool:
        return self._insert_item_with_status(item, chroma_id, "pending")

    def _insert_item_with_status(self, item, chroma_id: str, index_status: str) -> bool:
        hashed = _with_hash(item)
        conn = sqlite3.connect(self.db_path)
        try:
            try:
                conn.execute(
                    """
                    INSERT INTO football_news_items
                    (chroma_id, url, title, source, category, summary, published_at, fetched_at, content_hash,
                     canonical_url, index_status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chroma_id,
                        str(getattr(hashed, "url", "") or getattr(hashed, "canonical_url", "") or ""),
                        str(getattr(hashed, "title", "") or ""),
                        str(getattr(hashed, "source", "") or getattr(hashed, "source_name", "") or ""),
                        str(getattr(hashed, "category", "") or getattr(hashed, "competition", "") or ""),
                        str(getattr(hashed, "summary", "") or ""),
                        int(getattr(hashed, "published_at", 0) or 0),
                        int(getattr(hashed, "fetched_at", 0) or 0),
                        str(getattr(hashed, "content_hash", "") or ""),
                        str(getattr(hashed, "canonical_url", "") or getattr(hashed, "url", "") or ""),
                        str(index_status or "pending"),
                        int(time.time()),
                    ),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
        finally:
            conn.close()

    def mark_index_status(self, chroma_id: str, status: str) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE football_news_items SET index_status = ?, updated_at = ? WHERE chroma_id = ?",
                (str(status or "pending"), int(time.time()), chroma_id),
            )
            conn.commit()
        finally:
            conn.close()

    def list_items_by_index_status(self, status: str, limit: int = 100) -> List[Dict[str, object]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM football_news_items
                WHERE index_status = ?
                ORDER BY fetched_at DESC, id DESC
                LIMIT ?
                """,
                (str(status or ""), int(limit)),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def list_recent_items(
        self,
        days: int,
        now: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        current = int(now or time.time())
        cutoff = current - int(days) * 86400
        sql = """
            SELECT *
            FROM football_news_items
            WHERE fetched_at >= ?
        """
        params = [cutoff]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY fetched_at DESC, id DESC"
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def delete_older_than(self, days: int, now: Optional[int] = None) -> List[str]:
        current = int(now or time.time())
        cutoff = current - int(days) * 86400
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT chroma_id FROM football_news_items WHERE fetched_at < ? ORDER BY fetched_at ASC",
                (cutoff,),
            ).fetchall()
            chroma_ids = [row[0] for row in rows]
            conn.execute("DELETE FROM football_news_items WHERE fetched_at < ?", (cutoff,))
            conn.commit()
            return chroma_ids
        finally:
            conn.close()

    def start_sync_run(self, job_type: str, run_id: str, now: Optional[int] = None) -> FootballSyncRun:
        started_at = int(now or time.time())
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO football_sync_runs
                (run_id, job_type, started_at, finished_at, status)
                VALUES (?, ?, ?, 0, 'running')
                """,
                (run_id, job_type, started_at),
            )
            conn.commit()
        finally:
            conn.close()
        return FootballSyncRun(run_id=run_id, job_type=job_type, started_at=started_at)

    def finish_sync_run(self, run: FootballSyncRun, now: Optional[int] = None) -> FootballSyncRun:
        finished_at = int(now or time.time())
        run.finished_at = finished_at
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE football_sync_runs
                SET finished_at = ?,
                    status = ?,
                    query_count = ?,
                    fetched_count = ?,
                    inserted_count = ?,
                    updated_count = ?,
                    duplicate_count = ?,
                    failed_source_count = ?,
                    error_summary = ?
                WHERE run_id = ?
                """,
                (
                    int(run.finished_at),
                    str(run.status),
                    int(run.query_count),
                    int(run.fetched_count),
                    int(run.inserted_count),
                    int(run.updated_count),
                    int(run.duplicate_count),
                    int(run.failed_source_count),
                    str(run.error_summary or ""),
                    str(run.run_id),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return run

    def latest_sync_run(self) -> Dict[str, object]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT *
                FROM football_sync_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row is not None else {}
        finally:
            conn.close()

    def count_items_by_index_status(self, status: str) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            return int(conn.execute(
                "SELECT COUNT(*) FROM football_news_items WHERE index_status = ?",
                (status,),
            ).fetchone()[0])
        finally:
            conn.close()

    def count_news_items(self) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            return int(conn.execute("SELECT COUNT(*) FROM football_news_items").fetchone()[0])
        finally:
            conn.close()
