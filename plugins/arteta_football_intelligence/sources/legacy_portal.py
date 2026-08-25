import html
import re
from typing import Callable, List
from urllib.parse import urljoin

from .base import FootballEvidence, FootballSource, FootballSourceRequest, RawFootballCandidate


class LegacyPortalFootballSource(FootballSource):
    def __init__(self, source: dict, fetcher: Callable):
        self.source = dict(source or {})
        self.fetcher = fetcher

    async def discover(self, request: FootballSourceRequest) -> List[RawFootballCandidate]:
        html_text = await self.fetcher(self.source)
        base_url = str(self.source.get("base_url") or self.source.get("url") or "")
        source_name = str(self.source.get("source") or self.source.get("name") or "legacy_portal")
        max_items = min(int(self.source.get("max_items") or request.max_candidates or 10), int(request.max_candidates or 20))
        candidates = []
        for url, title in _parse_anchor_candidates(str(html_text or ""), base_url):
            if len(title) < 6:
                continue
            candidates.append(RawFootballCandidate(
                title=title,
                url=url,
                source_name=source_name,
                source_key=str(self.source.get("name") or "legacy_portal"),
                snippet="%s 来自 %s。" % (title, source_name),
                published_time="",
                event_types=list(request.event_types or []),
            ))
            if len(candidates) >= max_items:
                break
        return candidates

    async def fetch_evidence(self, candidate: RawFootballCandidate) -> FootballEvidence:
        return FootballEvidence(
            url=candidate.url,
            title=candidate.title,
            body_text=candidate.snippet,
            published_time=candidate.published_time,
        )


def _parse_anchor_candidates(html_text: str, base_url: str) -> List[tuple]:
    results = []
    for match in re.finditer(r"<a\b([^>]*)>(.*?)</a>", html_text or "", flags=re.I | re.S):
        attrs = match.group(1) or ""
        body = match.group(2) or ""
        href_match = re.search(r"href=[\"']([^\"']+)[\"']", attrs, flags=re.I)
        if not href_match:
            continue
        raw_url = html.unescape(href_match.group(1)).strip()
        if not raw_url or raw_url.startswith("<%"):
            continue
        title = _clean_title(body)
        if not title:
            title = _clean_title(attrs)
        if not title:
            continue
        results.append((urljoin(base_url, raw_url), title))
    return results


def _clean_title(value: str) -> str:
    text = html.unescape(value or "")
    for attr in ("alt", "title"):
        attr_match = re.search(r"%s=[\"']([^\"']+)[\"']" % attr, text, flags=re.I)
        if attr_match:
            text = attr_match.group(1)
            break
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
