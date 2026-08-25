from .base import FootballEvidence, RawFootballCandidate


class OfficialPageFetcher(object):
    def __init__(self, fetch_url):
        self.fetch_url = fetch_url

    async def fetch_evidence(self, candidate: RawFootballCandidate) -> FootballEvidence:
        page = await self.fetch_url(candidate.url)
        if not isinstance(page, dict):
            return FootballEvidence(url=candidate.url, title=candidate.title, body_text=candidate.snippet)
        return FootballEvidence(
            url=str(page.get("url") or page.get("final_url") or candidate.url),
            title=str(page.get("title") or candidate.title or ""),
            body_text=str(page.get("text") or page.get("body") or page.get("content") or ""),
            published_time=str(page.get("published_time") or candidate.published_time or ""),
        )
