import asyncio
import base64
import ipaddress
import json
import os
import re
import time
import warnings
from html import unescape
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

from ..context import ToolContext
from ..providers.http_client import get_shared_async_client
from ..registry import ToolSpec, ensure_tool


USER_AGENT = "ArtetaBot/1.0 (+https://github.com/arteta-bot; factual verification)"
MAX_SEARCH_RESULTS = 8
MAX_FETCH_BYTES = 500_000
MAX_EXCERPT_CHARS = 1800
GROKSEARCH_TIMEOUT = 80.0
GROKSEARCH_API_URL = os.environ.get("ARTETA_GROKSEARCH_API_URL", "").strip()
GROKSEARCH_API_KEY = os.environ.get("ARTETA_GROKSEARCH_API_KEY", "").strip()
GROKSEARCH_MODEL = os.environ.get("ARTETA_GROKSEARCH_MODEL", "").strip()
X_FETCH_API_URL = os.environ.get("ARTETA_X_FETCH_API_URL", "").strip()
X_FETCH_API_KEY = os.environ.get("ARTETA_X_FETCH_API_KEY", "").strip()

try:
    warnings.filterwarnings("ignore", message=r".*duckduckgo_search.*renamed.*", category=RuntimeWarning)
    from duckduckgo_search import DDGS as DDGS_CLASS
except Exception:
    DDGS_CLASS = None

FRESHNESS_TO_DDG = {
    "day": "d",
    "week": "w",
    "month": "m",
    "year": "y",
    "recent": "m",
}


def _http_client():
    return get_shared_async_client()

PRIMARY_DOMAINS = (
    "arsenal.com",
    "premierleague.com",
    "uefa.com",
    "fifa.com",
    "thefa.com",
    "gov.uk",
    ".gov",
    ".edu",
    ".ac.uk",
)

AUTHORITATIVE_MEDIA_DOMAINS = (
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "theguardian.com",
    "theathletic.com",
    "skysports.com",
    "espn.com",
)


class PageExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.canonical_url = ""
        self.published_time = ""
        self._tag_stack = []
        self._skip_depth = 0
        self._in_title = False
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = {str(k).lower(): str(v or "") for k, v in attrs}
        self._tag_stack.append(tag)
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "link" and attrs_dict.get("rel", "").lower() == "canonical":
            self.canonical_url = attrs_dict.get("href", "").strip()
        if tag == "meta":
            key = (attrs_dict.get("property") or attrs_dict.get("name") or "").lower()
            if key in {"article:published_time", "date", "pubdate", "publishdate", "publish_date", "datepublished"}:
                self.published_time = attrs_dict.get("content", "").strip()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data):
        text = _clean_text(data)
        if not text:
            return
        if self._in_title:
            self.title = (self.title + " " + text).strip()
            return
        if self._skip_depth:
            return
        self._text_parts.append(text)

    @property
    def body_text(self) -> str:
        return _clean_text(" ".join(self._text_parts))


class MetaExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return
        attrs_dict = {str(k).lower(): str(v or "") for k, v in attrs}
        key = (attrs_dict.get("property") or attrs_dict.get("name") or "").lower()
        content = attrs_dict.get("content", "").strip()
        if key and content:
            self.values[key] = content


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(str(text or ""))).strip()


def _safe_int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _safe_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    try:
        hostname = parsed.hostname
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or _is_private_netloc(hostname):
        return ""
    return value


def _unsafe_url_message() -> str:
    return "[UnsafeURL] URL 不安全：只支持 http/https 公网链接。"


def _is_private_netloc(hostname: str) -> bool:
    host = str(hostname or "").strip().strip("[]").lower().rstrip(".")
    if not host:
        return True
    if host == "localhost" or host.endswith(".localhost"):
        return True
    if host.endswith((".local", ".internal", ".lan")):
        return True
    if "." not in host and ":" not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    )


def _ensure_safe_fetch_url(url: str) -> str:
    safe_url = _safe_url(url)
    if not safe_url:
        raise ValueError(_unsafe_url_message())
    return safe_url


def _domain(url: str) -> str:
    parsed = urlparse(str(url or ""))
    domain = (parsed.hostname or parsed.netloc).lower()
    return domain[4:] if domain.startswith("www.") else domain


def _domain_matches(domain: str, item: str) -> bool:
    value = str(item or "").lower()
    if value.startswith("."):
        return domain.endswith(value)
    return domain == value or domain.endswith("." + value)


def _source_level(url: str) -> str:
    domain = _domain(url)
    if any(_domain_matches(domain, item) for item in PRIMARY_DOMAINS):
        return "一手/官方来源"
    if any(domain == item or domain.endswith("." + item) for item in AUTHORITATIVE_MEDIA_DOMAINS):
        return "权威媒体来源"
    return "普通网页来源"


def _claim_result_score(claim: str, item: dict) -> int:
    url = _search_result_url(item)
    title = str(item.get("title") or item.get("name") or "")
    snippet = str(item.get("body") or item.get("snippet") or item.get("description") or "")
    haystack = (title + " " + snippet + " " + url).lower()
    claim_text = str(claim or "").lower()
    source_level = _source_level(url)
    score = {"一手/官方来源": 6, "权威媒体来源": 4, "普通网页来源": 1}.get(source_level, 0)

    is_match_claim = any(token in claim_text for token in (
        "比赛",
        "比分",
        "赛果",
        "赛程",
        "match",
        "score",
        "result",
        "fixture",
    ))
    if is_match_claim:
        if re.search(r"\d+\s*[-:]\s*\d+", haystack):
            score += 8
        if "阿根廷" in haystack or "argentina" in haystack:
            score += 3
        if "佛得角" in haystack or "cape verde" in haystack or "cabo verde" in haystack:
            score += 3
        if "世界杯" in haystack or "world cup" in haystack:
            score += 2
        if "集锦" in haystack or "加时" in haystack or "战胜" in haystack:
            score += 3
        domain = _domain(url)
        if any(value in domain for value in ("sports.cctv.com", "espn.com", "flashscore.com", "sofascore.com")):
            score += 3
        if "/teams/" in url or "/squad" in url:
            score -= 5
    return score


def _is_strong_match_result(claim: str, item: dict) -> bool:
    return _claim_result_score(claim, item) >= 12


def _search_result_url(item: dict) -> str:
    return str(item.get("href") or item.get("url") or item.get("link") or "").strip()


def _is_grok_result(item: dict) -> bool:
    return isinstance(item, dict) and str(item.get("_backend") or "") == "grok"


def _x_status_id(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if domain not in {"x.com", "twitter.com", "mobile.twitter.com"}:
        return ""
    match = re.search(r"/status(?:es)?/(\d+)", parsed.path)
    return match.group(1) if match else ""


def _x_username(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if domain not in {"x.com", "twitter.com", "mobile.twitter.com"}:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 3 and parts[1].lower() in {"status", "statuses"}:
        return parts[0].lower()
    return ""


def _is_x_status_url(url: str) -> bool:
    return bool(_x_status_id(url))


def _normalize_duckduckgo_href(href: str) -> str:
    value = unescape(str(href or "").strip())
    parsed = urlparse(value)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return value


def _normalize_bing_href(href: str) -> str:
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
    pattern = re.compile(r'<li[^>]+class=["\'][^"\']*b_algo[^"\']*["\'][^>]*>(.*?)</li>', re.I | re.S)
    results = []
    seen = set()
    for block_match in pattern.finditer(str(html_text or "")):
        block = block_match.group(1)
        link_match = re.search(r'<h2[^>]*>.*?<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>.*?</h2>', block, re.I | re.S)
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


def _parse_duckduckgo_html(html_text: str, max_results: int) -> list:
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
        snippet_match = re.search(r'class=["\'][^"\']*result__snippet[^"\']*["\'][^>]*>(.*?)</', tail, re.I | re.S)
        snippet = _clean_text(re.sub(r"<[^>]+>", " ", snippet_match.group(1))) if snippet_match else ""
        if title and _safe_url(href):
            results.append({"title": title, "href": href, "body": snippet})
        if len(results) >= max_results:
            break
    return results


async def _fetch_duckduckgo_html(query: str, max_results: int) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    response = await _http_client().get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers=headers,
        timeout=12.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.text


async def _fetch_bing_html(query: str, max_results: int) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    response = await _http_client().get(
        "https://www.bing.com/search",
        params={"q": query},
        headers=headers,
        timeout=10.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.text


async def _fetch_jina_duckduckgo_markdown(query: str, max_results: int) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/plain, text/markdown"}
    response = await _http_client().get(
        "https://r.jina.ai/http://duckduckgo.com/html/",
        params={"q": query},
        headers=headers,
        timeout=18.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def _parse_markdown_search_results(markdown_text: str, max_results: int) -> list:
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


def _parse_groksearch_search_response(data: dict, max_results: int) -> list:
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


def _config_attr(name: str) -> str:
    try:
        from nonebot import get_driver
        config = get_driver().config
    except Exception:
        return ""
    return str(getattr(config, name.lower(), "") or getattr(config, name, "") or "").strip()


def _safe_float(value, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _groksearch_timeout() -> float:
    value = (
        os.environ.get("ARTETA_GROKSEARCH_TIMEOUT", "").strip()
        or os.environ.get("GROKSEARCH_TIMEOUT", "").strip()
        or _config_attr("ARTETA_GROKSEARCH_TIMEOUT")
        or GROKSEARCH_TIMEOUT
    )
    return _safe_float(value, GROKSEARCH_TIMEOUT, 5.0, 170.0)


def _groksearch_config() -> tuple:
    url = (
        os.environ.get("ARTETA_GROKSEARCH_API_URL", "").strip()
        or str(GROKSEARCH_API_URL or "").strip()
        or _config_attr("ARTETA_GROKSEARCH_API_URL")
    )
    key = (
        os.environ.get("ARTETA_GROKSEARCH_API_KEY", "").strip()
        or str(GROKSEARCH_API_KEY or "").strip()
        or _config_attr("ARTETA_GROKSEARCH_API_KEY")
    )
    model = (
        os.environ.get("ARTETA_GROKSEARCH_MODEL", "").strip()
        or str(GROKSEARCH_MODEL or "").strip()
        or _config_attr("ARTETA_GROKSEARCH_MODEL")
    )
    return url, key, model


def _groksearch_enabled() -> bool:
    url, key, _model = _groksearch_config()
    return bool(url and key)


def _x_fetch_bridge_config() -> tuple:
    url = (
        os.environ.get("ARTETA_X_FETCH_API_URL", "").strip()
        or str(X_FETCH_API_URL or "").strip()
        or _config_attr("ARTETA_X_FETCH_API_URL")
    )
    key = (
        os.environ.get("ARTETA_X_FETCH_API_KEY", "").strip()
        or str(X_FETCH_API_KEY or "").strip()
        or _config_attr("ARTETA_X_FETCH_API_KEY")
    )
    return url, key


def _x_fetch_bridge_enabled() -> bool:
    url, key = _x_fetch_bridge_config()
    return bool(url and key)


async def _x_fetch_bridge_fetch(url: str) -> dict:
    api_url, key = _x_fetch_bridge_config()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    response = await _http_client().post(
        f"{api_url.rstrip('/')}/fetch",
        json={"url": url},
        headers=headers,
        timeout=35.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


async def _groksearch_post(tool_name: str, payload: dict) -> dict:
    url, key, _model = _groksearch_config()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    response = await _http_client().post(
        f"{url.rstrip('/')}/{tool_name}",
        json=payload,
        headers=headers,
        timeout=_groksearch_timeout(),
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.json()


async def _groksearch_search(query: str, max_results: int, freshness: str = "recent") -> list:
    if not _groksearch_enabled():
        return []
    payload = {
        "query": query,
        "max_results": max_results,
        "freshness": freshness,
    }
    _url, _key, model = _groksearch_config()
    if model:
        payload["model"] = model
    data = await _groksearch_post("web_search", payload)
    results = _parse_groksearch_search_response(data, max_results)
    if results:
        for item in results:
            item["_backend"] = "grok"
        return results
    session_id = data.get("session_id") if isinstance(data, dict) else ""
    if session_id:
        sources_data = await _groksearch_post("get_sources", {"session_id": session_id})
        results = _parse_groksearch_sources_response(sources_data, max_results)
        for item in results:
            item["_backend"] = "grok"
        return results
    return []


async def _groksearch_fetch(url: str) -> Optional[str]:
    if not _groksearch_enabled():
        return None
    url = _ensure_safe_fetch_url(url)
    data = await _groksearch_post("web_fetch", {"url": url})
    if isinstance(data, dict):
        for key in ("content", "text", "markdown", "result"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
    if isinstance(data, str):
        return data
    return None


async def _fetch_x_syndication(tweet_id: str) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
    }
    endpoint = "https://cdn.syndication.twimg.com/tweet-result"
    response = await _http_client().get(
        endpoint,
        params={"id": tweet_id, "lang": "en"},
        headers=headers,
        timeout=18.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.json()


def _extract_x_text(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("text", "full_text", "tweetText", "content"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_text(value)
    legacy = data.get("legacy")
    if isinstance(legacy, dict):
        return _extract_x_text(legacy)
    return ""


def _extract_x_author(data: dict) -> tuple:
    if not isinstance(data, dict):
        return "", ""
    name = _clean_text(data.get("author_name") or data.get("name") or "")
    username = _clean_text(data.get("author_username") or data.get("screen_name") or data.get("username") or "")
    user = data.get("user")
    if isinstance(user, dict):
        name = name or _clean_text(user.get("name") or "")
        username = username or _clean_text(user.get("screen_name") or user.get("username") or "")
    if username.startswith("@"):
        username = username[1:]
    return name, username


def _x_mirror_urls(source_url: str) -> list:
    parsed = urlparse(str(source_url or ""))
    path = parsed.path or ""
    return [
        "https://fxtwitter.com{0}".format(path),
        "https://vxtwitter.com{0}".format(path),
    ]


async def _fetch_x_mirror(url: str) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
    }
    response = await _http_client().get(
        url,
        headers=headers,
        timeout=18.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    return {
        "url": url,
        "final_url": str(response.url),
        "content_type": response.headers.get("content-type", ""),
        "text": response.text,
    }


def _format_x_mirror_page(fetched: dict, source_url: str) -> str:
    parser = MetaExtractor()
    parser.feed(str(fetched.get("text") or ""))
    values = parser.values
    text = _clean_text(
        values.get("twitter:description")
        or values.get("og:description")
        or values.get("description")
        or ""
    )
    if not text:
        return ""
    title = _clean_text(values.get("twitter:title") or values.get("og:title") or "")
    author_name = ""
    username = ""
    if title:
        title = re.sub(r"\s+on\s+X\s*$", "", title, flags=re.I).strip()
        title = re.sub(r"\s+on\s+Twitter\s*$", "", title, flags=re.I).strip()
        author_name = title
        username_match = re.search(r"@([A-Za-z0-9_]{1,20})", title)
        if username_match:
            username = username_match.group(1)
    expected_username = _x_username(source_url)
    if expected_username and username and username.lower() != expected_username:
        return ""
    page = {
        "url": fetched.get("final_url") or fetched.get("url") or source_url,
        "author_name": author_name,
        "author_username": username,
        "created_at": "",
        "text": text,
    }
    return _format_x_post(page, source_url)


def _format_x_post(data: dict, source_url: str) -> str:
    text = _extract_x_text(data)
    if not text:
        return ""
    author_name, username = _extract_x_author(data)
    created_at = _clean_text(data.get("created_at") or data.get("date") or "")
    lines = [
        "[x-post]",
        "X 原帖证据：",
    ]
    if author_name or username:
        author = author_name
        if username:
            author = "{0} (@{1})".format(author_name or username, username)
        lines.append("作者：{0}".format(author))
    if created_at:
        lines.append("发布时间：{0}".format(created_at))
    lines.append("链接：{0}".format(_safe_url(data.get("url") or source_url) or source_url))
    lines.append("正文：{0}".format(text[:MAX_EXCERPT_CHARS]))
    return "\n".join(lines)


def _format_search_results(results: list) -> str:
    if not results:
        return "未找到可用搜索结果。"
    lines = ["搜索结果（仅用于发现线索，回答事实前应继续抓取来源页面核实）："]
    if any(_is_grok_result(item) for item in results):
        lines.insert(0, "[grok]")
    for index, item in enumerate(results, start=1):
        url = _search_result_url(item)
        title = _clean_text(item.get("title")) or "(无标题)"
        snippet = _clean_text(item.get("body") or item.get("snippet"))[:260]
        date = _clean_text(item.get("date") or item.get("published") or "")
        source_level = _source_level(url)
        lines.append("{0}. {1}".format(index, title))
        lines.append("   来源等级：{0}".format(source_level))
        if date:
            lines.append("   日期：{0}".format(date))
        lines.append("   链接：{0}".format(url))
        if snippet:
            lines.append("   摘要：{0}".format(snippet))
    return "\n".join(lines)


def _grok_source_urls(results: list) -> list:
    urls = []
    seen = set()
    for item in results or []:
        if not _is_grok_result(item):
            continue
        safe_url = _safe_url(_search_result_url(item))
        if safe_url and safe_url not in seen:
            urls.append(safe_url)
            seen.add(safe_url)
    return urls


async def _write_grok_snapshot_image(page: dict, source_url: str) -> str:
    from . import link_analysis

    os.makedirs(link_analysis.SNAPSHOT_DIR, exist_ok=True)
    screenshot_url = page.get("url") or source_url
    image_bytes = await link_analysis._capture_page_screenshot(screenshot_url)
    path = os.path.join(link_analysis.SNAPSHOT_DIR, "grok_source_{0}.png".format(int(time.time() * 1000)))
    with open(path, "wb") as fh:
        fh.write(image_bytes)
    return path


async def _grok_source_snapshot_marker(source_urls: list) -> str:
    for source_url in source_urls or []:
        safe_url = _safe_url(source_url)
        if not safe_url:
            continue
        try:
            page = {"url": safe_url, "title": "", "published_time": "", "text": ""}
            snapshot_path = await _write_grok_snapshot_image(page, safe_url)
        except Exception:
            continue
        if snapshot_path:
            return "[LinkSnapshotImage: {0}]".format(snapshot_path)
    return ""


async def _append_grok_snapshot_marker(text: str, results: list) -> str:
    output = str(text or "")
    if "[grok]" not in output or "[LinkSnapshotImage:" in output:
        return output
    marker = await _grok_source_snapshot_marker(_grok_source_urls(results))
    if not marker:
        return output
    return "{0}\n{1}".format(output.rstrip(), marker)


def _parse_page(url: str, html_text: str) -> dict:
    parser = PageExtractor()
    parser.feed(str(html_text or ""))
    final_url = parser.canonical_url or url
    return {
        "title": _clean_text(parser.title) or "(无标题)",
        "url": final_url,
        "published_time": _clean_text(parser.published_time),
        "text": parser.body_text,
    }


def _format_page_evidence(page: dict, source_url: str) -> str:
    excerpt = _clean_text(page.get("text"))[:MAX_EXCERPT_CHARS]
    lines = [
        "网页证据：",
        "标题：{0}".format(page.get("title") or "(无标题)"),
        "来源等级：{0}".format(_source_level(page.get("url") or source_url)),
        "链接：{0}".format(page.get("url") or source_url),
    ]
    if page.get("published_time"):
        lines.append("发布时间：{0}".format(page.get("published_time")))
    lines.append("摘录：{0}".format(excerpt or "未提取到正文。"))
    return "\n".join(lines)


async def _duckduckgo_search(query: str, max_results: int = 5, timelimit=None) -> list:
    limit = _safe_int(max_results, 5, 1, MAX_SEARCH_RESULTS)

    try:
        bing_html = await _fetch_bing_html(query, limit)
        results = _parse_bing_html(bing_html, limit)
        if results:
            return results
    except Exception:
        pass

    try:
        html_text = await _fetch_duckduckgo_html(query, limit)
        results = _parse_duckduckgo_html(html_text, limit)
        if results:
            return results
    except Exception:
        pass

    try:
        markdown_text = await _fetch_jina_duckduckgo_markdown(query, limit)
        results = _parse_markdown_search_results(markdown_text, limit)
        if results:
            return results
    except Exception:
        pass

    if os.environ.get("ARTETA_WEB_SEARCH_USE_DDGS", "").lower() not in {"1", "true", "yes"}:
        return []

    def _search():
        if DDGS_CLASS is None:
            return []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with DDGS_CLASS(headers={"User-Agent": USER_AGENT}) as ddgs:
                try:
                    return list(ddgs.text(query, max_results=limit, timelimit=timelimit))
                except TypeError:
                    return list(ddgs.text(query, max_results=limit))

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _search)
    except Exception:
        return []


async def _fetch_url(url: str, timeout_seconds: float = 10.0, max_bytes: int = MAX_FETCH_BYTES) -> dict:
    url = _ensure_safe_fetch_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5"}
    async with _http_client().stream(
        "GET",
        url,
        headers=headers,
        timeout=timeout_seconds,
        follow_redirects=True,
    ) as response:
        response.raise_for_status()
        final_url = _ensure_safe_fetch_url(str(response.url))
        content = await _read_limited_response(response, max_bytes)
        encoding = response.encoding or "utf-8"
        return {
            "url": url,
            "final_url": final_url,
            "content_type": response.headers.get("content-type", ""),
            "text": content.decode(encoding, errors="replace"),
        }


async def _read_limited_response(response, max_bytes: int) -> bytes:
    limit = max(0, int(max_bytes or 0))
    chunks = []
    total = 0
    async for chunk in response.aiter_bytes():
        if not chunk:
            continue
        remaining = limit - total
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            total += remaining
            break
        chunks.append(chunk)
        total += len(chunk)
        if total >= limit:
            break
    return b"".join(chunks)


async def _search_web(query: str, max_results: int = 5, freshness: str = "recent", timelimit=None) -> list:
    limit = _safe_int(max_results, 5, 1, MAX_SEARCH_RESULTS)
    if _groksearch_enabled():
        try:
            grok_results = await asyncio.wait_for(
                _groksearch_search(query, max_results=limit, freshness=freshness),
                timeout=_groksearch_timeout() + 2.0,
            )
            if grok_results:
                for item in grok_results:
                    if isinstance(item, dict):
                        item["_backend"] = "grok"
                return grok_results[:limit]
        except Exception:
            pass
    return await asyncio.wait_for(_duckduckgo_search(query, max_results=limit, timelimit=timelimit), timeout=12.0)


async def web_search(ctx: ToolContext, query: str, freshness: str = "recent", max_results: int = 5) -> str:
    text = _clean_text(query)
    if not text:
        return "请提供要搜索的关键词。"
    limit = _safe_int(max_results, 5, 1, MAX_SEARCH_RESULTS)
    timelimit = FRESHNESS_TO_DDG.get(str(freshness or "recent").lower())
    try:
        results = await _search_web(text, max_results=limit, freshness=str(freshness or "recent"), timelimit=timelimit)
    except asyncio.TimeoutError:
        return "[WebSearchTimeout] 搜索超时。"
    except Exception as exc:
        return "[WebSearchError] 搜索失败：{0}: {1}".format(exc.__class__.__name__, exc)
    visible_results = results[:limit]
    return await _append_grok_snapshot_marker(_format_search_results(visible_results), visible_results)


async def grok_search(ctx: ToolContext, query: str, freshness: str = "recent", max_results: int = 5) -> str:
    text = _clean_text(query)
    if not text:
        return "请提供要用 GrokSearch 搜索的关键词。"
    if not _groksearch_enabled():
        return "GrokSearch 未配置：请设置 ARTETA_GROKSEARCH_API_URL 和 ARTETA_GROKSEARCH_API_KEY。"
    limit = _safe_int(max_results, 5, 1, MAX_SEARCH_RESULTS)
    try:
        results = await asyncio.wait_for(
            _groksearch_search(text, max_results=limit, freshness=str(freshness or "recent")),
            timeout=_groksearch_timeout() + 2.0,
        )
    except asyncio.TimeoutError:
        return "[GrokSearchTimeout] GrokSearch 搜索超时。"
    except Exception as exc:
        return "[GrokSearchError] GrokSearch 搜索失败：{0}: {1}".format(exc.__class__.__name__, exc)
    for item in results:
        if isinstance(item, dict):
            item["_backend"] = "grok"
    visible_results = results[:limit]
    return await _append_grok_snapshot_marker(_format_search_results(visible_results), visible_results)


async def fetch_x_post(ctx: ToolContext, url: str) -> str:
    safe_url = _safe_url(url)
    tweet_id = _x_status_id(safe_url)
    if not safe_url or not tweet_id:
        return "请提供 x.com/twitter.com 的 status 链接。"

    if _x_fetch_bridge_enabled():
        try:
            data = await asyncio.wait_for(_x_fetch_bridge_fetch(safe_url), timeout=40.0)
            formatted = _format_x_post(data, safe_url)
            if formatted:
                backend = _clean_text(data.get("backend") or "")
                if backend:
                    formatted = "{0}\n读取方式：{1}".format(formatted, backend)
                return formatted
        except Exception:
            pass

    try:
        data = await asyncio.wait_for(_fetch_x_syndication(tweet_id), timeout=20.0)
        formatted = _format_x_post(data, safe_url)
        if formatted:
            return formatted
    except Exception:
        pass

    for mirror_url in _x_mirror_urls(safe_url):
        try:
            fetched = await asyncio.wait_for(_fetch_x_mirror(mirror_url), timeout=20.0)
            formatted = _format_x_mirror_page(fetched, safe_url)
            if formatted:
                return formatted
        except Exception:
            pass

    if _groksearch_enabled():
        try:
            grok_text = await asyncio.wait_for(_groksearch_fetch(safe_url), timeout=_groksearch_timeout() + 2.0)
            if grok_text:
                page = {
                    "url": safe_url,
                    "author_name": "GrokSearch",
                    "author_username": "",
                    "created_at": "",
                    "text": _clean_text(grok_text),
                }
                formatted = _format_x_post(page, safe_url)
                if formatted:
                    return "[grok]\n" + formatted
        except Exception:
            pass

    return (
        "[x-post-unavailable]\n"
        "无法读取 X 原帖正文：X 可能要求登录、JS 渲染或触发反爬限制。\n"
        "链接：{0}\n"
        "请让用户提供原帖截图、复制原文，或改用可公开打开的权威来源页面再核实。"
    ).format(safe_url)


async def web_fetch(ctx: ToolContext, url: str, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    safe_url = _safe_url(url)
    if not safe_url:
        return _unsafe_url_message()
    if _is_x_status_url(safe_url):
        return await fetch_x_post(ctx, safe_url)
    max_chars = _safe_int(max_chars, MAX_EXCERPT_CHARS, 300, 4000)
    if _groksearch_enabled():
        try:
            grok_text = await asyncio.wait_for(_groksearch_fetch(safe_url), timeout=_groksearch_timeout() + 2.0)
            if grok_text:
                page = {
                    "title": "(GrokSearch)",
                    "url": safe_url,
                    "published_time": "",
                    "text": _clean_text(grok_text)[:max_chars],
                }
                return "[grok]\n" + _format_page_evidence(page, safe_url)
        except ValueError as exc:
            return str(exc)
        except Exception:
            pass
    try:
        fetched = await asyncio.wait_for(_fetch_url(safe_url), timeout=12.0)
    except asyncio.TimeoutError:
        return "[WebFetchTimeout] 抓取超时。"
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return "[WebFetchError] 抓取失败：{0}: {1}".format(exc.__class__.__name__, exc)
    page = _parse_page(fetched.get("final_url") or safe_url, fetched.get("text") or "")
    page["text"] = page.get("text", "")[:max_chars]
    return _format_page_evidence(page, safe_url)


async def verify_recent_claim(ctx: ToolContext, claim: str, preferred_sources: str = "", max_results: int = 5) -> str:
    text = _clean_text(claim)
    if not text:
        return "请提供要核实的说法。"
    query = text
    if preferred_sources:
        query = "{0} {1}".format(text, _clean_text(preferred_sources))
    limit = _safe_int(max_results, 5, 1, MAX_SEARCH_RESULTS)
    try:
        results = await _search_web(query, max_results=limit, freshness="recent", timelimit="m")
    except asyncio.TimeoutError:
        return "[WebVerifyTimeout] 核实搜索超时。"
    except Exception as exc:
        return "[WebVerifyError] 核实搜索失败：{0}: {1}".format(exc.__class__.__name__, exc)

    candidates = [item for item in results if _safe_url(_search_result_url(item))]
    if not candidates:
        return "未找到可靠网页来源，不能确认该说法。"

    candidates.sort(key=lambda item: _claim_result_score(text, item), reverse=True)
    selected = candidates[0]
    selected_url = _search_result_url(selected)
    try:
        fetched = await asyncio.wait_for(_fetch_url(selected_url), timeout=12.0)
        page = _parse_page(fetched.get("final_url") or selected_url, fetched.get("text") or "")
        evidence = _format_page_evidence(page, selected_url)
    except Exception:
        page = {
            "title": _clean_text(selected.get("title")) or "(无标题)",
            "url": selected_url,
            "published_time": _clean_text(selected.get("date")),
            "text": _clean_text(selected.get("body") or selected.get("snippet")),
        }
        evidence = _format_page_evidence(page, selected_url)

    caveat = "结论：已找到可核查来源；请基于下方证据作答。"
    if _source_level(selected_url) == "普通网页来源" and not _is_strong_match_result(text, selected):
        caveat = "结论：只找到普通网页来源，不能当作强证据；回答时必须说明仍未核到官方/权威来源。"
    result = "{0}\n待核实说法：{1}\n{2}".format(caveat, text, evidence)
    if _is_grok_result(selected):
        return await _append_grok_snapshot_marker("[grok]\n" + result, [selected])
    return result


def register_tools() -> None:
    web_timeout = _groksearch_timeout() + 2.0
    ensure_tool(ToolSpec(
        name="grok_search",
        description="GrokSearch 独立搜索工具，优先用于最新新闻、X/Twitter/社媒内容、转会、伤病、官宣和需要强实时性的事实查询；不会回退到普通网页搜索，结果仍需按来源强度谨慎判断。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "GrokSearch 搜索关键词，查 X/Twitter 时可加入 site:x.com 或账号名"},
                "freshness": {"type": "string", "enum": ["day", "week", "month", "year", "recent", "all"], "description": "时间范围，默认 recent"},
                "max_results": {"type": "integer", "description": "返回条数，1-8"},
            },
            "required": ["query"],
        },
        handler=grok_search,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
    ))
    ensure_tool(ToolSpec(
        name="web_search",
        description="互联网搜索工具，用于发现真实来源线索。适合最新新闻、2024 年以后事实、陌生实体、需要联网核实时调用；搜索结果不是最终证据，回答前应继续用 web_fetch 或 verify_recent_claim 核实来源。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，尽量包含实体、日期、关键词"},
                "freshness": {"type": "string", "enum": ["day", "week", "month", "year", "recent", "all"], "description": "时间范围，默认 recent"},
                "max_results": {"type": "integer", "description": "返回条数，1-8"},
            },
            "required": ["query"],
        },
        handler=web_search,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
    ))
    ensure_tool(ToolSpec(
        name="fetch_x_post",
        description="读取 x.com/twitter.com status 原帖正文。用于核实 X/Twitter 原帖、记者原帖、俱乐部社媒官宣；比通用 web_fetch 更适合 X 链接，失败时会明确要求截图或原文。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "x.com/twitter.com 的 status 链接"},
            },
            "required": ["url"],
        },
        handler=fetch_x_post,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
    ))
    ensure_tool(ToolSpec(
        name="web_fetch",
        description="抓取并提取指定 http/https 网页的标题、链接、发布时间和正文摘录，用于核实 web_search 找到的来源；x.com/twitter.com status 链接应优先用 fetch_x_post。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要抓取的 http/https URL"},
                "max_chars": {"type": "integer", "description": "正文摘录最大长度，300-4000"},
            },
            "required": ["url"],
        },
        handler=web_fetch,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
    ))
    ensure_tool(ToolSpec(
        name="verify_recent_claim",
        description="核实近期/最新/2024 年以后事实陈述。会搜索来源并优先抓取官方或一手来源；用于降低 AI 幻觉，回答时应引用返回的来源。",
        parameters={
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "需要核实的说法或问题"},
                "preferred_sources": {"type": "string", "description": "可选，偏好的官方/权威来源关键词，如 Arsenal official"},
                "max_results": {"type": "integer", "description": "搜索条数，1-8"},
            },
            "required": ["claim"],
        },
        handler=verify_recent_claim,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
    ))
