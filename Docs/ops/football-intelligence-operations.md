# Football Intelligence Operations

## Deployment Order

Deploy code first with all football intelligence flags absent or false:

```text
ARTETA_FOOTBALL_INTELLIGENCE_ENABLED=false
ARTETA_FOOTBALL_KNOWLEDGE_FIRST=false
ARTETA_FOOTBALL_WRITE_THROUGH_ENABLED=false
```

Then roll forward in stages:

1. Enable `ARTETA_FOOTBALL_INTELLIGENCE_ENABLED=true`.
2. Run a manual sync and inspect SQLite rows, sync status, and Chroma index status.
3. Enable `ARTETA_FOOTBALL_KNOWLEDGE_FIRST=true`.
4. Watch fresh/miss/stale routing in Agent trace/logs.
5. Enable `ARTETA_FOOTBALL_WRITE_THROUGH_ENABLED=true` last.

## Backup

Before first rollout:

```bash
mkdir -p /opt/arteta_bot/backups/football_intelligence_$(date +%Y%m%d%H%M%S)
cp -a /opt/arteta_bot/arsenal_data.db /opt/arteta_bot/backups/football_intelligence_$(date +%Y%m%d%H%M%S)/
tar -czf /opt/arteta_bot/backups/football_intelligence_$(date +%Y%m%d%H%M%S)/chroma_db.tar.gz -C /opt/arteta_bot chroma_db
```

Also back up:

- `bot.py`
- `plugins/arteta_agent/`
- `plugins/arteta_football_intelligence/`
- `plugins/arteta_football_news.py`
- `plugins/arteta_tools.py`
- `config/football_intelligence_sources.json`
- `config/football_entities.json`

## Admin Commands

The compatibility plugin registers admin-only commands for operational checks:

- `足球情报同步状态` or `/足球情报同步状态`
- `同步足球情报` or `/同步足球情报`
- `重试足球索引` or `/重试足球索引`
- `重建足球新闻索引` or `/重建足球新闻索引`

## Rollback

Turn off the flags in this order and restart `arteta_bot`:

```text
ARTETA_FOOTBALL_WRITE_THROUGH_ENABLED=false
ARTETA_FOOTBALL_KNOWLEDGE_FIRST=false
ARTETA_FOOTBALL_INTELLIGENCE_ENABLED=false
```

No database schema rollback is required. The migration only adds tables, columns, and indexes. Old code can keep reading the legacy columns.

If Chroma writes fail, SQLite facts are preserved with `index_status='failed'`. Use the retry/rebuild index command after fixing Chroma.

## Smoke Checks

After deployment:

```bash
cd /opt/arteta_bot
./venv/bin/python -m py_compile bot.py plugins/arteta_football_intelligence/write_through.py plugins/arteta_football_news.py
supervisorctl restart arteta_bot
supervisorctl status arteta_bot
tail -80 /opt/arteta_bot/logs/arteta_bot.log
grep -E '^ARTETA_FOOTBALL' .env.prod || true
```

Expected initial grey rollout state: service is running, no import tracebacks appear in logs, and no `ARTETA_FOOTBALL_*` flags are present unless intentionally enabled.
