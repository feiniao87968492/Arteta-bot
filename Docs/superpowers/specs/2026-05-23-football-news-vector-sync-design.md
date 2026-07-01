# Football News Vector Sync Design

## Goal

Add a global football news intelligence pipeline that fetches Chinese football news several times per day, prioritizes Premier League coverage, stores both individual news entries and daily digests in ChromaDB, and exposes the data to the chat LLM through Function Calling.

This feature is global project knowledge, not group chat memory. It must not pollute the existing `group_memories` collection used for per-group conversation history.

## Scope

In scope:

- Add an APScheduler-backed automatic football news sync job.
- Use fixed Chinese media sources rather than open-ended search aggregation.
- Cover Premier League first, plus Champions League, La Liga, Serie A, Bundesliga, Ligue 1, and Chinese Super League.
- Store normalized news records in SQLite for deduplication and auditability.
- Store individual news items and per-run daily digests in a separate ChromaDB collection.
- Add a Function Calling tool so the LLM can query global football news on demand.
- Add an administrator-only manual refresh command.
- Keep 90 days of football news history and clean older records.
- Add local verification and ECS live validation steps.

Out of scope:

- Pushing news automatically to every QQ group.
- Replacing the existing Arsenal weekly report module.
- Building a full crawler framework for arbitrary sites.
- Adding role-based access control beyond the existing admin-only command pattern.

## Architecture

Create a new plugin module:

```text
plugins/arteta_football_news.py
```

The module owns:

- Fixed Chinese source definitions.
- HTML fetching and parsing.
- News normalization and classification.
- SQLite deduplication records.
- ChromaDB writes to a dedicated collection.
- 90-day cleanup.
- APScheduler jobs.
- Admin manual refresh command.

Add a dedicated ChromaDB collection:

```text
football_news
```

Keep `plugins/arteta_memory.py` and the existing `group_memories` collection focused on group conversation memory. The news module may use the same ChromaDB persistent directory but must initialize and operate on its own collection.

Extend `plugins/arteta_tools.py` with a new tool:

```text
search_football_news
```

The LLM uses this tool when users ask about recent Premier League, Champions League, top-five-league, or Chinese Super League news.

## News Sources

The first implementation uses fixed Chinese sources only. Each source is configured with:

- `name`
- `url`
- `category`
- `max_items`
- parser function or parsing strategy

Target categories:

- `premier_league`
- `champions_league`
- `laliga`
- `serie_a`
- `bundesliga`
- `ligue1`
- `chinese_super_league`
- `other`

Premier League receives the largest quota. Champions League, other top-five leagues, and Chinese Super League receive smaller per-category quotas.

Source failures are isolated. If one source fails, the sync logs a warning and continues with the remaining sources. If no sources produce news, the job logs a warning and does not write an empty digest.

## News Item Model

Normalize all fetched records into a `NewsItem` shape:

```text
title
url
source
category
summary
published_at
fetched_at
content_hash
```

If the article body or summary cannot be fetched, the item remains valid as long as it has a title, source, category, and URL. The stored summary can fall back to a short generated text based on the title and source.

Deduplication uses URL first and normalized title/content hash second. Normalized titles remove repeated whitespace and common punctuation differences before comparison.

## SQLite Storage

Add a table such as:

```sql
CREATE TABLE IF NOT EXISTS football_news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chroma_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    published_at INTEGER NOT NULL,
    fetched_at INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(url)
);
```

SQLite is the source of truth for deduplication, cleanup, and reporting sync results. ChromaDB is the semantic search index.

## ChromaDB Storage

Use the `football_news` collection.

Write two document kinds:

1. `item`: one document per individual news item.
2. `daily_digest`: one document per successful sync digest, grouped by category.

Item document content includes:

```text
Category: <category>
Source: <source>
Title: <title>
Summary: <summary>
URL: <url>
Published At: <date>
Fetched At: <date>
```

Digest document content includes the sync date and a short category-by-category summary of the selected new items.

Metadata fields:

```text
kind: item | daily_digest
category
source
url
published_at
fetched_at
```

The sync stores each Chroma ID in SQLite so cleanup can delete matching vectors later.

## Retention and Cleanup

Keep 90 days of football news.

Each sync should:

1. Insert newly discovered items.
2. Write a digest only if at least one new item was inserted.
3. Delete SQLite rows older than 90 days.
4. Delete matching Chroma documents by stored `chroma_id`.

Chroma cleanup failures should log warnings but must not fail the whole sync after new records are written.

## Scheduling

Register two daily jobs with `nonebot_plugin_apscheduler`:

```text
football_news_morning: cron hour=3 minute=30
football_news_evening: cron hour=18 minute=30
```

Use `misfire_grace_time=300`, matching the existing daily and weekly jobs.

Add config switch:

```text
football_news_enabled=true
```

The default is enabled.

The job does not send messages to QQ groups. It only updates SQLite and ChromaDB.

## Manual Refresh Command

Add admin-only command aliases:

```text
刷新足球新闻
足球新闻刷新
```

The command runs the same sync pipeline as the scheduled jobs.

On success, it reports:

- number of sources attempted
- number of sources succeeded
- number of new items inserted
- number of duplicate items skipped
- whether a digest was written
- cleanup count or cleanup warning

On total failure, it reports a concise failure message and asks the operator to check logs.

## Function Calling Tool

Add `search_football_news` to `plugins/arteta_tools.py`.

Parameters:

```text
query: string
category: optional string
days: optional integer, default 14, max 90
```

Behavior:

- Query the `football_news` Chroma collection.
- Filter to `fetched_at` or `published_at` within the requested day window when possible.
- If `category` is supplied, filter by category metadata.
- Return a compact list of relevant results with title, source, date, summary, and URL.
- Include both `item` and `daily_digest` results, but prefer item-level hits for specific questions.

The LLM should call this tool for user questions about recent football news, Premier League news, Champions League news, top-five-league news, and Chinese Super League news.

## Data Flow

```text
APScheduler / admin command
  -> fetch fixed Chinese sources
  -> normalize NewsItem records
  -> apply category quotas and dedupe
  -> insert SQLite rows
  -> add item documents to football_news collection
  -> build and add daily_digest document
  -> delete rows/vectors older than 90 days

User asks football-news question
  -> run_tool_loop
  -> search_football_news tool
  -> query football_news collection
  -> LLM answers in Arteta voice using retrieved results
```

## Error Handling

- Single source failure: log warning and continue.
- Parser failure for one item: skip that item and continue.
- Summary/body fetch failure: keep the item with title-based fallback summary.
- SQLite insert duplicate: count as skipped duplicate.
- Chroma add failure for an item: log warning and do not mark that item as fully indexed.
- Digest generation failure: keep item records; skip digest.
- Cleanup failure: log warning; do not fail the sync.

## Testing and Verification

Local tests and verification:

- Unit-test title normalization and content hashing.
- Unit-test URL/title deduplication.
- Unit-test category quota selection.
- Unit-test Chroma document construction.
- Unit-test 90-day cleanup candidate selection.
- Add or extend `tools/verify_features.py` with a `football_news` suite.
- Use fixture HTML under `tests/fixtures/` so verification does not depend on live media sites.
- Use isolated `ARTETA_DB_PATH` and `ARTETA_CHROMA_DIR` for verification.
- Verify both item and digest documents can be inserted and queried.

ECS live validation after implementation:

- Deploy changed files to `/opt/arteta_bot/`.
- Restart `arteta_bot` via Supervisor.
- Check logs for plugin load, scheduler registration, and `football_news` collection initialization.
- Run the manual refresh command or invoke the sync function on ECS.
- Confirm Chinese sources fetch at least some items, with failures isolated per source.
- Confirm SQLite rows and Chroma item/digest documents are written.
- Confirm 90-day cleanup does not delete fresh records.
- Ask real QQ chat questions such as:
  - `塔子 最近英超有什么新闻`
  - `塔子 欧冠最近有什么消息`
  - `塔子 中超最近怎么样`
- Check logs to confirm `search_football_news` was called and answers used the new vector store.

## Documentation Updates

Update or add:

- `docs/dev/football-news.md`
- `docs/dev/overview.md`
- `docs/dev/developer-verification.md`
- `docs/user/commands.md` for the admin manual refresh command
- `CLAUDE.md` if the new module becomes part of the core architecture summary

## Open Decisions Resolved

- Storage scope: global football intelligence, not per-group memory.
- Source type: fixed Chinese sources.
- Storage granularity: individual items plus daily digest.
- Retention: 90 days.
- Chat access: Function Calling tool, not automatic prompt injection.
- Schedule: multiple daily updates, initially 03:30 and 18:30.
- Manual command: admin-only refresh command.
- Deployment validation: ECS live validation is required before considering the task complete.
