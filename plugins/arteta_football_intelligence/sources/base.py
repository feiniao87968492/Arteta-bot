from dataclasses import dataclass, field
from typing import List


@dataclass
class FootballSourceRequest:
    query: str
    event_types: List[str] = field(default_factory=list)
    window_start: int = 0
    window_end: int = 0
    max_candidates: int = 20


@dataclass
class RawFootballCandidate:
    title: str
    url: str
    source_name: str
    source_key: str
    snippet: str = ""
    published_time: str = ""
    event_types: List[str] = field(default_factory=list)


@dataclass
class FootballEvidence:
    url: str
    title: str = ""
    body_text: str = ""
    published_time: str = ""


class FootballSource(object):
    async def discover(self, request: FootballSourceRequest) -> List[RawFootballCandidate]:
        raise NotImplementedError

    async def fetch_evidence(self, candidate: RawFootballCandidate) -> FootballEvidence:
        return FootballEvidence(
            url=candidate.url,
            title=candidate.title,
            body_text=candidate.snippet,
            published_time=candidate.published_time,
        )
