import hashlib
import re
from datetime import datetime
from typing import List, Optional

import chromadb
from chromadb.config import Settings


COLLECTION_NAME = "football_news"
SEARCH_DEFAULT_DAYS = 14
SEARCH_MAX_DAYS = 90


class StoredFootballNewsItem(object):
    def __init__(self, row: dict):
        self.title = str(row.get("title") or "")
        self.url = str(row.get("url") or "")
        self.source = str(row.get("source") or "")
        self.category = str(row.get("category") or "")
        self.summary = str(row.get("summary") or "")
        self.published_at = int(row.get("published_at") or 0)
        self.fetched_at = int(row.get("fetched_at") or 0)
        self.content_hash = str(row.get("content_hash") or "")

    def with_hash(self):
        return self


def build_item_chroma_id(item) -> str:
    hashed = item.with_hash() if hasattr(item, "with_hash") else item
    content_hash = str(getattr(hashed, "content_hash", "") or "")
    fetched_at = int(getattr(hashed, "fetched_at", 0) or 0)
    return "football_news_item_%s_%s" % (fetched_at, content_hash[:12])


def build_item_document(item) -> str:
    summary = str(getattr(item, "summary", "") or "")
    published = datetime.fromtimestamp(int(getattr(item, "published_at", 0) or 0)).isoformat()
    fetched = datetime.fromtimestamp(int(getattr(item, "fetched_at", 0) or 0)).isoformat()
    return "\n".join([
        "Football News Item",
        "Category: %s" % getattr(item, "category", ""),
        "Source: %s" % getattr(item, "source", ""),
        "Title: %s" % getattr(item, "title", ""),
        "Summary: %s" % summary,
        "URL: %s" % getattr(item, "url", ""),
        "Published At: %s" % published,
        "Fetched At: %s" % fetched,
    ])


def build_digest_document(items: List[object], fetched_at: int) -> str:
    date_text = datetime.fromtimestamp(int(fetched_at)).strftime("%Y-%m-%d %H:%M")
    grouped = {}
    for item in items:
        grouped.setdefault(str(getattr(item, "category", "") or ""), []).append(item)
    lines = ["Daily Football News Digest", "Fetched At: %s" % date_text]
    for category in sorted(grouped.keys()):
        lines.append("")
        lines.append("## %s" % category)
        for item in grouped[category]:
            summary = str(getattr(item, "summary", "") or "") or "%s 来自 %s。" % (
                getattr(item, "title", ""),
                getattr(item, "source", ""),
            )
            lines.append("- %s｜%s｜%s" % (
                getattr(item, "title", ""),
                getattr(item, "source", ""),
                summary[:160],
            ))
    return "\n".join(lines)


class FootballNewsChromaStore(object):
    def __init__(
        self,
        chroma_dir: str,
        collection=None,
        collection_name: str = COLLECTION_NAME,
    ):
        self.chroma_dir = chroma_dir
        self.collection_name = collection_name
        self.collection = collection
        self.client = None
        self._ready = collection is not None

    def initialize(self) -> None:
        if self.collection is not None:
            self._ready = True
            return
        self.client = chromadb.PersistentClient(
            path=self.chroma_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        try:
            self.collection = self.client.get_collection(self.collection_name)
        except Exception:
            self.collection = self.client.create_collection(self.collection_name)
        self._ready = True

    def add_item(self, item) -> str:
        if not self._ready or self.collection is None:
            raise RuntimeError("football_news collection is not ready")
        hashed = item.with_hash() if hasattr(item, "with_hash") else item
        chroma_id = build_item_chroma_id(hashed)
        self.collection.add(
            documents=[build_item_document(hashed)],
            metadatas=[{
                "kind": "item",
                "category": getattr(hashed, "category", ""),
                "source": getattr(hashed, "source", ""),
                "url": getattr(hashed, "url", ""),
                "published_at": int(getattr(hashed, "published_at", 0) or 0),
                "fetched_at": int(getattr(hashed, "fetched_at", 0) or 0),
            }],
            ids=[chroma_id],
        )
        return chroma_id

    def add_digest(self, items: List[object], fetched_at: int) -> str:
        if not self._ready or self.collection is None:
            raise RuntimeError("football_news collection is not ready")
        digest_hash = hashlib.sha1("|".join([
            str((item.with_hash() if hasattr(item, "with_hash") else item).content_hash)
            for item in items
        ]).encode("utf-8")).hexdigest()
        chroma_id = "football_news_digest_%s_%s" % (int(fetched_at), digest_hash[:12])
        self.collection.add(
            documents=[build_digest_document(items, fetched_at)],
            metadatas=[{
                "kind": "daily_digest",
                "category": "all",
                "source": "football_news_sync",
                "url": "",
                "published_at": int(fetched_at),
                "fetched_at": int(fetched_at),
            }],
            ids=[chroma_id],
        )
        return chroma_id

    def delete_ids(self, chroma_ids: List[str]) -> None:
        if not chroma_ids or not self._ready or self.collection is None:
            return
        self.collection.delete(ids=chroma_ids)

    def search(
        self,
        query: str,
        category: Optional[str] = None,
        days: int = SEARCH_DEFAULT_DAYS,
        now: Optional[int] = None,
        n_results: int = 8,
    ) -> str:
        import time

        if not self._ready or self.collection is None:
            return "足球新闻向量库尚未初始化。"
        if not query:
            return "请提供要查询的足球新闻关键词。"
        safe_days = max(1, min(int(days or SEARCH_DEFAULT_DAYS), SEARCH_MAX_DAYS))
        current = int(now or time.time())
        cutoff = current - safe_days * 86400
        where = {"category": category} if category else None
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
            )
        except Exception:
            return "足球新闻检索失败。"
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        lines = []
        for doc, meta in zip(documents, metadatas):
            fetched_at = int(meta.get("fetched_at", 0) or 0)
            if fetched_at and fetched_at < cutoff:
                continue
            date_text = datetime.fromtimestamp(fetched_at).strftime("%Y-%m-%d") if fetched_at else "未知日期"
            source = meta.get("source", "未知来源")
            url = meta.get("url", "")
            kind = meta.get("kind", "item")
            first_line = doc.split("\n")[0] if doc else ""
            title_match = re.search(r"Title: (.+)", doc)
            summary_match = re.search(r"Summary: (.+)", doc)
            title = title_match.group(1) if title_match else first_line
            summary = summary_match.group(1) if summary_match else doc[:180]
            line = "• [%s] %s｜%s｜%s" % (date_text, title, source, summary[:180])
            if url and kind == "item":
                line += "｜%s" % url
            lines.append(line)
        return "\n".join(lines) if lines else "没有找到符合时间范围的足球新闻。"


def repair_pending_indexes(sqlite_store, chroma_store, limit: int = 100) -> dict:
    attempted = 0
    repaired = 0
    failed = 0
    rows = []
    per_status_limit = max(1, int(limit))
    rows.extend(sqlite_store.list_items_by_index_status("pending", limit=per_status_limit))
    if len(rows) < per_status_limit:
        rows.extend(sqlite_store.list_items_by_index_status("failed", limit=per_status_limit - len(rows)))
    for row in rows[:per_status_limit]:
        attempted += 1
        item = StoredFootballNewsItem(row)
        chroma_id = str(row.get("chroma_id") or build_item_chroma_id(item))
        try:
            chroma_store.add_item(item)
            sqlite_store.mark_index_status(chroma_id, "ready")
            repaired += 1
        except Exception:
            sqlite_store.mark_index_status(chroma_id, "failed")
            failed += 1
    return {"attempted": attempted, "repaired": repaired, "failed": failed}
