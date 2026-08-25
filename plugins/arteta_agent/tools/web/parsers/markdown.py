"""Markdown search result parsing helpers."""

import re

from .duckduckgo import _normalize_duckduckgo_href
from ..security import _safe_url
from ..verification import _clean_text


def _parse_markdown_search_results(markdown_text: str, max_results: int) -> list:
    """Parse Jina/DuckDuckGo Markdown search results."""
    matches = list(re.finditer(r"##\s+\[([^\]]+)\]\(([^)]+)\)", str(markdown_text or "")))
    results = []
    seen = set()
    for index, match in enumerate(matches):
        title = _clean_text(match.group(1))
        href = _normalize_duckduckgo_href(match.group(2))
        if not title or not _safe_url(href) or href in seen:
            continue

        snippet_start = match.end()
        snippet_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        snippet = str(markdown_text or "")[snippet_start:snippet_end]
        snippet = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", snippet)
        snippet = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", snippet)
        snippet = _clean_text(snippet)[:300]

        results.append({"title": title, "href": href, "body": snippet})
        seen.add(href)

        if len(results) >= max_results:
            break

    return results
