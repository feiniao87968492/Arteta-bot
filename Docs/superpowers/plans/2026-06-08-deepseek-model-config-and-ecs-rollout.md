# DeepSeek Model Config and ECS Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded `deepseek-v4-flash` usage in Arteta Bot’s DeepSeek runtime paths with a unified `DEEPSEEK_MODEL` configuration that defaults to `deepseek-v4-pro`, expose it in Dashboard config, and deploy the change to ECS.

**Architecture:** Keep the existing split between the normal DeepSeek chat/tool pipeline and the separate `ALGO_MODEL` pipeline. Introduce `DEEPSEEK_MODEL` only where the project already uses DeepSeek, thread it through `plugins.arteta_tools.register_config(...)`, expose it via Dashboard’s `ENV_WHITELIST`, and make deployment/config docs match the new source of truth.

**Tech Stack:** Python 3.8, NoneBot2, OneBot V11, FastAPI, pytest, Bash/SSH, Markdown docs

---

## File Structure

- Create: `tests/test_deepseek_model_config.py` — source-level regression checks that runtime call sites, deploy config, and env template all moved to `DEEPSEEK_MODEL`.
- Modify: `plugins/arteta_tools.py` — add `DEEPSEEK_MODEL` runtime config, update `register_config(...)`, and use it in `call_deepseek_tool(...)`.
- Modify: `plugins/arteta_chat.py` — read `deepseek_model`, pass it into `register_tools_config(...)`, and use it in the profile-analysis DeepSeek request.
- Modify: `plugins/arteta_daily.py` — read `deepseek_model` and use it in summary generation.
- Modify: `plugins/arteta_weekly.py` — read `deepseek_model` and use it in weekly report generation.
- Modify: `plugins/arteta_standings.py` — read `deepseek_model` and use it in standings analysis.
- Modify: `dashboard/api/config.py` — add `DEEPSEEK_MODEL` to `ENV_WHITELIST`.
- Modify: `dashboard/api/services/bot_chat_service.py` — pass `deepseek_model` into `register_config(...)` for Dashboard bot chat.
- Modify: `.env.dev` — add `DEEPSEEK_MODEL=deepseek-v4-pro` so local dev has a visible sample.
- Modify: `deploy/deploy_ecs.sh` — add `DEEPSEEK_MODEL` variable handling and write it into `.env.prod`.
- Modify: `tests/test_arteta_tools.py` — add config-plumbing regression tests for `register_config(...)`.
- Modify: `tests/dashboard/test_dashboard_config.py` — assert `DEEPSEEK_MODEL` is in `ENV_WHITELIST`.
- Modify: `tests/dashboard/test_env_service.py` — assert `DEEPSEEK_MODEL` displays unmasked like other `MODEL` values.
- Modify: `tests/dashboard/test_bot_chat.py` — assert Dashboard bot chat passes `DEEPSEEK_MODEL` into `register_config(...)`.
- Modify: `Docs/dev/overview.md` — replace hardcoded DeepSeek model wording and add the new env var row.
- Modify: `Docs/dev/chat-llm.md` — update the tool loop/model/config sections to `DEEPSEEK_MODEL`.
- Modify: `Docs/dev/daily-summary.md` — update the summary model description and config section.
- Modify: `Docs/dev/weekly-news.md` — update the weekly report model description.
- Modify: `Docs/dev/developer-dashboard.md` — mention that Config now includes `DEEPSEEK_MODEL`.
- Modify: `Docs/ops/deployment.md` — include `DEEPSEEK_MODEL` in local/ECS/Docker deployment guidance.
- Modify: `Docs/ops/dashboard-public-deployment.md` — include `DEEPSEEK_MODEL` in the Dashboard config whitelist list.
- Modify: `Docs/ops/server-setup.md` — add the new env var to the server setup table.

---

### Task 1: Lock in regression coverage before changing runtime code

**Files:**
- Create: `tests/test_deepseek_model_config.py`
- Modify: `tests/test_arteta_tools.py`
- Modify: `tests/dashboard/test_dashboard_config.py`
- Modify: `tests/dashboard/test_env_service.py`
- Modify: `tests/dashboard/test_bot_chat.py`

- [ ] **Step 1: Write the failing regression tests**

Add a new file `tests/test_deepseek_model_config.py` to catch hardcoded model literals and missing deploy/env propagation.

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = [
    "plugins/arteta_chat.py",
    "plugins/arteta_tools.py",
    "plugins/arteta_daily.py",
    "plugins/arteta_weekly.py",
    "plugins/arteta_standings.py",
]


def _read(rel_path):
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_runtime_files_do_not_hardcode_deepseek_flash():
    for rel_path in RUNTIME_FILES:
        text = _read(rel_path)
        assert '"model": "deepseek-v4-flash"' not in text, rel_path


def test_chat_registers_tools_with_deepseek_model():
    text = _read("plugins/arteta_chat.py")
    assert "deepseek_model=DEEPSEEK_MODEL" in text


def test_deploy_files_expose_deepseek_model_default():
    deploy_text = _read("deploy/deploy_ecs.sh")
    env_dev_text = _read(".env.dev")

    assert 'DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-pro}"' in deploy_text
    assert "DEEPSEEK_MODEL=${DEEPSEEK_MODEL}" in deploy_text
    assert "DEEPSEEK_MODEL=deepseek-v4-pro" in env_dev_text
```

Extend `tests/test_arteta_tools.py` with a focused config test:

```python
def test_register_config_accepts_deepseek_model():
    arteta_tools.register_config(
        football_api_token="token",
        deepseek_api_key="deepseek-key",
        deepseek_model="deepseek-v4-pro",
        arsenal_id=57,
        has_web_search=False,
    )

    assert arteta_tools.DEEPSEEK_MODEL == "deepseek-v4-pro"
```

Extend `tests/dashboard/test_dashboard_config.py`:

```python
def test_dashboard_config_whitelist_includes_deepseek_model():
    assert "DEEPSEEK_MODEL" in ENV_WHITELIST
```

Extend `tests/dashboard/test_env_service.py` so `DEEPSEEK_MODEL` is treated as a visible model value rather than a secret:

```python
def test_model_and_url_values_are_not_masked(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ALGO_API_KEY=sk-secret123456\n"
        "ALGO_API_URL=https://www.boxying.com/v1/chat/completions\n"
        "ALGO_MODEL=gpt-5.5\n"
        "DEEPSEEK_MODEL=deepseek-v4-pro\n"
        "IMAGE_BASE_URL=https://image.example.com/v1\n",
        encoding="utf-8",
    )
    service = EnvService(
        str(env_file),
        ["ALGO_API_KEY", "ALGO_API_URL", "ALGO_MODEL", "DEEPSEEK_MODEL", "IMAGE_BASE_URL"],
    )

    values = {item["name"]: item for item in service.list_masked()}

    assert values["DEEPSEEK_MODEL"]["masked"] == "deepseek-v4-pro"
```

Extend `tests/dashboard/test_bot_chat.py` with a pass-through test for Dashboard bot chat config:

```python
import types


@pytest.mark.anyio
async def test_bot_chat_service_passes_deepseek_model_into_tool_config(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_KEY=unit-test-deepseek\n"
        "DEEPSEEK_MODEL=deepseek-v4-pro\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")

    captured = {}

    def fake_register_config(**kwargs):
        captured.update(kwargs)

    fake_memory_store = types.SimpleNamespace(initialize=lambda: None)

    monkeypatch.setattr("dashboard.api.services.bot_chat_service.register_config", fake_register_config)
    monkeypatch.setattr("dashboard.api.services.bot_chat_service.memory_store", fake_memory_store)

    from dashboard.api.services.bot_chat_service import BotChatService

    BotChatService()

    assert captured["deepseek_model"] == "deepseek-v4-pro"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/test_deepseek_model_config.py tests/test_arteta_tools.py tests/dashboard/test_dashboard_config.py tests/dashboard/test_env_service.py tests/dashboard/test_bot_chat.py -q
```

Expected: FAIL because runtime files still hardcode `deepseek-v4-flash`, `DEEPSEEK_MODEL` is missing from the whitelist, and Dashboard/tool config does not pass the new setting yet.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_deepseek_model_config.py tests/test_arteta_tools.py tests/dashboard/test_dashboard_config.py tests/dashboard/test_env_service.py tests/dashboard/test_bot_chat.py
git commit -m "test: add deepseek model config regression coverage"
```

---

### Task 2: Implement unified `DEEPSEEK_MODEL` runtime plumbing

**Files:**
- Modify: `plugins/arteta_tools.py`
- Modify: `plugins/arteta_chat.py`
- Modify: `plugins/arteta_daily.py`
- Modify: `plugins/arteta_weekly.py`
- Modify: `plugins/arteta_standings.py`
- Modify: `dashboard/api/config.py`
- Modify: `dashboard/api/services/bot_chat_service.py`
- Modify: `.env.dev`
- Modify: `deploy/deploy_ecs.sh`

- [ ] **Step 1: Update `plugins/arteta_tools.py` to store and use `DEEPSEEK_MODEL`**

Add a new global default, extend `register_config(...)`, and switch the API request to the config value.

```python
FOOTBALL_API_TOKEN = ""
DEEPSEEK_API_KEY = ""
DEEPSEEK_MODEL = "deepseek-v4-pro"
ARSENAL_ID = 57
HAS_WEB_SEARCH = False


def register_config(**kwargs):
    """在 bot 启动时注入全局配置"""
    global FOOTBALL_API_TOKEN, DEEPSEEK_API_KEY, DEEPSEEK_MODEL, ARSENAL_ID, HAS_WEB_SEARCH
    FOOTBALL_API_TOKEN = kwargs.get("football_api_token", "")
    DEEPSEEK_API_KEY = kwargs.get("deepseek_api_key", "")
    DEEPSEEK_MODEL = kwargs.get("deepseek_model", "deepseek-v4-pro")
    ARSENAL_ID = kwargs.get("arsenal_id", 57)
    HAS_WEB_SEARCH = kwargs.get("has_web_search", False)
```

Then update the request body:

```python
json={
    "model": DEEPSEEK_MODEL,
    "messages": messages,
    "tools": TOOLS,
    "tool_choice": "auto"
}
```

- [ ] **Step 2: Update `plugins/arteta_chat.py` to read and propagate `deepseek_model`**

Add the new config constant near `DEEPSEEK_API_KEY`:

```python
DEEPSEEK_API_KEY = str(config.get("deepseek_api_key", "")).strip('"\'')
DEEPSEEK_MODEL = str(config.get("deepseek_model", "deepseek-v4-pro")).strip('"\'')
IMAGE_API_KEY = str(config.get("image_api_key", "")).strip('"\'')
```

Pass it into tool registration:

```python
register_tools_config(
    football_api_token=FOOTBALL_API_TOKEN,
    deepseek_api_key=DEEPSEEK_API_KEY,
    deepseek_model=DEEPSEEK_MODEL,
    arsenal_id=ARSENAL_ID,
    has_web_search=HAS_WEB_SEARCH,
)
```

Switch the profile-analysis request:

```python
json={
    "model": DEEPSEEK_MODEL,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.3
}
```

- [ ] **Step 3: Update the other DeepSeek plugin call sites**

In `plugins/arteta_daily.py`, add the config constant and switch summary generation:

```python
DEEPSEEK_API_KEY = str(config.get("deepseek_api_key", "")).strip('"\'')
DEEPSEEK_MODEL = str(config.get("deepseek_model", "deepseek-v4-pro")).strip('"\'')
SUMMARY_ENABLED = str(config.get("daily_summary_enabled", "true")).lower() in ("true", "1", "yes")
```

```python
json={
    "model": DEEPSEEK_MODEL,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.7,
    "max_tokens": 1000,
}
```

In `plugins/arteta_weekly.py`, do the same:

```python
DEEPSEEK_API_KEY = str(config.get("deepseek_api_key", "")).strip('"\'')
DEEPSEEK_MODEL = str(config.get("deepseek_model", "deepseek-v4-pro")).strip('"\'')
WEEKLY_NEWS_ENABLED = str(config.get("weekly_news_enabled", "true")).lower() in ("true", "1", "yes")
```

```python
json={
    "model": DEEPSEEK_MODEL,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.7,
    "max_tokens": 2500,
}
```

In `plugins/arteta_standings.py`, add the constant and swap the model value:

```python
FOOTBALL_API_TOKEN = str(config.get("football_api_token", "da24063a4040404c89250b601f8994a2")).strip('"\'')
DEEPSEEK_API_KEY = str(config.get("deepseek_api_key", "")).strip('"\'')
DEEPSEEK_MODEL = str(config.get("deepseek_model", "deepseek-v4-pro")).strip('"\'')
ARSENAL_ID = 57
```

```python
json={
    "model": DEEPSEEK_MODEL,
    "messages": [
        {"role": "system", "content": ai_prompt},
        {"role": "user", "content": ai_data_str}
    ],
    "temperature": 0.7
}
```

- [ ] **Step 4: Expose `DEEPSEEK_MODEL` to Dashboard config and Dashboard bot chat**

In `dashboard/api/config.py`, extend the whitelist:

```python
ENV_WHITELIST = [
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "FOOTBALL_API_TOKEN",
    "ALGO_API_KEY",
    "ALGO_API_URL",
    "ALGO_MODEL",
    "IMAGE_API_KEY",
    "IMAGE_API_URL",
    "IMAGE_MODEL",
    "VISION_API_KEY",
    "VISION_API_URL",
    "VISION_MODEL",
]
```

In `dashboard/api/services/bot_chat_service.py`, pass the model through to the shared tool config:

```python
register_config(
    football_api_token=self._setting_value(env_values, "FOOTBALL_API_TOKEN"),
    deepseek_api_key=deepseek_api_key,
    deepseek_model=self._setting_value(env_values, "DEEPSEEK_MODEL") or "deepseek-v4-pro",
    arsenal_id=57,
    has_web_search=True,
)
```

- [ ] **Step 5: Add the new setting to local dev and ECS deploy config**

In `.env.dev`, add the visible default right after `DEEPSEEK_API_KEY`:

```dotenv
ENVIRONMENT=dev
DEEPSEEK_MODEL=deepseek-v4-pro
```

In `deploy/deploy_ecs.sh`, add the shell variable near the other config values:

```bash
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-pro}"
FOOTBALL_API_TOKEN="${FOOTBALL_API_TOKEN:-da24063a4040404c89250b601f8994a2}"
```

Then write it into `.env.prod`:

```bash
cat > "$BOT_DIR/.env.prod" << EOF
HOST=0.0.0.0
PORT=8088
DEBUG=false
SUPERUSERS=${SUPERUSERS}
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
DEEPSEEK_MODEL=${DEEPSEEK_MODEL}
COMMAND_START=["", "/"]
zhipu_api_key=""
FOOTBALL_API_TOKEN=${FOOTBALL_API_TOKEN}
BISON_USE_PIC=true
BISON_INIT_FILTER=true
EOF
```

- [ ] **Step 6: Run the targeted regression suite**

Run:

```bash
python -m pytest tests/test_deepseek_model_config.py tests/test_arteta_tools.py tests/dashboard/test_dashboard_config.py tests/dashboard/test_env_service.py tests/dashboard/test_bot_chat.py -q
```

Expected: PASS. The new tests should confirm that the runtime files no longer hardcode `deepseek-v4-flash`, the Dashboard exposes `DEEPSEEK_MODEL`, and tool registration receives the model value.

- [ ] **Step 7: Commit the runtime/config changes**

```bash
git add plugins/arteta_tools.py plugins/arteta_chat.py plugins/arteta_daily.py plugins/arteta_weekly.py plugins/arteta_standings.py dashboard/api/config.py dashboard/api/services/bot_chat_service.py .env.dev deploy/deploy_ecs.sh tests/test_deepseek_model_config.py tests/test_arteta_tools.py tests/dashboard/test_dashboard_config.py tests/dashboard/test_env_service.py tests/dashboard/test_bot_chat.py
git commit -m "feat: add configurable deepseek model"
```

---

### Task 3: Update developer and operations documentation

**Files:**
- Modify: `Docs/dev/overview.md`
- Modify: `Docs/dev/chat-llm.md`
- Modify: `Docs/dev/daily-summary.md`
- Modify: `Docs/dev/weekly-news.md`
- Modify: `Docs/dev/developer-dashboard.md`
- Modify: `Docs/ops/deployment.md`
- Modify: `Docs/ops/dashboard-public-deployment.md`
- Modify: `Docs/ops/server-setup.md`

- [ ] **Step 1: Update the developer architecture docs**

In `Docs/dev/overview.md`, replace the hardcoded DeepSeek model description and add the env var row:

```markdown
| LLM | DeepSeek API (`DEEPSEEK_MODEL`, 默认 `deepseek-v4-pro`) | AI 对话、Function Calling、周报生成 |
```

```markdown
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | — |
| `DEEPSEEK_MODEL` | DeepSeek 主链路模型 | `deepseek-v4-pro` |
| `ZHIPU_API_KEY` | 备用 API 密钥（暂无实际使用） | — |
```

In `Docs/dev/chat-llm.md`, update the tool-loop section and config snippet:

```markdown
- 使用 httpx.AsyncClient 调用 DeepSeek API (`https://api.deepseek.com/v1/chat/completions`)
- 模型：`DEEPSEEK_MODEL`（默认 `deepseek-v4-pro`）
- timeout：80s（单次请求）
```

```python
register_tools_config(
    football_api_token=FOOTBALL_API_TOKEN,
    deepseek_api_key=DEEPSEEK_API_KEY,
    deepseek_model=DEEPSEEK_MODEL,
    arsenal_id=ARSENAL_ID,
    has_web_search=HAS_WEB_SEARCH,
)
```

```markdown
| 主对话 + Function Calling | `https://api.deepseek.com/v1/chat/completions` | `DEEPSEEK_MODEL`（默认 `deepseek-v4-pro`） |
| 算法/技术问题 | `https://www.boxying.com/v1/chat/completions` | `gpt-5.5` |
| 人格画像分析 | `https://api.deepseek.com/v1/chat/completions` | `DEEPSEEK_MODEL`（默认 `deepseek-v4-pro`） |
```

- [ ] **Step 2: Update the feature-specific DeepSeek docs**

In `Docs/dev/daily-summary.md`, replace the model wording in both the flow and config section:

```markdown
  └─ 调用 DeepSeek API (`DEEPSEEK_MODEL`，默认 `deepseek-v4-pro`, temp=0.7, max_tokens=1000)
```

```markdown
- **模型**: `DEEPSEEK_MODEL`（默认 `deepseek-v4-pro`）, temperature=0.7, max_tokens=1000。
```

```markdown
| `deepseek_api_key` | str | "" | DeepSeek API 密钥 |
| `deepseek_model` | str | "deepseek-v4-pro" | DeepSeek 主链路模型 |
| `daily_summary_enabled` | str | "true" | 是否启用定时总结 |
```

In `Docs/dev/weekly-news.md`, update the weekly report model section:

```markdown
- 模型: `DEEPSEEK_MODEL`（默认 `deepseek-v4-pro`）
- API: `https://api.deepseek.com/v1/chat/completions`
- 参数: temperature 0.7, max_tokens 2500
```

- [ ] **Step 3: Update Dashboard and ops docs**

In `Docs/dev/developer-dashboard.md`, expand the Config bullet so DeepSeek model appears alongside the other model settings:

```markdown
- Config：脱敏查看白名单 API Key，并通过完整新值替换保存；包含 DeepSeek 主链路模型、算法、图片生成和图片识别（`DEEPSEEK_MODEL`、`VISION_API_KEY` / `VISION_API_URL` / `VISION_MODEL`）相关配置。
```

In `Docs/ops/dashboard-public-deployment.md`, add the new whitelist item:

```markdown
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_MODEL`
- `FOOTBALL_API_TOKEN`
```

In `Docs/ops/deployment.md`, add `DEEPSEEK_MODEL` wherever the file explains required env vars:

```markdown
# 编辑 .env，填入你的 API Key：
#   - DEEPSEEK_API_KEY：DeepSeek API 密钥
#   - DEEPSEEK_MODEL：DeepSeek 主链路模型（默认 deepseek-v4-pro）
#   - FOOTBALL_API_TOKEN：football-data.org API 令牌
#   - SUPERUSERS：管理员 QQ 号列表
```

```markdown
#   - DEEPSEEK_API_KEY：你的 DeepSeek API 密钥
#   - DEEPSEEK_MODEL：DeepSeek 主链路模型（默认 deepseek-v4-pro）
#   - FOOTBALL_API_TOKEN：football-data.org API 令牌
#   - SUPERUSERS：管理员 QQ 号列表
```

```dotenv
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_MODEL=deepseek-v4-pro
FOOTBALL_API_TOKEN=xxxxxxxxxxxxxxxx
SUPERUSERS=["2648955710"]
```

In `Docs/ops/server-setup.md`, add the row:

```markdown
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | `sk-xxxxxxxx` |
| `DEEPSEEK_MODEL` | DeepSeek 主链路模型 | `deepseek-v4-pro` |
| `FOOTBALL_API_TOKEN` | football-data.org API 令牌 | `xxxxxxxx` |
```

- [ ] **Step 4: Sanity-check the doc edits**

Run:

```bash
python -m pytest tests/test_deepseek_model_config.py tests/dashboard/test_dashboard_config.py tests/dashboard/test_env_service.py -q
```

Expected: PASS. This re-checks the config-facing contract after the docs/config text updates.

- [ ] **Step 5: Commit the documentation changes**

```bash
git add Docs/dev/overview.md Docs/dev/chat-llm.md Docs/dev/daily-summary.md Docs/dev/weekly-news.md Docs/dev/developer-dashboard.md Docs/ops/deployment.md Docs/ops/dashboard-public-deployment.md Docs/ops/server-setup.md
git commit -m "docs: document deepseek model config"
```

---

### Task 4: Verify locally and roll out to ECS

**Files:**
- Modify: none expected if verification passes cleanly
- Read/Upload: changed source, test, and doc files from Tasks 1-3

- [ ] **Step 1: Run the local regression suite**

Run:

```bash
python -m pytest tests/test_deepseek_model_config.py tests/test_arteta_tools.py tests/dashboard/test_dashboard_config.py tests/dashboard/test_env_service.py tests/dashboard/test_bot_chat.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the broader dashboard and bot-adjacent checks**

Run:

```bash
python -m pytest tests/dashboard -q
python -m pytest tests/test_arteta_tools.py tests/test_arteta_memory.py tests/test_arteta_chat_commands.py -q
```

Expected: PASS. If one of the broader suites fails for an unrelated pre-existing reason, stop and capture the exact failing test before deployment.

- [ ] **Step 3: Search the repo for leftover hardcoded runtime use of `deepseek-v4-flash`**

Run:

```bash
python - <<'PY'
from pathlib import Path
root = Path('.').resolve()
for rel in [
    'plugins/arteta_chat.py',
    'plugins/arteta_tools.py',
    'plugins/arteta_daily.py',
    'plugins/arteta_weekly.py',
    'plugins/arteta_standings.py',
]:
    text = (root / rel).read_text(encoding='utf-8')
    if 'deepseek-v4-flash' in text:
        raise SystemExit('leftover literal in %s' % rel)
print('runtime DeepSeek literals cleared')
PY
```

Expected: `runtime DeepSeek literals cleared`

- [ ] **Step 4: Prepare the ECS upload list**

Upload exactly these changed runtime/config/doc files to `/opt/arteta_bot/`:

```text
plugins/arteta_chat.py
plugins/arteta_tools.py
plugins/arteta_daily.py
plugins/arteta_weekly.py
plugins/arteta_standings.py
dashboard/api/config.py
dashboard/api/services/bot_chat_service.py
.env.dev
deploy/deploy_ecs.sh
Docs/dev/overview.md
Docs/dev/chat-llm.md
Docs/dev/daily-summary.md
Docs/dev/weekly-news.md
Docs/dev/developer-dashboard.md
Docs/ops/deployment.md
Docs/ops/dashboard-public-deployment.md
Docs/ops/server-setup.md
```

- [ ] **Step 5: SSH into ECS, back up config, and set `DEEPSEEK_MODEL`**

If you already use an SSH alias for this project, use that alias as the target; otherwise set the project’s normal `user@host` string in `ECS_TARGET` first.

```bash
export ECS_TARGET="arteta@your-ecs-host"
ssh "$ECS_TARGET" 'set -e; cd /opt/arteta_bot; cp .env.prod .env.prod.bak.$(date +%Y%m%d%H%M%S); supervisorctl status'
ssh "$ECS_TARGET" 'python3 - <<"PY"
from pathlib import Path
path = Path("/opt/arteta_bot/.env.prod")
text = path.read_text(encoding="utf-8") if path.exists() else ""
line = "DEEPSEEK_MODEL=deepseek-v4-pro"
if "DEEPSEEK_MODEL=" in text:
    rows = [line if row.startswith("DEEPSEEK_MODEL=") else row for row in text.splitlines()]
else:
    rows = text.splitlines()
    rows.append(line)
path.write_text("\n".join(rows).rstrip("\n") + "\n", encoding="utf-8")
PY'
```

Expected: `.env.prod` is backed up and contains `DEEPSEEK_MODEL=deepseek-v4-pro` exactly once.

- [ ] **Step 6: Upload changed files and restart services**

```bash
scp plugins/arteta_chat.py plugins/arteta_tools.py plugins/arteta_daily.py plugins/arteta_weekly.py plugins/arteta_standings.py "$ECS_TARGET:/opt/arteta_bot/plugins/"
scp dashboard/api/config.py dashboard/api/services/bot_chat_service.py "$ECS_TARGET:/opt/arteta_bot/dashboard/api/services/"
scp Docs/dev/overview.md Docs/dev/chat-llm.md Docs/dev/daily-summary.md Docs/dev/weekly-news.md Docs/dev/developer-dashboard.md "$ECS_TARGET:/opt/arteta_bot/Docs/dev/"
scp Docs/ops/deployment.md Docs/ops/dashboard-public-deployment.md Docs/ops/server-setup.md "$ECS_TARGET:/opt/arteta_bot/Docs/ops/"
ssh "$ECS_TARGET" 'cd /opt/arteta_bot && supervisorctl restart arteta_bot && supervisorctl restart arteta_dashboard && supervisorctl status arteta_bot arteta_dashboard'
```

Expected: both Supervisor processes report `RUNNING`.

- [ ] **Step 7: Tail logs for startup verification**

```bash
ssh "$ECS_TARGET" 'supervisorctl tail -100 arteta_bot'
ssh "$ECS_TARGET" 'supervisorctl tail -100 arteta_dashboard'
```

Expected: no import errors, no missing-config errors, and no crashes related to `DEEPSEEK_MODEL`.

- [ ] **Step 8: Commit the verification notes if any code changed during rollout**

If deployment required no additional code edits, skip the commit and only record the deployment result in the final report. If you had to patch tracked files during rollout, commit them immediately:

```bash
git add plugins/arteta_chat.py plugins/arteta_tools.py plugins/arteta_daily.py plugins/arteta_weekly.py plugins/arteta_standings.py dashboard/api/config.py dashboard/api/services/bot_chat_service.py .env.dev deploy/deploy_ecs.sh Docs/dev/overview.md Docs/dev/chat-llm.md Docs/dev/daily-summary.md Docs/dev/weekly-news.md Docs/dev/developer-dashboard.md Docs/ops/deployment.md Docs/ops/dashboard-public-deployment.md Docs/ops/server-setup.md tests/test_deepseek_model_config.py tests/test_arteta_tools.py tests/dashboard/test_dashboard_config.py tests/dashboard/test_env_service.py tests/dashboard/test_bot_chat.py
git commit -m "chore: finalize deepseek model rollout"
```

---

## Self-Review Checklist

- Spec coverage: This plan covers runtime call sites, shared tool config, Dashboard exposure, `.env.dev`, ECS deploy script, developer docs, ops docs, local verification, and ECS rollout.
- Placeholder scan: No `TODO`/`TBD` markers remain. The only environment-specific value is the SSH target, which is explicitly isolated in `ECS_TARGET` because the repository cannot know the operator’s real host.
- Type consistency: The plan uses one name everywhere — `DEEPSEEK_MODEL` in env/docs, `deepseek_model` in Python config lookups and `register_config(...)`, and `DEEPSEEK_MODEL` as the runtime module constant.
