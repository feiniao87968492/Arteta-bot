"""URL and response safety helpers for Web access tools."""

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse


MAX_URL_CHARS = 2048
ALLOWED_FETCH_PORTS = set([80, 443])
MAX_FETCH_REDIRECTS = 5
ALLOWED_TEXT_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    "application/json",
)

SENSITIVE_REMOTE_QUERY_KEYWORDS = set([
    "access",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "jwt",
    "key",
    "password",
    "secret",
    "session",
    "signature",
    "sig",
    "token",
])


@dataclass(frozen=True)
class _ValidatedURL(object):
    url: str
    hostname: str
    port: int
    resolved_ips: Tuple[str, ...]


def _parsed_port(parsed) -> Optional[int]:
    try:
        return parsed.port
    except ValueError:
        return -1


def _safe_url(url: str) -> str:
    """
    Validate a URL for public http/https fetches at the syntactic/netloc level.

    DNS-aware validation is handled by `_validate_public_http_url`.
    """
    value = str(url or "").strip()
    if not value or len(value) > MAX_URL_CHARS:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if parsed.username or parsed.password:
        return ""
    hostname = parsed.hostname or ""
    if not hostname:
        return ""
    port = _parsed_port(parsed)
    if port is not None and port not in ALLOWED_FETCH_PORTS:
        return ""
    if not parsed.netloc or _is_private_netloc(hostname):
        return ""
    return value


def _unsafe_url_message() -> str:
    return "[UnsafeURL] URL 不安全：只支持 http/https 公网链接。"


def _has_sensitive_remote_query(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    if not parsed.query:
        return False
    for key in parse_qs(parsed.query, keep_blank_values=True).keys():
        normalized = re.sub(r"[^a-z0-9]+", "_", str(key or "").lower()).strip("_")
        if not normalized:
            continue
        parts = [part for part in normalized.split("_") if part]
        if any(part in SENSITIVE_REMOTE_QUERY_KEYWORDS for part in parts):
            return True
        compact = normalized.replace("_", "")
        if any(compact.endswith(keyword) for keyword in SENSITIVE_REMOTE_QUERY_KEYWORDS):
            return True
    return False


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
        or not ip.is_global
    )


def _ensure_safe_fetch_url(url: str) -> str:
    safe_url = _safe_url(url)
    if not safe_url:
        raise ValueError(_unsafe_url_message())
    return safe_url


def _resolve_public_ips(hostname: str, port: int) -> Tuple[str, ...]:
    resolved = []
    seen = set()
    try:
        infos = socket.getaddrinfo(hostname, int(port), type=socket.SOCK_STREAM)
    except Exception:
        raise ValueError(_unsafe_url_message())
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_text = str(sockaddr[0] or "").strip()
        if not ip_text or ip_text in seen:
            continue
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            raise ValueError(_unsafe_url_message())
        if not ip.is_global:
            raise ValueError(_unsafe_url_message())
        seen.add(ip_text)
        resolved.append(ip_text)
    if not resolved:
        raise ValueError(_unsafe_url_message())
    return tuple(resolved)


def _validate_public_http_url(url: str, allowed_ports: Optional[Set[int]] = None) -> _ValidatedURL:
    safe_url = _ensure_safe_fetch_url(url)
    parsed = urlparse(safe_url)
    hostname = parsed.hostname or ""
    port = _parsed_port(parsed)
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    ports = allowed_ports or ALLOWED_FETCH_PORTS
    if port not in ports:
        raise ValueError(_unsafe_url_message())
    return _ValidatedURL(
        url=safe_url,
        hostname=hostname,
        port=port,
        resolved_ips=_resolve_public_ips(hostname, port),
    )


def _is_allowed_text_content_type(content_type: str) -> bool:
    value = str(content_type or "").split(";", 1)[0].strip().lower()
    if not value:
        return True
    return value in ALLOWED_TEXT_CONTENT_TYPES


def _content_length_exceeds(headers, max_bytes: int) -> bool:
    try:
        value = headers.get("content-length", "")
    except Exception:
        value = ""
    if not value:
        return False
    try:
        return int(value) > int(max_bytes)
    except (TypeError, ValueError):
        return False
