"""DuckDuckGo search result parsing helpers."""

import re
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

from ..security import _safe_url
from ..verification import _clean_text


def _normalize_duckduckgo_href(href: str) -> str:
    """
    Restore DuckDuckGo redirect links to their target URL.

    DuckDuckGo HTML result hrefs often look like /l/?uddg=https%3A%2F%2Fexample.com&...
    """
    value = unescape(str(href or "").strip())
    parsed = urlparse(value)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return value


def _parse_duckduckgo_html(html_text: str, max_results: int) -> list:
    """Parse title, URL, and snippet from DuckDuckGo HTML results."""
    pattern = re.compile(
        r'<a[^>]+class=["\'][^"\']*result__a[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
        r'(?P<tail>.*?)(?=<a[^>]+class=["\'][^"\']*result__a|\Z)',
        re.I | re.S,
    )
    results = []
    for match in pattern.finditer(str(html_text or "")):
        href = _normalize_duckduckgo_href(match.group(1))
        title = _clean_text(re.sub(r"<[^>]+>", " ", match.group(2)))
        tail = match.group("tail") or ""
        snippet_match = re.search(
            r'class=["\'][^"\']*result__snippet[^"\']*["\'][^>]*>(.*?)</',
            tail,
            re.I | re.S,
        )
        snippet = _clean_text(re.sub(r"<[^>]+>", " ", snippet_match.group(1))) if snippet_match else ""

        if title and _safe_url(href):
            results.append({"title": title, "href": href, "body": snippet})

        if len(results) >= max_results:
            break

    return results

