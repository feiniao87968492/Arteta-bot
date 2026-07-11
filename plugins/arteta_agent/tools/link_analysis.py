import asyncio
import json
import os
import re
import time
from typing import List
from urllib.parse import urlparse

from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool
from . import web_access


SNAPSHOT_DIR = os.path.join("artifacts", "agent_tools", "link_snapshots")
MAX_LINKS = 3
MAX_SNAPSHOT_TEXT_CHARS = 6000
DOCUMENT_EXTENSIONS = (".pdf", ".docx")
SNAPSHOT_VIEWPORT = {"width": 1365, "height": 900}


URL_RE = re.compile(r"https?://[^\s<>'\"\]\)）}]+", re.I)


def _clean_url(url: str) -> str:
    return str(url or "").strip().rstrip(".,;:!?，。！？、")


def extract_urls(text: str) -> List[str]:
    urls = []
    seen = set()
    for match in URL_RE.finditer(str(text or "")):
        url = _clean_url(match.group(0))
        if web_access._safe_url(url) and url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def _context_urls(ctx: ToolContext) -> List[str]:
    values = [
        getattr(ctx, "raw_message", ""),
        getattr(ctx, "reply_text", ""),
    ]
    extra = getattr(ctx, "extra", {}) or {}
    for key in ("detected_urls", "link_urls"):
        if isinstance(extra.get(key), list):
            values.extend(str(item) for item in extra.get(key))
    return extract_urls("\n".join(values))


def _write_snapshot(page: dict, source_url: str) -> str:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    payload = {
        "url": page.get("url") or source_url,
        "source_url": source_url,
        "title": page.get("title") or "",
        "published_time": page.get("published_time") or "",
        "text": str(page.get("text") or "")[:MAX_SNAPSHOT_TEXT_CHARS],
        "created_at": int(time.time()),
    }
    path = os.path.join(SNAPSHOT_DIR, "link_snapshot_{0}.json".format(int(time.time() * 1000)))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def _document_type(url: str, content_type: str = "") -> str:
    path = urlparse(str(url or "")).path.lower()
    lower_type = str(content_type or "").lower()
    if path.endswith(".pdf") or "application/pdf" in lower_type:
        return "PDF"
    if path.endswith(".docx") or "wordprocessingml.document" in lower_type:
        return "DOCX"
    return ""


async def _capture_page_screenshot(url: str) -> bytes:
    from plugins.arteta_render import _get_browser

    browser = await _get_browser()
    page = await browser.new_page(
        viewport=SNAPSHOT_VIEWPORT,
        device_scale_factor=1,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(0.8)
        return await page.screenshot(type="png", full_page=False)
    finally:
        await page.close()


def _write_text_snapshot_image(page: dict, source_url: str) -> str:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    title = page.get("title") or "(无标题)"
    url = page.get("url") or source_url
    text = web_access._clean_text(page.get("text") or "")[:2200]
    body = "\n".join([
        "链接快照",
        "标题：{0}".format(title),
        "链接：{0}".format(url),
        "摘录：{0}".format(text or "未提取到正文。"),
    ])
    from plugins.arteta_render import text_to_tactical_board

    image_bytes = text_to_tactical_board(body)
    path = os.path.join(SNAPSHOT_DIR, "link_snapshot_{0}.png".format(int(time.time() * 1000)))
    with open(path, "wb") as fh:
        fh.write(image_bytes)
    return path


async def _write_snapshot_image(page: dict, source_url: str) -> str:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    screenshot_url = page.get("url") or source_url
    try:
        image_bytes = await _capture_page_screenshot(screenshot_url)
    except Exception:
        return _write_text_snapshot_image(page, source_url)
    path = os.path.join(SNAPSHOT_DIR, "link_snapshot_{0}.png".format(int(time.time() * 1000)))
    with open(path, "wb") as fh:
        fh.write(image_bytes)
    return path


def _format_link_result(index: int, total: int, page: dict, source_url: str, snapshot_path: str, snapshot_image_path: str) -> str:
    text = web_access._clean_text(page.get("text") or "")[:1800]
    lines = [
        "链接 {0}/{1}".format(index, total),
        "标题：{0}".format(page.get("title") or "(无标题)"),
        "链接：{0}".format(page.get("url") or source_url),
    ]
    if page.get("published_time"):
        lines.append("发布时间：{0}".format(page.get("published_time")))
    lines.append("摘录：{0}".format(text or "未提取到正文。"))
    lines.append("快照：{0}".format(snapshot_path))
    lines.append("[LinkSnapshotImage: {0}]".format(snapshot_image_path))
    return "\n".join(lines)


async def _analyze_one(url: str, index: int, total: int) -> str:
    doc_type = _document_type(url)
    if doc_type:
        return "链接 {0}/{1}\n链接：{2}\n这是 PDF/DOCX 文档链接（{3}），请调用 read_document 读取文档内容，不要按网页链接分析。".format(index, total, url, doc_type)
    try:
        fetched = await asyncio.wait_for(web_access._fetch_url(url), timeout=12.0)
    except asyncio.TimeoutError:
        return "链接 {0}/{1}\n链接：{2}\n[LinkAnalyzeTimeout] 抓取超时。".format(index, total, url)
    except Exception as exc:
        return "链接 {0}/{1}\n链接：{2}\n[LinkAnalyzeError] 抓取失败：{3}: {4}".format(index, total, url, exc.__class__.__name__, exc)
    doc_type = _document_type(fetched.get("final_url") or url, fetched.get("content_type") or "")
    if doc_type:
        return "链接 {0}/{1}\n链接：{2}\n这是 PDF/DOCX 文档链接（{3}），请调用 read_document 读取文档内容，不要按网页链接分析。".format(index, total, fetched.get("final_url") or url, doc_type)
    page = web_access._parse_page(fetched.get("final_url") or url, fetched.get("text") or "")
    snapshot_path = _write_snapshot(page, url)
    snapshot_image_path = await _write_snapshot_image(page, url)
    return _format_link_result(index, total, page, url, snapshot_path, snapshot_image_path)


async def analyze_links(ctx: ToolContext, url: str = "", max_links: int = MAX_LINKS) -> str:
    explicit = _clean_url(url)
    if explicit:
        if not web_access._safe_url(explicit):
            return "URL 不安全：只支持 http/https 链接。"
        urls = [explicit]
    else:
        urls = _context_urls(ctx)
    if not urls:
        return "当前消息或引用里没有检测到 http/https 链接。"
    try:
        limit = max(1, min(int(max_links or MAX_LINKS), MAX_LINKS))
    except (TypeError, ValueError):
        limit = MAX_LINKS
    urls = urls[:limit]
    results = []
    for index, item in enumerate(urls, start=1):
        results.append(await _analyze_one(item, index, len(urls)))
    return "\n\n".join(results)


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="analyze_links",
        description="自动检测当前消息或引用里的 http/https 链接，抓取页面标题、正文摘录并保存内容快照 artifact；也可显式传入 url。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "可选，指定要分析的 http/https 链接；不填则自动从当前消息和引用中检测"},
                "max_links": {"type": "integer", "description": "最多分析几个链接，1-3", "default": MAX_LINKS},
            },
            "required": [],
        },
        handler=analyze_links,
        permission="safe_read",
        category="web",
        timeout_seconds=30.0,
    ))
