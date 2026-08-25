import asyncio
import time
import uuid
from typing import List, Optional

from .ingestion import FootballIngestionService, candidate_to_item
from .models import FootballSyncRun


class FootballSyncOrchestrator(object):
    def __init__(
        self,
        sqlite_store,
        chroma_store,
        sources,
        source_config,
        entity_catalog,
    ):
        self.sqlite_store = sqlite_store
        self.chroma_store = chroma_store
        self.sources = list(sources or [])
        self.source_config = source_config
        self.entity_catalog = entity_catalog
        self._lock = asyncio.Lock()

    async def run_sync(
        self,
        job_type: str,
        requests: Optional[List[object]] = None,
        now: Optional[int] = None,
    ) -> FootballSyncRun:
        if self._lock.locked():
            return FootballSyncRun(
                run_id="",
                job_type=job_type,
                started_at=int(now or time.time()),
                finished_at=int(now or time.time()),
                status="skipped",
                error_summary="sync already running",
            )
        async with self._lock:
            started_at = int(now or time.time())
            run = self.sqlite_store.start_sync_run(
                job_type=job_type,
                run_id="%s_%s" % (job_type, uuid.uuid4().hex[:12]),
                now=started_at,
            )
            service = FootballIngestionService(self.sqlite_store, self.chroma_store)
            candidates = []
            request_list = list(requests or [])
            try:
                for request in request_list:
                    run.query_count += 1
                    for source in self.sources:
                        try:
                            discovered = await source.discover(request)
                            candidates.extend(discovered)
                        except Exception as exc:
                            run.failed_source_count += 1
                            run.error_summary = _append_error(run.error_summary, type(exc).__name__)
                run.fetched_count = len(candidates)
                for candidate in candidates:
                    item = candidate_to_item(candidate, self.source_config, self.entity_catalog, fetched_at=started_at)
                    result = service.ingest_item(item)
                    if result.duplicate:
                        run.duplicate_count += 1
                    elif result.inserted:
                        run.inserted_count += 1
                run.status = "success" if candidates or run.failed_source_count < max(1, len(self.sources)) else "failed"
            except Exception as exc:
                run.status = "failed"
                run.error_summary = _append_error(run.error_summary, "%s: %s" % (type(exc).__name__, exc))
            self.sqlite_store.finish_sync_run(run, now=int(now or time.time()))
            return run


def _append_error(existing: str, value: str) -> str:
    if not existing:
        return value
    if value in existing:
        return existing
    return (existing + "; " + value)[:300]
