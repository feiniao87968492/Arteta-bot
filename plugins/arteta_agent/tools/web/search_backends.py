"""Search backend abstraction for Web access tools."""

import asyncio
import logging
import time
from typing import Awaitable, Callable, Iterable, List, Optional, Protocol

from .models import SearchHit


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
