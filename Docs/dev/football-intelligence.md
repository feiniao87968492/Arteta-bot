# Football Intelligence

This document describes the football intelligence pipeline added for current football news, local-first factual answers, and write-through from verified web results.

## Runtime Shape

The compatibility entrypoint remains `plugins.arteta_football_news`. New implementation lives under `plugins/arteta_football_intelligence/`:

- `models.py`, `config.py`, `schema.py`: domain dataclasses, feature flags, SQLite migration.
- `storage.py`, `vector_index.py`: SQLite authority store and Chroma semantic index.
- `sources/`, `source_catalog.py`: legacy portal, Grok Bridge, and official fetch source adapters.
- `normalize.py`, `classification.py`, `entities.py`, `source_ranking.py`, `dedupe.py`, `clustering.py`: rule pipeline for URL/time normalization, event type, entities, source level, confidence, dedupe, and story IDs.
- `ingestion.py`, `orchestrator.py`, `scheduler.py`: sync pipeline and admin status helpers.
- `freshness_policy.py`, `query.py`: local current-knowledge query and fresh/stale/miss/conflict result shaping.
- `write_through.py`: structured web observation ingestion queue.

SQLite is the fact store. ChromaDB is only the semantic retrieval index and can be rebuilt from SQLite.

## Feature Flags

All new behavior is guarded by environment variables:

```text
ARTETA_FOOTBALL_INTELLIGENCE_ENABLED=true
ARTETA_FOOTBALL_KNOWLEDGE_FIRST=true
ARTETA_FOOTBALL_WRITE_THROUGH_ENABLED=true
ARTETA_FOOTBALL_DEEP_SYNC_CRON=15 6 * * *
ARTETA_FOOTBALL_INCREMENTAL_SYNC_CRON=15 18 * * *
ARTETA_FOOTBALL_SYNC_TIMEZONE=Asia/Shanghai
ARTETA_FOOTBALL_SYNC_MAX_CANDIDATES=160
ARTETA_FOOTBALL_SYNC_FETCH_CONCURRENCY=3
ARTETA_FOOTBALL_SYNC_RETENTION_DAYS=120
ARTETA_FOOTBALL_SOURCE_CONFIG=config/football_intelligence_sources.json
ARTETA_FOOTBALL_ENTITY_CONFIG=config/football_entities.json
ARTETA_FOOTBALL_TRANSFER_WINDOW_MODE=false
```

Rollback order:

```text
ARTETA_FOOTBALL_WRITE_THROUGH_ENABLED=false
ARTETA_FOOTBALL_KNOWLEDGE_FIRST=false
ARTETA_FOOTBALL_INTELLIGENCE_ENABLED=false
```

With all flags off, existing `search_football_news` and web-current-fact behavior remain available.

## Write-through Contract

Write-through only consumes `ToolResult.metadata`, never user-visible display text. Supported tools are:

- `grok_search`
- `web_search`
- `web_fetch`
- `fetch_x_post`
- `verify_recent_claim`

An observation is enqueued only when:

- the tool result status is `ok`;
- the runtime context is football-related;
- the context is a group context;
- metadata contains at least one valid HTTP(S) source URL.

No-URL summaries, permission/error outputs, private context, unrelated pages, and plain visible-text URLs are rejected before storage.

## Query Path

When `ARTETA_FOOTBALL_KNOWLEDGE_FIRST=true`, current football questions that are suitable for local news knowledge first call `query_current_football_knowledge` before web fallback. `fresh` local results satisfy the current-info gate. `stale`, `miss`, `conflict`, and unavailable results continue to web verification.

Excluded current-info categories still use dedicated/live web paths instead of the news DB: live score, live match events, current standings, exact lineup, explicit refresh requests, and user-supplied URL verification.

## Verification

Focused local commands:

```bash
python -m pytest tests -q -k football_intelligence
python -m pytest tests/test_arteta_agent_football_freshness.py tests/test_arteta_agent_planning.py tests/test_arteta_agent_runtime.py tests/test_arteta_agent_web_search.py -q
python -m pytest tests/test_arteta_agent_tool_result_protocol.py tests/test_football_intelligence_write_through.py -q
python -m pytest tests/test_arteta_football_news.py -q
```

Python 3.8 parse check:

```bash
python -c "import ast,pathlib; files=list(pathlib.Path('plugins/arteta_football_intelligence').rglob('*.py')); [ast.parse(p.read_text(encoding='utf-8'), filename=str(p), feature_version=(3,8)) for p in files]; print('Python 3.8 parse OK')"
```

Before enabling flags in production, back up `arsenal_data.db` and `chroma_db/`, deploy with all flags off, then enable sync, local-first, and write-through in separate steps.
