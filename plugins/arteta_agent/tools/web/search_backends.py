"""Search backend abstraction for Web access tools."""

import asyncio
from typing import Awaitable, Callable, Iterable, List, Optional, Protocol

from .models import SearchHit


class SearchBackend(Protocol):
    name: str
    timeout_seconds: Optional[float]

    async def search(self, query: str, max_results: int, freshness: str) -> List[SearchHit]:
        ...


class CallableSearchBackend(object):
    def __init__(
        self,
        name: str,
        func: Callable[[str, int, str], Awaitable[Iterable[object]]],
        timeout_seconds: Optional[float] = None,
        result_backend: str = "",
    ):
        self.name = str(name or "")
        self._func = func
        self.timeout_seconds = timeout_seconds
        self._result_backend = str(result_backend or self.name)

    async def search(self, query: str, max_results: int, freshness: str) -> List[SearchHit]:
        results = await self._func(query, max_results, freshness)
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
) -> List[SearchHit]:
    backend_list = list(backends or [])
    for index, backend in enumerate(backend_list):
        is_last = index == len(backend_list) - 1
        try:
            timeout_seconds = getattr(backend, "timeout_seconds", None)
            if timeout_seconds:
                hits = await asyncio.wait_for(
                    backend.search(query, max_results, freshness),
                    timeout=float(timeout_seconds),
                )
            else:
                hits = await backend.search(query, max_results, freshness)
        except Exception:
            if is_last:
                raise
            continue
        if hits:
            return hits[:max_results]
    return []
