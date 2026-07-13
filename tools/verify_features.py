# -*- coding: utf-8 -*-
"""Developer feature verification runner for Arteta Bot.

This script runs small, local-first verification suites and writes artifacts under
an isolated timestamped output directory. Online checks are opt-in and avoid QQ
side effects unless explicitly allowed.
"""

from __future__ import print_function

import argparse
import asyncio
import importlib
import json
import os
import sqlite3
import sys
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from io import BytesIO
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

DEFAULT_OUTPUT_DIR = os.path.join(REPO_ROOT, "artifacts", "verify")
DEFAULT_SUITES = ["core"]
STATUS_PASS = "passed"
STATUS_FAIL = "failed"
STATUS_SKIP = "skipped"
STATUS_MANUAL = "manual_required"
TERMINAL_FAILURE_STATUSES = set([STATUS_FAIL])
NON_FAILURE_STATUSES = set([STATUS_PASS, STATUS_SKIP, STATUS_MANUAL])

UI_PREFERENCE_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {"type": "string"},
        "color": {"type": "string"},
        "bold": {"type": "boolean"},
        "font_size": {"type": "string"},
        "font_scale": {"type": "number"},
    },
    "required": ["target"],
}

VERIFY_RECENT_CLAIM_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string"},
        "preferred_sources": {"type": "string"},
        "max_results": {"type": "integer"},
    },
    "required": ["claim"],
}

MEMORY_PREFERENCE_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {"memory": {"type": "string"}},
    "required": ["memory"],
}


@dataclass
class CaseResult:
    """Result for a single verification case."""

    suite: str
    case: str
    status: str
    message: str = ""
    duration_seconds: float = 0.0
    artifacts: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SuiteSpec:
    """Registered suite and its case functions."""

    name: str
    description: str
    cases: List[Tuple[str, Callable[["RunContext"], CaseResult]]]


@dataclass
class RunContext:
    """State shared by verification cases."""

    args: argparse.Namespace
    repo_root: str
    run_dir: str
    artifacts_dir: str

    def artifact_path(self, *parts: str) -> str:
        path = os.path.join(self.artifacts_dir, *parts)
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        return path

    def run_path(self, *parts: str) -> str:
        path = os.path.join(self.run_dir, *parts)
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        return path


class VerificationError(Exception):
    pass


def now_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path)


def file_size(path: str) -> int:
    return os.path.getsize(path)


def write_text(path: str, text: str) -> None:
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_bytes(path: str, data: bytes) -> None:
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    with open(path, "wb") as f:
        f.write(data)


def ensure_nonebot_initialized() -> None:
    """Initialize NoneBot minimally before importing command plugins."""
    try:
        import nonebot
    except Exception:
        return
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()


def import_module(name: str):
    if name.startswith("plugins."):
        ensure_nonebot_initialized()
    return importlib.import_module(name)


def reload_module(name: str):
    if name.startswith("plugins."):
        ensure_nonebot_initialized()
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


class _StubMemoryStore(object):
    """Minimal memory store used for helper-only chat verification."""

    def initialize(self):
        return None

    def add_memory(self, group_id: str, user_id: str, user_msg: str, assistant_reply: str):
        return None

    def query_memories(self, group_id: str, query_text: str) -> List[str]:
        return []


def _install_arteta_memory_stub() -> None:
    stub = ModuleType("plugins.arteta_memory")
    stub.memory_store = _StubMemoryStore()
    stub.__verify_stub__ = True
    sys.modules["plugins.arteta_memory"] = stub


def _clear_arteta_chat_helper_stub() -> None:
    memory_module = sys.modules.get("plugins.arteta_memory")
    chat_module = sys.modules.get("plugins.arteta_chat")
    chat_memory_store = getattr(chat_module, "memory_store", None)
    if getattr(memory_module, "__verify_stub__", False) or isinstance(chat_memory_store, _StubMemoryStore):
        sys.modules.pop("plugins.arteta_chat", None)
        sys.modules.pop("plugins.arteta_memory", None)


def _is_missing_chromadb_error(exc: BaseException) -> bool:
    return isinstance(exc, ModuleNotFoundError) and getattr(exc, "name", None) == "chromadb"


def import_arteta_chat_for_helpers():
    """Import arteta_chat for pure helper checks, stubbing memory if ChromaDB is absent.

    The chat module imports plugins.arteta_memory at module load and initializes the
    global memory_store. Pure helper checks do not exercise vector memory, so when
    the only blocker is missing chromadb, install a lightweight memory_store stub
    and retry to avoid unrelated local dependency false negatives.
    """
    try:
        return import_module("plugins.arteta_chat")
    except ModuleNotFoundError as exc:
        if not _is_missing_chromadb_error(exc):
            raise
        for module_name in ("plugins.arteta_chat", "plugins.arteta_memory"):
            sys.modules.pop(module_name, None)
        _install_arteta_memory_stub()
        return import_module("plugins.arteta_chat")


def relative(path: str) -> str:
    try:
        return os.path.relpath(path, REPO_ROOT)
    except ValueError:
        return path


def is_missing_playwright_browser_error(exc: BaseException) -> bool:
    text = str(exc)
    lower = text.lower()
    return "executable doesn't exist" in lower and (
        "playwright" in lower or "chrome-headless-shell" in lower or "ms-playwright" in lower
    )


def make_result(
    suite: str,
    case: str,
    status: str,
    message: str = "",
    start: Optional[float] = None,
    artifacts: Optional[List[str]] = None,
    details: Optional[Dict[str, Any]] = None,
) -> CaseResult:
    duration = 0.0 if start is None else time.time() - start
    return CaseResult(
        suite=suite,
        case=case,
        status=status,
        message=message,
        duration_seconds=round(duration, 4),
        artifacts=artifacts or [],
        details=details or {},
    )


def pass_result(suite: str, case: str, message: str, start: float, artifacts: Optional[List[str]] = None, details: Optional[Dict[str, Any]] = None) -> CaseResult:
    return make_result(suite, case, STATUS_PASS, message, start, artifacts, details)


def fail_result(suite: str, case: str, message: str, start: float, artifacts: Optional[List[str]] = None, details: Optional[Dict[str, Any]] = None) -> CaseResult:
    return make_result(suite, case, STATUS_FAIL, message, start, artifacts, details)


def skip_result(suite: str, case: str, message: str, start: float, artifacts: Optional[List[str]] = None, details: Optional[Dict[str, Any]] = None) -> CaseResult:
    return make_result(suite, case, STATUS_SKIP, message, start, artifacts, details)


def manual_result(suite: str, case: str, message: str, start: float, artifacts: Optional[List[str]] = None, details: Optional[Dict[str, Any]] = None) -> CaseResult:
    return make_result(suite, case, STATUS_MANUAL, message, start, artifacts, details)


def safe_case(suite: str, case: str, func: Callable[[RunContext], CaseResult]) -> Callable[[RunContext], CaseResult]:
    def wrapper(ctx: RunContext) -> CaseResult:
        start = time.time()
        try:
            return func(ctx)
        except Exception as exc:
            tb_path = ctx.artifact_path("errors", "%s__%s.txt" % (suite, case))
            write_text(tb_path, traceback.format_exc())
            return fail_result(
                suite,
                case,
                "%s: %s" % (exc.__class__.__name__, exc),
                start,
                artifacts=[relative(tb_path)],
            )

    return wrapper


# ---------------------------------------------------------------------------
# Render suite
# ---------------------------------------------------------------------------


def render_template_exists(ctx: RunContext) -> CaseResult:
    start = time.time()
    template_path = os.path.join(ctx.repo_root, "templates", "arteta_render.html")
    if not os.path.exists(template_path):
        return fail_result("render", "template_exists", "Missing render template", start, details={"path": template_path})
    if file_size(template_path) <= 0:
        return fail_result("render", "template_exists", "Render template is empty", start, details={"path": template_path})
    return pass_result("render", "template_exists", "Render template exists", start, details={"path": relative(template_path), "bytes": file_size(template_path)})


def render_text_to_tactical_board(ctx: RunContext) -> CaseResult:
    start = time.time()
    render = import_module("plugins.arteta_render")
    image_bytes = render.text_to_tactical_board("[red]*阿森纳战术板*[/red]\n\n- 控制\n- 压迫\n")
    if not image_bytes.startswith(b"\x89PNG"):
        return fail_result("render", "text_to_tactical_board", "Output is not a PNG", start)
    artifact = ctx.artifact_path("render", "text_to_tactical_board.png")
    write_bytes(artifact, image_bytes)
    return pass_result(
        "render",
        "text_to_tactical_board",
        "Generated tactical board PNG",
        start,
        artifacts=[relative(artifact)],
        details={"bytes": len(image_bytes)},
    )


async def _render_html_image_once(render, markdown: str) -> bytes:
    try:
        return await render.html_to_image(markdown)
    finally:
        close_browser = getattr(render, "close_browser", None)
        if close_browser is not None:
            try:
                await close_browser()
            except Exception:
                pass



def render_html_to_image(ctx: RunContext) -> CaseResult:
    start = time.time()
    sample_path = os.path.join(ctx.repo_root, "tests", "fixtures", "markdown", "render_sample.md")
    if not os.path.exists(sample_path):
        return fail_result("render", "html_to_image", "Missing markdown fixture", start, details={"path": sample_path})
    render = import_module("plugins.arteta_render")
    markdown = read_text(sample_path)
    try:
        image_bytes = asyncio.run(_render_html_image_once(render, markdown))
    except Exception as exc:
        if is_missing_playwright_browser_error(exc):
            return skip_result(
                "render",
                "html_to_image",
                "Playwright Chromium is not installed; skipped HTML render case",
                start,
                details={"fixture": relative(sample_path)},
            )
        raise
    if not image_bytes.startswith(b"\x89PNG"):
        return fail_result("render", "html_to_image", "Output is not a PNG", start)
    artifact = ctx.artifact_path("render", "html_to_image.png")
    write_bytes(artifact, image_bytes)
    return pass_result(
        "render",
        "html_to_image",
        "Rendered markdown fixture through HTML renderer",
        start,
        artifacts=[relative(artifact)],
        details={"bytes": len(image_bytes), "fixture": relative(sample_path)},
    )


def render_quote_image_flow(ctx: RunContext) -> CaseResult:
    start = time.time()
    fixture_path = os.path.join(ctx.repo_root, "tests", "fixtures", "images", "quote_sample.png")
    if not os.path.exists(fixture_path):
        return fail_result("render", "quote_image_flow", "Missing quote image fixture", start, details={"path": fixture_path})
    arteta_image = import_module("plugins.arteta_image")
    with open(fixture_path, "rb") as f:
        source_bytes = f.read()
    processed = arteta_image.preprocess_reference_image(source_bytes)
    if not processed.startswith(b"\x89PNG"):
        return fail_result("render", "quote_image_flow", "Processed reference image is not a PNG", start)
    from PIL import Image

    img = Image.open(BytesIO(processed))
    if img.size != (1024, 1024):
        return fail_result("render", "quote_image_flow", "Processed image is not 1024x1024", start, details={"size": img.size})
    artifact = ctx.artifact_path("render", "quote_reference_preprocessed.png")
    write_bytes(artifact, processed)
    return pass_result(
        "render",
        "quote_image_flow",
        "Preprocessed quoted reference image for image edit flow",
        start,
        artifacts=[relative(artifact)],
        details={"bytes": len(processed), "size": list(img.size), "fixture": relative(fixture_path)},
    )


# ---------------------------------------------------------------------------
# Memory suite
# ---------------------------------------------------------------------------


def memory_sqlite_open(ctx: RunContext) -> CaseResult:
    start = time.time()
    db_path = ctx.run_path("memory", "sqlite_open.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS verification (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO verification (value) VALUES (?)", ("ok",))
        conn.commit()
        row = conn.execute("SELECT value FROM verification WHERE id=1").fetchone()
    finally:
        conn.close()
    if not row or row[0] != "ok":
        return fail_result("memory", "sqlite_open", "SQLite roundtrip returned unexpected row", start)
    return pass_result("memory", "sqlite_open", "SQLite opened and completed a local roundtrip", start, artifacts=[relative(db_path)])


def _reload_memory_with_dir(chroma_dir: str):
    os.environ["ARTETA_CHROMA_DIR"] = chroma_dir
    return reload_module("plugins.arteta_memory")


def memory_chromadb_init(ctx: RunContext) -> CaseResult:
    start = time.time()
    chroma_dir = ctx.run_path("memory", "chroma")
    memory = _reload_memory_with_dir(chroma_dir)
    store = memory.MemoryStore()
    store.initialize()
    if not getattr(store, "_ready", False):
        return fail_result("memory", "chromadb_init", "ChromaDB store did not become ready", start, artifacts=[relative(chroma_dir)])
    return pass_result("memory", "chromadb_init", "Initialized ChromaDB in isolated run directory", start, artifacts=[relative(chroma_dir)], details={"chroma_dir": relative(chroma_dir)})


def memory_add_query_roundtrip(ctx: RunContext) -> CaseResult:
    start = time.time()
    chroma_dir = ctx.run_path("memory", "chroma_roundtrip")
    memory = _reload_memory_with_dir(chroma_dir)
    store = memory.MemoryStore()
    store.initialize()
    if not getattr(store, "_ready", False):
        return fail_result("memory", "add_query_memory_roundtrip", "ChromaDB store did not become ready", start, artifacts=[relative(chroma_dir)])
    group_id = "verify-group"
    unique = "saka verification memory %s" % int(time.time() * 1000)
    store.add_memory(group_id, "verify-user-00000001", unique, "The assistant remembers Saka pressing cues.")
    # Chroma embedding/index updates are usually immediate, but a short retry keeps
    # this robust on slower machines without hiding failures indefinitely.
    results = []
    for _ in range(5):
        results = store.query_memories(group_id, "Saka pressing cues")
        if any(unique in item for item in results):
            break
        time.sleep(0.2)
    artifact = ctx.artifact_path("memory", "roundtrip_results.txt")
    write_text(artifact, "\n\n".join(results))
    if not any(unique in item for item in results):
        return fail_result(
            "memory",
            "add_query_memory_roundtrip",
            "Added memory was not found in query results",
            start,
            artifacts=[relative(chroma_dir), relative(artifact)],
            details={"result_count": len(results)},
        )
    return pass_result(
        "memory",
        "add_query_memory_roundtrip",
        "Added and queried a memory in isolated ChromaDB",
        start,
        artifacts=[relative(chroma_dir), relative(artifact)],
        details={"result_count": len(results)},
    )


def memory_knowledge_query(ctx: RunContext) -> CaseResult:
    start = time.time()
    knowledge = import_module("plugins.arteta_knowledge")
    if hasattr(knowledge, "clear_cache"):
        knowledge.clear_cache()
    result = knowledge.query_knowledge("信任", max_chars=1000)
    artifact = ctx.artifact_path("memory", "knowledge_query.txt")
    write_text(artifact, result)
    if not result:
        return fail_result("memory", "knowledge_query", "Knowledge query returned no text", start, artifacts=[relative(artifact)])
    return pass_result(
        "memory",
        "knowledge_query",
        "Queried local knowledge base and wrote text artifact",
        start,
        artifacts=[relative(artifact)],
        details={"chars": len(result)},
    )


# ---------------------------------------------------------------------------
# Chat suite
# ---------------------------------------------------------------------------


def chat_should_search(ctx: RunContext) -> CaseResult:
    start = time.time()
    chat = import_arteta_chat_for_helpers()
    checks = [
        ("latest Arsenal transfer news", True),
        ("今天阿森纳最新消息", True),
        ("解释一下高位逼抢", False),
    ]
    failed = []
    for query, expected in checks:
        actual = chat._should_search(query)
        if actual != expected:
            failed.append({"query": query, "expected": expected, "actual": actual})
    if failed:
        return fail_result("chat", "_should_search", "Unexpected search decisions", start, details={"failures": failed})
    return pass_result("chat", "_should_search", "Search intent helper matched expected decisions", start, details={"checks": len(checks)})


def chat_needs_fixtures(ctx: RunContext) -> CaseResult:
    start = time.time()
    chat = import_arteta_chat_for_helpers()
    checks = [
        ("阿森纳赛程表", True),
        ("fixture schedule", True),
        ("阿尔特塔战术", False),
    ]
    failed = []
    for query, expected in checks:
        actual = chat._needs_fixtures(query)
        if actual != expected:
            failed.append({"query": query, "expected": expected, "actual": actual})
    if failed:
        return fail_result("chat", "_needs_fixtures", "Unexpected fixture decisions", start, details={"failures": failed})
    return pass_result("chat", "_needs_fixtures", "Fixture intent helper matched expected decisions", start, details={"checks": len(checks)})


def chat_extract_favor_marker(ctx: RunContext) -> CaseResult:
    start = time.time()
    chat = import_arteta_chat_for_helpers()
    text = "不错。\n【好感度+】\n后来更糟。\n【好感度--】"
    marker = chat.extract_favor_marker(text)
    if marker != "【好感度--】":
        return fail_result("chat", "extract_favor_marker", "Did not return the last marker", start, details={"marker": marker})
    empty = chat.extract_favor_marker("没有标记")
    if empty is not None:
        return fail_result("chat", "extract_favor_marker", "Expected None when no marker is present", start, details={"marker": empty})
    return pass_result("chat", "extract_favor_marker", "Extracted last favor marker and handled missing marker", start)


def chat_check_keyword_penalty(ctx: RunContext) -> CaseResult:
    start = time.time()
    chat = import_arteta_chat_for_helpers()
    heavy_score, heavy_reason = chat.check_keyword_penalty("阿尔特塔滚")
    neutral_score, neutral_reason = chat.check_keyword_penalty("今天训练很积极")
    if not (-8 <= heavy_score <= -1) or "负面" not in heavy_reason:
        return fail_result("chat", "check_keyword_penalty", "Heavy keyword penalty outside expected range", start, details={"score": heavy_score, "reason": heavy_reason})
    if neutral_score != 0 or neutral_reason != "":
        return fail_result("chat", "check_keyword_penalty", "Neutral text received a penalty", start, details={"score": neutral_score, "reason": neutral_reason})
    return pass_result("chat", "check_keyword_penalty", "Keyword penalty helper handled negative and neutral inputs", start, details={"heavy_score": heavy_score})


# ---------------------------------------------------------------------------
# Commands suite
# ---------------------------------------------------------------------------


def commands_plugin_imports(ctx: RunContext) -> CaseResult:
    start = time.time()
    modules = [
        "plugins.arteta_admin",
        "plugins.arteta_chat",
        "plugins.arteta_cmath",
        "plugins.arteta_daily",
        "plugins.arteta_help",
        "plugins.arteta_image",
        "plugins.arteta_knowledge",
        "plugins.arteta_like",
        "plugins.arteta_memory",
        "plugins.arteta_football_news",
        "plugins.arteta_mute",
        "plugins.arteta_render",
        "plugins.arteta_standings",
        "plugins.arteta_swear",
        "plugins.arteta_tools",
        "plugins.arteta_weekly",
    ]
    imported = []
    failed = []
    for module_name in modules:
        _clear_arteta_chat_helper_stub()
        try:
            import_module(module_name)
            imported.append(module_name)
        except Exception as exc:
            failed.append({
                "module": module_name,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            })
    details = {"imported": imported, "failed": failed}
    if failed:
        failed_names = ", ".join([item["module"] for item in failed])
        return fail_result(
            "commands",
            "plugin_imports",
            "Imported %s plugin module(s); failed %s: %s" % (len(imported), len(failed), failed_names),
            start,
            details=details,
        )
    return pass_result(
        "commands",
        "plugin_imports",
        "Imported %s main plugin modules" % len(imported),
        start,
        details=details,
    )


def commands_local_feature_health(ctx: RunContext) -> CaseResult:
    start = time.time()
    help_mod = import_module("plugins.arteta_help")
    like_mod = import_module("plugins.arteta_like")
    help_text = help_mod.build_help_text()
    normal_limit = like_mod.get_daily_like_limit(False)
    vip_limit = like_mod.get_daily_like_limit(True)
    failures = []
    if "阿森纳战术指令板" not in help_text:
        failures.append("help text missing command board title")
    if "赞我" not in help_text:
        failures.append("help text missing like command")
    if normal_limit != 10:
        failures.append("normal like limit expected 10 got %s" % normal_limit)
    if vip_limit != 50:
        failures.append("vip like limit expected 50 got %s" % vip_limit)
    artifact = ctx.artifact_path("commands", "help_text.txt")
    write_text(artifact, help_text)
    if failures:
        return fail_result("commands", "local_feature_health", "; ".join(failures), start, artifacts=[relative(artifact)])
    return pass_result(
        "commands",
        "local_feature_health",
        "Validated extracted command helpers",
        start,
        artifacts=[relative(artifact)],
        details={"normal_like_limit": normal_limit, "vip_like_limit": vip_limit, "help_chars": len(help_text)},
    )


# ---------------------------------------------------------------------------
# Football news suite
# ---------------------------------------------------------------------------


def football_news_offline_roundtrip(ctx: RunContext) -> CaseResult:
    start = time.time()
    football_news = import_module("plugins.arteta_football_news")
    db_path = ctx.run_path("football_news", "football_news.db")
    chroma_dir = ctx.run_path("football_news", "chroma")
    sqlite_store = football_news.FootballNewsSQLiteStore(db_path)
    sqlite_store.initialize()
    chroma_store = football_news.FootballNewsChromaStore(chroma_dir)
    chroma_store.initialize()
    if not getattr(chroma_store, "_ready", False):
        return fail_result("football_news", "offline_roundtrip", "Chroma football_news collection did not initialize", start, artifacts=[relative(chroma_dir)])
    now = int(time.time())
    items = [
        football_news.NewsItem("阿森纳继续追逐英超冠军", "https://example.com/pl-a", "fixture", "premier_league", "阿森纳仍在争冠集团。", now, now).with_hash(),
        football_news.NewsItem("中超焦点战今晚打响", "https://example.com/csl-a", "fixture", "chinese_super_league", "中超焦点战今晚进行。", now, now).with_hash(),
    ]
    inserted = 0
    for item in items:
        chroma_id = chroma_store.add_item(item)
        if sqlite_store.insert_item(item, chroma_id):
            inserted += 1
    chroma_store.add_digest(items, now)
    search_result = chroma_store.search("英超 阿森纳", category="premier_league", days=14, now=now)
    artifact = ctx.artifact_path("football_news", "search_result.txt")
    write_text(artifact, search_result)
    if inserted != 2:
        return fail_result("football_news", "offline_roundtrip", "Expected 2 inserted football news items", start, artifacts=[relative(db_path), relative(artifact)], details={"inserted": inserted})
    if "阿森纳继续追逐英超冠军" not in search_result:
        return fail_result("football_news", "offline_roundtrip", "Inserted Premier League item was not returned by search", start, artifacts=[relative(db_path), relative(chroma_dir), relative(artifact)])
    return pass_result(
        "football_news",
        "offline_roundtrip",
        "Inserted item and digest documents into isolated football_news collection",
        start,
        artifacts=[relative(db_path), relative(chroma_dir), relative(artifact)],
        details={"inserted": inserted},
    )


# ---------------------------------------------------------------------------
# Agent registry suite
# ---------------------------------------------------------------------------


def agent_registry_has_tools(ctx: RunContext) -> CaseResult:
    start = time.time()
    registry = import_module("plugins.arteta_agent.registry")
    football = import_module("plugins.arteta_agent.tools.football")
    registry.clear_registry()
    football.register_tools()
    tools = registry.build_openai_tools()
    names = [tool["function"]["name"] for tool in tools]
    expected = [
        "get_arsenal_result",
        "get_pl_table",
        "get_arsenal_injuries",
        "search_news",
        "get_football_knowledge",
        "get_group_members",
        "get_member_relations",
    ]
    missing = [name for name in expected if name not in names]
    if missing:
        return fail_result("agent_registry", "registry_has_tools", "Missing tools: %s" % ", ".join(missing), start, details={"names": names})
    return pass_result("agent_registry", "registry_has_tools", "Agent registry exposes %s phase-1 tools" % len(names), start, details={"names": names})


def agent_registry_phase2_read_tools(ctx: RunContext) -> CaseResult:
    start = time.time()
    registry = import_module("plugins.arteta_agent.registry")
    tools = import_module("plugins.arteta_agent.tools")
    registry.clear_registry()
    tools.register_phase2_tools()
    specs = {spec.name: spec for spec in registry.list_enabled_tools()}
    expected = [
        "search_football_news",
        "get_user_profile",
        "get_current_user_profile",
        "query_group_memory",
        "get_recent_group_context",
        "find_recent_messages_by_alias",
        "search_daily_messages",
        "web_search",
        "web_fetch",
        "verify_recent_claim",
    ]
    missing = [name for name in expected if name not in specs]
    unsafe = [name for name in expected if name in specs and specs[name].permission != "safe_read"]
    if missing or unsafe:
        return fail_result(
            "agent_registry",
            "phase2_read_tools",
            "Phase-2 read tools are missing or have unsafe permissions",
            start,
            details={"missing": missing, "unsafe": unsafe, "registered": sorted(specs.keys())},
        )
    return pass_result(
        "agent_registry",
        "phase2_read_tools",
        "Agent registry exposes phase-2 read-only tools",
        start,
        details={"names": expected},
    )


def agent_registry_web_access_offline(ctx: RunContext) -> CaseResult:
    start = time.time()
    context_mod = import_module("plugins.arteta_agent.context")
    web_access = import_module("plugins.arteta_agent.tools.web_access")

    tool_ctx = context_mod.ToolContext(bot=None, event=None, user_id="verify-user", group_id="verify-group")

    async def fake_search(query, max_results=5, timelimit=None):
        return [{
            "title": "Arsenal official update",
            "href": "https://www.arsenal.com/news/official-update",
            "body": "Arsenal published an official update.",
            "date": "2026-07-01",
        }]

    async def fake_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        return {
            "url": url,
            "final_url": url,
            "content_type": "text/html",
            "text": "<html><head><title>Official update</title><meta property='article:published_time' content='2026-07-01'></head><body><article>Arsenal confirmed the update on the club website.</article></body></html>",
        }

    original_search = web_access._duckduckgo_search
    original_fetch = web_access._fetch_url
    original_config_attr = web_access._config_attr
    original_grok_url = getattr(web_access, "GROKSEARCH_API_URL", "")
    original_grok_key = getattr(web_access, "GROKSEARCH_API_KEY", "")
    original_grok_model = getattr(web_access, "GROKSEARCH_MODEL", "")
    original_x_url = getattr(web_access, "X_FETCH_API_URL", "")
    original_x_key = getattr(web_access, "X_FETCH_API_KEY", "")
    env_keys = [
        "ARTETA_GROKSEARCH_API_URL",
        "ARTETA_GROKSEARCH_API_KEY",
        "ARTETA_GROKSEARCH_MODEL",
        "GROKSEARCH_TIMEOUT",
        "ARTETA_X_FETCH_API_URL",
        "ARTETA_X_FETCH_API_KEY",
    ]
    original_env = {key: os.environ.get(key) for key in env_keys}
    try:
        for key in env_keys:
            os.environ.pop(key, None)
        web_access.GROKSEARCH_API_URL = ""
        web_access.GROKSEARCH_API_KEY = ""
        web_access.GROKSEARCH_MODEL = ""
        web_access.X_FETCH_API_URL = ""
        web_access.X_FETCH_API_KEY = ""
        web_access._config_attr = lambda name: ""
        web_access._duckduckgo_search = fake_search
        web_access._fetch_url = fake_fetch
        blocked = asyncio.run(web_access.web_fetch(tool_ctx, url="file:///etc/passwd"))
        fetched = asyncio.run(web_access.web_fetch(tool_ctx, url="https://www.arsenal.com/news/official-update"))
        verified = asyncio.run(web_access.verify_recent_claim(tool_ctx, claim="Arsenal official update 2026"))
    finally:
        web_access._duckduckgo_search = original_search
        web_access._fetch_url = original_fetch
        web_access.GROKSEARCH_API_URL = original_grok_url
        web_access.GROKSEARCH_API_KEY = original_grok_key
        web_access.GROKSEARCH_MODEL = original_grok_model
        web_access.X_FETCH_API_URL = original_x_url
        web_access.X_FETCH_API_KEY = original_x_key
        web_access._config_attr = original_config_attr
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    blocked_text = getattr(blocked, "content", blocked)
    fetched_text = getattr(fetched, "content", fetched)
    verified_text = getattr(verified, "content", verified)
    ok = (
        "只支持 http/https" in blocked_text
        and "发布时间：2026-07-01" in fetched_text
        and "来源等级：一手/官方来源" in verified_text
        and "https://www.arsenal.com/news/official-update" in verified_text
    )
    if not ok:
        return fail_result(
            "agent_registry",
            "web_access_offline",
            "Web access tools did not produce safe citable evidence offline",
            start,
            details={"blocked": blocked_text, "fetched": fetched_text, "verified": verified_text},
        )
    return pass_result(
        "agent_registry",
        "web_access_offline",
        "Web access tools reject unsafe URLs and produce citable source evidence",
        start,
        details={"blocked": blocked_text, "verified": verified_text},
    )


def agent_registry_phase3_safe_write_tools(ctx: RunContext) -> CaseResult:
    start = time.time()
    registry = import_module("plugins.arteta_agent.registry")
    tools = import_module("plugins.arteta_agent.tools")
    registry.clear_registry()
    tools.register_phase3_tools()
    specs = {spec.name: spec for spec in registry.list_enabled_tools()}
    expected = [
        "solve_science_question",
        "solve_algorithm_problem",
        "solve_code_question",
        "solve_math_question",
        "generate_today_group_summary",
        "render_markdown_to_image",
        "generate_image",
        "generate_weekly_report",
        "update_behavior_policy",
        "update_ui_preference",
    ]
    missing = [name for name in expected if name not in specs]
    wrong_permission = [name for name in expected if name in specs and specs[name].permission != "safe_write"]
    if missing or wrong_permission:
        return fail_result(
            "agent_registry",
            "phase3_safe_write_tools",
            "Phase-3 safe-write tools are missing or have unexpected permissions",
            start,
            details={"missing": missing, "wrong_permission": wrong_permission, "registered": sorted(specs.keys())},
        )
    return pass_result(
        "agent_registry",
        "phase3_safe_write_tools",
        "Agent registry exposes phase-3 safe-write generation tools",
        start,
        details={"names": expected},
    )


def agent_registry_phase3_read_tools(ctx: RunContext) -> CaseResult:
    start = time.time()
    registry = import_module("plugins.arteta_agent.registry")
    tools = import_module("plugins.arteta_agent.tools")
    registry.clear_registry()
    tools.register_phase3_tools()
    specs = {spec.name: spec for spec in registry.list_enabled_tools()}
    expected = [
        "analyze_image",
        "show_behavior_policy",
        "show_agent_trace",
    ]
    missing = [name for name in expected if name not in specs]
    wrong_permission = [name for name in expected if name in specs and specs[name].permission != "safe_read"]
    if missing or wrong_permission:
        return fail_result(
            "agent_registry",
            "phase3_read_tools",
            "Phase-3 read/debug tools are missing or have unexpected permissions",
            start,
            details={"missing": missing, "wrong_permission": wrong_permission, "registered": sorted(specs.keys())},
        )
    return pass_result(
        "agent_registry",
        "phase3_read_tools",
        "Agent registry exposes phase-3 image analysis and trace read tools",
        start,
        details={"names": expected},
    )


def agent_registry_phase4_confirm_write_tools(ctx: RunContext) -> CaseResult:
    start = time.time()
    registry = import_module("plugins.arteta_agent.registry")
    tools = import_module("plugins.arteta_agent.tools")
    executor = import_module("plugins.arteta_agent.executor")
    context_mod = import_module("plugins.arteta_agent.context")
    pending = import_module("plugins.arteta_agent.pending")
    registry.clear_registry()
    tools.register_phase4_tools()
    specs = {spec.name: spec for spec in registry.list_enabled_tools()}
    expected_confirm = ["send_like", "send_group_message", "clear_group_memory", "update_user_profile_by_llm"]
    expected_safe_write = ["send_mood_emoji"]
    expected = expected_confirm + expected_safe_write
    missing = [name for name in expected if name not in specs]
    wrong_permission = [
        name for name in expected_confirm
        if name in specs and specs[name].permission != "confirm_write"
    ] + [
        name for name in expected_safe_write
        if name in specs and specs[name].permission != "safe_write"
    ]
    db_path = ctx.run_path("agent_registry", "pending_actions_%s.db" % uuid.uuid4().hex)
    tool_ctx = context_mod.ToolContext(
        bot=None,
        event=None,
        user_id="verify-user",
        group_id="verify-group",
        extra={"pending_action_db_path": db_path},
    )
    denied = asyncio.run(executor.execute_tool_call(
        {"id": "call-verify", "function": {"name": "clear_group_memory", "arguments": "{}"}},
        tool_ctx,
    ))
    actions = pending.PendingActionStore(db_path).list_actions(user_id="verify-user", group_id="verify-group")
    if missing or wrong_permission or not denied.startswith("[PermissionRequired]") or len(actions) != 1:
        return fail_result(
            "agent_registry",
            "phase4_confirm_write_tools",
            "Phase-4 QQ/action tools or pending action behavior failed",
            start,
            artifacts=[relative(db_path)],
            details={
                "missing": missing,
                "wrong_permission": wrong_permission,
                "denied": denied,
                "actions": actions,
                "registered": sorted(specs.keys()),
            },
        )
    return pass_result(
        "agent_registry",
        "phase4_confirm_write_tools",
        "Agent registry exposes phase-4 QQ/action tools and records pending actions",
        start,
        artifacts=[relative(db_path)],
        details={"names": expected, "pending_action": actions[0]["id"]},
    )


def agent_registry_remember_user_preference_tool(ctx: RunContext) -> CaseResult:
    start = time.time()
    registry = import_module("plugins.arteta_agent.registry")
    tools = import_module("plugins.arteta_agent.tools")
    memory_actions = import_module("plugins.arteta_agent.tools.memory_actions")
    context_mod = import_module("plugins.arteta_agent.context")

    registry.clear_registry()
    tools.register_phase4_tools()
    spec = registry.get_tool("remember_user_preference")
    calls = []

    class FakeMemoryStore(object):
        def add_memory(self, group_id, user_id, user_msg, assistant_reply, nickname="", aliases=None):
            calls.append((group_id, user_id, user_msg, assistant_reply, nickname, aliases))

    original_get_memory = memory_actions._get_arteta_memory
    memory_actions._get_arteta_memory = lambda: type("FakeMemoryModule", (), {"memory_store": FakeMemoryStore()})()
    try:
        result = memory_actions.remember_user_preference(
            context_mod.ToolContext(bot=None, event=None, user_id="u1", group_id="g1", nickname="Nick"),
            memory="以后我说开会就是提醒我看阿森纳赛程",
        )
    finally:
        memory_actions._get_arteta_memory = original_get_memory

    if not spec or spec.permission != "safe_write" or not result.startswith("已写入长期记忆") or not calls or calls[0][0:2] != ("g1", "u1"):
        return fail_result(
            "agent_registry",
            "remember_user_preference_tool",
            "Explicit memory tool was not registered or did not write scoped memory",
            start,
            details={"permission": getattr(spec, "permission", None), "result": result, "calls": calls},
        )
    return pass_result(
        "agent_registry",
        "remember_user_preference_tool",
        "Explicit future preferences write immediately to scoped long-term memory",
        start,
        details={"permission": spec.permission, "call": calls[0]},
    )


def agent_registry_phase5_admin_tools(ctx: RunContext) -> CaseResult:
    start = time.time()
    registry = import_module("plugins.arteta_agent.registry")
    tools = import_module("plugins.arteta_agent.tools")
    context_mod = import_module("plugins.arteta_agent.context")
    audit = import_module("plugins.arteta_agent.audit")
    admin_tools = import_module("plugins.arteta_agent.tools.admin")
    registry.clear_registry()
    tools.register_phase5_tools()
    specs = {spec.name: spec for spec in registry.list_enabled_tools()}
    expected = ["mute_member", "read_logs", "run_verify_suite", "check_config", "update_config", "delete_message"]
    missing = [name for name in expected if name not in specs]
    wrong_permission = [name for name in expected if name in specs and specs[name].permission != "admin_action"]

    unique = uuid.uuid4().hex
    env_file = ctx.run_path("agent_registry", "phase5_%s.env" % unique)
    write_text(env_file, "DEEPSEEK_MODEL=deepseek-v4-pro\n")
    audit_db = ctx.run_path("agent_registry", "agent_audit_%s.db" % unique)
    tool_ctx = context_mod.ToolContext(
        bot=None,
        event=None,
        user_id="admin-user",
        group_id="admin-group",
        is_admin=True,
        extra={"env_file": env_file, "audit_db_path": audit_db},
    )
    config_result = admin_tools.check_config(tool_ctx)
    records = audit.AuditStore(audit_db).list_records()
    if missing or wrong_permission or "DEEPSEEK_MODEL" not in config_result or not records:
        return fail_result(
            "agent_registry",
            "phase5_admin_tools",
            "Phase-5 admin tools or audit logging failed",
            start,
            artifacts=[relative(env_file), relative(audit_db)],
            details={
                "missing": missing,
                "wrong_permission": wrong_permission,
                "config_result": config_result[:200],
                "records": records,
                "registered": sorted(specs.keys()),
            },
        )
    return pass_result(
        "agent_registry",
        "phase5_admin_tools",
        "Agent registry exposes phase-5 admin tools and writes audit logs",
        start,
        artifacts=[relative(env_file), relative(audit_db)],
        details={"names": expected, "audit_tool": records[0]["tool_name"]},
    )


def agent_registry_duplicate_rejected(ctx: RunContext) -> CaseResult:
    start = time.time()
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    registry.clear_registry()

    async def handler(ctx):
        return "ok"

    spec = registry.ToolSpec("verify_duplicate", "duplicate", {"type": "object", "properties": {}}, handler)
    registry.register_tool(spec)
    try:
        registry.register_tool(spec)
    except ValueError:
        return pass_result("agent_registry", "duplicate_rejected", "Duplicate tool registration is rejected", start)
    return fail_result("agent_registry", "duplicate_rejected", "Duplicate tool registration was accepted", start)


def agent_registry_permission_gates(ctx: RunContext) -> CaseResult:
    start = time.time()
    context_mod = import_module("plugins.arteta_agent.context")
    permissions = import_module("plugins.arteta_agent.permissions")
    registry = import_module("plugins.arteta_agent.registry")
    tool_ctx = context_mod.ToolContext(bot=None, event=None, user_id="u", group_id="g", is_admin=False)
    admin_ctx = context_mod.ToolContext(bot=None, event=None, user_id="u", group_id="g", is_admin=True, extra={"confirmed_tool": "admin_tool"})
    confirm_spec = registry.ToolSpec("confirm_tool", "confirm", {"type": "object", "properties": {}}, lambda ctx: "ok", permission="confirm_write")
    admin_spec = registry.ToolSpec("admin_tool", "admin", {"type": "object", "properties": {}}, lambda ctx: "ok", permission="admin_action")
    confirm_allowed, confirm_reason = permissions.check_permission(confirm_spec, tool_ctx, {})
    admin_allowed, admin_reason = permissions.check_permission(admin_spec, tool_ctx, {})
    legacy_admin_confirmed, legacy_admin_reason = permissions.check_permission(admin_spec, admin_ctx, {})
    if confirm_allowed or admin_allowed or legacy_admin_confirmed:
        return fail_result(
            "agent_registry",
            "permission_gates",
            "Permission gates returned unexpected decisions",
            start,
            details={
                "confirm": [confirm_allowed, confirm_reason],
                "admin": [admin_allowed, admin_reason],
                "legacy_admin_confirmed": [legacy_admin_confirmed, legacy_admin_reason],
            },
        )
    return pass_result(
        "agent_registry",
        "permission_gates",
        "Permission gates reject unconfirmed/admin actions and do not honor legacy confirmed_tool bypass",
        start,
    )


def agent_registry_executor_error_paths(ctx: RunContext) -> CaseResult:
    start = time.time()
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    executor = import_module("plugins.arteta_agent.executor")
    registry.clear_registry()

    async def slow(ctx):
        await asyncio.sleep(0.05)
        return "slow"

    registry.register_tool(registry.ToolSpec("slow_tool", "slow", {"type": "object", "properties": {}}, slow, timeout_seconds=0.001))
    tool_ctx = context_mod.ToolContext(bot=None, event=None, user_id="u", group_id="g")
    unknown = asyncio.run(executor.execute_tool_call({"function": {"name": "missing", "arguments": "{}"}}, tool_ctx))
    timeout = asyncio.run(executor.execute_tool_call({"function": {"name": "slow_tool", "arguments": "{}"}}, tool_ctx))
    if "未知工具" not in unknown or not timeout.startswith("[ToolTimeout]"):
        return fail_result("agent_registry", "executor_error_paths", "Executor error paths did not return readable errors", start, details={"unknown": unknown, "timeout": timeout})
    return pass_result("agent_registry", "executor_error_paths", "Executor returns readable unknown-tool and timeout errors", start)


def agent_activation_candidate_gates(ctx: RunContext) -> CaseResult:
    start = time.time()
    activation = import_module("plugins.arteta_agent.activation")
    plain = activation.is_activation_candidate("罗哥的比赛是七点", has_image=False)
    task = activation.is_activation_candidate("最近阿森纳怎么样", has_image=False)
    pure_image = activation.is_activation_candidate("", has_image=True)
    trace = activation.is_activation_candidate("show trace", has_image=False)
    if plain or not task or pure_image or not trace:
        return fail_result(
            "agent_loop",
            "activation_candidate_gates",
            "Activation candidate gates returned unexpected decisions",
            start,
            details={"plain": plain, "task": task, "pure_image": pure_image, "trace": trace},
        )
    return pass_result(
        "agent_loop",
        "activation_candidate_gates",
        "Activation gates reject plain chatter while allowing task-like messages",
        start,
        details={"plain": plain, "task": task, "pure_image": pure_image, "trace": trace},
    )


def agent_activation_judge_fail_closed(ctx: RunContext) -> CaseResult:
    start = time.time()
    activation = import_module("plugins.arteta_agent.activation")

    async def invalid_llm(messages, model, api_key, timeout):
        return "maybe"

    async def broken_llm(messages, model, api_key, timeout):
        raise TimeoutError("slow")

    invalid = asyncio.run(activation.decide_activation_with_agent(
        "查一下阿森纳",
        False,
        "verify-group",
        "model",
        "key",
        llm_call=invalid_llm,
    ))
    broken = asyncio.run(activation.decide_activation_with_agent(
        "查一下阿森纳",
        False,
        "verify-group",
        "model",
        "key",
        llm_call=broken_llm,
    ))
    if invalid.should_reply or broken.should_reply:
        return fail_result(
            "agent_loop",
            "activation_judge_fail_closed",
            "Activation judge should fail closed on invalid or failed LLM responses",
            start,
            details={"invalid": asdict(invalid), "broken": asdict(broken)},
        )
    return pass_result(
        "agent_loop",
        "activation_judge_fail_closed",
        "Activation judge fails closed on invalid or failed LLM responses",
        start,
        details={"invalid": asdict(invalid), "broken": asdict(broken)},
    )


def agent_loop_forces_trace_tool(ctx: RunContext) -> CaseResult:
    start = time.time()
    planner = import_module("plugins.arteta_agent.planner")
    registry = import_module("plugins.arteta_agent.registry")
    trace_tool = import_module("plugins.arteta_agent.tools.trace")
    context_mod = import_module("plugins.arteta_agent.context")
    trace_mod = import_module("plugins.arteta_agent.trace")

    registry.clear_registry()
    trace_tool.register_tools()
    agent_trace = trace_mod.new_trace("agent_registry")
    tool_ctx = context_mod.ToolContext(
        bot=None,
        event=None,
        user_id="verify-user",
        group_id="verify-group",
        extra={"agent_trace": agent_trace},
    )
    original_call = planner.call_llm_with_tools
    llm_called = False

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        nonlocal llm_called
        llm_called = True
        return {"role": "assistant", "content": "should not be used"}

    try:
        planner.call_llm_with_tools = fake_call
        result = asyncio.run(planner.run_agent_loop(
            [{"role": "user", "content": "show trace"}],
            tool_ctx,
            "model",
            "key",
            max_rounds=2,
            trace=agent_trace,
        ))
    finally:
        planner.call_llm_with_tools = original_call

    tools = agent_trace.get("tools") or []
    if llm_called or "调用工具：show_agent_trace" not in result or not tools or tools[0].get("name") != "show_agent_trace" or tools[0].get("status") != "ok":
        return fail_result(
            "agent_loop",
            "forces_trace_tool",
            "Trace request did not return show_agent_trace result directly",
            start,
            details={"result": result, "tools": tools, "llm_called": llm_called},
        )
    return pass_result(
        "agent_loop",
        "forces_trace_tool",
        "Trace requests force the read-only show_agent_trace tool and avoid a second LLM call",
        start,
        details={"result": result, "tools": tools, "llm_called": llm_called},
    )


def agent_loop_does_not_force_mood_emoji_after_behavior_policy_query(ctx: RunContext) -> CaseResult:
    start = time.time()
    planner = import_module("plugins.arteta_agent.planner")
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    trace_mod = import_module("plugins.arteta_agent.trace")

    registry.clear_registry()
    agent_trace = trace_mod.new_trace("agent_registry")
    emoji_calls = []

    def show_policy_handler(ctx):
        return "No behavior policy is set for this group."

    async def emoji_handler(ctx, mood="", reason="", emoji_name=""):
        emoji_calls.append({"mood": mood, "reason": reason, "emoji_name": emoji_name})
        return "emoji sent"

    registry.register_tool(registry.ToolSpec(
        name="show_behavior_policy",
        description="show policy",
        parameters={"type": "object", "properties": {}},
        handler=show_policy_handler,
        permission="safe_read",
    ))
    registry.register_tool(registry.ToolSpec(
        name="send_mood_emoji",
        description="send emoji",
        parameters={"type": "object", "properties": {"mood": {"type": "string"}}},
        handler=emoji_handler,
        permission="safe_write",
    ))

    responses = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call-policy",
                "function": {"name": "show_behavior_policy", "arguments": "{}"},
            }],
        },
        {"role": "assistant", "content": "No behavior policy is set for this group."},
    ]
    original_call = planner.call_llm_with_tools

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        return responses.pop(0)

    tool_ctx = context_mod.ToolContext(
        bot=None,
        event=None,
        user_id="verify-user",
        group_id="verify-group",
        extra={"agent_trace": agent_trace},
    )
    try:
        planner.call_llm_with_tools = fake_call
        result = asyncio.run(planner.run_agent_loop(
            [{"role": "user", "content": "show behavior policy"}],
            tool_ctx,
            "model",
            "key",
            max_rounds=3,
            trace=agent_trace,
        ))
    finally:
        planner.call_llm_with_tools = original_call

    tools = [item.get("name") for item in agent_trace.get("tools") or []]
    if result != "No behavior policy is set for this group." or emoji_calls or tools != ["show_behavior_policy"]:
        return fail_result(
            "agent_loop",
            "does_not_force_mood_emoji_after_behavior_policy_query",
            "Behavior policy query incorrectly forced send_mood_emoji",
            start,
            details={"result": result, "tools": tools, "emoji_calls": emoji_calls},
        )
    return pass_result(
        "agent_loop",
        "does_not_force_mood_emoji_after_behavior_policy_query",
        "Behavior policy and trace/debug turns do not auto-send mood emoji",
        start,
        details={"result": result, "tools": tools},
    )


def agent_loop_forces_math_tool(ctx: RunContext) -> CaseResult:
    start = time.time()
    planner = import_module("plugins.arteta_agent.planner")
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    trace_mod = import_module("plugins.arteta_agent.trace")

    registry.clear_registry()
    agent_trace = trace_mod.new_trace("agent_registry")

    async def math_handler(ctx, question=""):
        return "math solved: {0}".format(question)

    registry.register_tool(registry.ToolSpec(
        name="solve_math_question",
        description="solve math",
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": [],
        },
        handler=math_handler,
        permission="safe_write",
    ))
    tool_ctx = context_mod.ToolContext(
        bot=None,
        event=None,
        user_id="verify-user",
        group_id="verify-group",
        extra={"agent_trace": agent_trace},
    )
    original_call = planner.call_llm_with_tools
    llm_called = False

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        nonlocal llm_called
        llm_called = True
        return {"role": "assistant", "content": "model answered directly"}

    try:
        planner.call_llm_with_tools = fake_call
        result = asyncio.run(planner.run_agent_loop(
            [{"role": "user", "content": "求解数学题：x^2 - 1 = 0"}],
            tool_ctx,
            "model",
            "key",
            max_rounds=2,
            trace=agent_trace,
        ))
    finally:
        planner.call_llm_with_tools = original_call

    tools = agent_trace.get("tools") or []
    if llm_called or not result.startswith("math solved:") or not tools or tools[0].get("name") != "solve_math_question" or tools[0].get("status") != "ok":
        return fail_result(
            "agent_loop",
            "forces_math_tool",
            "Obvious math question did not return solve_math_question result directly",
            start,
            details={"result": result, "tools": tools, "llm_called": llm_called},
        )
    return pass_result(
        "agent_loop",
        "forces_math_tool",
        "Obvious math questions force solve_math_question and keep the call visible in trace",
        start,
        details={"result": result, "tools": tools, "llm_called": llm_called},
    )


def agent_loop_does_not_expose_math_tool_for_scoreline_chat(ctx: RunContext) -> CaseResult:
    start = time.time()
    planner = import_module("plugins.arteta_agent.planner")
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    trace_mod = import_module("plugins.arteta_agent.trace")

    registry.clear_registry()
    agent_trace = trace_mod.new_trace("agent_registry")

    def math_handler(ctx, question=""):
        return "math solved: {0}".format(question)

    registry.register_tool(registry.ToolSpec(
        name="solve_math_question",
        description="solve math",
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": [],
        },
        handler=math_handler,
        permission="safe_write",
    ))
    tool_ctx = context_mod.ToolContext(
        bot=None,
        event=None,
        user_id="verify-user",
        group_id="verify-group",
        extra={"agent_trace": agent_trace},
    )
    original_call = planner.call_llm_with_tools
    llm_called = False
    exposed_math_tool = True

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        nonlocal llm_called, exposed_math_tool
        llm_called = True
        exposed_math_tool = "solve_math_question" not in set(disabled_tools or [])
        return {"role": "assistant", "content": "这是普通聊天，不是数学题。"}

    try:
        planner.call_llm_with_tools = fake_call
        result = asyncio.run(planner.run_agent_loop(
            [{"role": "user", "content": "@阿尔特塔 老子1-0"}],
            tool_ctx,
            "model",
            "key",
            max_rounds=2,
            trace=agent_trace,
        ))
    finally:
        planner.call_llm_with_tools = original_call

    tools = agent_trace.get("tools") or []
    if result != "这是普通聊天，不是数学题。" or tools or not llm_called or exposed_math_tool:
        return fail_result(
            "agent_loop",
            "does_not_expose_math_tool_for_scoreline_chat",
            "Scoreline-like chat incorrectly forced or exposed solve_math_question",
            start,
            details={"result": result, "tools": tools, "llm_called": llm_called, "exposed_math_tool": exposed_math_tool},
        )
    return pass_result(
        "agent_loop",
        "does_not_expose_math_tool_for_scoreline_chat",
        "Scoreline-like chat does not force or expose solve_math_question",
        start,
        details={"result": result, "tools": tools, "llm_called": llm_called, "exposed_math_tool": exposed_math_tool},
    )


def agent_loop_forces_ui_preference_tool(ctx: RunContext) -> CaseResult:
    start = time.time()
    planner = import_module("plugins.arteta_agent.planner")
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    trace_mod = import_module("plugins.arteta_agent.trace")

    registry.clear_registry()
    agent_trace = trace_mod.new_trace("agent_registry")

    def ui_handler(ctx, target="", color="", bold=None, font_size="", font_scale=None):
        return "ui updated: {0} {1} {2} {3}".format(target, color, bold, font_size)

    registry.register_tool(registry.ToolSpec(
        name="update_ui_preference",
        description="update ui",
        parameters=UI_PREFERENCE_VERIFY_SCHEMA,
        handler=ui_handler,
        permission="safe_write",
    ))
    tool_ctx = context_mod.ToolContext(bot=None, event=None, user_id="verify-user", group_id="verify-group", extra={"agent_trace": agent_trace})
    original_call = planner.call_llm_with_tools
    llm_called = False

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        nonlocal llm_called
        llm_called = True
        return {"role": "assistant", "content": "model answered directly"}

    try:
        planner.call_llm_with_tools = fake_call
        result = asyncio.run(planner.run_agent_loop(
            [{"role": "user", "content": "下次 agent 调度的字样标红、加粗、放大"}],
            tool_ctx,
            "model",
            "key",
            max_rounds=2,
            trace=agent_trace,
        ))
    finally:
        planner.call_llm_with_tools = original_call

    tools = agent_trace.get("tools") or []
    if llm_called or result != "ui updated: agent_trace_title red True large" or not tools or tools[0].get("name") != "update_ui_preference" or tools[0].get("status") != "ok":
        return fail_result(
            "agent_loop",
            "forces_ui_preference_tool",
            "UI customization request did not force update_ui_preference",
            start,
            details={"result": result, "tools": tools, "llm_called": llm_called},
        )
    return pass_result(
        "agent_loop",
        "forces_ui_preference_tool",
        "UI customization requests force update_ui_preference and stay visible in trace",
        start,
        details={"result": result, "tools": tools, "llm_called": llm_called},
    )


def agent_loop_forces_reply_body_ui_preference_tool(ctx: RunContext) -> CaseResult:
    start = time.time()
    planner = import_module("plugins.arteta_agent.planner")
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    trace_mod = import_module("plugins.arteta_agent.trace")

    registry.clear_registry()
    agent_trace = trace_mod.new_trace("agent_registry")

    def ui_handler(ctx, target="", color="", bold=None, font_size="", font_scale=None):
        return "ui updated: {0} {1} {2} {3} {4}".format(target, color, bold, font_size, font_scale)

    registry.register_tool(registry.ToolSpec(
        name="update_ui_preference",
        description="update ui",
        parameters=UI_PREFERENCE_VERIFY_SCHEMA,
        handler=ui_handler,
        permission="safe_write",
    ))
    tool_ctx = context_mod.ToolContext(bot=None, event=None, user_id="verify-user", group_id="verify-group", extra={"agent_trace": agent_trace})
    original_call = planner.call_llm_with_tools
    llm_called = False

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        nonlocal llm_called
        llm_called = True
        return {"role": "assistant", "content": "model answered directly"}

    try:
        planner.call_llm_with_tools = fake_call
        result = asyncio.run(planner.run_agent_loop(
            [{"role": "user", "content": "下次回复文字标红、加粗、放大五倍"}],
            tool_ctx,
            "model",
            "key",
            max_rounds=2,
            trace=agent_trace,
        ))
    finally:
        planner.call_llm_with_tools = original_call

    tools = agent_trace.get("tools") or []
    if llm_called or result != "ui updated: reply_body red True  5.0" or not tools or tools[0].get("name") != "update_ui_preference" or tools[0].get("status") != "ok":
        return fail_result(
            "agent_loop",
            "forces_reply_body_ui_preference_tool",
            "Reply-body UI customization request did not force update_ui_preference",
            start,
            details={"result": result, "tools": tools, "llm_called": llm_called},
        )
    return pass_result(
        "agent_loop",
        "forces_reply_body_ui_preference_tool",
        "Reply-body UI customization requests force update_ui_preference with exact font_scale",
        start,
        details={"result": result, "tools": tools, "llm_called": llm_called},
    )


def agent_loop_lets_llm_choose_memory_for_yesterday_prediction_score(ctx: RunContext) -> CaseResult:
    start = time.time()
    planner = import_module("plugins.arteta_agent.planner")
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    trace_mod = import_module("plugins.arteta_agent.trace")

    registry.clear_registry()
    agent_trace = trace_mod.new_trace("agent_registry")

    def memory_handler(ctx, query=""):
        return "群记忆：昨天我预测这场比赛是 2-1。"

    def web_handler(ctx, claim="", preferred_sources="", max_results=5):
        raise AssertionError("memory recall should not be forced through web verification")

    registry.register_tool(registry.ToolSpec(
        name="query_group_memory",
        description="query group memory",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        handler=memory_handler,
        permission="safe_read",
    ))
    registry.register_tool(registry.ToolSpec(
        name="verify_recent_claim",
        description="verify recent claim",
        parameters=VERIFY_RECENT_CLAIM_VERIFY_SCHEMA,
        handler=web_handler,
        permission="safe_read",
    ))
    tool_ctx = context_mod.ToolContext(bot=None, event=None, user_id="verify-user", group_id="verify-group", extra={"agent_trace": agent_trace})
    original_call = planner.call_llm_with_tools
    calls = []

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-memory-1",
                    "type": "function",
                    "function": {
                        "name": "query_group_memory",
                        "arguments": json.dumps({"query": "昨天预测的这场比赛的比分"}, ensure_ascii=False),
                    },
                }],
            }
        return {"role": "assistant", "content": "我记得，昨天我预测的是 2-1。"}

    try:
        planner.call_llm_with_tools = fake_call
        result = asyncio.run(planner.run_agent_loop(
            [{"role": "user", "content": "塔子你还记得你昨天预测的这场比赛的比分吗"}],
            tool_ctx,
            "model",
            "key",
            max_rounds=3,
            trace=agent_trace,
        ))
    finally:
        planner.call_llm_with_tools = original_call

    tools = agent_trace.get("tools") or []
    used_web = any(item.get("name") == "verify_recent_claim" for item in tools)
    if result != "我记得，昨天我预测的是 2-1。" or len(calls) != 2 or not tools or tools[0].get("name") != "query_group_memory" or used_web:
        return fail_result(
            "agent_loop",
            "lets_llm_choose_memory_for_yesterday_prediction_score",
            "Memory-style score recall incorrectly used web verification or skipped memory",
            start,
            details={"result": result, "tools": tools, "calls": len(calls), "used_web": used_web},
        )
    return pass_result(
        "agent_loop",
        "lets_llm_choose_memory_for_yesterday_prediction_score",
        "Memory-style score recall stays in LLM-selected memory flow instead of forced web verification",
        start,
        details={"result": result, "tools": tools, "calls": len(calls)},
    )


def agent_loop_allows_llm_to_choose_web_verification_tool(ctx: RunContext) -> CaseResult:
    start = time.time()
    planner = import_module("plugins.arteta_agent.planner")
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    trace_mod = import_module("plugins.arteta_agent.trace")

    registry.clear_registry()
    agent_trace = trace_mod.new_trace("agent_registry")

    def web_handler(ctx, claim="", preferred_sources="", max_results=5):
        return "verified: {0}".format(claim)

    registry.register_tool(registry.ToolSpec(
        name="verify_recent_claim",
        description="verify recent claim",
        parameters=VERIFY_RECENT_CLAIM_VERIFY_SCHEMA,
        handler=web_handler,
        permission="safe_read",
    ))
    tool_ctx = context_mod.ToolContext(bot=None, event=None, user_id="verify-user", group_id="verify-group", extra={"agent_trace": agent_trace})
    original_call = planner.call_llm_with_tools
    calls = []

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-web-1",
                    "type": "function",
                    "function": {
                        "name": "verify_recent_claim",
                        "arguments": json.dumps({"claim": "2026 年阿森纳最新转会新闻"}, ensure_ascii=False),
                    },
                }],
            }
        return {"role": "assistant", "content": "查到的最新转会新闻已核验。"}

    try:
        planner.call_llm_with_tools = fake_call
        result = asyncio.run(planner.run_agent_loop(
            [{"role": "user", "content": "查一下 2026 年阿森纳最新转会新闻"}],
            tool_ctx,
            "model",
            "key",
            max_rounds=2,
            trace=agent_trace,
        ))
    finally:
        planner.call_llm_with_tools = original_call

    tools = agent_trace.get("tools") or []
    if result != "查到的最新转会新闻已核验。" or len(calls) != 2 or not tools or tools[0].get("name") != "verify_recent_claim" or tools[0].get("status") != "ok":
        return fail_result(
            "agent_loop",
            "allows_llm_to_choose_web_verification_tool",
            "LLM-chosen recent factual verification did not execute verify_recent_claim",
            start,
            details={"result": result, "tools": tools, "calls": len(calls)},
        )
    return pass_result(
        "agent_loop",
        "allows_llm_to_choose_web_verification_tool",
        "Recent factual questions can be verified when the LLM chooses verify_recent_claim",
        start,
        details={"result": result, "tools": tools, "calls": len(calls)},
    )


def agent_loop_continues_after_unavailable_web_verification(ctx: RunContext) -> CaseResult:
    start = time.time()
    planner = import_module("plugins.arteta_agent.planner")
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    trace_mod = import_module("plugins.arteta_agent.trace")

    registry.clear_registry()
    agent_trace = trace_mod.new_trace("agent_registry")

    def web_handler(ctx, claim="", preferred_sources="", max_results=5):
        return "未找到可靠网页来源，不能确认该说法。"

    registry.register_tool(registry.ToolSpec(
        name="verify_recent_claim",
        description="verify recent claim",
        parameters=VERIFY_RECENT_CLAIM_VERIFY_SCHEMA,
        handler=web_handler,
        permission="safe_read",
    ))
    tool_ctx = context_mod.ToolContext(bot=None, event=None, user_id="verify-user", group_id="verify-group", extra={"agent_trace": agent_trace})
    original_call = planner.call_llm_with_tools
    calls = []

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-web-1",
                    "type": "function",
                    "function": {
                        "name": "verify_recent_claim",
                        "arguments": json.dumps({"claim": "阿尔特塔喜欢高位逼抢"}, ensure_ascii=False),
                    },
                }],
            }
        return {"role": "assistant", "content": "我没核到可靠来源，所以不能确认；但会继续针对原问题回答。"}

    try:
        planner.call_llm_with_tools = fake_call
        result = asyncio.run(planner.run_agent_loop(
            [{"role": "user", "content": "帮我核一下阿尔特塔喜欢高位逼抢这个说法"}],
            tool_ctx,
            "model",
            "key",
            max_rounds=2,
            trace=agent_trace,
        ))
    finally:
        planner.call_llm_with_tools = original_call

    tools = agent_trace.get("tools") or []
    if (
        len(calls) != 2
        or not result.startswith("我没核到可靠来源")
        or not tools
        or tools[0].get("name") != "verify_recent_claim"
    ):
        return fail_result(
            "agent_loop",
            "continues_after_unavailable_web_verification",
            "Unavailable web verification did not return to answering the original question",
            start,
            details={"result": result, "tools": tools, "calls": len(calls)},
        )
    return pass_result(
        "agent_loop",
        "continues_after_unavailable_web_verification",
        "Unavailable web verification is passed back as context instead of becoming the final answer",
        start,
        details={"result": result, "tools": tools, "calls": len(calls)},
    )


def agent_loop_blocks_stale_answer_after_required_current_info_unavailable(ctx: RunContext) -> CaseResult:
    start = time.time()
    planner = import_module("plugins.arteta_agent.planner")
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    result_mod = import_module("plugins.arteta_agent.result")
    trace_mod = import_module("plugins.arteta_agent.trace")

    registry.clear_registry()
    agent_trace = trace_mod.new_trace("agent_registry")

    def web_handler(ctx, claim="", preferred_sources="", max_results=5):
        return result_mod.ToolResult(
            name="verify_recent_claim",
            permission="safe_read",
            status=result_mod.TOOL_STATUS_UNAVAILABLE,
            content="未找到可靠网页来源，不能确认该说法。",
            error_code="NoReliableSource",
        )

    registry.register_tool(registry.ToolSpec(
        name="verify_recent_claim",
        description="verify recent claim",
        parameters=VERIFY_RECENT_CLAIM_VERIFY_SCHEMA,
        handler=web_handler,
        permission="safe_read",
    ))
    tool_ctx = context_mod.ToolContext(bot=None, event=None, user_id="verify-user", group_id="verify-group", extra={"agent_trace": agent_trace})
    original_call = planner.call_llm_with_tools
    calls = []

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        calls.append(messages)
        return {"role": "assistant", "content": "根据我所知这笔转会已经完成。"}

    try:
        planner.call_llm_with_tools = fake_call
        result = asyncio.run(planner.run_agent_loop(
            [{"role": "user", "content": "查一下 2026 年阿森纳最新转会新闻"}],
            tool_ctx,
            "model",
            "key",
            max_rounds=2,
            trace=agent_trace,
        ))
    finally:
        planner.call_llm_with_tools = original_call

    tools = agent_trace.get("tools") or []
    if (
        calls
        or "无法核实" not in result
        or not tools
        or tools[0].get("name") != "verify_recent_claim"
        or tools[0].get("status") != "unavailable"
    ):
        return fail_result(
            "agent_loop",
            "blocks_stale_answer_after_required_current_info_unavailable",
            "Required current-information failure allowed stale model fallback or skipped unavailable status",
            start,
            details={"result": result, "tools": tools, "calls": len(calls)},
        )
    return pass_result(
        "agent_loop",
        "blocks_stale_answer_after_required_current_info_unavailable",
        "Required current-information failure stops before stale model fallback",
        start,
        details={"result": result, "tools": tools, "calls": len(calls)},
    )


def agent_loop_forces_explicit_memory_tool(ctx: RunContext) -> CaseResult:
    start = time.time()
    planner = import_module("plugins.arteta_agent.planner")
    registry = import_module("plugins.arteta_agent.registry")
    context_mod = import_module("plugins.arteta_agent.context")
    trace_mod = import_module("plugins.arteta_agent.trace")

    registry.clear_registry()
    agent_trace = trace_mod.new_trace("agent_registry")

    def memory_handler(ctx, memory=""):
        return "remembered: {0}".format(memory)

    registry.register_tool(registry.ToolSpec(
        name="remember_user_preference",
        description="remember",
        parameters=MEMORY_PREFERENCE_VERIFY_SCHEMA,
        handler=memory_handler,
        permission="safe_write",
    ))
    tool_ctx = context_mod.ToolContext(bot=None, event=None, user_id="verify-user", group_id="verify-group", extra={"agent_trace": agent_trace})
    original_call = planner.call_llm_with_tools
    llm_called = False

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        nonlocal llm_called
        llm_called = True
        return {"role": "assistant", "content": "model answered directly"}

    try:
        planner.call_llm_with_tools = fake_call
        result = asyncio.run(planner.run_agent_loop(
            [{"role": "user", "content": "以后我说开会就是提醒我看阿森纳赛程"}],
            tool_ctx,
            "model",
            "key",
            max_rounds=2,
            trace=agent_trace,
        ))
    finally:
        planner.call_llm_with_tools = original_call

    tools = agent_trace.get("tools") or []
    if llm_called or not result.startswith("remembered:") or not tools or tools[0].get("name") != "remember_user_preference" or tools[0].get("status") != "ok":
        return fail_result(
            "agent_loop",
            "forces_explicit_memory_tool",
            "Explicit future preference did not force remember_user_preference",
            start,
            details={"result": result, "tools": tools, "llm_called": llm_called},
        )
    return pass_result(
        "agent_loop",
        "forces_explicit_memory_tool",
        "Explicit future preferences force remember_user_preference and skip free-form answering",
        start,
        details={"result": result, "tools": tools, "llm_called": llm_called},
    )


# ---------------------------------------------------------------------------
# Personality manual acceptance suite
# ---------------------------------------------------------------------------


def personality_manual_evidence_complete(ctx: RunContext) -> CaseResult:
    start = time.time()
    validator = import_module("tools.validate_personality_manual_evidence")
    evidence_path = os.path.join(ctx.repo_root, "Docs", "dev", "personality-response-manual-evidence.md")
    result = validator.validate_manual_evidence(evidence_path, repo_root=ctx.repo_root)
    artifact = ctx.artifact_path("personality_manual", "manual_evidence_validation.json")
    write_text(artifact, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    details = {
        "sample_rows": result.get("sample_rows", 0),
        "before_after_rows": result.get("before_after_rows", 0),
        "category_counts": result.get("category_counts", {}),
        "errors": result.get("errors", []),
        "evidence": relative(evidence_path),
    }
    if result.get("ok"):
        return pass_result(
            "personality_manual",
            "manual_evidence_complete",
            "manual evidence complete",
            start,
            artifacts=[relative(artifact)],
            details=details,
        )
    return fail_result(
        "personality_manual",
        "manual_evidence_complete",
        "manual evidence incomplete: {0} validation error(s)".format(len(result.get("errors", []))),
        start,
        artifacts=[relative(artifact)],
        details=details,
    )


# ---------------------------------------------------------------------------
# Online suite
# ---------------------------------------------------------------------------


def online_image_api_config(ctx: RunContext) -> CaseResult:
    start = time.time()
    image = import_module("plugins.arteta_image")
    url = getattr(image, "IMAGE_API_URL", "")
    key = getattr(image, "IMAGE_API_KEY", "")
    model = getattr(image, "IMAGE_MODEL", "")
    details = {"image_api_url": url, "image_model": model, "has_key": bool(key)}
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return fail_result("online", "image_api_config", "Image API URL is not configured as HTTP(S)", start, details=details)
    if not key:
        return skip_result("online", "image_api_config", "Image API key is not configured; skipped connectivity to avoid unauthenticated request", start, details=details)
    try:
        import httpx
    except Exception as exc:
        return skip_result("online", "image_api_config", "httpx unavailable: %s" % exc, start, details=details)

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(url.rstrip("/") + "/v1/models", headers={"Authorization": "Bearer %s" % key})
        details["status_code"] = resp.status_code
        if resp.status_code in (200, 401, 403, 404, 405):
            return pass_result("online", "image_api_config", "Image API endpoint responded without generating media", start, details=details)
        return fail_result("online", "image_api_config", "Unexpected image API status %s" % resp.status_code, start, details=details)
    except Exception as exc:
        return fail_result("online", "image_api_config", "Connectivity check failed: %s" % exc, start, details=details)


def online_side_effects_gate(ctx: RunContext) -> CaseResult:
    start = time.time()
    if not ctx.args.allow_side_effects:
        return manual_result(
            "online",
            "side_effects_gate",
            "Side-effecting checks are gated; rerun with --allow-side-effects only for explicit manual validation",
            start,
        )
    return skip_result(
        "online",
        "side_effects_gate",
        "--allow-side-effects set, but this runner intentionally has no automated QQ side-effect cases yet",
        start,
    )


# ---------------------------------------------------------------------------
# Suite registry and execution
# ---------------------------------------------------------------------------


def build_registry() -> Dict[str, SuiteSpec]:
    registry = {
        "render": SuiteSpec(
            "render",
            "Rendering and image preprocessing checks",
            [
                ("template_exists", safe_case("render", "template_exists", render_template_exists)),
                ("text_to_tactical_board", safe_case("render", "text_to_tactical_board", render_text_to_tactical_board)),
                ("html_to_image", safe_case("render", "html_to_image", render_html_to_image)),
                ("quote_image_flow", safe_case("render", "quote_image_flow", render_quote_image_flow)),
            ],
        ),
        "memory": SuiteSpec(
            "memory",
            "SQLite, ChromaDB, and knowledge retrieval checks",
            [
                ("sqlite_open", safe_case("memory", "sqlite_open", memory_sqlite_open)),
                ("chromadb_init", safe_case("memory", "chromadb_init", memory_chromadb_init)),
                ("add_query_memory_roundtrip", safe_case("memory", "add_query_memory_roundtrip", memory_add_query_roundtrip)),
                ("knowledge_query", safe_case("memory", "knowledge_query", memory_knowledge_query)),
            ],
        ),
        "chat": SuiteSpec(
            "chat",
            "Local chat helper checks",
            [
                ("_should_search", safe_case("chat", "_should_search", chat_should_search)),
                ("_needs_fixtures", safe_case("chat", "_needs_fixtures", chat_needs_fixtures)),
                ("extract_favor_marker", safe_case("chat", "extract_favor_marker", chat_extract_favor_marker)),
                ("check_keyword_penalty", safe_case("chat", "check_keyword_penalty", chat_check_keyword_penalty)),
            ],
        ),
        "commands": SuiteSpec(
            "commands",
            "Plugin import and extracted command helper checks",
            [
                ("plugin_imports", safe_case("commands", "plugin_imports", commands_plugin_imports)),
                ("local_feature_health", safe_case("commands", "local_feature_health", commands_local_feature_health)),
            ],
        ),
        "football_news": SuiteSpec(
            "football_news",
            "Global football news SQLite and ChromaDB checks",
            [
                ("offline_roundtrip", safe_case("football_news", "offline_roundtrip", football_news_offline_roundtrip)),
            ],
        ),
        "agent_registry": SuiteSpec(
            "agent_registry",
            "Unified agent tool registry, permission, and executor checks",
            [
                ("registry_has_tools", safe_case("agent_registry", "registry_has_tools", agent_registry_has_tools)),
                ("phase2_read_tools", safe_case("agent_registry", "phase2_read_tools", agent_registry_phase2_read_tools)),
                ("web_access_offline", safe_case("agent_registry", "web_access_offline", agent_registry_web_access_offline)),
                ("phase3_read_tools", safe_case("agent_registry", "phase3_read_tools", agent_registry_phase3_read_tools)),
                ("phase3_safe_write_tools", safe_case("agent_registry", "phase3_safe_write_tools", agent_registry_phase3_safe_write_tools)),
                ("phase4_confirm_write_tools", safe_case("agent_registry", "phase4_confirm_write_tools", agent_registry_phase4_confirm_write_tools)),
                ("remember_user_preference_tool", safe_case("agent_registry", "remember_user_preference_tool", agent_registry_remember_user_preference_tool)),
                ("phase5_admin_tools", safe_case("agent_registry", "phase5_admin_tools", agent_registry_phase5_admin_tools)),
                ("duplicate_rejected", safe_case("agent_registry", "duplicate_rejected", agent_registry_duplicate_rejected)),
                ("permission_gates", safe_case("agent_registry", "permission_gates", agent_registry_permission_gates)),
                ("executor_error_paths", safe_case("agent_registry", "executor_error_paths", agent_registry_executor_error_paths)),
            ],
        ),
        "agent_permissions": SuiteSpec(
            "agent_permissions",
            "Agent tool permission, confirmation, pending action, and admin audit checks",
            [
                ("permission_gates", safe_case("agent_permissions", "permission_gates", agent_registry_permission_gates)),
                ("phase4_confirm_write_tools", safe_case("agent_permissions", "phase4_confirm_write_tools", agent_registry_phase4_confirm_write_tools)),
                ("phase5_admin_tools", safe_case("agent_permissions", "phase5_admin_tools", agent_registry_phase5_admin_tools)),
            ],
        ),
        "agent_loop": SuiteSpec(
            "agent_loop",
            "Agent executor error-path and observation-loop safety checks",
            [
                ("executor_error_paths", safe_case("agent_loop", "executor_error_paths", agent_registry_executor_error_paths)),
                ("activation_candidate_gates", safe_case("agent_loop", "activation_candidate_gates", agent_activation_candidate_gates)),
                ("activation_judge_fail_closed", safe_case("agent_loop", "activation_judge_fail_closed", agent_activation_judge_fail_closed)),
                ("forces_trace_tool", safe_case("agent_loop", "forces_trace_tool", agent_loop_forces_trace_tool)),
                ("does_not_force_mood_emoji_after_behavior_policy_query", safe_case("agent_loop", "does_not_force_mood_emoji_after_behavior_policy_query", agent_loop_does_not_force_mood_emoji_after_behavior_policy_query)),
                ("forces_math_tool", safe_case("agent_loop", "forces_math_tool", agent_loop_forces_math_tool)),
                ("does_not_expose_math_tool_for_scoreline_chat", safe_case("agent_loop", "does_not_expose_math_tool_for_scoreline_chat", agent_loop_does_not_expose_math_tool_for_scoreline_chat)),
                ("forces_ui_preference_tool", safe_case("agent_loop", "forces_ui_preference_tool", agent_loop_forces_ui_preference_tool)),
                ("forces_reply_body_ui_preference_tool", safe_case("agent_loop", "forces_reply_body_ui_preference_tool", agent_loop_forces_reply_body_ui_preference_tool)),
                ("lets_llm_choose_memory_for_yesterday_prediction_score", safe_case("agent_loop", "lets_llm_choose_memory_for_yesterday_prediction_score", agent_loop_lets_llm_choose_memory_for_yesterday_prediction_score)),
                ("allows_llm_to_choose_web_verification_tool", safe_case("agent_loop", "allows_llm_to_choose_web_verification_tool", agent_loop_allows_llm_to_choose_web_verification_tool)),
                ("continues_after_unavailable_web_verification", safe_case("agent_loop", "continues_after_unavailable_web_verification", agent_loop_continues_after_unavailable_web_verification)),
                ("blocks_stale_answer_after_required_current_info_unavailable", safe_case("agent_loop", "blocks_stale_answer_after_required_current_info_unavailable", agent_loop_blocks_stale_answer_after_required_current_info_unavailable)),
                ("forces_explicit_memory_tool", safe_case("agent_loop", "forces_explicit_memory_tool", agent_loop_forces_explicit_memory_tool)),
            ],
        ),
        "online": SuiteSpec(
            "online",
            "Opt-in online checks with safe side-effect gating",
            [
                ("image_api_config", safe_case("online", "image_api_config", online_image_api_config)),
                ("side_effects_gate", safe_case("online", "side_effects_gate", online_side_effects_gate)),
            ],
        ),
        "personality_manual": SuiteSpec(
            "personality_manual",
            "Manual personality response screenshot acceptance gate",
            [
                ("manual_evidence_complete", safe_case("personality_manual", "manual_evidence_complete", personality_manual_evidence_complete)),
            ],
        ),
    }
    core_cases = []
    for suite_name in ("render", "memory", "chat", "commands", "football_news", "agent_registry"):
        core_cases.extend(registry[suite_name].cases)
    registry["core"] = SuiteSpec("core", "Default local verification suite (render, memory, chat, commands)", core_cases)
    registry["all"] = SuiteSpec("all", "All offline verification suites", core_cases)
    return registry


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Arteta Bot developer feature verification suites.")
    parser.add_argument("--suite", action="append", dest="suites", help="Suite to run. Repeatable. Default: core")
    parser.add_argument("--online", action="store_true", help="Append the online suite unless already selected")
    parser.add_argument("--allow-side-effects", action="store_true", help="Allow explicitly gated side-effecting checks")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Base output directory for timestamped artifacts")
    parser.add_argument("--fail-fast", action="store_true", help="Stop on first failed case")
    parser.add_argument("--json-only", action="store_true", help="Only print final JSON report path and summary JSON")
    parser.add_argument("--list-suites", action="store_true", help="List available suites and cases, then exit")
    parser.add_argument("--case", action="append", dest="cases", help="Case name to run. Repeatable. Matches case name only, across selected suites")
    return parser.parse_args(argv)


def selected_suites(args: argparse.Namespace, registry: Dict[str, SuiteSpec]) -> List[str]:
    suites = list(args.suites or DEFAULT_SUITES)
    if args.online and "online" not in suites:
        suites.append("online")
    unknown = [suite for suite in suites if suite not in registry]
    if unknown:
        raise VerificationError("Unknown suite(s): %s" % ", ".join(unknown))
    return suites


def list_suites(registry: Dict[str, SuiteSpec]) -> Dict[str, Any]:
    return {
        name: {
            "description": spec.description,
            "cases": [case_name for case_name, _func in spec.cases],
        }
        for name, spec in sorted(registry.items())
    }


def create_context(args: argparse.Namespace) -> RunContext:
    base_output_dir = os.path.abspath(args.output_dir)
    run_dir = os.path.join(base_output_dir, now_timestamp())
    artifacts_dir = os.path.join(run_dir, "artifacts")
    ensure_dir(artifacts_dir)
    return RunContext(args=args, repo_root=REPO_ROOT, run_dir=run_dir, artifacts_dir=artifacts_dir)


def prepare_isolated_runtime(ctx: RunContext) -> None:
    runtime_dir = ctx.run_path("runtime")
    ensure_dir(runtime_dir)
    os.environ["ARTETA_DB_PATH"] = os.path.join(runtime_dir, "verification.db")
    os.environ["ARTETA_SWEARS_FILE"] = os.path.join(runtime_dir, "arteta_swears.json")



def iter_cases(suite_names: Iterable[str], registry: Dict[str, SuiteSpec], selected_case_names: Optional[List[str]]) -> Iterable[Tuple[str, str, Callable[[RunContext], CaseResult]]]:
    selected = set(selected_case_names or [])
    matched = set()
    for suite_name in suite_names:
        spec = registry[suite_name]
        for case_name, case_func in spec.cases:
            if selected and case_name not in selected:
                continue
            matched.add(case_name)
            yield suite_name, case_name, case_func
    if selected:
        missing = selected - matched
        if missing:
            raise VerificationError("Unknown or unselected case(s): %s" % ", ".join(sorted(missing)))


def summarize(results: List[CaseResult], started_at: str, ended_at: str, suite_names: List[str], ctx: RunContext) -> Dict[str, Any]:
    counts = {STATUS_PASS: 0, STATUS_FAIL: 0, STATUS_SKIP: 0, STATUS_MANUAL: 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return {
        "started_at": started_at,
        "ended_at": ended_at,
        "repo_root": ctx.repo_root,
        "run_dir": ctx.run_dir,
        "suites": suite_names,
        "counts": counts,
        "exit_code": 1 if counts.get(STATUS_FAIL, 0) else 0,
        "results": [result.to_dict() for result in results],
    }


def write_reports(ctx: RunContext, report: Dict[str, Any]) -> Tuple[str, str]:
    json_path = os.path.join(ctx.run_dir, "report.json")
    summary_path = os.path.join(ctx.run_dir, "summary.txt")
    write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    lines = []
    lines.append("Arteta Bot verification summary")
    lines.append("Started: %s" % report["started_at"])
    lines.append("Ended: %s" % report["ended_at"])
    lines.append("Suites: %s" % ", ".join(report["suites"]))
    counts = report["counts"]
    lines.append("Counts: passed=%s failed=%s skipped=%s manual_required=%s" % (
        counts.get(STATUS_PASS, 0),
        counts.get(STATUS_FAIL, 0),
        counts.get(STATUS_SKIP, 0),
        counts.get(STATUS_MANUAL, 0),
    ))
    lines.append("")
    for result in report["results"]:
        lines.append("[%s] %s/%s - %s" % (result["status"], result["suite"], result["case"], result["message"]))
        if result.get("artifacts"):
            lines.append("  artifacts: %s" % ", ".join(result["artifacts"]))
    write_text(summary_path, "\n".join(lines) + "\n")
    return json_path, summary_path


def print_human_result(result: CaseResult) -> None:
    print("[%s] %s/%s - %s" % (result.status, result.suite, result.case, result.message))
    for artifact in result.artifacts:
        print("  artifact: %s" % artifact)


def run(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    registry = build_registry()

    if args.list_suites:
        data = list_suites(registry)
        if args.json_only:
            print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            for name, spec in sorted(registry.items()):
                print("%s: %s" % (name, spec.description))
                for case_name, _func in spec.cases:
                    print("  - %s" % case_name)
        return 0

    try:
        suite_names = selected_suites(args, registry)
        ctx = create_context(args)
        prepare_isolated_runtime(ctx)
        started_at = datetime.now().isoformat(timespec="seconds")
        if not args.json_only:
            print("Run directory: %s" % ctx.run_dir)
            print("Suites: %s" % ", ".join(suite_names))

        results = []
        for _suite_name, _case_name, case_func in iter_cases(suite_names, registry, args.cases):
            result = case_func(ctx)
            results.append(result)
            if not args.json_only:
                print_human_result(result)
            if args.fail_fast and result.status in TERMINAL_FAILURE_STATUSES:
                break

        ended_at = datetime.now().isoformat(timespec="seconds")
        report = summarize(results, started_at, ended_at, suite_names, ctx)
        json_path, summary_path = write_reports(ctx, report)
        if args.json_only:
            print(json.dumps({"report": json_path, "summary": summary_path, "counts": report["counts"], "exit_code": report["exit_code"]}, ensure_ascii=False, sort_keys=True))
        else:
            print("Report: %s" % json_path)
            print("Summary: %s" % summary_path)
        return int(report["exit_code"])
    except VerificationError as exc:
        if args.json_only:
            print(json.dumps({"error": str(exc), "exit_code": 2}, ensure_ascii=False, sort_keys=True))
        else:
            print("ERROR: %s" % exc, file=sys.stderr)
        return 2


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
