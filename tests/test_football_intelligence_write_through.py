import asyncio
import inspect
import json
from pathlib import Path

from plugins.arteta_agent.context import ToolContext
from plugins.arteta_agent.result import TOOL_STATUS_ERROR, TOOL_STATUS_OK, ToolResult
from plugins.arteta_football_intelligence.storage import FootballNewsSQLiteStore


class RecordingChromaStore(object):
    def __init__(self):
        self.items = []

    def add_item(self, item):
        self.items.append(item)
        return "ok"


def make_context(**kwargs):
    data = {
        "bot": None,
        "event": None,
        "user_id": "user-1",
        "group_id": "group-1",
        "nickname": "Tester",
        "raw_message": "Arsenal Saka injury latest",
        "reply_text": "",
        "is_group": True,
        "is_admin": False,
        "request_id": "req-1",
        "extra": {},
    }
    data.update(kwargs)
    return ToolContext(**data)


def source_result(url="https://www.arsenal.com/news/saka-update"):
    return ToolResult(
        name="web_search",
        permission="safe_read",
        status=TOOL_STATUS_OK,
        content="visible text is not the write-through API",
        metadata={
            "tool": "web_search",
            "sources": [{
                "title": "Arsenal confirm Saka injury update",
                "url": url,
                "snippet": "Bukayo Saka returned to training after injury.",
                "published_time": "2026-05-23T12:30:00Z",
                "source_name": "Arsenal",
                "backend": "grok",
            }],
        },
    )


def test_write_through_ingests_structured_football_web_source(tmp_path):
    from plugins.arteta_football_intelligence.write_through import ingest_tool_observation

    sqlite_store = FootballNewsSQLiteStore(str(Path(tmp_path) / "news.db"))
    sqlite_store.initialize()
    chroma_store = RecordingChromaStore()

    result = asyncio.run(ingest_tool_observation(
        "web_search",
        source_result(),
        {"is_football": True, "query": "Saka injury", "request_id": "req-1"},
        sqlite_store=sqlite_store,
        chroma_store=chroma_store,
        now=1780000000,
    ))

    rows = sqlite_store.list_recent_items(days=90, now=1780000100)
    assert result.accepted == 1
    assert result.rejected == 0
    assert rows[0]["canonical_url"] == "https://www.arsenal.com/news/saka-update"
    assert rows[0]["event_type"] == "injury"
    assert rows[0]["index_status"] == "ready"
    assert chroma_store.items[0].title == "Arsenal confirm Saka injury update"


def test_write_through_rejects_visible_text_url_without_structured_metadata(tmp_path):
    from plugins.arteta_football_intelligence.write_through import ingest_tool_observation

    sqlite_store = FootballNewsSQLiteStore(str(Path(tmp_path) / "news.db"))
    sqlite_store.initialize()

    result = asyncio.run(ingest_tool_observation(
        "web_search",
        ToolResult(
            name="web_search",
            permission="safe_read",
            status=TOOL_STATUS_OK,
            content="Found https://www.arsenal.com/news/saka-update in visible text only.",
        ),
        {"is_football": True, "query": "Saka injury"},
        sqlite_store=sqlite_store,
        chroma_store=RecordingChromaStore(),
        now=1780000000,
    ))

    assert result.accepted == 0
    assert result.rejected == 1
    assert "no_structured_sources" in result.reason_codes
    assert sqlite_store.list_recent_items(days=90, now=1780000100) == []


def test_write_through_rejects_error_and_non_football_observations(tmp_path):
    from plugins.arteta_football_intelligence.write_through import ingest_tool_observation

    sqlite_store = FootballNewsSQLiteStore(str(Path(tmp_path) / "news.db"))
    sqlite_store.initialize()

    error_result = asyncio.run(ingest_tool_observation(
        "web_search",
        ToolResult(
            name="web_search",
            permission="safe_read",
            status=TOOL_STATUS_ERROR,
            content="search failed",
            metadata={"sources": [{"url": "https://www.arsenal.com/news/saka-update"}]},
        ),
        {"is_football": True, "query": "Saka injury"},
        sqlite_store=sqlite_store,
        chroma_store=RecordingChromaStore(),
        now=1780000000,
    ))
    non_football_result = asyncio.run(ingest_tool_observation(
        "web_search",
        source_result(),
        {"is_football": False, "query": "weather"},
        sqlite_store=sqlite_store,
        chroma_store=RecordingChromaStore(),
        now=1780000000,
    ))

    assert error_result.accepted == 0
    assert "tool_status_not_ok" in error_result.reason_codes
    assert non_football_result.accepted == 0
    assert "not_football_context" in non_football_result.reason_codes
    assert sqlite_store.list_recent_items(days=90, now=1780000100) == []


def test_write_through_queue_drains_enqueued_items():
    from plugins.arteta_football_intelligence.write_through import FootballWriteThroughQueue

    processed = []

    async def processor(tool_name, tool_result, query_context):
        processed.append((tool_name, tool_result.metadata["sources"][0]["url"], query_context["query"]))

    async def run_queue():
        queue = FootballWriteThroughQueue(processor=processor)
        await queue.enqueue("web_search", source_result(), {"is_football": True, "query": "Saka injury"})
        await queue.drain()

    asyncio.run(run_queue())

    assert processed == [("web_search", "https://www.arsenal.com/news/saka-update", "Saka injury")]


def test_runtime_observer_enqueues_only_successful_football_web_observations(monkeypatch):
    from plugins.arteta_agent.runtime import service
    from plugins.arteta_agent.runtime.state import AgentState
    from plugins.arteta_football_intelligence import write_through

    enqueued = []

    class FakeQueue(object):
        async def enqueue(self, tool_name, tool_result, query_context):
            enqueued.append((tool_name, tool_result, query_context))

    async def run_observer(tool_result, raw_message):
        monkeypatch.setenv("ARTETA_FOOTBALL_WRITE_THROUGH_ENABLED", "true")
        monkeypatch.setattr(write_through, "get_write_through_queue", lambda: FakeQueue())
        observer = service._observe_runtime_tool_result([])
        state = AgentState(
            messages=[{"role": "user", "content": raw_message}],
            ctx=make_context(raw_message=raw_message),
            allowed_permissions={"safe_read"},
            freshness_mode="required",
        )
        observed = observer(tool_result, state)
        if inspect.isawaitable(observed):
            await observed

    asyncio.run(run_observer(source_result(), "Arsenal Saka injury latest"))
    asyncio.run(run_observer(
        ToolResult(
            name="web_search",
            permission="safe_read",
            status=TOOL_STATUS_ERROR,
            content="failed",
            metadata={"sources": [{"url": "https://www.arsenal.com/news/saka-update"}]},
        ),
        "Arsenal Saka injury latest",
    ))
    asyncio.run(run_observer(source_result("https://example.com/weather"), "weather tomorrow"))

    assert len(enqueued) == 1
    tool_name, tool_result, query_context = enqueued[0]
    assert tool_name == "web_search"
    assert tool_result.metadata["sources"][0]["url"] == "https://www.arsenal.com/news/saka-update"
    assert query_context["is_football"] is True
    assert query_context["query"] == "Arsenal Saka injury latest"
