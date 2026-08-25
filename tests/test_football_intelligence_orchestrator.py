import asyncio
from pathlib import Path

from plugins.arteta_football_intelligence.config import load_source_config
from plugins.arteta_football_intelligence.entities import load_entity_catalog
from plugins.arteta_football_intelligence.orchestrator import FootballSyncOrchestrator
from plugins.arteta_football_intelligence.scheduler import format_sync_status
from plugins.arteta_football_intelligence.sources.base import FootballSourceRequest, RawFootballCandidate
from plugins.arteta_football_intelligence.storage import FootballNewsSQLiteStore


class StaticSource(object):
    def __init__(self, key, candidates=None, fail=False, delay=0):
        self.key = key
        self.candidates = candidates or []
        self.fail = fail
        self.delay = delay

    async def discover(self, request):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("source failed")
        return list(self.candidates)


class RecordingChromaStore(object):
    def __init__(self):
        self.items = []

    def add_item(self, item):
        self.items.append(item)
        return "ok"


def _candidate(title="Arsenal confirm Saka injury update"):
    return RawFootballCandidate(
        title=title,
        url="https://www.arsenal.com/news/saka-update",
        source_name="Arsenal",
        source_key="official",
        snippet="Bukayo Saka returned to training after injury.",
        published_time="2026-05-23T12:30:00Z",
        event_types=["injury"],
    )


def _orchestrator(tmp_path, sources):
    store = FootballNewsSQLiteStore(str(Path(tmp_path) / "news.db"))
    store.initialize()
    return FootballSyncOrchestrator(
        sqlite_store=store,
        chroma_store=RecordingChromaStore(),
        sources=sources,
        source_config=load_source_config(""),
        entity_catalog=load_entity_catalog(""),
    ), store


def test_orchestrator_records_sync_run_and_continues_after_single_source_failure(tmp_path):
    orchestrator, store = _orchestrator(tmp_path, [
        StaticSource("bad", fail=True),
        StaticSource("good", [_candidate()]),
    ])
    request = FootballSourceRequest(query="Arsenal injury latest", event_types=["injury"], max_candidates=5)

    result = asyncio.run(orchestrator.run_sync("manual", [request], now=1780000000))

    assert result.status == "success"
    assert result.failed_source_count == 1
    assert result.inserted_count == 1
    assert store.latest_sync_run()["status"] == "success"
    assert "最后成功时间" in format_sync_status(store)
    assert "新增/更新：1" in format_sync_status(store)


def test_orchestrator_rejects_concurrent_sync_run(tmp_path):
    orchestrator, _store = _orchestrator(tmp_path, [StaticSource("slow", [_candidate()], delay=0.05)])
    request = FootballSourceRequest(query="Arsenal injury latest", event_types=["injury"], max_candidates=5)

    async def run_both():
        first = asyncio.create_task(orchestrator.run_sync("manual", [request], now=1780000000))
        await asyncio.sleep(0.01)
        second = await orchestrator.run_sync("manual", [request], now=1780000000)
        return await first, second

    first, second = asyncio.run(run_both())

    assert first.status == "success"
    assert second.status == "skipped"
    assert "already running" in second.error_summary
