# Football News Vector Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a global football news intelligence pipeline that fetches fixed Chinese football news sources several times per day, stores item-level news and digest documents in ChromaDB, and lets the chat LLM query them through Function Calling.

**Architecture:** Add a focused `plugins/arteta_football_news.py` module that owns source parsing, SQLite deduplication, ChromaDB indexing, APScheduler jobs, cleanup, and the admin refresh command. Keep the existing `group_memories` collection unchanged and add a separate `football_news` collection for global football intelligence. Extend `plugins/arteta_tools.py` with a `search_football_news` tool that queries the new collection on demand.

**Tech Stack:** Python 3.8, NoneBot2, nonebot-plugin-apscheduler, SQLite, ChromaDB PersistentClient, httpx, unittest, `tools/verify_features.py`, existing ECS Supervisor deployment.

---

## File Structure

Create:

- `plugins/arteta_football_news.py` — fixed Chinese source definitions, parser helpers, SQLite store, Chroma store, sync pipeline, APScheduler jobs, admin command, and search helper used by Function Calling.
- `tests/test_arteta_football_news.py` — pure and stubbed unit tests for normalization, dedupe, quota selection, SQLite cleanup, Chroma document construction, sync behavior, and search formatting.
- `tests/fixtures/football_news/sina_premier_league.html` — fixture page with Premier League links.
- `tests/fixtures/football_news/netease_chinese_super_league.html` — fixture page with Chinese Super League links.
- `docs/dev/football-news.md` — developer documentation for the new sync pipeline.

Modify:

- `plugins/arteta_tools.py` — add the `search_football_news` Function Calling schema and executor branch.
- `tools/verify_features.py` — add a `football_news` suite with an isolated offline roundtrip.
- `docs/dev/overview.md` — list the new plugin, collection, command, and data flow.
- `docs/dev/developer-verification.md` — document the new verification suite.
- `docs/user/commands.md` — add admin-only `刷新足球新闻` / `足球新闻刷新` command.
- `CLAUDE.md` — update the plugin list and Function Calling tool count if the new module is treated as core architecture.

---

### Task 1: Pure football-news models and helpers

**Files:**
- Create: `plugins/arteta_football_news.py`
- Create: `tests/test_arteta_football_news.py`

- [ ] **Step 1: Write failing tests for normalization, hashing, quotas, and document builders**

Create `tests/test_arteta_football_news.py` with this initial content:

```python
import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "arteta_football_news.py"


def load_module():
    previous = {}

    def remember(name, module):
        previous[name] = sys.modules.get(name)
        sys.modules[name] = module

    nonebot = types.ModuleType("nonebot")

    class DummyMatcher(object):
        def handle(self):
            def decorator(func):
                return func
            return decorator

    class DummyDriver(object):
        def __init__(self):
            self.config = types.SimpleNamespace(dict=lambda: {}, model_dump=lambda: {})

    nonebot.on_command = lambda *args, **kwargs: DummyMatcher()
    nonebot.get_driver = lambda: DummyDriver()
    remember("nonebot", nonebot)

    adapter = types.ModuleType("nonebot.adapters.onebot.v11")
    adapter.Bot = object
    adapter.GroupMessageEvent = object
    remember("nonebot.adapters.onebot.v11", adapter)

    params = types.ModuleType("nonebot.params")
    params.CommandArg = object
    remember("nonebot.params", params)

    apscheduler_mod = types.ModuleType("nonebot_plugin_apscheduler")

    class DummyScheduler(object):
        def scheduled_job(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    apscheduler_mod.scheduler = DummyScheduler()
    remember("nonebot_plugin_apscheduler", apscheduler_mod)

    chromadb_stub = types.ModuleType("chromadb")
    chromadb_stub.PersistentClient = object
    remember("chromadb", chromadb_stub)

    chromadb_config = types.ModuleType("chromadb.config")

    class FakeSettings(object):
        def __init__(self, anonymized_telemetry=False):
            self.anonymized_telemetry = anonymized_telemetry

    chromadb_config.Settings = FakeSettings
    remember("chromadb.config", chromadb_config)

    try:
        spec = importlib.util.spec_from_file_location("arteta_football_news_for_test", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous_module in previous.items():
            if previous_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous_module


class FootballNewsHelperTests(unittest.TestCase):
    def test_normalize_title_collapses_space_and_punctuation(self):
        module = load_module()
        self.assertEqual("曼城 2-1 阿森纳", module.normalize_title("  曼城　2-1——阿森纳！！ "))

    def test_content_hash_is_stable_for_same_title_and_source(self):
        module = load_module()
        first = module.build_content_hash("曼城 2-1 阿森纳", "新浪体育")
        second = module.build_content_hash("  曼城　2-1——阿森纳！！ ", "新浪体育")
        self.assertEqual(first, second)
        self.assertEqual(40, len(first))

    def test_apply_category_quotas_prefers_premier_league(self):
        module = load_module()
        now = 1716400000
        items = [
            module.NewsItem("英超新闻A", "https://example.com/pl-a", "新浪体育", "premier_league", "", now, now),
            module.NewsItem("英超新闻B", "https://example.com/pl-b", "新浪体育", "premier_league", "", now, now),
            module.NewsItem("英超新闻C", "https://example.com/pl-c", "新浪体育", "premier_league", "", now, now),
            module.NewsItem("中超新闻A", "https://example.com/csl-a", "网易体育", "chinese_super_league", "", now, now),
            module.NewsItem("中超新闻B", "https://example.com/csl-b", "网易体育", "chinese_super_league", "", now, now),
        ]
        selected = module.apply_category_quotas(items, {"premier_league": 2, "chinese_super_league": 1})
        self.assertEqual(["英超新闻A", "英超新闻B", "中超新闻A"], [item.title for item in selected])

    def test_build_item_document_contains_searchable_fields(self):
        module = load_module()
        item = module.NewsItem(
            title="阿森纳关注新前锋",
            url="https://example.com/a",
            source="新浪体育",
            category="premier_league",
            summary="阿森纳正在关注锋线补强。",
            published_at=1716400000,
            fetched_at=1716400300,
        )
        document = module.build_item_document(item)
        self.assertIn("Category: premier_league", document)
        self.assertIn("Source: 新浪体育", document)
        self.assertIn("Title: 阿森纳关注新前锋", document)
        self.assertIn("Summary: 阿森纳正在关注锋线补强。", document)
        self.assertIn("URL: https://example.com/a", document)

    def test_build_digest_document_groups_by_category(self):
        module = load_module()
        now = 1716400000
        items = [
            module.NewsItem("英超争冠进入冲刺", "https://example.com/pl", "新浪体育", "premier_league", "争冠进入关键阶段。", now, now),
            module.NewsItem("中超焦点战结束", "https://example.com/csl", "网易体育", "chinese_super_league", "中超焦点战结束。", now, now),
        ]
        document = module.build_digest_document(items, now)
        self.assertIn("Daily Football News Digest", document)
        self.assertIn("premier_league", document)
        self.assertIn("英超争冠进入冲刺", document)
        self.assertIn("chinese_super_league", document)
        self.assertIn("中超焦点战结束", document)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify they fail because the module does not exist**

Run:

```bash
python -m unittest tests.test_arteta_football_news -v
```

Expected: FAIL with `FileNotFoundError` or `ModuleNotFoundError` for `plugins/arteta_football_news.py`.

- [ ] **Step 3: Create the module with pure helpers only**

Create `plugins/arteta_football_news.py` with this content:

```python
"""Global football news sync and vector search."""

import hashlib
import html
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import pysqlite3  # type: ignore
    import sys
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

import chromadb
from chromadb.config import Settings
from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot_plugin_apscheduler import scheduler

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.environ.get("ARTETA_DB_PATH", os.path.join(REPO_ROOT, "arsenal_data.db"))
CHROMA_DB_DIR = os.environ.get("ARTETA_CHROMA_DIR", os.path.join(REPO_ROOT, "chroma_db"))
COLLECTION_NAME = "football_news"
RETENTION_DAYS = 90
SEARCH_DEFAULT_DAYS = 14
SEARCH_MAX_DAYS = 90
ADMIN_QQ = "2648955710"

try:
    _config = get_driver().config
    try:
        _config_dict = _config.model_dump()
    except AttributeError:
        _config_dict = _config.dict()
except Exception:
    _config_dict = {}

FOOTBALL_NEWS_ENABLED = str(_config_dict.get("football_news_enabled", "true")).lower() in ("true", "1", "yes")

CATEGORY_QUOTAS = {
    "premier_league": 12,
    "champions_league": 6,
    "laliga": 4,
    "serie_a": 4,
    "bundesliga": 4,
    "ligue1": 4,
    "chinese_super_league": 6,
    "other": 4,
}


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    category: str
    summary: str
    published_at: int
    fetched_at: int
    content_hash: str = ""

    def with_hash(self):
        if self.content_hash:
            return self
        return NewsItem(
            title=self.title,
            url=self.url,
            source=self.source,
            category=self.category,
            summary=self.summary,
            published_at=self.published_at,
            fetched_at=self.fetched_at,
            content_hash=build_content_hash(self.title, self.source),
        )


@dataclass
class SyncResult:
    sources_attempted: int = 0
    sources_succeeded: int = 0
    fetched_items: int = 0
    inserted_items: int = 0
    duplicate_items: int = 0
    digest_written: bool = False
    cleanup_deleted: int = 0
    cleanup_warning: str = ""


def normalize_title(title: str) -> str:
    text = html.unescape(title or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("　", " ")
    text = re.sub(r"[！!。；;，,：:]+", "", text)
    text = re.sub(r"[—–−]+", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_content_hash(title: str, source: str) -> str:
    normalized = "%s|%s" % (normalize_title(title), str(source or "").strip())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def clean_text(text: str) -> str:
    value = html.unescape(text or "")
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def apply_category_quotas(items: List[NewsItem], quotas: Dict[str, int]) -> List[NewsItem]:
    counts = {}
    selected = []
    for item in items:
        limit = quotas.get(item.category, quotas.get("other", 4))
        current = counts.get(item.category, 0)
        if current >= limit:
            continue
        selected.append(item)
        counts[item.category] = current + 1
    return selected


def build_item_document(item: NewsItem) -> str:
    published = datetime.fromtimestamp(item.published_at).strftime("%Y-%m-%d %H:%M")
    fetched = datetime.fromtimestamp(item.fetched_at).strftime("%Y-%m-%d %H:%M")
    summary = item.summary or "%s 来自 %s。" % (item.title, item.source)
    return "\n".join([
        "Category: %s" % item.category,
        "Source: %s" % item.source,
        "Title: %s" % item.title,
        "Summary: %s" % summary,
        "URL: %s" % item.url,
        "Published At: %s" % published,
        "Fetched At: %s" % fetched,
    ])


def build_digest_document(items: List[NewsItem], fetched_at: int) -> str:
    date_text = datetime.fromtimestamp(fetched_at).strftime("%Y-%m-%d %H:%M")
    grouped = {}
    for item in items:
        grouped.setdefault(item.category, []).append(item)
    lines = ["Daily Football News Digest", "Fetched At: %s" % date_text]
    for category in sorted(grouped.keys()):
        lines.append("")
        lines.append("## %s" % category)
        for item in grouped[category]:
            summary = item.summary or "%s 来自 %s。" % (item.title, item.source)
            lines.append("- %s｜%s｜%s" % (item.title, item.source, summary[:160]))
    return "\n".join(lines)
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```bash
python -m unittest tests.test_arteta_football_news -v
```

Expected: PASS for the five helper tests.

- [ ] **Step 5: Commit the helpers**

Run:

```bash
git add plugins/arteta_football_news.py tests/test_arteta_football_news.py
git commit -m "feat: add football news helper model"
```

---

### Task 2: SQLite deduplication and cleanup store

**Files:**
- Modify: `plugins/arteta_football_news.py`
- Modify: `tests/test_arteta_football_news.py`

- [ ] **Step 1: Add failing SQLite store tests**

Append this test class to `tests/test_arteta_football_news.py` before the `if __name__ == "__main__"` block:

```python
class FootballNewsSQLiteTests(unittest.TestCase):
    def test_sqlite_store_inserts_once_and_counts_duplicate(self):
        module = load_module()
        import tempfile
        now = 1716400000
        item = module.NewsItem("英超新闻", "https://example.com/pl", "新浪体育", "premier_league", "摘要", now, now).with_hash()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "news.db")
            store = module.FootballNewsSQLiteStore(db_path)
            store.initialize()
            first = store.insert_item(item, "chroma-1")
            second = store.insert_item(item, "chroma-2")
            self.assertTrue(first)
            self.assertFalse(second)
            rows = store.list_recent_items(days=90, now=now + 60)
            self.assertEqual(1, len(rows))
            self.assertEqual("chroma-1", rows[0]["chroma_id"])

    def test_sqlite_cleanup_returns_old_chroma_ids(self):
        module = load_module()
        import tempfile
        now = 1716400000
        old_time = now - 91 * 86400
        fresh_item = module.NewsItem("新新闻", "https://example.com/new", "新浪体育", "premier_league", "摘要", now, now).with_hash()
        old_item = module.NewsItem("旧新闻", "https://example.com/old", "新浪体育", "premier_league", "摘要", old_time, old_time).with_hash()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "news.db")
            store = module.FootballNewsSQLiteStore(db_path)
            store.initialize()
            store.insert_item(old_item, "old-chroma")
            store.insert_item(fresh_item, "fresh-chroma")
            deleted_ids = store.delete_older_than(90, now=now)
            self.assertEqual(["old-chroma"], deleted_ids)
            rows = store.list_recent_items(days=90, now=now)
            self.assertEqual(["新新闻"], [row["title"] for row in rows])
```

- [ ] **Step 2: Run the SQLite tests and verify they fail because the store class is missing**

Run:

```bash
python -m unittest tests.test_arteta_football_news.FootballNewsSQLiteTests -v
```

Expected: FAIL with `AttributeError: module ... has no attribute 'FootballNewsSQLiteStore'`.

- [ ] **Step 3: Add SQLite store implementation**

Append this code to `plugins/arteta_football_news.py` after `build_digest_document`:

```python
class FootballNewsSQLiteStore(object):
    def __init__(self, db_path: str):
        self.db_path = db_path

    def initialize(self) -> None:
        parent = os.path.dirname(self.db_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
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
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_football_news_fetched_at ON football_news_items(fetched_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_football_news_category ON football_news_items(category)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_football_news_content_hash ON football_news_items(content_hash)")
            conn.commit()
        finally:
            conn.close()

    def insert_item(self, item: NewsItem, chroma_id: str) -> bool:
        hashed = item.with_hash()
        conn = sqlite3.connect(self.db_path)
        try:
            try:
                conn.execute(
                    """
                    INSERT INTO football_news_items
                    (chroma_id, url, title, source, category, summary, published_at, fetched_at, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chroma_id,
                        hashed.url,
                        hashed.title,
                        hashed.source,
                        hashed.category,
                        hashed.summary,
                        int(hashed.published_at),
                        int(hashed.fetched_at),
                        hashed.content_hash,
                    ),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
        finally:
            conn.close()

    def list_recent_items(self, days: int, now: Optional[int] = None, category: Optional[str] = None) -> List[Dict[str, object]]:
        current = int(now or time.time())
        cutoff = current - int(days) * 86400
        sql = """
            SELECT chroma_id, url, title, source, category, summary, published_at, fetched_at, content_hash
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
```

- [ ] **Step 4: Run all football-news tests**

Run:

```bash
python -m unittest tests.test_arteta_football_news -v
```

Expected: PASS for helper and SQLite tests.

- [ ] **Step 5: Commit SQLite store**

Run:

```bash
git add plugins/arteta_football_news.py tests/test_arteta_football_news.py
git commit -m "feat: add football news sqlite store"
```

---

### Task 3: ChromaDB collection wrapper and search formatting

**Files:**
- Modify: `plugins/arteta_football_news.py`
- Modify: `tests/test_arteta_football_news.py`

- [ ] **Step 1: Add failing Chroma wrapper tests with an in-memory fake collection**

Append this test class to `tests/test_arteta_football_news.py` before the `if __name__ == "__main__"` block:

```python
class FakeFootballNewsCollection(object):
    def __init__(self):
        self.added = []
        self.deleted_ids = []

    def add(self, documents, metadatas, ids):
        for doc, meta, doc_id in zip(documents, metadatas, ids):
            self.added.append({"document": doc, "metadata": meta, "id": doc_id})

    def delete(self, ids):
        self.deleted_ids.extend(ids)
        self.added = [item for item in self.added if item["id"] not in ids]

    def query(self, query_texts, n_results, where=None):
        docs = []
        metas = []
        ids = []
        for item in self.added:
            if where:
                matched = True
                for key, expected in where.items():
                    if item["metadata"].get(key) != expected:
                        matched = False
                        break
                if not matched:
                    continue
            docs.append(item["document"])
            metas.append(item["metadata"])
            ids.append(item["id"])
            if len(docs) >= n_results:
                break
        return {"documents": [docs], "metadatas": [metas], "ids": [ids]}


class FootballNewsChromaTests(unittest.TestCase):
    def test_chroma_store_adds_item_and_digest_documents(self):
        module = load_module()
        now = 1716400000
        collection = FakeFootballNewsCollection()
        store = module.FootballNewsChromaStore(collection=collection)
        item = module.NewsItem("英超新闻", "https://example.com/pl", "新浪体育", "premier_league", "摘要", now, now).with_hash()
        item_id = store.add_item(item)
        digest_id = store.add_digest([item], now)
        self.assertTrue(item_id.startswith("football_news_item_"))
        self.assertTrue(digest_id.startswith("football_news_digest_"))
        self.assertEqual(["item", "daily_digest"], [entry["metadata"]["kind"] for entry in collection.added])

    def test_chroma_store_formats_search_results(self):
        module = load_module()
        now = 1716400000
        collection = FakeFootballNewsCollection()
        store = module.FootballNewsChromaStore(collection=collection)
        item = module.NewsItem("英超新闻", "https://example.com/pl", "新浪体育", "premier_league", "摘要", now, now).with_hash()
        store.add_item(item)
        result = store.search("英超", category="premier_league", days=14, now=now + 60)
        self.assertIn("英超新闻", result)
        self.assertIn("新浪体育", result)
        self.assertIn("https://example.com/pl", result)

    def test_chroma_store_delete_ids(self):
        module = load_module()
        collection = FakeFootballNewsCollection()
        store = module.FootballNewsChromaStore(collection=collection)
        store.delete_ids(["a", "b"])
        self.assertEqual(["a", "b"], collection.deleted_ids)
```

- [ ] **Step 2: Run Chroma tests and verify they fail because the wrapper class is missing**

Run:

```bash
python -m unittest tests.test_arteta_football_news.FootballNewsChromaTests -v
```

Expected: FAIL with `AttributeError` for `FootballNewsChromaStore`.

- [ ] **Step 3: Add Chroma wrapper implementation**

Append this code to `plugins/arteta_football_news.py` after `FootballNewsSQLiteStore`:

```python
class FootballNewsChromaStore(object):
    def __init__(self, chroma_dir: str = CHROMA_DB_DIR, collection=None):
        self.chroma_dir = chroma_dir
        self.collection = collection
        self.client = None
        self._ready = collection is not None

    def initialize(self) -> None:
        if self.collection is not None:
            self._ready = True
            return
        try:
            self.client = chromadb.PersistentClient(
                path=self.chroma_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            try:
                self.collection = self.client.get_collection(COLLECTION_NAME)
            except Exception:
                self.collection = self.client.create_collection(COLLECTION_NAME)
            self._ready = True
            logger.info("[FootballNews] ChromaDB collection ready: %s", COLLECTION_NAME)
        except Exception as e:
            self._ready = False
            logger.error("[FootballNews] ChromaDB initialization failed: %s", e)

    def add_item(self, item: NewsItem) -> str:
        if not self._ready or self.collection is None:
            raise RuntimeError("football_news collection is not ready")
        hashed = item.with_hash()
        chroma_id = "football_news_item_%s_%s" % (hashed.fetched_at, hashed.content_hash[:12])
        self.collection.add(
            documents=[build_item_document(hashed)],
            metadatas=[{
                "kind": "item",
                "category": hashed.category,
                "source": hashed.source,
                "url": hashed.url,
                "published_at": int(hashed.published_at),
                "fetched_at": int(hashed.fetched_at),
            }],
            ids=[chroma_id],
        )
        return chroma_id

    def add_digest(self, items: List[NewsItem], fetched_at: int) -> str:
        if not self._ready or self.collection is None:
            raise RuntimeError("football_news collection is not ready")
        digest_hash = hashlib.sha1("|".join([item.with_hash().content_hash for item in items]).encode("utf-8")).hexdigest()
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

    def search(self, query: str, category: Optional[str] = None, days: int = SEARCH_DEFAULT_DAYS,
               now: Optional[int] = None, n_results: int = 8) -> str:
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
        except Exception as e:
            logger.warning("[FootballNews] search failed: %s", e)
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
```

- [ ] **Step 4: Run all football-news tests**

Run:

```bash
python -m unittest tests.test_arteta_football_news -v
```

Expected: PASS for helper, SQLite, and Chroma wrapper tests.

- [ ] **Step 5: Commit Chroma wrapper**

Run:

```bash
git add plugins/arteta_football_news.py tests/test_arteta_football_news.py
git commit -m "feat: add football news chroma store"
```

---

### Task 4: Fixed Chinese source parsing and fixtures

**Files:**
- Modify: `plugins/arteta_football_news.py`
- Modify: `tests/test_arteta_football_news.py`
- Create: `tests/fixtures/football_news/sina_premier_league.html`
- Create: `tests/fixtures/football_news/netease_chinese_super_league.html`

- [ ] **Step 1: Create fixture HTML files**

Create `tests/fixtures/football_news/sina_premier_league.html`:

```html
<html>
  <body>
    <a href="https://sports.sina.com.cn/g/pl/2026-05-23/doc-arsenal.html">阿森纳继续追逐英超冠军</a>
    <a href="https://sports.sina.com.cn/g/pl/2026-05-23/doc-city.html">曼城公布新赛季计划</a>
    <a href="/g/pl/2026-05-23/doc-liverpool.html">利物浦完成关键续约</a>
  </body>
</html>
```

Create `tests/fixtures/football_news/netease_chinese_super_league.html`:

```html
<html>
  <body>
    <a href="https://sports.163.com/26/0523/20/csl-a.html">中超焦点战今晚打响</a>
    <a href="/26/0523/21/csl-b.html">上海海港公布伤病情况</a>
  </body>
</html>
```

- [ ] **Step 2: Add failing parser tests**

Append this test class to `tests/test_arteta_football_news.py` before the `if __name__ == "__main__"` block:

```python
class FootballNewsParserTests(unittest.TestCase):
    def test_parse_links_extracts_absolute_and_relative_urls(self):
        module = load_module()
        fixture = Path(__file__).resolve().parent / "fixtures" / "football_news" / "sina_premier_league.html"
        html = fixture.read_text(encoding="utf-8")
        items = module.parse_source_html(
            html_text=html,
            base_url="https://sports.sina.com.cn",
            source="新浪体育",
            category="premier_league",
            fetched_at=1716400000,
            max_items=10,
        )
        self.assertEqual(3, len(items))
        self.assertEqual("阿森纳继续追逐英超冠军", items[0].title)
        self.assertEqual("https://sports.sina.com.cn/g/pl/2026-05-23/doc-liverpool.html", items[2].url)
        self.assertEqual("premier_league", items[0].category)

    def test_parse_links_applies_max_items_and_skips_short_titles(self):
        module = load_module()
        html = '<a href="/a.html">短</a><a href="/b.html">中超焦点战今晚打响</a><a href="/c.html">上海海港公布伤病情况</a>'
        items = module.parse_source_html(html, "https://sports.163.com", "网易体育", "chinese_super_league", 1716400000, max_items=1)
        self.assertEqual(1, len(items))
        self.assertEqual("中超焦点战今晚打响", items[0].title)
```

- [ ] **Step 3: Run parser tests and verify they fail because `parse_source_html` is missing**

Run:

```bash
python -m unittest tests.test_arteta_football_news.FootballNewsParserTests -v
```

Expected: FAIL with `AttributeError` for `parse_source_html`.

- [ ] **Step 4: Add source configuration and parser implementation**

Add this code to `plugins/arteta_football_news.py` after `CATEGORY_QUOTAS`:

```python
NEWS_SOURCES = [
    {
        "name": "新浪体育-英超",
        "source": "新浪体育",
        "url": "https://sports.sina.com.cn/global/england/",
        "base_url": "https://sports.sina.com.cn",
        "category": "premier_league",
        "max_items": 12,
    },
    {
        "name": "新浪体育-欧冠",
        "source": "新浪体育",
        "url": "https://sports.sina.com.cn/global/championsleague/",
        "base_url": "https://sports.sina.com.cn",
        "category": "champions_league",
        "max_items": 6,
    },
    {
        "name": "网易体育-国际足球",
        "source": "网易体育",
        "url": "https://sports.163.com/world/",
        "base_url": "https://sports.163.com",
        "category": "other",
        "max_items": 10,
    },
    {
        "name": "网易体育-中超",
        "source": "网易体育",
        "url": "https://sports.163.com/china/",
        "base_url": "https://sports.163.com",
        "category": "chinese_super_league",
        "max_items": 8,
    },
    {
        "name": "搜狐体育-英超",
        "source": "搜狐体育",
        "url": "https://sports.sohu.com/yingchao.shtml",
        "base_url": "https://sports.sohu.com",
        "category": "premier_league",
        "max_items": 10,
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
```

Add this code after `clean_text`:

```python
def absolutize_url(url: str, base_url: str) -> str:
    value = html.unescape(url or "").strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("/"):
        return base_url.rstrip("/") + value
    return base_url.rstrip("/") + "/" + value


def parse_source_html(html_text: str, base_url: str, source: str, category: str,
                      fetched_at: int, max_items: int) -> List[NewsItem]:
    matches = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_text or "", re.I | re.S)
    items = []
    seen = set()
    for href, raw_title in matches:
        title = normalize_title(raw_title)
        if len(title) < 6:
            continue
        url = absolutize_url(href, base_url)
        if not url.startswith("http"):
            continue
        key = url
        if key in seen:
            continue
        seen.add(key)
        summary = "%s 来自 %s。" % (title, source)
        item = NewsItem(
            title=title,
            url=url,
            source=source,
            category=category,
            summary=summary,
            published_at=fetched_at,
            fetched_at=fetched_at,
        ).with_hash()
        items.append(item)
        if len(items) >= max_items:
            break
    return items
```

- [ ] **Step 5: Run all football-news tests**

Run:

```bash
python -m unittest tests.test_arteta_football_news -v
```

Expected: PASS.

- [ ] **Step 6: Commit parser and fixtures**

Run:

```bash
git add plugins/arteta_football_news.py tests/test_arteta_football_news.py tests/fixtures/football_news/sina_premier_league.html tests/fixtures/football_news/netease_chinese_super_league.html
git commit -m "feat: add fixed football news parsers"
```

---

### Task 5: Sync pipeline, scheduler jobs, and admin command

**Files:**
- Modify: `plugins/arteta_football_news.py`
- Modify: `tests/test_arteta_football_news.py`

- [ ] **Step 1: Add failing sync pipeline tests using fake fetcher and fake Chroma collection**

Append this test class to `tests/test_arteta_football_news.py` before the `if __name__ == "__main__"` block:

```python
class FootballNewsSyncTests(unittest.TestCase):
    def test_sync_inserts_items_writes_digest_and_skips_duplicates(self):
        module = load_module()
        import asyncio
        import tempfile
        now = 1716400000
        html = '<a href="/pl-a.html">阿森纳继续追逐英超冠军</a><a href="/pl-b.html">曼城公布新赛季计划</a>'

        async def fake_fetch(source):
            return html

        sources = [{
            "name": "fixture",
            "source": "新浪体育",
            "url": "https://sports.sina.com.cn/global/england/",
            "base_url": "https://sports.sina.com.cn",
            "category": "premier_league",
            "max_items": 10,
        }]
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_store = module.FootballNewsSQLiteStore(str(Path(tmpdir) / "news.db"))
            sqlite_store.initialize()
            chroma_store = module.FootballNewsChromaStore(collection=FakeFootballNewsCollection())
            result = asyncio.run(module.sync_football_news(sources, sqlite_store, chroma_store, fake_fetch, now=now))
            self.assertEqual(1, result.sources_attempted)
            self.assertEqual(1, result.sources_succeeded)
            self.assertEqual(2, result.inserted_items)
            self.assertEqual(0, result.duplicate_items)
            self.assertTrue(result.digest_written)
            second = asyncio.run(module.sync_football_news(sources, sqlite_store, chroma_store, fake_fetch, now=now + 60))
            self.assertEqual(0, second.inserted_items)
            self.assertEqual(2, second.duplicate_items)
            self.assertFalse(second.digest_written)

    def test_sync_continues_when_one_source_fails(self):
        module = load_module()
        import asyncio
        import tempfile
        now = 1716400000

        async def fake_fetch(source):
            if source["name"] == "bad":
                raise RuntimeError("network failed")
            return '<a href="/pl-a.html">阿森纳继续追逐英超冠军</a>'

        sources = [
            {"name": "bad", "source": "坏源", "url": "https://bad.example", "base_url": "https://bad.example", "category": "premier_league", "max_items": 10},
            {"name": "good", "source": "新浪体育", "url": "https://sports.sina.com.cn/global/england/", "base_url": "https://sports.sina.com.cn", "category": "premier_league", "max_items": 10},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_store = module.FootballNewsSQLiteStore(str(Path(tmpdir) / "news.db"))
            sqlite_store.initialize()
            chroma_store = module.FootballNewsChromaStore(collection=FakeFootballNewsCollection())
            result = asyncio.run(module.sync_football_news(sources, sqlite_store, chroma_store, fake_fetch, now=now))
            self.assertEqual(2, result.sources_attempted)
            self.assertEqual(1, result.sources_succeeded)
            self.assertEqual(1, result.inserted_items)
```

- [ ] **Step 2: Run sync tests and verify they fail because `sync_football_news` is missing**

Run:

```bash
python -m unittest tests.test_arteta_football_news.FootballNewsSyncTests -v
```

Expected: FAIL with `AttributeError` for `sync_football_news`.

- [ ] **Step 3: Add fetch, sync, global store, scheduler jobs, and admin command**

Append this code to `plugins/arteta_football_news.py` after `FootballNewsChromaStore`:

```python
async def fetch_source_html(source: Dict[str, object]) -> str:
    import httpx
    async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
        resp = await client.get(str(source["url"]), headers=HEADERS, follow_redirects=True)
        if resp.status_code != 200:
            raise RuntimeError("%s returned HTTP %s" % (source.get("name"), resp.status_code))
        return resp.text


async def sync_football_news(sources: List[Dict[str, object]], sqlite_store: FootballNewsSQLiteStore,
                             chroma_store: FootballNewsChromaStore, fetcher=fetch_source_html,
                             now: Optional[int] = None) -> SyncResult:
    fetched_at = int(now or time.time())
    result = SyncResult(sources_attempted=len(sources))
    all_items = []
    for source in sources:
        try:
            html_text = await fetcher(source)
            parsed = parse_source_html(
                html_text=html_text,
                base_url=str(source["base_url"]),
                source=str(source["source"]),
                category=str(source["category"]),
                fetched_at=fetched_at,
                max_items=int(source.get("max_items", 10)),
            )
            if parsed:
                result.sources_succeeded += 1
                all_items.extend(parsed)
        except Exception as e:
            logger.warning("[FootballNews] source failed %s: %s", source.get("name"), e)
    selected_items = apply_category_quotas(all_items, CATEGORY_QUOTAS)
    result.fetched_items = len(selected_items)
    inserted_items = []
    for item in selected_items:
        try:
            chroma_id = chroma_store.add_item(item)
        except Exception as e:
            logger.warning("[FootballNews] chroma add failed for %s: %s", item.title, e)
            continue
        if sqlite_store.insert_item(item, chroma_id):
            inserted_items.append(item)
            result.inserted_items += 1
        else:
            result.duplicate_items += 1
            try:
                chroma_store.delete_ids([chroma_id])
            except Exception as e:
                logger.warning("[FootballNews] duplicate vector cleanup failed: %s", e)
    if inserted_items:
        try:
            chroma_store.add_digest(inserted_items, fetched_at)
            result.digest_written = True
        except Exception as e:
            logger.warning("[FootballNews] digest write failed: %s", e)
    try:
        old_ids = sqlite_store.delete_older_than(RETENTION_DAYS, now=fetched_at)
        result.cleanup_deleted = len(old_ids)
        chroma_store.delete_ids(old_ids)
    except Exception as e:
        result.cleanup_warning = "%s: %s" % (type(e).__name__, e)
        logger.warning("[FootballNews] cleanup failed: %s", result.cleanup_warning)
    return result


def get_default_stores() -> Tuple[FootballNewsSQLiteStore, FootballNewsChromaStore]:
    sqlite_store = FootballNewsSQLiteStore(DB_PATH)
    sqlite_store.initialize()
    chroma_store = FootballNewsChromaStore(CHROMA_DB_DIR)
    chroma_store.initialize()
    return sqlite_store, chroma_store


async def run_default_sync() -> SyncResult:
    sqlite_store, chroma_store = get_default_stores()
    return await sync_football_news(NEWS_SOURCES, sqlite_store, chroma_store)


def format_sync_result(result: SyncResult) -> str:
    lines = [
        "足球新闻刷新完成",
        "源：%s/%s 成功" % (result.sources_succeeded, result.sources_attempted),
        "新增：%s 条" % result.inserted_items,
        "重复：%s 条" % result.duplicate_items,
        "总览：%s" % ("已写入" if result.digest_written else "未写入"),
        "清理：%s 条" % result.cleanup_deleted,
    ]
    if result.cleanup_warning:
        lines.append("清理警告：%s" % result.cleanup_warning)
    return "\n".join(lines)


@scheduler.scheduled_job("cron", hour=3, minute=30, id="football_news_morning", misfire_grace_time=300)
async def football_news_morning_job():
    if not FOOTBALL_NEWS_ENABLED:
        logger.info("[FootballNews] football news sync disabled")
        return
    result = await run_default_sync()
    logger.info("[FootballNews] morning sync finished: %s", format_sync_result(result).replace("\n", " | "))


@scheduler.scheduled_job("cron", hour=18, minute=30, id="football_news_evening", misfire_grace_time=300)
async def football_news_evening_job():
    if not FOOTBALL_NEWS_ENABLED:
        logger.info("[FootballNews] football news sync disabled")
        return
    result = await run_default_sync()
    logger.info("[FootballNews] evening sync finished: %s", format_sync_result(result).replace("\n", " | "))


refresh_football_news_cmd = on_command("刷新足球新闻", aliases={"足球新闻刷新"}, priority=5, block=True)


@refresh_football_news_cmd.handle()
async def handle_refresh_football_news(bot: Bot, event: GroupMessageEvent):
    user_id = event.get_user_id()
    if str(user_id) != ADMIN_QQ:
        await refresh_football_news_cmd.finish("只有教练组可以刷新足球新闻。")
    await refresh_football_news_cmd.send("开始刷新足球新闻，请稍候...")
    try:
        result = await run_default_sync()
    except Exception as e:
        logger.exception("[FootballNews] manual refresh failed: %s", e)
        await refresh_football_news_cmd.finish("足球新闻刷新失败，请检查日志。")
    await refresh_football_news_cmd.finish(format_sync_result(result))
```

- [ ] **Step 4: Run all football-news tests**

Run:

```bash
python -m unittest tests.test_arteta_football_news -v
```

Expected: PASS.

- [ ] **Step 5: Commit sync pipeline**

Run:

```bash
git add plugins/arteta_football_news.py tests/test_arteta_football_news.py
git commit -m "feat: sync football news into vector store"
```

---

### Task 6: Function Calling tool integration

**Files:**
- Modify: `plugins/arteta_tools.py`
- Modify: `tests/test_arteta_football_news.py`

- [ ] **Step 1: Add failing tests for the Function Calling schema and executor**

Append this test class to `tests/test_arteta_football_news.py` before the `if __name__ == "__main__"` block:

```python
class FootballNewsToolIntegrationTests(unittest.TestCase):
    def test_tools_schema_contains_search_football_news(self):
        import importlib
        tools = importlib.import_module("plugins.arteta_tools")
        names = [tool["function"]["name"] for tool in tools.TOOLS]
        self.assertIn("search_football_news", names)

    def test_execute_tool_call_routes_to_football_news_search(self):
        import asyncio
        import importlib
        import json
        tools = importlib.import_module("plugins.arteta_tools")
        original = tools._search_football_news
        async def fake_search(query, category=None, days=14):
            return "RESULT:%s:%s:%s" % (query, category, days)
        try:
            tools._search_football_news = fake_search
            result = asyncio.run(tools.execute_tool_call({
                "function": {
                    "name": "search_football_news",
                    "arguments": json.dumps({"query": "英超", "category": "premier_league", "days": 7}, ensure_ascii=False),
                }
            }))
            self.assertEqual("RESULT:英超:premier_league:7", result)
        finally:
            tools._search_football_news = original
```

- [ ] **Step 2: Run the tool integration tests and verify they fail**

Run:

```bash
python -m unittest tests.test_arteta_football_news.FootballNewsToolIntegrationTests -v
```

Expected: FAIL because `search_football_news` is not in `TOOLS` and `_search_football_news` is missing.

- [ ] **Step 3: Modify `plugins/arteta_tools.py` to add the new tool schema**

Insert this object in the `TOOLS` list after the existing `search_news` object:

```python
    {
        "type": "function",
        "function": {
            "name": "search_football_news",
            "description": "查询本地全局足球新闻向量库。当用户问最近英超、欧冠、西甲、意甲、德甲、法甲、中超、五大联赛新闻或球队动态时调用。优先用中文关键词查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户关心的新闻关键词，如 '英超争冠', '欧冠最新消息', '中超转会'"
                    },
                    "category": {
                        "type": "string",
                        "description": "可选分类：premier_league, champions_league, laliga, serie_a, bundesliga, ligue1, chinese_super_league, other"
                    },
                    "days": {
                        "type": "integer",
                        "description": "查询最近多少天，默认14，最大90"
                    }
                },
                "required": ["query"]
            }
        }
    },
```

- [ ] **Step 4: Add executor branch and helper function in `plugins/arteta_tools.py`**

Add this branch in `execute_tool_call` after `search_news`:

```python
    elif name == "search_football_news":
        return await _search_football_news(
            args.get("query", ""),
            args.get("category"),
            args.get("days", 14),
        )
```

Add this helper after `_search_news`:

```python
async def _search_football_news(query: str, category=None, days: int = 14) -> str:
    """查询本地足球新闻向量库。"""
    try:
        from plugins.arteta_football_news import FootballNewsChromaStore, CHROMA_DB_DIR
        store = FootballNewsChromaStore(CHROMA_DB_DIR)
        store.initialize()
        try:
            safe_days = int(days)
        except (TypeError, ValueError):
            safe_days = 14
        category_value = str(category).strip() if category else None
        return store.search(query=query, category=category_value, days=safe_days)
    except Exception as e:
        print(f"[Tool Error] _search_football_news: {e}")
        return "足球新闻库暂时不可用。"
```

- [ ] **Step 5: Run tool and football-news tests**

Run:

```bash
python -m unittest tests.test_arteta_football_news -v
```

Expected: PASS.

- [ ] **Step 6: Commit Function Calling integration**

Run:

```bash
git add plugins/arteta_tools.py tests/test_arteta_football_news.py
git commit -m "feat: add football news function tool"
```

---

### Task 7: Developer verification suite

**Files:**
- Modify: `tools/verify_features.py`
- Modify: `tests/test_verify_features.py`

- [ ] **Step 1: Add failing registry test for the new suite**

Append this test method to `VerifyFeaturesTests` in `tests/test_verify_features.py`:

```python
    def test_registry_contains_football_news_suite(self):
        registry = verify_features.build_registry()
        self.assertIn("football_news", registry)
        case_names = [name for name, _case in registry["football_news"].cases]
        self.assertIn("offline_roundtrip", case_names)
```

- [ ] **Step 2: Run the registry test and verify it fails**

Run:

```bash
python -m unittest tests.test_verify_features.VerifyFeaturesTests.test_registry_contains_football_news_suite -v
```

Expected: FAIL because `football_news` is missing from the registry.

- [ ] **Step 3: Add `football_news_offline_roundtrip` case to `tools/verify_features.py`**

Insert this section before the Online suite section:

```python
# ---------------------------------------------------------------------------
# Football news suite
# ---------------------------------------------------------------------------


def football_news_offline_roundtrip(ctx: RunContext) -> CaseResult:
    start = time.time()
    football_news = import_module("plugins.arteta_football_news")
    db_path = ctx.run_path("football_news", "football_news.db")
    chroma_dir = ctx.run_path("football_news", "chroma")
    sqlite_store = football_news.FootballNewsSQLiteStore(db_path)
    sqlite_store.initialize()
    chroma_store = football_news.FootballNewsChromaStore(chroma_dir)
    chroma_store.initialize()
    if not getattr(chroma_store, "_ready", False):
        return fail_result("football_news", "offline_roundtrip", "Chroma football_news collection did not initialize", start, artifacts=[relative(chroma_dir)])
    now = int(time.time())
    items = [
        football_news.NewsItem("阿森纳继续追逐英超冠军", "https://example.com/pl-a", "fixture", "premier_league", "阿森纳仍在争冠集团。", now, now).with_hash(),
        football_news.NewsItem("中超焦点战今晚打响", "https://example.com/csl-a", "fixture", "chinese_super_league", "中超焦点战今晚进行。", now, now).with_hash(),
    ]
    inserted = 0
    for item in items:
        chroma_id = chroma_store.add_item(item)
        if sqlite_store.insert_item(item, chroma_id):
            inserted += 1
    chroma_store.add_digest(items, now)
    search_result = chroma_store.search("英超 阿森纳", category="premier_league", days=14, now=now)
    artifact = ctx.artifact_path("football_news", "search_result.txt")
    write_text(artifact, search_result)
    if inserted != 2:
        return fail_result("football_news", "offline_roundtrip", "Expected 2 inserted football news items", start, artifacts=[relative(db_path), relative(artifact)], details={"inserted": inserted})
    if "阿森纳继续追逐英超冠军" not in search_result:
        return fail_result("football_news", "offline_roundtrip", "Inserted Premier League item was not returned by search", start, artifacts=[relative(db_path), relative(chroma_dir), relative(artifact)])
    return pass_result(
        "football_news",
        "offline_roundtrip",
        "Inserted item and digest documents into isolated football_news collection",
        start,
        artifacts=[relative(db_path), relative(chroma_dir), relative(artifact)],
        details={"inserted": inserted},
    )
```

- [ ] **Step 4: Register the new suite in `build_registry`**

Add this registry entry before `online`:

```python
        "football_news": SuiteSpec(
            "football_news",
            "Global football news SQLite and ChromaDB checks",
            [
                ("offline_roundtrip", safe_case("football_news", "offline_roundtrip", football_news_offline_roundtrip)),
            ],
        ),
```

Update the `core_cases` suite list from:

```python
    for suite_name in ("render", "memory", "chat", "commands"):
```

to:

```python
    for suite_name in ("render", "memory", "chat", "commands", "football_news"):
```

- [ ] **Step 5: Add the new plugin to command import verification**

In `commands_plugin_imports`, add this string to the `modules` list:

```python
        "plugins.arteta_football_news",
```

- [ ] **Step 6: Run verification tests and the new suite**

Run:

```bash
python -m unittest tests.test_verify_features -v
python tools/verify_features.py --suite football_news
```

Expected: unittest PASS and verification case `football_news/offline_roundtrip` PASS.

- [ ] **Step 7: Commit verification suite**

Run:

```bash
git add tools/verify_features.py tests/test_verify_features.py
git commit -m "test: verify football news vector sync"
```

---

### Task 8: Documentation updates

**Files:**
- Create: `docs/dev/football-news.md`
- Modify: `docs/dev/overview.md`
- Modify: `docs/dev/developer-verification.md`
- Modify: `docs/user/commands.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Create developer documentation**

Create `docs/dev/football-news.md`:

```markdown
# 全局足球新闻向量库

`plugins/arteta_football_news.py` 负责每天多次抓取固定中文足球新闻源，并把新闻写入全局 ChromaDB collection `football_news`。

## 覆盖范围

- 英超：最高优先级，入库配额最大。
- 欧冠：独立分类 `champions_league`。
- 其他五大联赛：`laliga`、`serie_a`、`bundesliga`、`ligue1`。
- 中超：分类 `chinese_super_league`。

## 存储

SQLite 表 `football_news_items` 用于去重、审计和清理。ChromaDB collection `football_news` 用于语义检索。

每次成功同步会写入两类向量文档：

- `item`：单条新闻，包含标题、来源、分类、摘要、链接和时间。
- `daily_digest`：本次同步新增新闻的分类总览。

新闻保留 90 天。同步时会删除 SQLite 中 90 天前的记录，并按 `chroma_id` 删除对应向量。

## 调度

默认开启，配置项：

```bash
FOOTBALL_NEWS_ENABLED=true
```

定时任务：

- `football_news_morning`：每天 03:30
- `football_news_evening`：每天 18:30

定时任务不主动群发，只更新本地数据库和向量库。

## 手动刷新

管理员命令：

- `刷新足球新闻`
- `足球新闻刷新`

命令会返回源成功数、新增条数、重复条数、总览写入状态和清理结果。

## 聊天接入

`plugins/arteta_tools.py` 提供 Function Calling 工具 `search_football_news`。当用户询问最近英超、欧冠、五大联赛或中超新闻时，LLM 可以按需检索 `football_news` collection。

## 验证

```bash
python -m unittest tests.test_arteta_football_news -v
python tools/verify_features.py --suite football_news
```

ECS 实机验证需确认插件加载、定时任务注册、手动刷新可写入 SQLite/ChromaDB，并在 QQ 群自然语言提问时触发 `search_football_news`。
```

- [ ] **Step 2: Update `docs/dev/overview.md`**

Add one row under the feature plugin table:

```markdown
| `plugins/arteta_football_news.py` | **全局足球新闻向量库**。固定中文源抓取英超/欧冠/五大联赛/中超新闻；写入 SQLite 去重表和 ChromaDB `football_news` collection；提供管理员刷新命令和 Function Calling 查询工具。 |
```

Add one row under the ChromaDB table:

```markdown
| `football_news` | 全局足球新闻情报：包含单条新闻和每日同步总览，供 `search_football_news` 工具语义检索 | arteta_football_news.py |
```

Add one row under the Function Calling tools table:

```markdown
| `search_football_news` | 查询全局足球新闻向量库 | ChromaDB `football_news` collection |
```

- [ ] **Step 3: Update `docs/dev/developer-verification.md`**

Add `football_news` to the suite list and add this command block:

```markdown
python tools/verify_features.py --suite football_news
```

Add this explanation:

```markdown
- `football_news`：使用隔离 SQLite/ChromaDB 路径验证全局足球新闻条目和总览可以写入并检索。
```

- [ ] **Step 4: Update `docs/user/commands.md`**

Add this command row:

```markdown
| `刷新足球新闻` | `足球新闻刷新` | 手动刷新全局足球新闻向量库（仅管理员） |
```

- [ ] **Step 5: Update `CLAUDE.md`**

Add this plugin row in the plugin list:

```markdown
│   ├── arteta_football_news.py # 全局足球新闻向量库（定时抓取 + ChromaDB）
```

Update the Function Calling tool count and table to include `search_football_news`.

- [ ] **Step 6: Run documentation-adjacent verification**

Run:

```bash
python tools/verify_features.py --list-suites
```

Expected: output includes `football_news`.

- [ ] **Step 7: Commit documentation**

Run:

```bash
git add docs/dev/football-news.md docs/dev/overview.md docs/dev/developer-verification.md docs/user/commands.md CLAUDE.md
git commit -m "docs: document football news vector sync"
```

---

### Task 9: Local full validation

**Files:**
- No new files expected.

- [ ] **Step 1: Run focused unit tests**

Run:

```bash
python -m unittest tests.test_arteta_football_news -v
python -m unittest tests.test_verify_features -v
```

Expected: PASS.

- [ ] **Step 2: Run focused verification suite**

Run:

```bash
python tools/verify_features.py --suite football_news
```

Expected: PASS with a report under `artifacts/verify/<timestamp>/report.json`.

- [ ] **Step 3: Run full offline verification**

Run:

```bash
python tools/verify_features.py --suite all
```

Expected: PASS or only documented environment skips such as Playwright Chromium missing.

- [ ] **Step 4: Check git status and commit any validation-only fixes**

Run:

```bash
git status --short
```

Expected: no unexpected untracked files outside `artifacts/verify/`. If validation revealed a code or docs fix, commit only the relevant source/docs/test files with:

```bash
git add <specific files>
git commit -m "fix: stabilize football news validation"
```

---

### Task 10: ECS deployment and live validation

**Files:**
- No repository files should be changed unless ECS validation reveals a real bug.

- [ ] **Step 1: Confirm current local diff is committed or intentionally staged**

Run:

```bash
git status --short
```

Expected: implementation files are committed or the operator has explicitly chosen to deploy uncommitted local files.

- [ ] **Step 2: Upload changed files to ECS**

Upload these paths to `/opt/arteta_bot/` on ECS using the project's established deployment method:

```text
plugins/arteta_football_news.py
plugins/arteta_tools.py
tools/verify_features.py
docs/dev/football-news.md
docs/dev/overview.md
docs/dev/developer-verification.md
docs/user/commands.md
CLAUDE.md
```

If tests or fixtures are also available on ECS, upload:

```text
tests/test_arteta_football_news.py
tests/test_verify_features.py
tests/fixtures/football_news/sina_premier_league.html
tests/fixtures/football_news/netease_chinese_super_league.html
```

- [ ] **Step 3: Restart the bot on ECS**

Run on ECS:

```bash
supervisorctl restart arteta_bot
supervisorctl status arteta_bot
```

Expected: `arteta_bot RUNNING`.

- [ ] **Step 4: Check ECS logs for startup health**

Run on ECS:

```bash
supervisorctl tail -f arteta_bot
```

Expected log evidence:

```text
plugins.arteta_football_news loaded without ImportError
football_news collection ready
football_news_morning registered
football_news_evening registered
```

If the scheduler does not print job IDs, confirm no plugin import traceback appears.

- [ ] **Step 5: Run ECS manual refresh**

From the admin QQ account, send in a real group:

```text
刷新足球新闻
```

Expected bot response includes:

```text
足球新闻刷新完成
源：<succeeded>/<attempted> 成功
新增：<number> 条
重复：<number> 条
总览：已写入
```

A result with some failed sources is acceptable if at least one source succeeds and new or duplicate items are counted.

- [ ] **Step 6: Inspect ECS SQLite and Chroma side effects**

Run on ECS:

```bash
python - <<'PY'
import sqlite3
conn = sqlite3.connect('/opt/arteta_bot/arsenal_data.db')
print(conn.execute('select count(*) from football_news_items').fetchone()[0])
print(conn.execute('select title, source, category from football_news_items order by fetched_at desc limit 5').fetchall())
conn.close()
PY
```

Expected: count is greater than zero after a successful refresh.

Run on ECS:

```bash
python - <<'PY'
from plugins.arteta_football_news import FootballNewsChromaStore
store = FootballNewsChromaStore('/opt/arteta_bot/chroma_db')
store.initialize()
print(store.search('英超 阿森纳', category='premier_league', days=14))
PY
```

Expected: output contains at least one football news result or a clear no-result message if the refresh inserted only other categories.

- [ ] **Step 7: Verify real chat tool use**

In QQ group, ask:

```text
塔子 最近英超有什么新闻
塔子 欧冠最近有什么消息
塔子 中超最近怎么样
```

Expected: bot answers in Arteta voice and references recent news. Logs should show `search_football_news` tool execution.

- [ ] **Step 8: Commit ECS validation fix if needed**

If ECS reveals a source parser or environment bug, fix locally, run:

```bash
python -m unittest tests.test_arteta_football_news -v
python tools/verify_features.py --suite football_news
```

Then commit:

```bash
git add <specific fixed files>
git commit -m "fix: handle ecs football news validation"
```

Redeploy the fixed files and repeat ECS validation steps 3 through 7.

---

## Self-Review

Spec coverage:

- APScheduler automatic jobs: Task 5.
- Fixed Chinese media sources: Task 4.
- Premier League plus Champions League, top-five leagues, and Chinese Super League categories: Tasks 1 and 4.
- SQLite deduplication and audit storage: Task 2.
- Separate ChromaDB `football_news` collection with item and digest documents: Task 3.
- Function Calling tool: Task 6.
- Admin manual refresh command: Task 5.
- 90-day retention: Tasks 2 and 5.
- Local verification: Task 7 and Task 9.
- ECS live validation: Task 10.
- Documentation updates: Task 8.

Placeholder scan:

- The plan contains no `TBD`, `TODO`, or unspecified implementation steps.
- Every code-changing task includes concrete code blocks and exact test commands.

Type and naming consistency:

- `NewsItem`, `SyncResult`, `FootballNewsSQLiteStore`, `FootballNewsChromaStore`, `sync_football_news`, and `search_football_news` names are consistent across tests, implementation, verification, and docs.
- Category names match the spec: `premier_league`, `champions_league`, `laliga`, `serie_a`, `bundesliga`, `ligue1`, `chinese_super_league`, `other`.
