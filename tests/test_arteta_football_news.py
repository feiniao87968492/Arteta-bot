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

    def test_news_sources_cover_required_competitions(self):
        module = load_module()
        categories = {source["category"] for source in module.NEWS_SOURCES}
        self.assertTrue({
            "premier_league",
            "champions_league",
            "laliga",
            "serie_a",
            "bundesliga",
            "ligue1",
            "chinese_super_league",
        }.issubset(categories))

    def test_news_sources_include_netease_premier_league_fallback(self):
        module = load_module()
        urls = [source["url"] for source in module.NEWS_SOURCES if source["category"] == "premier_league"]
        self.assertIn("https://sports.163.com/yc/", urls)

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

    def test_decode_html_response_handles_gbk_pages(self):
        module = load_module()
        body = '<a href="/a.html">英超阿森纳新闻</a>'.encode("gbk")
        html = module.decode_html_response(body, "text/html")
        self.assertIn("英超阿森纳新闻", html)

    def test_parse_links_filters_unrelated_category_links(self):
        module = load_module()
        html = '<a href="https://open.163.com/ocw/#ftopnav3">国际名校公开课</a><a href="/sports/article.html">中超焦点战今晚打响</a>'
        items = module.parse_source_html(html, "https://sports.163.com", "网易体育", "chinese_super_league", 1716400000, max_items=10)
        self.assertEqual(1, len(items))
        self.assertEqual("中超焦点战今晚打响", items[0].title)

    def test_parse_links_filters_old_archive_urls(self):
        module = load_module()
        html = '<a href="https://www.sohu.com/a/294740764_461392">英超三强争冠分析曼城火力最猛</a><a href="https://sports.sina.com.cn/g/pl/2026-05-23/doc-arsenal.html">阿森纳继续追逐英超冠军</a>'
        items = module.parse_source_html(html, "https://sports.sohu.com", "搜狐体育", "premier_league", 1779532200, max_items=10)
        self.assertEqual(1, len(items))
        self.assertEqual("阿森纳继续追逐英超冠军", items[0].title)

    def test_parse_links_filters_stale_dated_urls_and_portal_links(self):
        module = load_module()
        html = '<a href="http://sports.sina.com.cn/l/2015-05-11/05327603598.shtml">法甲-马赛2-1摩纳哥</a><a href="https://mail.163.com/register/index.htm">注册免费邮箱</a><a href="https://sports.sina.com.cn/global/france/2026-05-23/doc-fresh.shtml">法甲巴黎新赛季动态</a>'
        items = module.parse_source_html(html, "https://sports.sina.com.cn", "新浪体育", "ligue1", 1779532200, max_items=10)
        self.assertEqual(1, len(items))
        self.assertEqual("法甲巴黎新赛季动态", items[0].title)

    def test_parse_links_reads_nested_title_attributes_and_skips_portal_nav(self):
        module = load_module()
        html = '''
        <a href="https://www.163.com/">网易首页</a>
        <a href="https://sports.163.com/yc/">英超</a>
        <a href="https://sports.163.com/26/0523/20/example.html"><img src="a.jpg" alt="阿森纳继续追逐英超冠军"></a>
        <a href="https://epay.163.com/">网易跨境支付</a>
        <a href="<%=ms.previewLink || ''%>" target="_blank">前瞻</a>
        '''
        items = module.parse_source_html(html, "https://sports.163.com", "网易体育", "premier_league", 1779532200, max_items=10)
        self.assertEqual(1, len(items))
        self.assertEqual("阿森纳继续追逐英超冠军", items[0].title)


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


class FootballNewsToolIntegrationTests(unittest.TestCase):
    def test_detect_football_news_query_maps_recent_league_questions(self):
        import importlib
        tools = importlib.import_module("plugins.arteta_tools")
        self.assertEqual(("塔子 最近英超有什么新闻", "premier_league"), tools.detect_football_news_query("塔子 最近英超有什么新闻"))
        self.assertEqual(("塔子 欧冠最近有什么消息", "champions_league"), tools.detect_football_news_query("塔子 欧冠最近有什么消息"))
        self.assertIsNone(tools.detect_football_news_query("塔子 你怎么看训练强度"))

    def test_detect_football_news_query_ignores_image_understanding_requests(self):
        import importlib
        tools = importlib.import_module("plugins.arteta_tools")
        query = "这张图讲了什么\n\n【引用的消息】：[图片内容：画面里有英超最新积分榜和阿森纳新闻]"
        self.assertIsNone(tools.detect_football_news_query(query))

    def test_detect_football_news_query_ignores_image_descriptions_with_news_words(self):
        import importlib
        tools = importlib.import_module("plugins.arteta_tools")
        query = (
            "这个图讲了什么\n\n【引用的消息】：[图片内容：标题是 PREMIER LEAGUE SITUATION ROOM，"
            "正文提到了英超、阿森纳、曼城和最新新闻动态。]"
        )
        self.assertIsNone(tools.detect_football_news_query(query))

    def test_format_football_news_direct_answer_uses_search_results(self):
        import importlib
        tools = importlib.import_module("plugins.arteta_tools")
        result = "• [2026-05-23] 英超-曼城3-0 萨内破门｜搜狐体育｜摘要｜https://example.com/a\n• [2026-05-23] 英超三强争冠分析｜搜狐体育｜摘要｜https://example.com/b"
        answer = tools.format_football_news_direct_answer("塔子 最近英超有什么新闻", result)
        self.assertIn("英超-曼城3-0 萨内破门", answer)
        self.assertIn("英超三强争冠分析", answer)
        self.assertIn("【好感度+】", answer)
        self.assertNotIn("没有查到", answer)


if __name__ == "__main__":
    unittest.main()
