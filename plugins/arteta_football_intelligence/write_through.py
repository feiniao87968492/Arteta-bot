import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

from plugins.arteta_agent.result import TOOL_STATUS_OK

from .config import load_settings, load_source_config
from .entities import load_entity_catalog
from .ingestion import FootballIngestionService, candidate_to_item
from .normalize import normalize_url
from .sources.base import RawFootballCandidate


LOGGER = logging.getLogger(__name__)

WRITE_THROUGH_TOOLS = set([
    "grok_search",
    "web_search",
    "web_fetch",
    "fetch_x_post",
    "verify_recent_claim",
])

FOOTBALL_CONTEXT_TERMS = (
    "arsenal",
    "gunners",
    "saka",
    "rice",
    "odegaard",
    "romano",
    "ornstein",
    "premier league",
    "champions league",
    "football",
    "soccer",
    "transfer",
    "injury",
    "lineup",
    "fixture",
    "match",
    "uefa",
    "fifa",
    "\u963f\u68ee\u7eb3",
    "\u8428\u5361",
    "\u82f1\u8d85",
    "\u6b27\u51a0",
    "\u8f6c\u4f1a",
    "\u4f24\u75c5",
    "\u9996\u53d1",
    "\u6bd4\u8d5b",
    "\u8db3\u7403",
)


@dataclass
class WriteThroughResult:
    accepted: int = 0
    rejected: int = 0
    duplicate: int = 0
    index_failed: int = 0
    reason_codes: List[str] = field(default_factory=list)


def write_through_enabled() -> bool:
    return bool(load_settings().write_through_enabled)


def build_query_context_from_runtime_state(runtime_state) -> Dict[str, object]:
    ctx = getattr(runtime_state, "ctx", None)
    raw_message = str(getattr(ctx, "raw_message", "") or "").strip()
    if not raw_message:
        for message in reversed(list(getattr(runtime_state, "messages", []) or [])):
            if (message or {}).get("role") == "user":
                raw_message = str((message or {}).get("content") or "").strip()
                if raw_message:
                    break
    reply_text = str(getattr(ctx, "reply_text", "") or "").strip()
    combined = " ".join([raw_message, reply_text, " ".join(list(getattr(runtime_state, "freshness_reason_codes", []) or []))])
    return {
        "query": raw_message,
        "is_football": _looks_like_football_context(combined),
        "is_group": bool(getattr(ctx, "is_group", True)),
        "group_id": str(getattr(ctx, "group_id", "") or ""),
        "user_id": str(getattr(ctx, "user_id", "") or ""),
        "request_id": str(getattr(runtime_state, "request_id", "") or getattr(ctx, "request_id", "") or ""),
        "freshness_mode": str(getattr(runtime_state, "freshness_mode", "") or ""),
    }


def should_enqueue_tool_observation(tool_result, query_context: Dict[str, object]) -> bool:
    if str(getattr(tool_result, "name", "") or "") not in WRITE_THROUGH_TOOLS:
        return False
    if str(getattr(tool_result, "status", "") or "") != TOOL_STATUS_OK:
        return False
    if not is_football_query_context(query_context):
        return False
    if query_context.get("is_group") is False:
        return False
    return any(_source_has_valid_url(source) for source in extract_structured_sources(tool_result))


def is_football_query_context(query_context: Optional[Dict[str, object]]) -> bool:
    context = dict(query_context or {})
    if "is_football" in context:
        return bool(context.get("is_football"))
    return _looks_like_football_context(str(context.get("query") or ""))


def extract_structured_sources(tool_result) -> List[Dict[str, object]]:
    metadata = getattr(tool_result, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        return []
    sources = metadata.get("sources")
    if not isinstance(sources, list):
        return []
    return [dict(item) for item in sources if isinstance(item, dict)]


async def ingest_tool_observation(
    tool_name: str,
    tool_result,
    query_context: Optional[Dict[str, object]],
    sqlite_store=None,
    chroma_store=None,
    source_config=None,
    entity_catalog=None,
    now: Optional[int] = None,
) -> WriteThroughResult:
    result = WriteThroughResult()
    context = dict(query_context or {})
    actual_tool_name = str(tool_name or getattr(tool_result, "name", "") or "")

    if actual_tool_name not in WRITE_THROUGH_TOOLS:
        return _reject(result, "unsupported_tool")
    if str(getattr(tool_result, "status", "") or "") != TOOL_STATUS_OK:
        return _reject(result, "tool_status_not_ok")
    if context.get("is_group") is False:
        return _reject(result, "private_context")
    if not is_football_query_context(context):
        return _reject(result, "not_football_context")

    sources = extract_structured_sources(tool_result)
    if not sources:
        return _reject(result, "no_structured_sources")

    candidates = []
    for source in sources:
        candidate = _candidate_from_source(actual_tool_name, source, context)
        if candidate is None:
            result.rejected += 1
            _add_reason(result, "no_valid_sources")
            continue
        candidates.append(candidate)

    if not candidates:
        if result.rejected == 0:
            result.rejected = 1
        _add_reason(result, "no_valid_sources")
        return result

    current = int(now or time.time())
    if sqlite_store is None or chroma_store is None:
        sqlite_store, chroma_store = _default_stores()
    if source_config is None:
        settings = load_settings()
        source_config = load_source_config(settings.source_config_path)
    if entity_catalog is None:
        settings = load_settings()
        entity_catalog = load_entity_catalog(settings.entity_config_path)

    ingestion = FootballIngestionService(sqlite_store, chroma_store)
    for candidate in candidates:
        item = candidate_to_item(candidate, source_config, entity_catalog, fetched_at=current)
        ingest_result = ingestion.ingest_item(item)
        if ingest_result.duplicate:
            result.duplicate += 1
            continue
        if ingest_result.inserted:
            result.accepted += 1
        if ingest_result.index_status == "failed":
            result.index_failed += 1
            _add_reason(result, "index_failed")
    return result


class FootballWriteThroughQueue(object):
    def __init__(self, processor: Optional[Callable] = None, maxsize: int = 100):
        self.processor = processor or ingest_tool_observation
        self.queue = asyncio.Queue(maxsize=max(1, int(maxsize or 100)))
        self.worker = None
        self.closed = False

    async def enqueue(self, tool_name: str, tool_result, query_context: Dict[str, object]) -> bool:
        if self.closed:
            return False
        try:
            self.queue.put_nowait((str(tool_name or ""), tool_result, dict(query_context or {})))
        except asyncio.QueueFull:
            LOGGER.warning("football_write_through_queue_full")
            return False
        self._ensure_worker()
        return True

    async def drain(self) -> None:
        self._ensure_worker()
        await self.queue.join()

    async def close(self) -> None:
        self.closed = True
        await self.drain()
        if self.worker and not self.worker.done():
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass

    def _ensure_worker(self) -> None:
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while True:
            item = await self.queue.get()
            try:
                tool_name, tool_result, query_context = item
                await self.processor(tool_name, tool_result, query_context)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning(
                    "football_write_through_failed error_code=%s",
                    exc.__class__.__name__,
                )
            finally:
                self.queue.task_done()


_GLOBAL_QUEUE = None


def get_write_through_queue() -> FootballWriteThroughQueue:
    global _GLOBAL_QUEUE
    if _GLOBAL_QUEUE is None:
        _GLOBAL_QUEUE = FootballWriteThroughQueue()
    return _GLOBAL_QUEUE


async def drain_write_through_queue() -> None:
    global _GLOBAL_QUEUE
    if _GLOBAL_QUEUE is None:
        return
    await _GLOBAL_QUEUE.close()
    _GLOBAL_QUEUE = None


def _candidate_from_source(tool_name: str, source: Dict[str, object], query_context: Dict[str, object]):
    url = normalize_url(str(source.get("url") or ""))
    if not url:
        return None
    title = str(source.get("title") or query_context.get("query") or url).strip()
    snippet = str(source.get("snippet") or source.get("excerpt") or "").strip()
    combined = " ".join([str(query_context.get("query") or ""), title, snippet, url])
    if not _looks_like_football_context(combined):
        return None
    domain = _domain_from_url(url)
    source_name = str(source.get("source_name") or domain or tool_name).strip()
    event_types = source.get("event_types")
    return RawFootballCandidate(
        title=title,
        url=url,
        source_name=source_name,
        source_key=str(tool_name or ""),
        snippet=snippet,
        published_time=str(source.get("published_time") or ""),
        event_types=list(event_types or []),
    )


def _source_has_valid_url(source: Dict[str, object]) -> bool:
    return bool(normalize_url(str((source or {}).get("url") or "")))


def _looks_like_football_context(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(term.lower() in lowered for term in FOOTBALL_CONTEXT_TERMS)


def _domain_from_url(url: str) -> str:
    domain = (urlparse(str(url or "")).hostname or "").lower()
    return domain[4:] if domain.startswith("www.") else domain


def _default_stores():
    from plugins.arteta_football_news import get_default_stores

    return get_default_stores()


def _reject(result: WriteThroughResult, reason_code: str) -> WriteThroughResult:
    result.rejected += 1
    _add_reason(result, reason_code)
    return result


def _add_reason(result: WriteThroughResult, reason_code: str) -> None:
    if reason_code not in result.reason_codes:
        result.reason_codes.append(reason_code)
