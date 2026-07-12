"""Bing search result parsing helpers."""

import base64
import re
from html import unescape
from urllib.parse import parse_qs, urlparse

from ..security import _safe_url
from ..verification import _clean_text


def _normalize_bing_href(href: str) -> str:
    """
    Restore Bing redirect links to their target URL.

    Bing results may look like /ck/a?...&u=a1<base64>...
    """
    value = unescape(str(href or "").strip())
    parsed = urlparse(value)
    if "bing.com" in parsed.netloc and parsed.path.startswith("/ck/"):
        target = parse_qs(parsed.query).get("u", [""])[0]
        if target.startswith("a1"):
            payload = target[2:]
            payload += "=" * (-len(payload) % 4)
            try:
                return base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8", errors="replace")
            except Exception:
                return value
    return value


def _parse_bing_html(html_text: str, max_results: int) -> list:
    """Parse title, URL, and snippet from Bing result HTML."""
    pattern = re.compile(r'<li[^>]+class=["\'][^"\']*b_algo[^"\']*["\'][^>]*>(.*?)</li>', re.I | re.S)
    results = []
    seen = set()
    for block_match in pattern.finditer(str(html_text or "")):
        block = block_match.group(1)
        link_match = re.search(
            r'<h2[^>]*>.*?<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>.*?</h2>',
            block,
            re.I | re.S,
        )
        if not link_match:
            continue

        href = _normalize_bing_href(link_match.group(1))
        title = _clean_text(re.sub(r"<[^>]+>", " ", link_match.group(2)))
        snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, re.I | re.S)
        snippet = _clean_text(re.sub(r"<[^>]+>", " ", snippet_match.group(1))) if snippet_match else ""

        if title and _safe_url(href) and href not in seen:
            results.append({"title": title, "href": href, "body": snippet})
            seen.add(href)

        if len(results) >= max_results:
            break

    return results

