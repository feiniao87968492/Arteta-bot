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
    if not (-80 <= heavy_score <= -40) or "滚" not in heavy_reason:
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
        "online": SuiteSpec(
            "online",
            "Opt-in online checks with safe side-effect gating",
            [
                ("image_api_config", safe_case("online", "image_api_config", online_image_api_config)),
                ("side_effects_gate", safe_case("online", "side_effects_gate", online_side_effects_gate)),
            ],
        ),
    }
    core_cases = []
    for suite_name in ("render", "memory", "chat", "commands"):
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
