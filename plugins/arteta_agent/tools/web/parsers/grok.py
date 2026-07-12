"""GrokSearch response parsing helpers."""

import re

from ..security import _safe_url
from ..verification import _clean_text


def _search_result_url(item: dict) -> str:
    """Extract URL from common search result mapping fields."""
    return str(item.get("href") or item.get("url") or item.get("link") or "").strip()


def _parse_groksearch_search_response(data: dict, max_results: int) -> list:
    """
    Parse GrokSearch web_search JSON.

    Supports structured result lists and falls back to Markdown links in text content.
    """
    results = []
    seen = set()
    items = []

    if isinstance(data, dict):
        for key in ("results", "data", "sources"):
            value = data.get(key)
            if isinstance(value, list):
                items = value
                break

    for item in items:
        if not isinstance(item, dict):
            continue
        url = _search_result_url(item)
        title = _clean_text(item.get("title") or item.get("name")) or ""
        snippet = _clean_text(item.get("snippet") or item.get("content") or item.get("description") or "")
        if not title and url:
            title = url
        if title and _safe_url(url) and url not in seen:
            results.append({"title": title, "href": url, "body": snippet})
            seen.add(url)
        if len(results) >= max_results:
            break

    if not results and isinstance(data, dict):
        results = _parse_groksearch_content_links(data, max_results)

    return results


def _parse_groksearch_content_links(data: dict, max_results: int) -> list:
    """Extract Markdown links from GrokSearch text content."""
    content = ""
    if isinstance(data, dict):
        for key in ("content", "text", "markdown", "result"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                content = value
                break
    if not content:
        return []

    matches = list(re.finditer(r"\[{1,2}([^\[\]]+)\]{1,2}\((https?://[^)\s]+)\)", content))
    results = []
    seen = set()

    for index, match in enumerate(matches):
        url = match.group(2).strip()
        if not _safe_url(url) or url in seen:
            continue

        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        tail = content[match.end():next_start]
        snippet = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", tail)
        snippet = _clean_text(snippet)

        if not snippet:
            start = max(0, match.start() - 180)
            end = min(len(content), match.end() + 260)
            snippet = _clean_text(re.sub(r"\[[^\]]+\]\([^)]+\)", " ", content[start:end]))

        label = _clean_text(match.group(1))
        if re.fullmatch(r"\[?\d+\]?", label):
            title = snippet[:100] or url
        else:
            title = label or snippet[:100] or url

        results.append({"title": title, "href": url, "body": snippet})
        seen.add(url)

        if len(results) >= max_results:
            break

    return results


def _parse_groksearch_sources_response(data: dict, max_results: int) -> list:
    """Parse GrokSearch get_sources JSON."""
    results = []
    seen = set()
    items = []

    if isinstance(data, dict):
        value = data.get("sources")
        if isinstance(value, list):
            items = value

    for item in items:
        if not isinstance(item, dict):
            continue
        url = _search_result_url(item)
        title = _clean_text(item.get("title") or item.get("name") or item.get("provider")) or ""
        snippet = _clean_text(item.get("description") or item.get("content") or item.get("snippet") or "")
        if not title and url:
            title = url
        if title and _safe_url(url) and url not in seen:
            results.append({"title": title, "href": url, "body": snippet})
            seen.add(url)
        if len(results) >= max_results:
            break

    return results

