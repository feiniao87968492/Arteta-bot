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
except ImportError:
    pysqlite3 = None

if pysqlite3 is not None and callable(getattr(pysqlite3, "connect", None)) and all(
    hasattr(pysqlite3, name)
    for name in (
        "DatabaseError",
        "Error",
        "IntegrityError",
        "NotSupportedError",
        "OperationalError",
        "ProgrammingError",
        "Row",
        "Warning",
        "sqlite_version_info",
    )
):
    sys.modules["sqlite3"] = pysqlite3

import chromadb
from chromadb.config import Settings
from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot_plugin_apscheduler import scheduler

from plugins.arteta_football_intelligence.storage import FootballNewsSQLiteStore as BaseFootballNewsSQLiteStore
from plugins.arteta_football_intelligence.vector_index import (
    FootballNewsChromaStore as BaseFootballNewsChromaStore,
    build_item_chroma_id,
)

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
        "name": "网易体育-英超",
        "source": "网易体育",
        "url": "https://sports.163.com/yc/",
        "base_url": "https://sports.163.com",
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
        "name": "新浪体育-西甲",
        "source": "新浪体育",
        "url": "https://sports.sina.com.cn/global/spain/",
        "base_url": "https://sports.sina.com.cn",
        "category": "laliga",
        "max_items": 4,
    },
    {
        "name": "新浪体育-意甲",
        "source": "新浪体育",
        "url": "https://sports.sina.com.cn/global/italy/",
        "base_url": "https://sports.sina.com.cn",
        "category": "serie_a",
        "max_items": 4,
    },
    {
        "name": "新浪体育-德甲",
        "source": "新浪体育",
        "url": "https://sports.sina.com.cn/global/germany/",
        "base_url": "https://sports.sina.com.cn",
        "category": "bundesliga",
        "max_items": 4,
    },
    {
        "name": "新浪体育-法甲",
        "source": "新浪体育",
        "url": "https://sports.sina.com.cn/global/france/",
        "base_url": "https://sports.sina.com.cn",
        "category": "ligue1",
        "max_items": 4,
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
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
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
    text = re.sub(r"[—–−]+", " ", text)
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


def extract_link_title(raw_html: str) -> str:
    candidates = [raw_html or ""]
    for attr in ("alt", "title"):
        for match in re.finditer(r'%s=["\']([^"\']+)["\']' % attr, raw_html or "", re.I):
            candidates.append(match.group(1))
    for candidate in candidates:
        title = normalize_title(candidate)
        if title:
            return title
    return ""


def absolutize_url(url: str, base_url: str) -> str:
    value = html.unescape(url or "").strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("/"):
        return base_url.rstrip("/") + value
    return base_url.rstrip("/") + "/" + value


def decode_html_response(content: bytes, content_type: str = "") -> str:
    match = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    encodings = []
    if match:
        encodings.append(match.group(1))
    encodings.extend(["utf-8", "gb18030", "gbk"])
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


def is_fresh_url(url: str, fetched_at: int) -> bool:
    current_year = datetime.fromtimestamp(fetched_at).year
    patterns = [
        r"/(20\d{2})[-/](\d{1,2})[-/](\d{1,2})/",
        r"/(20\d{2})(\d{2})(\d{2})/",
        r"/(20\d{2})-\d{2}-\d{2}/",
        r"doc-[^/]*(20\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return int(match.group(1)) >= current_year - 1
    return True


def is_relevant_news_link(title: str, url: str, category: str, fetched_at: Optional[int] = None) -> bool:
    lowered_url = (url or "").lower()
    if any(marker in lowered_url for marker in ("open.163.com", "mail.163.com", "sitemap.163.com", "reg1.vip.163.com", "epay.163.com", "globalpay.163.com", "<%", "#", "javascript:", "mailto:")):
        return False
    if fetched_at is not None and not is_fresh_url(lowered_url, fetched_at):
        return False
    if re.search(r"sohu\.com/(a|picture)/", lowered_url):
        return False
    category_keywords = {
        "premier_league": ["英超", "阿森纳", "曼城", "曼联", "利物浦", "切尔西", "热刺"],
        "champions_league": ["欧冠", "冠军联赛", "冠军杯", "欧联", "欧战", "梅西", "C罗", "皇马", "巴萨"],
        "laliga": ["西甲", "皇马", "巴萨", "马竞"],
        "serie_a": ["意甲", "国米", "米兰", "尤文", "罗马", "那不勒斯"],
        "bundesliga": ["德甲", "拜仁", "多特", "勒沃库森"],
        "ligue1": ["法甲", "巴黎", "马赛", "里昂", "摩纳哥"],
        "chinese_super_league": ["中超", "国安", "申花", "海港", "泰山", "蓉城", "浙江队", "三镇"],
    }
    keywords = category_keywords.get(category)
    if not keywords:
        return True
    return any(keyword in title for keyword in keywords)


def parse_source_html(html_text: str, base_url: str, source: str, category: str,
                      fetched_at: int, max_items: int) -> List[NewsItem]:
    matches = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_text or "", re.I | re.S)
    items = []
    seen = set()
    for href, raw_title in matches:
        title = extract_link_title(raw_title)
        if len(title) < 6:
            continue
        url = absolutize_url(href, base_url)
        if not url.startswith("http") or not is_relevant_news_link(title, url, category, fetched_at):
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


class FootballNewsSQLiteStore(BaseFootballNewsSQLiteStore):
    pass


class FootballNewsChromaStore(BaseFootballNewsChromaStore):
    def __init__(self, chroma_dir: str = CHROMA_DB_DIR, collection=None):
        super(FootballNewsChromaStore, self).__init__(
            chroma_dir=chroma_dir,
            collection=collection,
            collection_name=COLLECTION_NAME,
        )


async def fetch_source_html(source: Dict[str, object]) -> str:
    import httpx
    async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
        resp = await client.get(str(source["url"]), headers=HEADERS, follow_redirects=True)
        if resp.status_code != 200:
            raise RuntimeError("%s returned HTTP %s" % (source.get("name"), resp.status_code))
        return decode_html_response(resp.content, resp.headers.get("content-type", ""))


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
    indexed_items = []
    for item in selected_items:
        hashed = item.with_hash()
        chroma_id = build_item_chroma_id(hashed)
        if not sqlite_store.insert_pending_item(hashed, chroma_id):
            result.duplicate_items += 1
            continue
        result.inserted_items += 1
        try:
            chroma_store.add_item(hashed)
        except Exception as e:
            sqlite_store.mark_index_status(chroma_id, "failed")
            logger.warning("[FootballNews] chroma add failed for %s: %s", hashed.title, e)
            continue
        sqlite_store.mark_index_status(chroma_id, "ready")
        indexed_items.append(hashed)
    if indexed_items:
        try:
            chroma_store.add_digest(indexed_items, fetched_at)
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
