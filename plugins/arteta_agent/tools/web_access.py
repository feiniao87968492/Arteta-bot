"""
Web 访问工具模块 —— ArtetaBot 的网络搜索、网页抓取与事实核实。

提供五类对外工具（经由 ToolSpec 注册）：
- web_search      — 通用网页搜索（优先 GrokSearch，回退 DuckDuckGo / Bing）
- grok_search     — 独立的 GrokSearch 搜索（不回退，适合强实时内容）
- web_fetch       — 抓取指定 URL 并提取正文、标题、发布时间等
- fetch_x_post    — 专门抓取 X/Twitter 原帖正文（多通道自动降级）
- verify_recent_claim — 核实近期事实陈述，自动搜索并抓取最佳来源

内部依赖：
- duckduckgo_search（可选）：DDGS 作为最后回退的搜索引擎
- GrokSearch MCP 兼容 API：需 ARTETA_GROKSEARCH_* 环境变量
- X Fetch Bridge：可选的 X/Twitter 内容抓取中继
"""

import asyncio
import base64
import ipaddress
import json
import os
import re
import socket
import time
import warnings
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Optional, Set, Tuple
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

from ..context import ToolContext
from ..providers.http_client import get_shared_async_client
from ..registry import ToolSpec, ensure_tool
from ..result import TOOL_STATUS_ERROR, TOOL_STATUS_OK, TOOL_STATUS_TIMEOUT, TOOL_STATUS_UNAVAILABLE, ToolResult


# ---------------------------------------------------------------------------
# 全局常量
# ---------------------------------------------------------------------------

# 请求 UA，标识 ArtetaBot 身份与用途
USER_AGENT = "ArtetaBot/1.0 (+https://github.com/arteta-bot; factual verification)"

# 搜索结果数量上限（防止 LLM 上下文膨胀）
MAX_SEARCH_RESULTS = 8

# 单次网页抓取最大字节数（约 500KB）
MAX_FETCH_BYTES = 500_000

# URL 最大长度，和工具 schema 保持一致
MAX_URL_CHARS = 2048

# 抓取 URL 默认只允许常规 HTTP(S) 端口
ALLOWED_FETCH_PORTS = set([80, 443])

# 手动重定向上限
MAX_FETCH_REDIRECTS = 5

# 允许直接作为文本网页处理的 Content-Type
ALLOWED_TEXT_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    "application/json",
)

# 正文摘录最大字符数（返回给 LLM 的片段长度）
MAX_EXCERPT_CHARS = 1800

# GrokSearch API 超时秒数
GROKSEARCH_TIMEOUT = 80.0

# ---------------------------------------------------------------------------
# GrokSearch / X Fetch 配置（环境变量优先）
# ---------------------------------------------------------------------------

GROKSEARCH_API_URL = os.environ.get("ARTETA_GROKSEARCH_API_URL", "").strip()
GROKSEARCH_API_KEY = os.environ.get("ARTETA_GROKSEARCH_API_KEY", "").strip()
GROKSEARCH_MODEL = os.environ.get("ARTETA_GROKSEARCH_MODEL", "").strip()

X_FETCH_API_URL = os.environ.get("ARTETA_X_FETCH_API_URL", "").strip()
X_FETCH_API_KEY = os.environ.get("ARTETA_X_FETCH_API_KEY", "").strip()

# ---------------------------------------------------------------------------
# DuckDuckGo（可选依赖，忽略重命名警告）
# ---------------------------------------------------------------------------

try:
    warnings.filterwarnings("ignore", message=r".*duckduckgo_search.*renamed.*", category=RuntimeWarning)
    from duckduckgo_search import DDGS as DDGS_CLASS
except Exception:
    DDGS_CLASS = None  # 未安装时回退到 HTML 抓取路径

# 时间范围映射：ArtetaBot freshness → DuckDuckGo timelimit 参数
FRESHNESS_TO_DDG = {
    "day": "d",
    "week": "w",
    "month": "m",
    "year": "y",
    "recent": "m",  # 近期默认按月
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ValidatedURL(object):
    url: str
    hostname: str
    port: int
    resolved_ips: Tuple[str, ...]


@dataclass
class _VerificationEvidence(object):
    url: str
    title: str
    source_level: str
    stance: str
    excerpt: str
    fetched: bool = True


def _http_client():
    """获取共享的异步 HTTP 客户端（复用连接池）。"""
    return get_shared_async_client()


def _web_tool_result(
    name: str,
    status: str,
    content: str,
    error_code: str = "",
    markers: Optional[list] = None,
) -> ToolResult:
    return ToolResult(
        name=str(name or ""),
        permission="safe_read",
        status=str(status or TOOL_STATUS_OK),
        content=str(content or ""),
        error_code=str(error_code or ""),
        markers=list(markers or []),
    )


# 一手 / 官方来源域名（精确匹配或后缀匹配）
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

# 权威媒体域名
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


# ===================================================================
# HTML 解析器：PageExtractor —— 提取标题、正文、发布时间、canonical URL
# ===================================================================

class PageExtractor(HTMLParser):
    """
    流式 HTML 解析器，提取页面结构化信息。

    产出字段：
    - title          : <title> 标签内容
    - canonical_url  : <link rel="canonical"> 指向的规范 URL
    - published_time : meta 标签中的发布时间
    - body_text      : 去除 script/style/nav/footer 等噪声后的可见文本
    """

    def __init__(self):
        super().__init__()
        self.title = ""
        self.canonical_url = ""
        self.published_time = ""
        self._tag_stack = []       # 标签栈（用于跟踪嵌套层级）
        self._skip_depth = 0       # 当前处于需跳过的标签内的深度（>0 表示正在跳过）
        self._in_title = False     # 是否正在解析 <title> 内文本
        self._text_parts = []      # 正文片段缓冲区

    def handle_starttag(self, tag, attrs):
        """遇到开始标签时：
        - 追踪标签栈
        - 识别并跳过 script/style/noscript/svg/nav/footer（不计入正文）
        - 提取 <title>、canonical link、发布时间 meta
        """
        tag = tag.lower()
        attrs_dict = {str(k).lower(): str(v or "") for k, v in attrs}
        self._tag_stack.append(tag)

        # 进入需跳过的噪声标签，增加跳过深度
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self._skip_depth += 1

        if tag == "title":
            self._in_title = True

        # <link rel="canonical" href="...">
        if tag == "link" and attrs_dict.get("rel", "").lower() == "canonical":
            self.canonical_url = attrs_dict.get("href", "").strip()

        # <meta property/article:published_time content="...">
        if tag == "meta":
            key = (attrs_dict.get("property") or attrs_dict.get("name") or "").lower()
            if key in {"article:published_time", "date", "pubdate", "publishdate", "publish_date", "datepublished"}:
                self.published_time = attrs_dict.get("content", "").strip()

    def handle_endtag(self, tag):
        """遇到结束标签时恢复状态（退出标题区、减少跳过深度、弹出标签栈）。"""
        tag = tag.lower()

        if tag == "title":
            self._in_title = False

        if tag in {"script", "style", "noscript", "svg", "nav", "footer"} and self._skip_depth > 0:
            self._skip_depth -= 1

        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data):
        """处理标签间的文本数据：
        - <title> 内文本 → 累积到 title
        - 跳过深度 > 0 → 丢弃（噪声区）
        - 否则 → 累积到正文缓冲区
        """
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
        """将所有正文片段合并为一个字符串并清洗。"""
        return _clean_text(" ".join(self._text_parts))


# ===================================================================
# HTML 解析器：MetaExtractor —— 仅提取所有 <meta> 键值对
# ===================================================================

class MetaExtractor(HTMLParser):
    """
    轻量解析器，只收集页面中所有 <meta> 标签的 name/property → content 映射。

    用于 fx/vx Twitter 镜像页面的 og/twitter card 元数据提取。
    """

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


# ---------------------------------------------------------------------------
# 文本清洗 & 安全校验
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """压缩连续空白、反转 HTML 实体、去除首尾空格。"""
    return re.sub(r"\s+", " ", unescape(str(text or ""))).strip()


def _safe_int(value, default: int, low: int, high: int) -> int:
    """安全整数转换，失败时用 default，且钳制在 [low, high] 区间。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _safe_float(value, default: float, low: float, high: float) -> float:
    """安全浮点数转换，失败时用 default，且钳制在 [low, high] 区间。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _parsed_port(parsed) -> Optional[int]:
    try:
        return parsed.port
    except ValueError:
        return None


def _safe_url(url: str) -> str:
    """
    校验 URL 安全性：仅允许 http/https 公网链接。

    拒绝条件：
    - 非 http/https scheme
    - 私有/回环/链路本地/多播/保留 IP 地址
    - localhost / .local / .internal / .lan 域名
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
    """不安全 URL 的统一错误提示。"""
    return "[UnsafeURL] URL 不安全：只支持 http/https 公网链接。"


def _is_private_netloc(hostname: str) -> bool:
    """
    判断主机名/IP 是否属于私有/内网地址。

    检查范围：
    - localhost / .local / .internal / .lan 域名
    - 无点的短主机名（可能是内网机器名）
    - RFC 1918 私有 IP、回环、链路本地、保留、未指定、多播地址
    """
    host = str(hostname or "").strip().strip("[]").lower().rstrip(".")
    if not host:
        return True
    if host == "localhost" or host.endswith(".localhost"):
        return True
    if host.endswith((".local", ".internal", ".lan")):
        return True
    # 无点且无冒号 → 可能是内网短主机名
    if "." not in host and ":" not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # 非 IP 格式，交由 DNS 解析，暂不拦截
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
    """校验抓取 URL 安全性，不通过则抛出 ValueError。"""
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


# ---------------------------------------------------------------------------
# 域名与来源评级
# ---------------------------------------------------------------------------

def _domain(url: str) -> str:
    """从 URL 提取域名（去除 www. 前缀，小写化）。"""
    parsed = urlparse(str(url or ""))
    domain = (parsed.hostname or parsed.netloc).lower()
    return domain[4:] if domain.startswith("www.") else domain


def _domain_matches(domain: str, item: str) -> bool:
    """
    域名匹配逻辑：
    - item 以 "." 开头 → 后缀匹配（如 ".gov" 匹配 "www.example.gov"）
    - 否则 → 精确匹配或子域名匹配
    """
    value = str(item or "").lower()
    if value.startswith("."):
        return domain.endswith(value)
    return domain == value or domain.endswith("." + value)


def _source_level(url: str) -> str:
    """
    对 URL 来源进行三级分类：

    - "一手/官方来源"   : PRIMARY_DOMAINS 中的官方机构域名
    - "权威媒体来源"     : AUTHORITATIVE_MEDIA_DOMAINS 中的知名媒体
    - "普通网页来源"     : 其他
    """
    domain = _domain(url)
    if any(_domain_matches(domain, item) for item in PRIMARY_DOMAINS):
        return "一手/官方来源"
    if any(domain == item or domain.endswith("." + item) for item in AUTHORITATIVE_MEDIA_DOMAINS):
        return "权威媒体来源"
    return "普通网页来源"


# ---------------------------------------------------------------------------
# 搜索结果评分（用于 verify_recent_claim 的"最佳来源"选取）
# ---------------------------------------------------------------------------

def _claim_result_score(claim: str, item: dict) -> int:
    """
    对搜索结果与待核实说法的相关性进行启发式打分。

    评分维度：
    - 来源等级加成：一手/官方 +6，权威媒体 +4，普通 +1
    - 体育赛事相关 token 匹配 → 额外加分（比分格式、关键词等）
    - 赛事/集锦/赛果关键词匹配 → 额外加分
    - 团队/阵容页面 → 扣分（对赛事比分核实无帮助）
    """
    url = _search_result_url(item)
    title = str(item.get("title") or item.get("name") or "")
    snippet = str(item.get("body") or item.get("snippet") or item.get("description") or "")
    haystack = (title + " " + snippet + " " + url).lower()
    claim_text = str(claim or "").lower()

    source_level = _source_level(url)
    score = {"一手/官方来源": 6, "权威媒体来源": 4, "普通网页来源": 1}.get(source_level, 0)

    # 判断是否为赛事/比分类问题
    is_match_claim = any(token in claim_text for token in (
        "比赛", "比分", "赛果", "赛程",
        "match", "score", "result", "fixture",
    ))

    if is_match_claim:
        # 含比分格式 "3-1" / "2:0" 的页面高度相关
        if re.search(r"\d+\s*[-:]\s*\d+", haystack):
            score += 8
        if "比赛" in haystack or "比分" in haystack or "赛果" in haystack:
            score += 2
        if "match" in haystack or "score" in haystack or "result" in haystack:
            score += 2
        if "集锦" in haystack or "加时" in haystack or "战胜" in haystack or "决赛" in haystack:
            score += 3

        domain = _domain(url)
        # 知名体育站点加分
        if any(value in domain for value in ("sports.cctv.com", "espn.com", "flashscore.com", "sofascore.com")):
            score += 3
        # /teams/ 或 /squad 路径 → 扣分（阵容页而非赛果页）
        if "/teams/" in url or "/squad" in url:
            score -= 5

    return score


def _is_strong_match_result(claim: str, item: dict) -> bool:
    """搜索结果与说法高度匹配（得分 ≥ 12）时视为强证据候选。"""
    return _claim_result_score(claim, item) >= 12


def _claim_tokens(text: str) -> list:
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", str(text or "").lower())
    stopwords = set([
        "a", "an", "the", "to", "of", "and", "or", "in", "on", "for", "with",
        "after", "before", "was", "were", "is", "are", "be", "been", "being",
    ])
    return [token for token in tokens if token not in stopwords and len(token) > 1]


def _token_overlap_ratio(claim: str, text: str) -> float:
    claim_tokens = set(_claim_tokens(claim))
    if not claim_tokens:
        return 0.0
    text_tokens = set(_claim_tokens(text))
    if not text_tokens:
        return 0.0
    return float(len(claim_tokens.intersection(text_tokens))) / float(len(claim_tokens))


def _contains_negation_near_claim(claim: str, text: str) -> bool:
    value = str(text or "").lower()
    negations = (
        "did not",
        "has not",
        "have not",
        "not signed",
        "not agree",
        "not completed",
        "false",
        "denied",
        "refuted",
        "no agreement",
        "未",
        "没有",
        "否认",
        "不属实",
        "辟谣",
    )
    if not any(term in value for term in negations):
        return False
    return _token_overlap_ratio(claim, value) >= 0.5


def _classify_evidence_stance(claim: str, page_text: str) -> str:
    normalized_claim = _clean_text(claim).lower()
    normalized_text = _clean_text(page_text).lower()
    if not normalized_text:
        return "unclear"
    if _contains_negation_near_claim(claim, normalized_text):
        return "refute"
    if normalized_claim and normalized_claim in normalized_text:
        return "support"
    if _token_overlap_ratio(claim, normalized_text) >= 0.75:
        return "support"
    return "unclear"


def _stance_label(stance: str) -> str:
    return {
        "support": "支持",
        "refute": "反驳",
        "unclear": "不明确",
    }.get(str(stance or ""), "不明确")


def _verdict_marker(verdict: str) -> str:
    return {
        "support": "supported",
        "refute": "refuted",
        "unclear": "unclear",
    }.get(str(verdict or ""), "unclear")


def _is_authoritative_source_level(source_level: str) -> bool:
    return source_level in ("一手/官方来源", "权威媒体来源")


def _select_verification_verdict(evidence: list) -> tuple:
    authoritative_support = [
        item for item in evidence
        if item.stance == "support" and _is_authoritative_source_level(item.source_level)
    ]
    authoritative_refute = [
        item for item in evidence
        if item.stance == "refute" and _is_authoritative_source_level(item.source_level)
    ]
    fetched_items = [item for item in evidence if item.fetched]
    limitations = []
    if authoritative_support and authoritative_refute:
        limitations.append("来源冲突：权威来源之间存在支持和反驳。")
        return "unclear", limitations
    if authoritative_support:
        return "support", limitations
    if authoritative_refute:
        return "refute", limitations
    if not fetched_items and evidence:
        limitations.append("搜索摘要不能单独确认该说法。")
    elif any(item.stance in ("support", "refute") for item in evidence):
        limitations.append("ordinary source only: 找到的支持/反驳线索不是官方或权威来源。")
    else:
        limitations.append("未找到足够明确的正文证据。")
    return "unclear", limitations


def _format_verification_result(claim: str, verdict: str, evidence: list, limitations: list) -> str:
    lines = [
        "核验结论：{0}".format(_stance_label(verdict)),
        "待核实说法：{0}".format(_clean_text(claim)),
        "证据：",
    ]
    for index, item in enumerate(evidence, start=1):
        lines.append("{0}. {1}".format(index, item.title or "(无标题)"))
        lines.append("   立场：{0}".format(_stance_label(item.stance)))
        lines.append("   来源等级：{0}".format(item.source_level))
        lines.append("   链接：{0}".format(item.url))
        if item.excerpt:
            lines.append("   摘录：{0}".format(_clean_text(item.excerpt)[:MAX_EXCERPT_CHARS]))
    if limitations:
        lines.append("局限：")
        for limitation in limitations:
            lines.append("- {0}".format(limitation))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 搜索结果数据结构工具
# ---------------------------------------------------------------------------

def _search_result_url(item: dict) -> str:
    """从不同引擎返回的 dict 中提取 URL（兼容 href/url/link 字段名差异）。"""
    return str(item.get("href") or item.get("url") or item.get("link") or "").strip()


def _is_grok_result(item: dict) -> bool:
    """判断搜索结果是否来自 GrokSearch 后端。"""
    return isinstance(item, dict) and str(item.get("_backend") or "") == "grok"


# ---------------------------------------------------------------------------
# X/Twitter URL 解析工具
# ---------------------------------------------------------------------------

def _x_status_id(url: str) -> str:
    """
    从 x.com/twitter.com URL 提取推文 status ID。

    示例：
    "https://x.com/Arsenal/status/1812345678901234567" → "1812345678901234567"
    非 X/Twitter 域名返回空字符串。
    """
    parsed = urlparse(str(url or "").strip())
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if domain not in {"x.com", "twitter.com", "mobile.twitter.com"}:
        return ""
    match = re.search(r"/status(?:es)?/(\d+)", parsed.path)
    return match.group(1) if match else ""


def _x_username(url: str) -> str:
    """
    从 x.com/twitter.com URL 提取发推用户名。

    示例：
    "https://x.com/Arsenal/status/123" → "arsenal"
    """
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
    """判断 URL 是否为 X/Twitter 推文链接。"""
    return bool(_x_status_id(url))


# ---------------------------------------------------------------------------
# 搜索引擎结果 URL 规范化
# ---------------------------------------------------------------------------

def _normalize_duckduckgo_href(href: str) -> str:
    """
    还原 DuckDuckGo 跳转链接中的真实目标 URL。

    DuckDuckGo HTML 结果中的 href 形如：
    /l/?uddg=https%3A%2F%2Fexample.com&...
    此函数提取 uddg 参数并 URL 解码。
    """
    value = unescape(str(href or "").strip())
    parsed = urlparse(value)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return value


def _normalize_bing_href(href: str) -> str:
    """
    还原 Bing 跳转链接中的真实目标 URL。

    Bing 结果链接可能形如 /ck/a?...&u=a1<base64>...，
    需解码 a1 前缀的 base64url 编码。
    """
    value = unescape(str(href or "").strip())
    parsed = urlparse(value)
    if "bing.com" in parsed.netloc and parsed.path.startswith("/ck/"):
        target = parse_qs(parsed.query).get("u", [""])[0]
        if target.startswith("a1"):
            payload = target[2:]
            # 补齐 base64 填充
            payload += "=" * (-len(payload) % 4)
            try:
                return base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8", errors="replace")
            except Exception:
                return value
    return value


# ---------------------------------------------------------------------------
# 搜索 HTML 解析器
# ---------------------------------------------------------------------------

def _parse_bing_html(html_text: str, max_results: int) -> list:
    """
    从 Bing 搜索结果 HTML 中解析出标题、链接、摘要。

    匹配策略：
    1. 正则定位 class 含 "b_algo" 的 <li> 块
    2. 在块内提取 <h2><a href="..."> 标题和链接
    3. 在块内提取 <p> 摘要
    """
    # 匹配 Bing 搜索结果块
    pattern = re.compile(r'<li[^>]+class=["\'][^"\']*b_algo[^"\']*["\'][^>]*>(.*?)</li>', re.I | re.S)
    results = []
    seen = set()
    for block_match in pattern.finditer(str(html_text or "")):
        block = block_match.group(1)

        # 提取标题链接
        link_match = re.search(
            r'<h2[^>]*>.*?<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>.*?</h2>',
            block, re.I | re.S,
        )
        if not link_match:
            continue

        href = _normalize_bing_href(link_match.group(1))
        title = _clean_text(re.sub(r"<[^>]+>", " ", link_match.group(2)))

        # 提取摘要
        snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, re.I | re.S)
        snippet = _clean_text(re.sub(r"<[^>]+>", " ", snippet_match.group(1))) if snippet_match else ""

        if title and _safe_url(href) and href not in seen:
            results.append({"title": title, "href": href, "body": snippet})
            seen.add(href)

        if len(results) >= max_results:
            break

    return results


def _parse_duckduckgo_html(html_text: str, max_results: int) -> list:
    """
    从 DuckDuckGo HTML 搜索结果中解析标题、链接、摘要。

    匹配策略：
    - 定位 class 含 "result__a" 的 <a> 标签作为结果条目
    - 从后续 HTML 中提取 class 含 "result__snippet" 的摘要
    """
    pattern = re.compile(
        r'<a[^>]+class=["\'][^"\']*result__a[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
        r'(?P<tail>.*?)(?=<a[^>]+class=["\'][^"\']*result__a|\Z)',
        re.I | re.S,
    )
    results = []
    for match in pattern.finditer(str(html_text or "")):
        href = _normalize_duckduckgo_href(match.group(1))
        title = _clean_text(re.sub(r"<[^>]+>", " ", match.group(2)))

        # 在当前结果条目和下一个条目之间的 HTML 中寻找摘要
        tail = match.group("tail") or ""
        snippet_match = re.search(
            r'class=["\'][^"\']*result__snippet[^"\']*["\'][^>]*>(.*?)</',
            tail, re.I | re.S,
        )
        snippet = _clean_text(re.sub(r"<[^>]+>", " ", snippet_match.group(1))) if snippet_match else ""

        if title and _safe_url(href):
            results.append({"title": title, "href": href, "body": snippet})

        if len(results) >= max_results:
            break

    return results


# ---------------------------------------------------------------------------
# 搜索请求发送（Bing / DuckDuckGo / Jina）
# ---------------------------------------------------------------------------

async def _fetch_duckduckgo_html(query: str, max_results: int) -> str:
    """通过 DuckDuckGo HTML 版（无 JS）发送搜索请求并返回原始 HTML。"""
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    response = await _http_client().get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers=headers,
        timeout=12.0,
        follow_redirects=False,
    )
    response.raise_for_status()
    return response.text


async def _fetch_bing_html(query: str, max_results: int) -> str:
    """向 Bing 发送搜索请求并返回原始 HTML。"""
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    response = await _http_client().get(
        "https://www.bing.com/search",
        params={"q": query},
        headers=headers,
        timeout=10.0,
        follow_redirects=False,
    )
    response.raise_for_status()
    return response.text


async def _fetch_jina_duckduckgo_markdown(query: str, max_results: int) -> str:
    """
    通过 Jina AI Reader（r.jina.ai）抓取 DuckDuckGo 搜索结果并返回 Markdown。

    Jina 作为中间层可以处理 JS 渲染和内容提取。
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "text/plain, text/markdown"}
    response = await _http_client().get(
        "https://r.jina.ai/http://duckduckgo.com/html/",
        params={"q": query},
        headers=headers,
        timeout=18.0,
        follow_redirects=False,
    )
    response.raise_for_status()
    return response.text


# ---------------------------------------------------------------------------
# Markdown 搜索结果解析（Jina 通道）
# ---------------------------------------------------------------------------

def _parse_markdown_search_results(markdown_text: str, max_results: int) -> list:
    """
    从 Jina 返回的 Markdown 中解析搜索结果。

    Jina 将 DuckDuckGo 结果转为 `## [标题](链接)` 格式的 Markdown 标题，
    标题之间的正文即为该结果的摘要。
    """
    matches = list(re.finditer(r"##\s+\[([^\]]+)\]\(([^)]+)\)", str(markdown_text or "")))
    results = []
    seen = set()
    for index, match in enumerate(matches):
        title = _clean_text(match.group(1))
        href = _normalize_duckduckgo_href(match.group(2))
        if not title or not _safe_url(href) or href in seen:
            continue

        # 两个标题之间的文本即为摘要
        snippet_start = match.end()
        snippet_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        snippet = str(markdown_text or "")[snippet_start:snippet_end]

        # 去掉图片和链接 Markdown 语法，保留纯文本
        snippet = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", snippet)
        snippet = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", snippet)
        snippet = _clean_text(snippet)[:300]

        results.append({"title": title, "href": href, "body": snippet})
        seen.add(href)

        if len(results) >= max_results:
            break

    return results


# ---------------------------------------------------------------------------
# GrokSearch API 响应解析
# ---------------------------------------------------------------------------

def _parse_groksearch_search_response(data: dict, max_results: int) -> list:
    """
    解析 GrokSearch web_search 返回的 JSON。

    兼容多种响应结构：
    - data.results / data.data / data.sources 中的列表
    - 每条记录的 title/name、url/href/link、snippet/content/description
    - 如果结构化列表为空，则尝试从 content 中的 Markdown 链接提取
    """
    results = []
    seen = set()
    items = []

    # 枚举可能的列表字段
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

    # 回退：从 content 文本中提取 Markdown 链接
    if not results and isinstance(data, dict):
        results = _parse_groksearch_content_links(data, max_results)

    return results


def _parse_groksearch_content_links(data: dict, max_results: int) -> list:
    """
    从 GrokSearch 返回的 content/markdown 文本中提取 Markdown 链接作为结果。

    当 API 返回的是一个文本回答而非结构化结果列表时使用此回退逻辑。
    """
    content = ""
    if isinstance(data, dict):
        for key in ("content", "text", "markdown", "result"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                content = value
                break
    if not content:
        return []

    # 匹配 [标签](url) 或 [[标签]](url) 格式
    matches = list(re.finditer(r"\[{1,2}([^\[\]]+)\]{1,2}\((https?://[^)\s]+)\)", content))
    results = []
    seen = set()

    for index, match in enumerate(matches):
        url = match.group(2).strip()
        if not _safe_url(url) or url in seen:
            continue

        # 用链接前后的文本作为摘要
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        tail = content[match.end():next_start]
        snippet = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", tail)
        snippet = _clean_text(snippet)

        if not snippet:
            start = max(0, match.start() - 180)
            end = min(len(content), match.end() + 260)
            snippet = _clean_text(re.sub(r"\[[^\]]+\]\([^)]+\)", " ", content[start:end]))

        label = _clean_text(match.group(1))
        # 纯数字引用标签 → 用 snippet 作为标题
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
    """
    解析 GrokSearch get_sources 返回的来源列表。

    结构与主搜索结果类似，但从 data.sources 字段读取。
    """
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


# ---------------------------------------------------------------------------
# 配置读取（环境变量 & NoneBot 配置）
# ---------------------------------------------------------------------------

def _config_attr(name: str) -> str:
    """
    从 NoneBot 驱动的全局配置中读取指定属性。

    用于兼容将配置写在 NoneBot .env 中的场景。
    """
    try:
        from nonebot import get_driver
        config = get_driver().config
    except Exception:
        return ""
    return str(getattr(config, name.lower(), "") or getattr(config, name, "") or "").strip()


def _groksearch_timeout() -> float:
    """
    解析 GrokSearch 超时配置，优先级：
    环境变量 ARTETA_GROKSEARCH_TIMEOUT > GROKSEARCH_TIMEOUT > NoneBot 配置 > 默认值
    """
    value = (
        os.environ.get("ARTETA_GROKSEARCH_TIMEOUT", "").strip()
        or os.environ.get("GROKSEARCH_TIMEOUT", "").strip()
        or _config_attr("ARTETA_GROKSEARCH_TIMEOUT")
        or GROKSEARCH_TIMEOUT
    )
    return _safe_float(value, GROKSEARCH_TIMEOUT, 5.0, 170.0)


def _groksearch_config() -> tuple:
    """
    读取 GrokSearch 三元组配置 (API URL, API Key, Model)，
    优先级：环境变量 > 模块级常量 > NoneBot 配置。
    """
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
    """GrokSearch 是否已配置（URL 和 Key 均非空）。"""
    url, key, _model = _groksearch_config()
    return bool(url and key)


def _remote_fetch_proxy_enabled() -> bool:
    value = os.environ.get("ARTETA_ALLOW_REMOTE_FETCH_PROXY", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _x_fetch_bridge_config() -> tuple:
    """
    读取 X Fetch Bridge 配置 (API URL, API Key)，
    优先级：环境变量 > 模块级常量 > NoneBot 配置。
    """
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
    """X Fetch Bridge 是否已配置（URL 和 Key 均非空）。"""
    url, key = _x_fetch_bridge_config()
    return bool(url and key)


# ---------------------------------------------------------------------------
# X Fetch Bridge —— 抓取 X/Twitter 推文的中继 API
# ---------------------------------------------------------------------------

async def _x_fetch_bridge_fetch(url: str) -> dict:
    """
    通过 X Fetch Bridge API 抓取 X/Twitter 推文。

    这是一个外部中继服务，可以绕过 X 的反爬/登录限制。
    """
    api_url, key = _x_fetch_bridge_config()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    response = await _http_client().post(
        f"{api_url.rstrip('/')}/fetch",
        json={"url": url},
        headers=headers,
        timeout=35.0,
        follow_redirects=False,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# GrokSearch API 调用
# ---------------------------------------------------------------------------

async def _groksearch_post(tool_name: str, payload: dict) -> dict:
    """
    向 GrokSearch MCP 兼容 API 发送 POST 请求。

    Args:
        tool_name: API 端点名（如 "web_search"、"web_fetch"、"get_sources"）
        payload: 请求体 JSON
    """
    url, key, _model = _groksearch_config()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    response = await _http_client().post(
        f"{url.rstrip('/')}/{tool_name}",
        json=payload,
        headers=headers,
        timeout=_groksearch_timeout(),
        follow_redirects=False,
    )
    response.raise_for_status()
    return response.json()


async def _groksearch_search(query: str, max_results: int, freshness: str = "recent") -> list:
    """
    通过 GrokSearch 执行搜索。

    策略：
    1. 先调用 web_search 端点
    2. 若返回了 session_id 但无结构化结果，再用 get_sources 获取来源列表
    3. 所有结果标记 _backend = "grok" 用于后续识别
    """
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

    # 主搜索无结构化结果 → 尝试获取来源列表
    session_id = data.get("session_id") if isinstance(data, dict) else ""
    if session_id:
        sources_data = await _groksearch_post("get_sources", {"session_id": session_id})
        results = _parse_groksearch_sources_response(sources_data, max_results)
        for item in results:
            item["_backend"] = "grok"
        return results

    return []


async def _groksearch_fetch(url: str) -> Optional[str]:
    """
    通过 GrokSearch 抓取指定 URL 的网页内容。

    返回提取后的文本内容；失败或未配置时返回 None。
    """
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


# ---------------------------------------------------------------------------
# X/Twitter 内容抓取（多通道降级）
# ---------------------------------------------------------------------------

async def _fetch_x_syndication(tweet_id: str) -> dict:
    """
    通过 Twitter 官方 CDN 的 syndication 端点获取推文 JSON。

    优点：无需认证、返回结构化 JSON
    局限：可能被限流，对敏感/受限推文无效
    """
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
        follow_redirects=False,
    )
    response.raise_for_status()
    return response.json()


def _extract_x_text(data: dict) -> str:
    """
    从推文 JSON 中提取正文文本。

    兼容多种 API 返回的字段名：
    - text / full_text / tweetText / content
    - 嵌套在 data.legacy 中（Twitter API v1.1 格式）
    """
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
    """
    从推文 JSON 中提取作者信息，返回 (显示名称, 用户名)。

    兼容多种字段名格式和嵌套结构。
    """
    if not isinstance(data, dict):
        return "", ""
    name = _clean_text(data.get("author_name") or data.get("name") or "")
    username = _clean_text(data.get("author_username") or data.get("screen_name") or data.get("username") or "")
    # 尝试从嵌套的 user 对象中提取
    user = data.get("user")
    if isinstance(user, dict):
        name = name or _clean_text(user.get("name") or "")
        username = username or _clean_text(user.get("screen_name") or user.get("username") or "")
    if username.startswith("@"):
        username = username[1:]
    return name, username


def _x_mirror_urls(source_url: str) -> list:
    """
    生成 X/Twitter 推文的镜像站点 URL。

    使用 fxtwitter.com 和 vxtwitter.com 镜像，
    这些镜像会渲染 Open Graph / Twitter Card meta 标签，
    可以直接从 HTML 中提取推文内容而无需 JS 执行。
    """
    parsed = urlparse(str(source_url or ""))
    path = parsed.path or ""
    return [
        "https://fxtwitter.com{0}".format(path),
        "https://vxtwitter.com{0}".format(path),
    ]


async def _fetch_x_mirror(url: str) -> dict:
    """抓取 X/Twitter 镜像站点的 HTML 页面。"""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
    }
    response = await _http_client().get(
        url,
        headers=headers,
        timeout=18.0,
        follow_redirects=False,
    )
    response.raise_for_status()
    return {
        "url": url,
        "final_url": str(response.url),
        "content_type": response.headers.get("content-type", ""),
        "text": response.text,
    }


def _format_x_mirror_page(fetched: dict, source_url: str) -> str:
    """
    从 fx/vx Twitter 镜像页面的 HTML meta 标签中提取推文内容并格式化。

    验证逻辑：
    - 提取 og:description / twitter:description 作为正文
    - 从 og:title / twitter:title 提取作者
    - 校验推文用户名与源 URL 中的用户名一致（防止镜像返回错误内容）
    """
    parser = MetaExtractor()
    parser.feed(str(fetched.get("text") or ""))
    values = parser.values

    # 从 meta 标签提取推文正文
    text = _clean_text(
        values.get("twitter:description")
        or values.get("og:description")
        or values.get("description")
        or ""
    )
    if not text:
        return ""

    # 从 title meta 提取作者信息
    title = _clean_text(values.get("twitter:title") or values.get("og:title") or "")
    author_name = ""
    username = ""
    if title:
        # 去掉末尾的 " on X" / " on Twitter" 后缀
        title = re.sub(r"\s+on\s+X\s*$", "", title, flags=re.I).strip()
        title = re.sub(r"\s+on\s+Twitter\s*$", "", title, flags=re.I).strip()
        author_name = title
        username_match = re.search(r"@([A-Za-z0-9_]{1,20})", title)
        if username_match:
            username = username_match.group(1)

    # 安全校验：镜像返回的用户名必须与源 URL 一致
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
    """
    将推文数据格式化为统一的 X 原帖证据文本。

    输出格式：
    [x-post]
    X 原帖证据：
    作者：Name (@username)
    发布时间：...
    链接：...
    正文：...
    """
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


# ---------------------------------------------------------------------------
# 搜索结果格式化
# ---------------------------------------------------------------------------

def _format_search_results(results: list) -> str:
    """
    将搜索结果列表格式化为 LLM 可读的文本块。

    每条结果包含：序号、标题、来源等级、日期（如有）、链接、摘要。
    若含 GrokSearch 结果，顶部追加 [grok] 标记。
    """
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


# ---------------------------------------------------------------------------
# GrokSearch 来源截图
# ---------------------------------------------------------------------------

def _grok_source_urls(results: list) -> list:
    """从搜索结果中提取所有 GrokSearch 后端的 URL。"""
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
    """
    对 GrokSearch 来源页面截图并保存到本地快照目录。

    返回截图文件的本地路径。
    """
    from . import link_analysis

    os.makedirs(link_analysis.SNAPSHOT_DIR, exist_ok=True)
    screenshot_url = page.get("url") or source_url
    image_bytes = await link_analysis._capture_page_screenshot(screenshot_url)
    path = os.path.join(link_analysis.SNAPSHOT_DIR, "grok_source_{0}.png".format(int(time.time() * 1000)))
    with open(path, "wb") as fh:
        fh.write(image_bytes)
    return path


async def _grok_source_snapshot_marker(source_urls: list) -> str:
    """
    为 GrokSearch 来源列表中的第一个有效 URL 生成截图标记。

    返回格式：[LinkSnapshotImage: <本地路径>]
    失败时返回空字符串。
    """
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
    """
    如果搜索结果包含 [grok] 标记但尚无截图，追加一张来源页面截图标记。

    条件：文本中有 [grok] 且尚未含 [LinkSnapshotImage: 标记。
    """
    output = str(text or "")
    if "[grok]" not in output or "[LinkSnapshotImage:" in output:
        return output
    marker = await _grok_source_snapshot_marker(_grok_source_urls(results))
    if not marker:
        return output
    return "{0}\n{1}".format(output.rstrip(), marker)


# ---------------------------------------------------------------------------
# 通用网页抓取 & 格式化
# ---------------------------------------------------------------------------

def _parse_page(url: str, html_text: str) -> dict:
    """
    使用 PageExtractor 解析 HTML，提取结构化页面信息。

    返回 dict: {title, url, published_time, text}
    """
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
    """
    将页面证据 dict 格式化为 LLM 可读文本。

    输出格式：
    网页证据：
    标题：...
    来源等级：...
    链接：...
    发布时间：...
    摘录：...
    """
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


# ---------------------------------------------------------------------------
# DuckDuckGo 搜索（多通道回退）
# ---------------------------------------------------------------------------

async def _duckduckgo_search(query: str, max_results: int = 5, timelimit=None) -> list:
    """
    执行搜索，按优先级依次尝试以下通道：

    1. Bing HTML 抓取 + 解析（最稳定）
    2. DuckDuckGo HTML 版抓取 + 解析
    3. Jina AI Reader 通过 DuckDuckGo 返回 Markdown
    4. duckduckgo_search 库（DDGS）—— 仅当环境变量开启时

    任意通道返回非空结果即停止尝试后续通道。
    """
    limit = _safe_int(max_results, 5, 1, MAX_SEARCH_RESULTS)

    # 通道 1：Bing HTML
    try:
        bing_html = await _fetch_bing_html(query, limit)
        results = _parse_bing_html(bing_html, limit)
        if results:
            return results
    except Exception:
        pass

    # 通道 2：DuckDuckGo HTML
    try:
        html_text = await _fetch_duckduckgo_html(query, limit)
        results = _parse_duckduckgo_html(html_text, limit)
        if results:
            return results
    except Exception:
        pass

    # 通道 3：Jina AI + DuckDuckGo
    try:
        markdown_text = await _fetch_jina_duckduckgo_markdown(query, limit)
        results = _parse_markdown_search_results(markdown_text, limit)
        if results:
            return results
    except Exception:
        pass

    # 通道 4：duckduckgo_search 库（需显式开启）
    if os.environ.get("ARTETA_WEB_SEARCH_USE_DDGS", "").lower() not in {"1", "true", "yes"}:
        return []

    def _search():
        """同步搜索函数，在 executor 中运行以避开 DDGS 的同步阻塞。"""
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


# ---------------------------------------------------------------------------
# 通用 HTTP 抓取（流式，限制字节数）
# ---------------------------------------------------------------------------

async def _fetch_url(
    url: str,
    timeout_seconds: float = 10.0,
    max_bytes: int = MAX_FETCH_BYTES,
    max_redirects: int = MAX_FETCH_REDIRECTS,
) -> dict:
    """
    流式抓取指定 URL，限制最大下载字节数（防止大文件撑爆内存）。

    返回 dict: {url, final_url, content_type, text, truncated}
    """
    original_url = _ensure_safe_fetch_url(url)
    current_url = original_url
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5"}

    for redirect_index in range(max(0, int(max_redirects or 0)) + 1):
        validated = _validate_public_http_url(current_url)
        async with _http_client().stream(
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
    """
    从流式响应中读取最多 max_bytes 字节。

    到达上限后截断当前 chunk 并停止读取。
    """
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


# ---------------------------------------------------------------------------
# 统一搜索入口（GrokSearch 优先，回退 DuckDuckGo）
# ---------------------------------------------------------------------------

async def _search_web(query: str, max_results: int = 5, freshness: str = "recent", timelimit=None) -> list:
    """
    统一网页搜索入口。

    优先级：GrokSearch > DuckDuckGo（多通道回退）
    若 GrokSearch 已配置，优先使用；失败或超时则回退到 DuckDuckGo。
    """
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

    return await asyncio.wait_for(
        _duckduckgo_search(query, max_results=limit, timelimit=timelimit),
        timeout=12.0,
    )


# ===================================================================
# 对外工具函数（由 ToolSpec 注册，LLM 可调用）
# ===================================================================

async def web_search(ctx: ToolContext, query: str, freshness: str = "recent", max_results: int = 5) -> ToolResult:
    """
    通用网页搜索工具。

    用于发现真实来源线索，适合最新新闻、2024 年以后事实、陌生实体、
    需要联网核实时调用。搜索结果不是最终证据，回答前应继续抓取来源核实。
    """
    text = _clean_text(query)
    if not text:
        return _web_tool_result("web_search", TOOL_STATUS_ERROR, "请提供要搜索的关键词。", "EmptyQuery")

    limit = _safe_int(max_results, 5, 1, MAX_SEARCH_RESULTS)
    timelimit = FRESHNESS_TO_DDG.get(str(freshness or "recent").lower())

    try:
        results = await _search_web(text, max_results=limit, freshness=str(freshness or "recent"), timelimit=timelimit)
    except asyncio.TimeoutError:
        return _web_tool_result("web_search", TOOL_STATUS_TIMEOUT, "[WebSearchTimeout] 搜索超时。", "TimeoutError")
    except Exception as exc:
        return _web_tool_result(
            "web_search",
            TOOL_STATUS_ERROR,
            "[WebSearchError] 搜索失败：{0}: {1}".format(exc.__class__.__name__, exc),
            exc.__class__.__name__,
        )

    visible_results = results[:limit]
    markers = ["[grok]"] if any(_is_grok_result(item) for item in visible_results) else []
    return _web_tool_result("web_search", TOOL_STATUS_OK, _format_search_results(visible_results), markers=markers)


async def grok_search(ctx: ToolContext, query: str, freshness: str = "recent", max_results: int = 5) -> ToolResult:
    """
    GrokSearch 独立搜索工具。

    优先用于最新新闻、X/Twitter/社媒内容、转会、伤病、官宣和需要强实时性
    的事实查询。不会回退到普通网页搜索。结果仍需按来源强度谨慎判断。
    """
    text = _clean_text(query)
    if not text:
        return _web_tool_result("grok_search", TOOL_STATUS_ERROR, "请提供要用 GrokSearch 搜索的关键词。", "EmptyQuery")

    if not _groksearch_enabled():
        return _web_tool_result(
            "grok_search",
            TOOL_STATUS_UNAVAILABLE,
            "GrokSearch 未配置：请设置 ARTETA_GROKSEARCH_API_URL 和 ARTETA_GROKSEARCH_API_KEY。",
            "GrokSearchNotConfigured",
        )

    limit = _safe_int(max_results, 5, 1, MAX_SEARCH_RESULTS)
    try:
        results = await asyncio.wait_for(
            _groksearch_search(text, max_results=limit, freshness=str(freshness or "recent")),
            timeout=_groksearch_timeout() + 2.0,
        )
    except asyncio.TimeoutError:
        return _web_tool_result("grok_search", TOOL_STATUS_TIMEOUT, "[GrokSearchTimeout] GrokSearch 搜索超时。", "TimeoutError")
    except Exception as exc:
        return _web_tool_result(
            "grok_search",
            TOOL_STATUS_ERROR,
            "[GrokSearchError] GrokSearch 搜索失败：{0}: {1}".format(exc.__class__.__name__, exc),
            exc.__class__.__name__,
        )

    for item in results:
        if isinstance(item, dict):
            item["_backend"] = "grok"

    visible_results = results[:limit]
    return _web_tool_result("grok_search", TOOL_STATUS_OK, _format_search_results(visible_results), markers=["[grok]"])


async def fetch_x_post(ctx: ToolContext, url: str) -> str:
    """
    抓取 X/Twitter 推文原文，多通道自动降级。

    降级链（按优先级依次尝试）：
    1. X Fetch Bridge（外部中继，可绕过 X 限制）
    2. Twitter CDN syndication 端点（无需认证，但有局限）
    3. fx/vx Twitter 镜像站点（从 OG meta 提取内容）
    4. GrokSearch web_fetch（最后回退）

    所有通道均失败时返回友好提示，引导用户提供截图或原文。
    """
    safe_url = _safe_url(url)
    tweet_id = _x_status_id(safe_url)
    if not safe_url or not tweet_id:
        return "请提供 x.com/twitter.com 的 status 链接。"

    # 通道 1：X Fetch Bridge
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

    # 通道 2：Twitter CDN syndication
    try:
        data = await asyncio.wait_for(_fetch_x_syndication(tweet_id), timeout=20.0)
        formatted = _format_x_post(data, safe_url)
        if formatted:
            return formatted
    except Exception:
        pass

    # 通道 3：fx/vx Twitter 镜像
    for mirror_url in _x_mirror_urls(safe_url):
        try:
            fetched = await asyncio.wait_for(_fetch_x_mirror(mirror_url), timeout=20.0)
            formatted = _format_x_mirror_page(fetched, safe_url)
            if formatted:
                return formatted
        except Exception:
            pass

    # 通道 4：GrokSearch 抓取
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

    # 全部失败
    return (
        "[x-post-unavailable]\n"
        "无法读取 X 原帖正文：X 可能要求登录、JS 渲染或触发反爬限制。\n"
        "链接：{0}\n"
        "请让用户提供原帖截图、复制原文，或改用可公开打开的权威来源页面再核实。"
    ).format(safe_url)


async def web_fetch(ctx: ToolContext, url: str, max_chars: int = MAX_EXCERPT_CHARS) -> ToolResult:
    """
    抓取指定 http/https 网页并提取标题、链接、发布时间和正文摘录。

    特殊处理：
    - X/Twitter 推文链接自动转发到 fetch_x_post
    - 默认先直接 HTTP 流式抓取
    - 仅显式开启 ARTETA_ALLOW_REMOTE_FETCH_PROXY 时，才在本地抓取失败后使用 GrokSearch web_fetch
    """
    safe_url = _safe_url(url)
    if not safe_url:
        return _web_tool_result("web_fetch", TOOL_STATUS_ERROR, _unsafe_url_message(), "UnsafeURL")

    # X/Twitter 链接 → 专门的推文抓取
    if _is_x_status_url(safe_url):
        x_result = await fetch_x_post(ctx, safe_url)
        status = TOOL_STATUS_UNAVAILABLE if str(x_result).startswith("[x-post-unavailable]") else TOOL_STATUS_OK
        return _web_tool_result("web_fetch", status, str(x_result), "XPostUnavailable" if status == TOOL_STATUS_UNAVAILABLE else "")

    max_chars = _safe_int(max_chars, MAX_EXCERPT_CHARS, 300, 4000)

    local_error = ""
    try:
        fetched = await asyncio.wait_for(_fetch_url(safe_url), timeout=12.0)
        page = _parse_page(fetched.get("final_url") or safe_url, fetched.get("text") or "")
        page["text"] = page.get("text", "")[:max_chars]
        return _web_tool_result("web_fetch", TOOL_STATUS_OK, _format_page_evidence(page, safe_url))
    except asyncio.TimeoutError:
        local_error = "[WebFetchTimeout] 抓取超时。"
        local_error_code = "TimeoutError"
    except ValueError as exc:
        local_error = str(exc)
        local_error_code = "ValueError"
    except Exception as exc:
        local_error = "[WebFetchError] 抓取失败：{0}: {1}".format(exc.__class__.__name__, exc)
        local_error_code = exc.__class__.__name__

    if _remote_fetch_proxy_enabled() and _groksearch_enabled():
        try:
            grok_text = await asyncio.wait_for(_groksearch_fetch(safe_url), timeout=_groksearch_timeout() + 2.0)
            if grok_text:
                page = {
                    "title": "(GrokSearch)",
                    "url": safe_url,
                    "published_time": "",
                    "text": _clean_text(grok_text)[:max_chars],
                }
                return _web_tool_result("web_fetch", TOOL_STATUS_OK, "[grok]\n" + _format_page_evidence(page, safe_url))
        except ValueError as exc:
            return _web_tool_result("web_fetch", TOOL_STATUS_ERROR, str(exc), "ValueError")
        except Exception:
            pass

    status = TOOL_STATUS_TIMEOUT if local_error_code == "TimeoutError" else TOOL_STATUS_ERROR
    return _web_tool_result("web_fetch", status, local_error, local_error_code)


async def verify_recent_claim(ctx: ToolContext, claim: str, preferred_sources: str = "", max_results: int = 5) -> ToolResult:
    """
    核实近期/最新事实陈述。

    流程：
    1. 用 claim（可选拼接 preferred_sources）搜索
    2. 对结果按来源等级和相关性评分排序
    3. 抓取最佳匹配来源的页面内容
    4. 格式化返回证据，并标注来源强度

    用途：降低 AI 幻觉，回答时引用返回的来源。
    """
    text = _clean_text(claim)
    if not text:
        return _web_tool_result("verify_recent_claim", TOOL_STATUS_ERROR, "请提供要核实的说法。", "EmptyClaim")

    query = text
    if preferred_sources:
        query = "{0} {1}".format(text, _clean_text(preferred_sources))

    limit = _safe_int(max_results, 5, 2, MAX_SEARCH_RESULTS)

    try:
        results = await _search_web(query, max_results=limit, freshness="recent", timelimit="m")
    except asyncio.TimeoutError:
        return _web_tool_result("verify_recent_claim", TOOL_STATUS_TIMEOUT, "[WebVerifyTimeout] 核实搜索超时。", "TimeoutError")
    except Exception as exc:
        return _web_tool_result(
            "verify_recent_claim",
            TOOL_STATUS_ERROR,
            "[WebVerifyError] 核实搜索失败：{0}: {1}".format(exc.__class__.__name__, exc),
            exc.__class__.__name__,
        )

    # 过滤无有效 URL 的结果
    candidates = [item for item in results if _safe_url(_search_result_url(item))]
    if not candidates:
        content = _format_verification_result(
            text,
            "unclear",
            [],
            ["未找到可靠网页来源，不能确认该说法。"],
        )
        return _web_tool_result("verify_recent_claim", TOOL_STATUS_OK, content, markers=["unclear"])

    # 按得分降序排列，选取最多 3 个独立候选来源
    candidates.sort(key=lambda item: _claim_result_score(text, item), reverse=True)
    evidence_items = []
    seen_domains = set()
    for selected in candidates:
        selected_url = _search_result_url(selected)
        domain = _domain(selected_url)
        if domain in seen_domains:
            continue
        seen_domains.add(domain)
        title = _clean_text(selected.get("title") or selected.get("name") or "") or "(无标题)"
        source_level = _source_level(selected_url)
        try:
            fetched = await asyncio.wait_for(_fetch_url(selected_url), timeout=12.0)
            page = _parse_page(fetched.get("final_url") or selected_url, fetched.get("text") or "")
            page_text = _clean_text(page.get("text") or "")
            evidence_items.append(_VerificationEvidence(
                url=page.get("url") or selected_url,
                title=page.get("title") or title,
                source_level=_source_level(page.get("url") or selected_url),
                stance=_classify_evidence_stance(text, page_text),
                excerpt=page_text[:MAX_EXCERPT_CHARS],
                fetched=True,
            ))
        except Exception:
            evidence_items.append(_VerificationEvidence(
                url=selected_url,
                title=title,
                source_level=source_level,
                stance="unclear",
                excerpt=_clean_text(selected.get("body") or selected.get("snippet") or selected.get("description") or ""),
                fetched=False,
            ))
        if len(evidence_items) >= 3:
            break

    verdict, limitations = _select_verification_verdict(evidence_items)
    content = _format_verification_result(text, verdict, evidence_items, limitations)
    markers = [_verdict_marker(verdict)]
    if any(_is_grok_result(item) for item in candidates):
        markers.append("[grok]")
        content = "[grok]\n" + content
    return _web_tool_result("verify_recent_claim", TOOL_STATUS_OK, content, markers=markers)


# ===================================================================
# 工具注册 —— 将上述函数暴露为 LLM 可调用的 Tool
# ===================================================================

def register_tools() -> None:
    """
    向 ArtetaBot 工具注册表注册全部 Web 访问工具。

    注册的工具：
    - grok_search         : GrokSearch 独立搜索
    - web_search          : 通用网页搜索（GrokSearch 优先，回退 DDG/Bing）
    - fetch_x_post        : X/Twitter 推文抓取
    - web_fetch           : 通用网页抓取
    - verify_recent_claim : 近期事实核实
    """
    web_timeout = _groksearch_timeout() + 2.0

    ensure_tool(ToolSpec(
        name="grok_search",
        description="GrokSearch 独立搜索工具，优先用于最新新闻、X/Twitter/社媒内容、转会、伤病、官宣和需要强实时性的事实查询；不会回退到普通网页搜索，结果仍需按来源强度谨慎判断。",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 500, "description": "GrokSearch 搜索关键词，查 X/Twitter 时可加入 site:x.com 或账号名"},
                "freshness": {"type": "string", "enum": ["day", "week", "month", "year", "recent", "all"], "description": "时间范围，默认 recent"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 8, "description": "返回条数，1-8"},
            },
            "required": ["query"],
        },
        handler=grok_search,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
        parallel_safe=True,
        concurrency_group="web_http",
        idempotent=True,
    ))

    ensure_tool(ToolSpec(
        name="web_search",
        description="互联网搜索工具，用于发现真实来源线索。适合最新新闻、2024 年以后事实、陌生实体、需要联网核实时调用；搜索结果不是最终证据，回答前应继续用 web_fetch 或 verify_recent_claim 核实来源。",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 500, "description": "搜索关键词，尽量包含实体、日期、关键词"},
                "freshness": {"type": "string", "enum": ["day", "week", "month", "year", "recent", "all"], "description": "时间范围，默认 recent"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 8, "description": "返回条数，1-8"},
            },
            "required": ["query"],
        },
        handler=web_search,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
        parallel_safe=True,
        concurrency_group="web_http",
        idempotent=True,
    ))

    ensure_tool(ToolSpec(
        name="fetch_x_post",
        description="读取 x.com/twitter.com status 原帖正文。用于核实 X/Twitter 原帖、记者原帖、俱乐部社媒官宣；比通用 web_fetch 更适合 X 链接，失败时会明确要求截图或原文。",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string", "minLength": 8, "maxLength": 2048, "description": "x.com/twitter.com 的 status 链接"},
            },
            "required": ["url"],
        },
        handler=fetch_x_post,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
        parallel_safe=True,
        concurrency_group="web_http",
        idempotent=True,
    ))

    ensure_tool(ToolSpec(
        name="web_fetch",
        description="抓取并提取指定 http/https 网页的标题、链接、发布时间和正文摘录，用于核实 web_search 找到的来源；x.com/twitter.com status 链接应优先用 fetch_x_post。",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string", "minLength": 8, "maxLength": 2048, "description": "要抓取的 http/https URL"},
                "max_chars": {"type": "integer", "minimum": 300, "maximum": 4000, "description": "正文摘录最大长度，300-4000"},
            },
            "required": ["url"],
        },
        handler=web_fetch,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
        parallel_safe=True,
        concurrency_group="web_http",
        idempotent=True,
    ))

    ensure_tool(ToolSpec(
        name="verify_recent_claim",
        description="核实近期/最新/2024 年以后事实陈述。会搜索来源并优先抓取官方或一手来源；用于降低 AI 幻觉，回答时应引用返回的来源。",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "claim": {"type": "string", "minLength": 1, "maxLength": 1000, "description": "需要核实的说法或问题"},
                "preferred_sources": {"type": "string", "maxLength": 300, "description": "可选，偏好的官方/权威来源关键词，如 Arsenal official"},
                "max_results": {"type": "integer", "minimum": 2, "maximum": 8, "description": "搜索条数，2-8"},
            },
            "required": ["claim"],
        },
        handler=verify_recent_claim,
        permission="safe_read",
        category="web",
        timeout_seconds=web_timeout,
        parallel_safe=True,
        concurrency_group="web_http",
        idempotent=True,
    ))
