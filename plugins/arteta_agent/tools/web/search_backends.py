"""Search backend abstraction for Web access tools."""

import asyncio
import logging
import time
import warnings
from typing import Awaitable, Callable, Iterable, List, Optional, Protocol

from .models import SearchHit
from .parsers.bing import _parse_bing_html
from .parsers.duckduckgo import _parse_duckduckgo_html
from .parsers.markdown import _parse_markdown_search_results


LOGGER = logging.getLogger(__name__)


class TimeBudget(object):
    def __init__(self, total_seconds: Optional[float], now_func: Optional[Callable[[], float]] = None):
        self._now_func = now_func or time.monotonic
        if total_seconds is None:
            self._deadline = None
        else:
            self._deadline = self._now_func() + max(0.0, float(total_seconds))

    def remaining(self) -> Optional[float]:
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - self._now_func())


class SearchBackend(Protocol):
    name: str
    timeout_seconds: Optional[float]

    async def search(self, query: str, max_results: int, freshness: str, budget: Optional[TimeBudget]) -> List[SearchHit]:
        ...


class CallableSearchBackend(object):
    def __init__(
        self,
        name: str,
        func: Callable[[str, int, str, Optional[TimeBudget]], Awaitable[Iterable[object]]],
        timeout_seconds: Optional[float] = None,
        result_backend: str = "",
    ):
        self.name = str(name or "")
        self._func = func
        self.timeout_seconds = timeout_seconds
        self._result_backend = str(result_backend or self.name)

    async def search(self, query: str, max_results: int, freshness: str, budget: Optional[TimeBudget]) -> List[SearchHit]:
        results = await self._func(query, max_results, freshness, budget)
        hits = []
        for item in list(results or []):
            hit = SearchHit.from_mapping(item, default_backend=self._result_backend)
            if hit.title and hit.url:
                hits.append(hit)
        return hits[:max_results]


def _hits_from_items(items: Iterable[object], max_results: int, default_backend: str) -> List[SearchHit]:
    hits = []
    for item in list(items or []):
        hit = SearchHit.from_mapping(item, default_backend=default_backend)
        if hit.title and hit.url:
            hits.append(hit)
    return hits[:max_results]


class BingHtmlBackend(object):
    name = "bing_html"

    def __init__(self, fetch_html: Callable[[str, int], Awaitable[str]], timeout_seconds: float = 10.0):
        self._fetch_html = fetch_html
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, max_results: int, freshness: str, budget: Optional[TimeBudget]) -> List[SearchHit]:
        html_text = await self._fetch_html(query, max_results)
        return _hits_from_items(_parse_bing_html(html_text, max_results), max_results, "bing")


class DuckDuckGoHtmlBackend(object):
    name = "duckduckgo_html"

    def __init__(self, fetch_html: Callable[[str, int], Awaitable[str]], timeout_seconds: float = 12.0):
        self._fetch_html = fetch_html
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, max_results: int, freshness: str, budget: Optional[TimeBudget]) -> List[SearchHit]:
        html_text = await self._fetch_html(query, max_results)
        return _hits_from_items(_parse_duckduckgo_html(html_text, max_results), max_results, "duckduckgo")


class JinaSearchBackend(object):
    name = "jina_duckduckgo"

    def __init__(self, fetch_markdown: Callable[[str, int], Awaitable[str]], timeout_seconds: float = 18.0):
        self._fetch_markdown = fetch_markdown
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, max_results: int, freshness: str, budget: Optional[TimeBudget]) -> List[SearchHit]:
        markdown_text = await self._fetch_markdown(query, max_results)
        return _hits_from_items(_parse_markdown_search_results(markdown_text, max_results), max_results, "jina")


class DDGSBackend(object):
    name = "ddgs"

    def __init__(
        self,
        ddgs_class,
        user_agent: str,
        timelimit=None,
        timeout_seconds: float = 12.0,
    ):
        self._ddgs_class = ddgs_class
        self._user_agent = str(user_agent or "")
        self._timelimit = timelimit
        self.timeout_seconds = timeout_seconds

    async def search(self, query: str, max_results: int, freshness: str, budget: Optional[TimeBudget]) -> List[SearchHit]:
        if self._ddgs_class is None:
            return []

        def _search():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with self._ddgs_class(headers={"User-Agent": self._user_agent}) as ddgs:
                    try:
                        return list(ddgs.text(query, max_results=max_results, timelimit=self._timelimit))
                    except TypeError:
                        return list(ddgs.text(query, max_results=max_results))

        results = await asyncio.get_event_loop().run_in_executor(None, _search)
        return _hits_from_items(results, max_results, "ddgs")


async def run_search_backends(
    backends: Iterable[SearchBackend],
    query: str,
    max_results: int,
    freshness: str,
    budget: Optional[TimeBudget] = None,
    total_timeout_seconds: Optional[float] = None,
) -> List[SearchHit]:
    backend_list = list(backends or [])
    active_budget = budget
    if active_budget is None and total_timeout_seconds is not None:
        active_budget = TimeBudget(total_timeout_seconds)
    for index, backend in enumerate(backend_list):
        is_last = index == len(backend_list) - 1
        try:
            timeout_seconds = getattr(backend, "timeout_seconds", None)
            remaining = active_budget.remaining() if active_budget is not None else None
            if remaining is not None:
                if remaining <= 0:
                    raise asyncio.TimeoutError("search backend budget exhausted")
                timeout_seconds = min(float(timeout_seconds), remaining) if timeout_seconds else remaining
            if timeout_seconds:
                hits = await asyncio.wait_for(
                    backend.search(query, max_results, freshness, active_budget),
                    timeout=float(timeout_seconds),
                )
            else:
                hits = await backend.search(query, max_results, freshness, active_budget)
        except Exception as exc:
            LOGGER.warning(
                "web_search_backend_failed backend=%s error_code=%s",
                str(getattr(backend, "name", "") or "unknown"),
                exc.__class__.__name__,
            )
            if is_last:
                raise
            continue
        if hits:
            return hits[:max_results]
    return []
