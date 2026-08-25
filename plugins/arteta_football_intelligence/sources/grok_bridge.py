from typing import List, Optional
from urllib.parse import urlparse

from .base import FootballEvidence, FootballSource, FootballSourceRequest, RawFootballCandidate


class GrokBridgeFootballSource(FootballSource):
    def __init__(
        self,
        api_url: str,
        api_key: str = "",
        http_client=None,
        timeout_seconds: float = 30.0,
    ):
        self.api_url = str(api_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.http_client = http_client
        self.timeout_seconds = float(timeout_seconds or 30.0)

    async def discover(self, request: FootballSourceRequest) -> List[RawFootballCandidate]:
        data = await self._post_json("/web_search", {
            "query": request.query,
            "max_results": int(request.max_candidates or 20),
            "freshness": "recent",
        })
        candidates = []
        for item in self._result_items(data):
            url = self._field(item, "url", "href", "link")
            if not url:
                continue
            title = self._field(item, "title", "name")
            snippet = self._field(item, "snippet", "body", "description", "content")
            if not title and not snippet:
                continue
            candidates.append(RawFootballCandidate(
                title=title or url,
                url=url,
                source_name=self._source_name(url),
                source_key="grok_bridge",
                snippet=snippet,
                published_time=self._field(item, "published_time", "published", "date"),
                event_types=list(request.event_types or []),
            ))
            if len(candidates) >= int(request.max_candidates or 20):
                break
        return candidates

    async def fetch_evidence(self, candidate: RawFootballCandidate) -> FootballEvidence:
        data = await self._post_json("/web_fetch", {"url": candidate.url})
        return FootballEvidence(
            url=str(data.get("url") or data.get("final_url") or candidate.url),
            title=str(data.get("title") or candidate.title or ""),
            body_text=str(data.get("text") or data.get("body") or data.get("content") or candidate.snippet or ""),
            published_time=str(data.get("published_time") or data.get("published") or candidate.published_time or ""),
        )

    async def _post_json(self, path: str, payload: dict) -> dict:
        client = self.http_client
        close_client = False
        if client is None:
            import httpx
            client = httpx.AsyncClient()
            close_client = True
        try:
            response = await client.post(
                self.api_url + path,
                json=payload,
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}
        finally:
            if close_client:
                await client.aclose()

    def _headers(self) -> dict:
        if not self.api_key:
            return {}
        return {"Authorization": "Bearer " + self.api_key}

    @staticmethod
    def _result_items(data: dict) -> list:
        for key in ("results", "data", "sources"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return []

    @staticmethod
    def _field(item: dict, *names: str) -> str:
        if not isinstance(item, dict):
            return ""
        for name in names:
            value = item.get(name)
            if value:
                return str(value).strip()
        return ""

    @staticmethod
    def _source_name(url: str) -> str:
        domain = urlparse(str(url or "")).netloc.lower()
        return domain[4:] if domain.startswith("www.") else domain
