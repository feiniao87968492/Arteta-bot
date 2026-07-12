"""X/Twitter URL parsing and text formatting helpers."""

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

from .security import _safe_url


MAX_EXCERPT_CHARS = 1800


class MetaExtractor(HTMLParser):
    """Small HTML parser that only collects meta property/name content."""

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
