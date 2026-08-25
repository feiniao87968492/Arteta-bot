import asyncio
import os
import re
import tempfile
import zipfile
from io import BytesIO
from typing import Optional
from urllib.parse import urlparse
from xml.etree import ElementTree

from ..context import ToolContext
from ..providers.http_client import get_shared_async_client
from ..registry import ToolSpec, ensure_tool
from . import web_access


MAX_DOCUMENT_BYTES = 3_000_000
MAX_DOCUMENT_CHARS = 4000
USER_AGENT = "ArtetaBot/1.0 (+https://github.com/arteta-bot; document reader)"
DOCUMENT_DIR = os.path.join("artifacts", "agent_tools", "documents")
DOCUMENT_FALLBACK_DIR = os.path.join(tempfile.gettempdir(), "arteta_agent_tools", "documents")


def _http_client():
    return get_shared_async_client()


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _safe_url(url: str) -> str:
    return web_access._safe_url(url)


def _filename_from_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    name = os.path.basename(parsed.path) or "document"
    return name.split("?")[0] or "document"


def _safe_filename(name: str) -> str:
    base = os.path.basename(str(name or "document"))
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return base or "document"


def _document_type(name: str, content_type: str = "") -> str:
    suffix = os.path.splitext(str(name or "").lower())[1]
    lower_type = str(content_type or "").lower()
    if suffix == ".pdf" or "application/pdf" in lower_type:
        return "pdf"
    if suffix == ".docx" or "wordprocessingml.document" in lower_type:
        return "docx"
    return ""


def _document_type_from_content(content: bytes) -> str:
    data = bytes(content or b"")
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                if "word/document.xml" in archive.namelist():
                    return "docx"
        except Exception:
            return ""
    return ""


async def _fetch_binary(url: str, timeout_seconds: float = 20.0, max_bytes: int = MAX_DOCUMENT_BYTES) -> dict:
    url = web_access._ensure_safe_fetch_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,*/*;q=0.5"}
    async with _http_client().stream(
        "GET",
        url,
        headers=headers,
        timeout=timeout_seconds,
        follow_redirects=True,
    ) as response:
        response.raise_for_status()
        final_url = web_access._ensure_safe_fetch_url(str(response.url))
        return {
            "url": url,
            "final_url": final_url,
            "content_type": response.headers.get("content-type", ""),
            "content": await web_access._read_limited_response(response, max_bytes),
        }


def _write_document_file_to_dir(directory: str, name: str, content: bytes) -> str:
    os.makedirs(directory, exist_ok=True)
    root, ext = os.path.splitext(_safe_filename(name))
    filename = "{0}_{1}{2}".format(root or "document", int(asyncio.get_event_loop().time() * 1000), ext)
    path = os.path.join(directory, filename)
    with open(path, "wb") as fh:
        fh.write(content)
    return path


def _write_document_file(name: str, content: bytes) -> str:
    try:
        return _write_document_file_to_dir(DOCUMENT_DIR, name, content)
    except OSError:
        return _write_document_file_to_dir(DOCUMENT_FALLBACK_DIR, name, content)


def _extract_docx_text(content: bytes) -> str:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml_bytes)
    parts = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            parts.append(node.text)
        elif node.tag.endswith("}tab"):
            parts.append("\t")
        elif node.tag.endswith("}br"):
            parts.append("\n")
    return _clean_text(" ".join(parts))


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception:
            return "PDF 解析依赖未安装：请安装 pypdf 或 PyPDF2 后再读取 PDF。"

    reader = PdfReader(BytesIO(content))
    pages = []
    for page in reader.pages[:20]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return _clean_text("\n".join(pages))


def _current_document(ctx: ToolContext, document_index: int = 0) -> Optional[dict]:
    documents = list((ctx.extra or {}).get("document_urls") or [])
    if not documents:
        return None
    try:
        index = int(document_index or 0)
    except (TypeError, ValueError):
        index = 0
    if index < 0 or index >= len(documents):
        return {"error": "文档序号超出范围，当前共有 {0} 个文档。".format(len(documents))}
    item = documents[index]
    if isinstance(item, dict):
        return item
    return {"url": str(item), "name": _filename_from_url(str(item))}


async def read_document(ctx: ToolContext, url: str = "", document_index: int = 0, max_chars: int = MAX_DOCUMENT_CHARS) -> str:
    selected = None
    safe_url = _safe_url(url)
    if safe_url:
        selected = {"url": safe_url, "name": _filename_from_url(safe_url)}
    elif str(url or "").strip():
        return web_access._unsafe_url_message()
    else:
        selected = _current_document(ctx, document_index=document_index)
        if not selected:
            return "当前消息或引用里没有可读取的 PDF/DOCX 文档。"
        if selected.get("error"):
            return selected["error"]
        safe_url = _safe_url(selected.get("url") or "")
        if not safe_url:
            return web_access._unsafe_url_message()

    name = str(selected.get("name") or _filename_from_url(safe_url))
    doc_type = _document_type(name)
    suffix = os.path.splitext(name)[1]
    if not doc_type and suffix:
        return "仅支持 PDF/DOCX 文档：{0}".format(name)

    try:
        fetched = await asyncio.wait_for(_fetch_binary(safe_url), timeout=25.0)
    except asyncio.TimeoutError:
        return "[DocumentTimeout] 文档下载超时。"
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return "[DocumentError] 文档下载失败：{0}: {1}".format(exc.__class__.__name__, exc)

    final_url = fetched.get("final_url") or safe_url
    content_type = fetched.get("content_type") or ""
    content = fetched.get("content") or b""
    doc_type = _document_type(name, content_type) or _document_type_from_content(content) or doc_type
    if not doc_type:
        return "仅支持 PDF/DOCX 文档：{0}".format(name)
    if not os.path.splitext(name)[1]:
        name = "{0}.{1}".format(name, doc_type)
    local_path = _write_document_file(name, content)
    with open(local_path, "rb") as fh:
        local_content = fh.read()
    if doc_type == "docx":
        try:
            text = _extract_docx_text(local_content)
        except Exception as exc:
            return "[DocumentError] DOCX 解析失败：{0}: {1}".format(exc.__class__.__name__, exc)
    elif doc_type == "pdf":
        text = _extract_pdf_text(local_content)
    else:
        return "仅支持 PDF/DOCX 文档：{0}".format(name)

    try:
        limit = max(300, min(int(max_chars or MAX_DOCUMENT_CHARS), 8000))
    except (TypeError, ValueError):
        limit = MAX_DOCUMENT_CHARS
    excerpt = _clean_text(text)[:limit]
    if not excerpt:
        excerpt = "未提取到可读正文。"
    return "\n".join([
        "文档：{0}".format(name),
        "类型：{0}".format(doc_type),
        "链接：{0}".format(final_url),
        "本地文件：{0}".format(local_path),
        "摘录：{0}".format(excerpt),
    ])


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="read_document",
        description="读取当前消息/引用中的 PDF 或 DOCX 文档，也可传入 http/https 文档 URL。用于用户引用文档后提问、总结、提取要点。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "可选，PDF/DOCX 的 http/https URL；不填则读取当前消息或引用里的第一个文档"},
                "document_index": {"type": "integer", "description": "不传 url 时，从 0 开始选择第几个文档", "default": 0},
                "max_chars": {"type": "integer", "description": "正文摘录最大长度，300-8000", "default": MAX_DOCUMENT_CHARS},
            },
            "required": [],
        },
        handler=read_document,
        permission="safe_read",
        category="document",
        timeout_seconds=35.0,
    ))
