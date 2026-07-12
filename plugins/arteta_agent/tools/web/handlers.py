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
import json
import logging
import os
import time
import warnings
from typing import Optional
from urllib.parse import quote

from ...context import ToolContext
from ...providers.http_client import get_shared_async_client
from ...result import TOOL_STATUS_ERROR, TOOL_STATUS_OK, TOOL_STATUS_TIMEOUT, TOOL_STATUS_UNAVAILABLE, ToolResult
from .fetch import (
    PageExtractor,
    _fetch_url as _fetch_url_impl,
    _format_page_evidence,
    _parse_page,
    _read_limited_response,
)
from .formatting import _format_search_results, _is_grok_result
from .parsers.bing import _normalize_bing_href, _parse_bing_html
from .parsers.duckduckgo import _normalize_duckduckgo_href, _parse_duckduckgo_html
from .parsers.grok import (
    _parse_groksearch_content_links,
    _parse_groksearch_search_response,
    _parse_groksearch_sources_response,
    _search_result_url,
)
from .parsers.markdown import _parse_markdown_search_results
from .registration import register_tools
from .search_backends import (
    BingHtmlBackend,
    CallableSearchBackend,
    DDGSBackend,
    DuckDuckGoHtmlBackend,
    JinaSearchBackend,
    TimeBudget,
    run_search_backends,
)
from .security import (
    ALLOWED_FETCH_PORTS,
    ALLOWED_TEXT_CONTENT_TYPES,
    MAX_FETCH_REDIRECTS,
    MAX_URL_CHARS,
    SENSITIVE_REMOTE_QUERY_KEYWORDS,
    _ensure_safe_fetch_url,
    _has_sensitive_remote_query,
    _is_allowed_text_content_type,
    _safe_url,
    _unsafe_url_message,
    _validate_public_http_url,
)
from .x_reader import (
    MetaExtractor,
    X_PROVENANCE_CONFIGURED_BRIDGE,
    X_PROVENANCE_GENERATED_EXTRACTION,
    X_PROVENANCE_OFFICIAL_EMBED,
    _extract_x_author,
    _extract_x_text,
    _format_x_mirror_page,
    _format_x_post,
    _is_x_status_url,
    _x_mirror_urls,
    _x_status_id,
    _x_username,
)
from .verification import (
    AUTHORITATIVE_MEDIA_DOMAINS,
    PRIMARY_DOMAINS,
    _VerificationEvidence,
    _claim_result_score,
    _claim_tokens,
    _classify_evidence_stance,
    _clean_text,
    _contains_negation_near_claim,
    _domain,
    _domain_matches,
    _format_verification_result,
    _is_authoritative_source_level,
    _is_strong_match_result,
    _select_verification_verdict,
    _source_level,
    _stance_label,
    _token_overlap_ratio,
    _verdict_marker,
)


# ---------------------------------------------------------------------------
# 全局常量
# ---------------------------------------------------------------------------

# 请求 UA，标识 ArtetaBot 身份与用途
USER_AGENT = "ArtetaBot/1.0 (+https://github.com/arteta-bot; factual verification)"

# 搜索结果数量上限（防止 LLM 上下文膨胀）
MAX_SEARCH_RESULTS = 8

# 单次网页抓取最大字节数（约 500KB）
MAX_FETCH_BYTES = 500_000

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

LOGGER = logging.getLogger(__name__)

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


# 搜索结果数据结构工具
# ---------------------------------------------------------------------------

def _log_web_fallback(event: str, exc: Exception, source: str = "") -> None:
    LOGGER.warning(
        "web_access_fallback_failed event=%s source=%s error_code=%s",
        str(event or ""),
        str(source or ""),
        exc.__class__.__name__,
    )


def _safe_int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _safe_float(value, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


# ---------------------------------------------------------------------------
# 搜索请求发送（Bing / DuckDuckGo / Jina）
# ---------------------------------------------------------------------------

async def _fetch_duckduckgo_html(query: str, max_results: int, timeout_seconds: float = 12.0) -> str:
    """通过 DuckDuckGo HTML 版（无 JS）发送搜索请求并返回原始 HTML。"""
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    response = await _http_client().get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers=headers,
        timeout=timeout_seconds,
        follow_redirects=False,
    )
    response.raise_for_status()
    return response.text


async def _fetch_bing_html(query: str, max_results: int, timeout_seconds: float = 10.0) -> str:
    """向 Bing 发送搜索请求并返回原始 HTML。"""
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    response = await _http_client().get(
        "https://www.bing.com/search",
        params={"q": query},
        headers=headers,
        timeout=timeout_seconds,
        follow_redirects=False,
    )
    response.raise_for_status()
    return response.text


async def _fetch_jina_duckduckgo_markdown(query: str, max_results: int, timeout_seconds: float = 18.0) -> str:
    """
    通过 Jina AI Reader（r.jina.ai）抓取 DuckDuckGo 搜索结果并返回 Markdown。

    Jina 作为中间层可以处理 JS 渲染和内容提取。
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "text/plain, text/markdown"}
    response = await _http_client().get(
        "https://r.jina.ai/http://duckduckgo.com/html/",
        params={"q": query},
        headers=headers,
        timeout=timeout_seconds,
        follow_redirects=False,
    )
    response.raise_for_status()
    return response.text


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
    from .. import link_analysis

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

async def _fetch_url(
    url: str,
    timeout_seconds: float = 10.0,
    max_bytes: int = MAX_FETCH_BYTES,
    max_redirects: int = MAX_FETCH_REDIRECTS,
) -> dict:
    return await _fetch_url_impl(
        url,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        http_client_factory=_http_client,
    )

# ---------------------------------------------------------------------------
# DuckDuckGo 搜索（多通道回退）
# ---------------------------------------------------------------------------

async def _duckduckgo_search(query: str, max_results: int = 5, timelimit=None, budget: Optional[TimeBudget] = None) -> list:
    """
    执行搜索，按优先级依次尝试以下通道：

    1. Bing HTML 抓取 + 解析（最稳定）
    2. DuckDuckGo HTML 版抓取 + 解析
    3. Jina AI Reader 通过 DuckDuckGo 返回 Markdown
    4. duckduckgo_search 库（DDGS）—— 仅当环境变量开启时

    任意通道返回非空结果即停止尝试后续通道。
    """
    limit = _safe_int(max_results, 5, 1, MAX_SEARCH_RESULTS)
    try:
        hits = await run_search_backends(
            _legacy_search_backends(timelimit=timelimit),
            query=query,
            max_results=limit,
            freshness="recent",
            budget=budget,
        )
    except Exception:
        return []
    return [hit.to_legacy_dict() for hit in hits]


def _legacy_search_backends(timelimit=None) -> list:
    backends = [
        BingHtmlBackend(_fetch_bing_html),
        DuckDuckGoHtmlBackend(_fetch_duckduckgo_html),
        JinaSearchBackend(_fetch_jina_duckduckgo_markdown),
    ]
    if os.environ.get("ARTETA_WEB_SEARCH_USE_DDGS", "").lower() in {"1", "true", "yes"}:
        backends.append(DDGSBackend(DDGS_CLASS, USER_AGENT, timelimit=timelimit))
    return backends


# ---------------------------------------------------------------------------
# 通用 HTTP 抓取（流式，限制字节数）
# ---------------------------------------------------------------------------

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
    hits = await run_search_backends(
        _search_backends_for_request(freshness=freshness, timelimit=timelimit),
        query=query,
        max_results=limit,
        freshness=freshness,
        total_timeout_seconds=_groksearch_timeout() + 2.0,
    )
    return [hit.to_legacy_dict() for hit in hits]


def _search_backends_for_request(freshness: str = "recent", timelimit=None) -> list:
    backends = []

    if _groksearch_enabled():
        async def _run_grok(query: str, max_results: int, freshness_arg: str, budget: Optional[TimeBudget]):
            return await _groksearch_search(query, max_results=max_results, freshness=freshness_arg)

        backends.append(CallableSearchBackend(
            name="grok",
            func=_run_grok,
            timeout_seconds=_groksearch_timeout() + 2.0,
            result_backend="grok",
        ))

    async def _run_legacy(query: str, max_results: int, freshness_arg: str, budget: Optional[TimeBudget]):
        try:
            return await _duckduckgo_search(query, max_results=max_results, timelimit=timelimit, budget=budget)
        except TypeError as exc:
            if "budget" not in str(exc):
                raise
            return await _duckduckgo_search(query, max_results=max_results, timelimit=timelimit)

    backends.append(CallableSearchBackend(
        name="legacy",
        func=_run_legacy,
        timeout_seconds=12.0,
        result_backend="",
    ))
    return backends


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


async def fetch_x_post(ctx: ToolContext, url: str) -> ToolResult:
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
        return _web_tool_result("fetch_x_post", TOOL_STATUS_ERROR, "请提供 x.com/twitter.com 的 status 链接。", "InvalidXStatusURL")

    # 通道 1：X Fetch Bridge
    if _x_fetch_bridge_enabled() and not _has_sensitive_remote_query(safe_url):
        try:
            data = await asyncio.wait_for(_x_fetch_bridge_fetch(safe_url), timeout=40.0)
            backend = _clean_text(data.get("backend") or "")
            formatted = _format_x_post(
                data,
                safe_url,
                provenance=X_PROVENANCE_CONFIGURED_BRIDGE,
                backend=backend,
            )
            if formatted:
                return _web_tool_result("fetch_x_post", TOOL_STATUS_OK, formatted, markers=["[x-post]"])
        except Exception as exc:
            _log_web_fallback("x_fetch", exc, "configured_bridge")

    # 通道 2：Twitter CDN syndication
    try:
        data = await asyncio.wait_for(_fetch_x_syndication(tweet_id), timeout=20.0)
        formatted = _format_x_post(data, safe_url, provenance=X_PROVENANCE_OFFICIAL_EMBED)
        if formatted:
            return _web_tool_result("fetch_x_post", TOOL_STATUS_OK, formatted, markers=["[x-post]"])
    except Exception as exc:
        _log_web_fallback("x_fetch", exc, "official_embed")

    # 通道 3：fx/vx Twitter 镜像
    for mirror_url in _x_mirror_urls(safe_url):
        try:
            fetched = await asyncio.wait_for(_fetch_x_mirror(mirror_url), timeout=20.0)
            formatted = _format_x_mirror_page(fetched, safe_url)
            if formatted:
                return _web_tool_result("fetch_x_post", TOOL_STATUS_OK, formatted, markers=["[x-post]"])
        except Exception as exc:
            _log_web_fallback("x_fetch", exc, "third_party_mirror")

    # 通道 4：GrokSearch 抓取
    if _groksearch_enabled() and not _has_sensitive_remote_query(safe_url):
        try:
            grok_text = await asyncio.wait_for(_groksearch_fetch(safe_url), timeout=_groksearch_timeout() + 2.0)
            if grok_text:
                page = {
                    "url": safe_url,
                    "author_name": "",
                    "author_username": "",
                    "created_at": "",
                    "text": _clean_text(grok_text),
                }
                formatted = _format_x_post(page, safe_url, provenance=X_PROVENANCE_GENERATED_EXTRACTION)
                if formatted:
                    return _web_tool_result("fetch_x_post", TOOL_STATUS_OK, "[grok]\n" + formatted, markers=["[grok]", "[x-post]"])
        except Exception as exc:
            _log_web_fallback("x_fetch", exc, "generated_extraction")

    # 全部失败
    content = (
        "[x-post-unavailable]\n"
        "无法读取 X 原帖正文：X 可能要求登录、JS 渲染或触发反爬限制。\n"
        "链接：{0}\n"
        "请让用户提供原帖截图、复制原文，或改用可公开打开的权威来源页面再核实。"
    ).format(safe_url)
    return _web_tool_result("fetch_x_post", TOOL_STATUS_UNAVAILABLE, content, "XPostUnavailable", markers=["[x-post-unavailable]"])


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
        if isinstance(x_result, ToolResult):
            return _web_tool_result(
                "web_fetch",
                x_result.status,
                x_result.content,
                x_result.error_code,
                markers=x_result.markers,
            )
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

    if _remote_fetch_proxy_enabled() and _groksearch_enabled() and not _has_sensitive_remote_query(safe_url):
        try:
            _validate_public_http_url(safe_url)
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
