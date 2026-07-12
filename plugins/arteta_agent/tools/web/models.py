"""Internal structured models for Web access tools."""

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class SearchHit(object):
    title: str
    url: str
    snippet: str = ""
    backend: str = ""
    published_time: str = ""

    @classmethod
    def from_mapping(cls, item, default_backend: str = ""):
        if isinstance(item, cls):
            return item
        if not isinstance(item, dict):
            return cls(title="", url="", snippet="", backend=default_backend)
        return cls(
            title=str(item.get("title") or item.get("name") or ""),
            url=str(item.get("href") or item.get("url") or item.get("link") or ""),
            snippet=str(item.get("body") or item.get("snippet") or item.get("description") or item.get("content") or ""),
            backend=str(item.get("_backend") or item.get("backend") or default_backend or ""),
            published_time=str(item.get("date") or item.get("published_time") or item.get("published") or ""),
        )

    def to_legacy_dict(self) -> Dict[str, str]:
        data = {
            "title": self.title,
            "href": self.url,
            "body": self.snippet,
        }
        if self.backend:
            data["_backend"] = self.backend
        if self.published_time:
            data["date"] = self.published_time
        return data
