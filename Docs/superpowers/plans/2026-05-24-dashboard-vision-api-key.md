# Dashboard Vision API Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an editable `VISION_API_KEY` field to Dashboard Config and make vision fallback calls use it before `IMAGE_API_KEY`.

**Architecture:** Dashboard Config is driven by the backend `ENV_WHITELIST`, so adding the key there automatically creates the field. Runtime image recognition reads NoneBot config values at import time, so `plugins/arteta_chat.py` needs a small config read and fallback selection change.

**Tech Stack:** FastAPI, React/Vite/TypeScript, NoneBot2, pytest, npm build.

---

## File Structure

- Modify `dashboard/api/config.py`: add `VISION_API_KEY` to the environment whitelist.
- Modify `plugins/arteta_chat.py`: read `vision_api_key` and use it for vision fallback calls, falling back to `IMAGE_API_KEY` when empty.
- Modify `tests/dashboard/test_dashboard_config.py`: assert `VISION_API_KEY` is exposed by the whitelist.
- Modify `docs/dev/developer-dashboard.md`: document the new vision key entry in Dashboard Config.

---

### Task 1: Dashboard Config exposes VISION_API_KEY

**Files:**
- Modify: `tests/dashboard/test_dashboard_config.py`
- Modify: `dashboard/api/config.py`

- [ ] **Step 1: Write the failing test**

Add this import and test to `tests/dashboard/test_dashboard_config.py`:

```python
from dashboard.api.config import ENV_WHITELIST, get_settings, validate_public_settings


def test_dashboard_config_whitelist_includes_vision_api_key():
    assert "VISION_API_KEY" in ENV_WHITELIST
    assert "VISION_MODEL" in ENV_WHITELIST
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/dashboard/test_dashboard_config.py::test_dashboard_config_whitelist_includes_vision_api_key -v
```

Expected: FAIL because `VISION_API_KEY` is not in `ENV_WHITELIST`.

- [ ] **Step 3: Implement whitelist addition**

Change `dashboard/api/config.py` so the image/vision section is:

```python
    "IMAGE_API_KEY",
    "IMAGE_API_URL",
    "IMAGE_MODEL",
    "VISION_API_KEY",
    "VISION_MODEL",
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/dashboard/test_dashboard_config.py::test_dashboard_config_whitelist_includes_vision_api_key -v
```

Expected: PASS.

---

### Task 2: Runtime vision fallback uses VISION_API_KEY

**Files:**
- Modify: `plugins/arteta_chat.py`

- [ ] **Step 1: Add the config read**

Near the existing image config reads in `plugins/arteta_chat.py`, make the block:

```python
IMAGE_API_KEY = str(config.get("image_api_key", "")).strip('"\'')
IMAGE_API_URL = str(config.get("image_api_url", "https://api.duckcoding.ai")).strip('"\'')
VISION_API_KEY = str(config.get("vision_api_key", IMAGE_API_KEY)).strip('"\'')
VISION_MODEL = str(config.get("vision_model", "gpt-4o-mini")).strip('"\'')
```

- [ ] **Step 2: Use the vision key for fallback**

In `analyze_image_base64()`, change the fallback call to:

```python
    fallback = await _call_vision_api(IMAGE_API_URL, VISION_API_KEY or IMAGE_API_KEY, VISION_MODEL, data_url)
```

- [ ] **Step 3: Run a syntax check**

Run:

```bash
python -m py_compile plugins/arteta_chat.py
```

Expected: command exits successfully.

---

### Task 3: Document the Dashboard Config entry

**Files:**
- Modify: `docs/dev/developer-dashboard.md`

- [ ] **Step 1: Update docs wording**

Change the Config bullet in `docs/dev/developer-dashboard.md` to mention image and vision keys:

```markdown
- Config：脱敏查看白名单 API Key，并通过完整新值替换保存；包含算法、图片生成和图片识别（`VISION_API_KEY` / `VISION_MODEL`）相关配置。
```

- [ ] **Step 2: No doc build required**

This project does not define a docs build command for Markdown-only changes.

---

### Task 4: Local verification

**Files:**
- No source edits.

- [ ] **Step 1: Run dashboard tests**

Run:

```bash
python -m pytest tests/dashboard/test_dashboard_config.py tests/dashboard/test_env_service.py -v
```

Expected: PASS.

- [ ] **Step 2: Build frontend**

Run:

```bash
npm --prefix dashboard/web run build
```

Expected: PASS and Vite reports a successful production build.

---

### Task 5: ECS configuration and smoke test

**Files:**
- Remote ECS `.env` only.

- [ ] **Step 1: Connect to ECS using the existing deployment method**

Use the repository's deployment documentation and existing local SSH configuration for ECS access. Do not print the full API key in logs or chat.

- [ ] **Step 2: Update remote environment values**

Set these exact values in `/opt/arteta_bot/.env`:

```bash
VISION_API_KEY=<user-provided-key>
VISION_MODEL=mimo-v2.5-pro
```

- [ ] **Step 3: Restart services**

Run the existing production restart command from `CLAUDE.md`:

```bash
supervisorctl restart arteta_bot
```

If Dashboard runs under a separate supervisor program, restart that program too.

- [ ] **Step 4: Verify dashboard config endpoint**

Call the Dashboard config endpoint from the ECS host or through the configured access path:

```bash
curl -s http://127.0.0.1:8765/api/config/keys
```

Expected: response includes `VISION_API_KEY` with a masked value and `VISION_MODEL` with `mimo-v2.5-pro`.

- [ ] **Step 5: Verify vision path**

Send or trigger one image-recognition interaction through the bot and check logs for a successful vision response, not `[图片识别失败]` or `[图片识别异常]`.

---

## Self-Review

- Spec coverage: dashboard field, runtime key usage, docs, local verification, and ECS smoke test are all covered.
- Placeholder scan: no implementation placeholders; the secret is intentionally represented as `<user-provided-key>` to avoid writing the API key into the plan file.
- Type consistency: all config names match existing lowercase NoneBot config access and uppercase `.env` names.
