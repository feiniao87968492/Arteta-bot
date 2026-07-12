"""Page fetching, parsing, and formatting helpers for Web access tools."""

from html.parser import HTMLParser
from urllib.parse import urljoin

from ...providers.http_client import get_shared_async_client
from .security import (
    MAX_FETCH_REDIRECTS,
    _content_length_exceeds,
    _ensure_safe_fetch_url,
    _is_allowed_text_content_type,
    _validate_public_http_url,
)
from .verification import _clean_text, _source_level


USER_AGENT = "ArtetaBot/1.0 (+https://github.com/arteta-bot; factual verification)"
MAX_FETCH_BYTES = 500_000
MAX_EXCERPT_CHARS = 1800


def _http_client():
    return get_shared_async_client()


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
        tag = str(tag or "").lower()
        attrs_dict = dict((str(k).lower(), str(v or "")) for k, v in attrs)
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
        tag = str(tag or "").lower()
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


async def _fetch_url(
    url: str,
    timeout_seconds: float = 10.0,
    max_bytes: int = MAX_FETCH_BYTES,
    max_redirects: int = MAX_FETCH_REDIRECTS,
    http_client_factory=None,
) -> dict:
    original_url = _ensure_safe_fetch_url(url)
    current_url = original_url
    client_factory = http_client_factory or _http_client
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5"}

    for redirect_index in range(max(0, int(max_redirects or 0)) + 1):
        validated = _validate_public_http_url(current_url)
        async with client_factory().stream(
            "GET",
            validated.url,
            headers=headers,
            timeout=timeout_seconds,
            follow_redirects=False,
        ) as response:
            status_code = int(getattr(response, "status_code", 0) or 0)
            is_redirect = bool(getattr(response, "is_redirect", False)) or status_code in (301, 302, 303, 307, 308)
            if is_redirect:
                location = response.headers.get("location", "")
                if not location:
                    raise ValueError("[WebFetchError] redirect response has no Location header")
                if redirect_index >= max_redirects:
                    raise ValueError("[WebFetchError] too many redirects")
                current_url = urljoin(validated.url, location)
                _validate_public_http_url(current_url)
                continue

            response.raise_for_status()
            final_url = _ensure_safe_fetch_url(str(getattr(response, "url", validated.url)))
            content_type = response.headers.get("content-type", "")
            if not _is_allowed_text_content_type(content_type):
                raise ValueError("[UnsupportedContentType] 不支持直接抓取该 Content-Type：{0}".format(content_type or "(unknown)"))
            if _content_length_exceeds(response.headers, max_bytes):
                raise ValueError("[ResponseTooLarge] 响应体过大。")
            content = await _read_limited_response(response, max_bytes)
            encoding = getattr(response, "encoding", None) or "utf-8"
            return {
                "url": original_url,
                "final_url": final_url,
                "content_type": content_type,
                "text": content.decode(encoding, errors="replace"),
                "truncated": len(content) >= max(0, int(max_bytes or 0)),
            }

    raise ValueError("[WebFetchError] too many redirects")


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
