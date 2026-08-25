# Dashboard Prompt Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Dashboard Prompt 人设 module that edits file-backed bot prompts and lets ECS runtime use the same prompt registry.

**Architecture:** Add a shared prompt registry service under `dashboard/api/services/` with code defaults and safe JSON persistence. Mount a new FastAPI router under `/api/prompts`, add a React `PromptPage`, then wire bot prompt call sites to read overrides by stable keys while falling back to existing defaults.

**Tech Stack:** Python 3.8, FastAPI, Pydantic, pytest, React, TypeScript, Vite, Supervisor on ECS.

---

## File Structure

Create:

- `dashboard/api/services/prompt_service.py` — prompt defaults, JSON registry load/save, validation, atomic writes, runtime lookup.
- `dashboard/api/routers/prompts.py` — authenticated Dashboard API for listing, creating, updating, restoring, and deleting prompt entries.
- `dashboard/web/src/pages/PromptPage.tsx` — Prompt 人设 UI.
- `tests/dashboard/test_prompt_service.py` — unit tests for registry behavior and runtime fallback.
- `tests/dashboard/test_prompt_api.py` — API tests for Dashboard endpoints and readonly behavior.
- `config/prompts.json` — default local registry template.

Modify:

- `dashboard/api/config.py` — add `prompts_file` to settings and `ARTETA_PROMPTS_FILE` env support.
- `dashboard/api/main.py` — include prompt router.
- `dashboard/api/services/bot_chat_service.py` — read `arteta.dashboard_chat` and `algo.coach` from registry.
- `plugins/arteta_chat.py` — read `arteta.main`, `profile.analysis`, and algorithm prompt from registry.
- `plugins/arteta_daily.py` — read `daily.summary` from registry.
- `plugins/arteta_weekly.py` — read `weekly.report` from registry.
- `dashboard/web/src/App.tsx` — render `PromptPage`.
- `dashboard/web/src/components/Shell.tsx` — add navigation item.
- `dashboard/web/src/api/client.ts` — add `apiPut` helper.
- `dashboard/web/src/styles.css` — add prompt page layout styles.
- `deploy/deploy_ecs.sh` — create `/opt/arteta_bot/config`, preserve prompt registry, set `ARTETA_PROMPTS_FILE` in bot and dashboard environments.
- `tests/dashboard/test_dashboard_config.py` — assert `prompts_file` setting.
- `tests/dashboard/test_deploy_ecs_dashboard.py` — assert prompt registry deployment and Supervisor env.
- `docs/dev/developer-dashboard.md` — document Prompt 人设 module.
- `docs/ops/dashboard-public-deployment.md` — document `ARTETA_PROMPTS_FILE` and preservation behavior.

---

### Task 1: Settings and Prompt Service Tests

**Files:**
- Modify: `dashboard/api/config.py`
- Create: `tests/dashboard/test_prompt_service.py`
- Modify: `tests/dashboard/test_dashboard_config.py`

- [ ] **Step 1: Add failing settings test**

Append to `tests/dashboard/test_dashboard_config.py`:

```python
def test_dashboard_settings_include_prompts_file(monkeypatch, tmp_path):
    prompts_file = tmp_path / "prompts.json"

    monkeypatch.setenv("ARTETA_PROMPTS_FILE", str(prompts_file))

    settings = get_settings()

    assert settings.prompts_file == str(prompts_file)
```

- [ ] **Step 2: Add failing prompt service tests**

Create `tests/dashboard/test_prompt_service.py`:

```python
import json

import pytest

from dashboard.api.services.prompt_service import PromptService, get_prompt


def test_missing_registry_returns_builtin_defaults(tmp_path):
    service = PromptService(str(tmp_path / "missing.json"))

    entries = service.list_entries()

    keys = {entry["key"] for entry in entries}
    assert "arteta.main" in keys
    assert "daily.summary" in keys
    assert next(entry for entry in entries if entry["key"] == "arteta.main")["builtin"] is True


def test_registry_override_is_returned(tmp_path):
    registry = tmp_path / "prompts.json"
    registry.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "key": "arteta.main",
            "title": "主对话人设",
            "category": "主对话",
            "content": "新的塔子人设",
            "variables": [],
            "enabled": True,
            "builtin": True,
        }],
    }, ensure_ascii=False), encoding="utf-8")

    service = PromptService(str(registry))

    assert service.get_prompt("arteta.main", "默认人设") == "新的塔子人设"


def test_disabled_builtin_falls_back_to_default(tmp_path):
    registry = tmp_path / "prompts.json"
    registry.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "key": "arteta.main",
            "title": "主对话人设",
            "category": "主对话",
            "content": "禁用内容",
            "variables": [],
            "enabled": False,
            "builtin": True,
        }],
    }, ensure_ascii=False), encoding="utf-8")

    service = PromptService(str(registry))

    assert service.get_prompt("arteta.main", "默认人设") == "默认人设"


def test_create_update_delete_user_entry(tmp_path):
    service = PromptService(str(tmp_path / "prompts.json"))

    created = service.create_entry({
        "key": "custom.touchline",
        "title": "边线提醒",
        "category": "自定义",
        "content": "压上去！",
        "variables": [],
        "enabled": True,
    })
    assert created["builtin"] is False

    updated = service.update_entry("custom.touchline", {"content": "稳住阵型。", "enabled": True})
    assert updated["content"] == "稳住阵型。"

    service.delete_entry("custom.touchline")
    assert all(entry["key"] != "custom.touchline" for entry in service.list_entries())


def test_builtin_delete_is_rejected(tmp_path):
    service = PromptService(str(tmp_path / "prompts.json"))

    with pytest.raises(ValueError) as exc:
        service.delete_entry("arteta.main")

    assert "built-in" in str(exc.value)


def test_invalid_json_returns_defaults(tmp_path):
    registry = tmp_path / "prompts.json"
    registry.write_text("{ broken", encoding="utf-8")

    service = PromptService(str(registry))

    assert service.get_prompt("arteta.main", "默认人设") == "默认人设"
    assert any(entry["key"] == "arteta.main" for entry in service.list_entries())


def test_required_variable_validation(tmp_path):
    service = PromptService(str(tmp_path / "prompts.json"))
    service.update_entry("weekly.report", {"content": "新闻：{missing}", "enabled": True})

    assert service.get_prompt("weekly.report", "新闻：{articles}", variables={"articles": "A"}) == "新闻：A"


def test_module_get_prompt_uses_environment_path(monkeypatch, tmp_path):
    registry = tmp_path / "prompts.json"
    registry.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "key": "arteta.main",
            "title": "主对话人设",
            "category": "主对话",
            "content": "环境覆盖",
            "variables": [],
            "enabled": True,
            "builtin": True,
        }],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("ARTETA_PROMPTS_FILE", str(registry))

    assert get_prompt("arteta.main", "默认") == "环境覆盖"
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/dashboard/test_dashboard_config.py::test_dashboard_settings_include_prompts_file tests/dashboard/test_prompt_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'dashboard.api.services.prompt_service'` or missing `prompts_file`.

- [ ] **Step 4: Add setting field**

Modify `dashboard/api/config.py`:

```python
@dataclass
class DashboardSettings:
    host: str
    port: int
    admin_password: str
    secret_key: str
    allowed_origins: List[str]
    env_file: str
    readonly: bool
    public: bool
    db_path: str
    chroma_dir: str
    logs_dir: str
    docs_roots: List[str]
    audit_log_path: str
    sync_status_path: str
    web_dist: str
    prompts_file: str
```

In `get_settings()` add:

```python
        prompts_file=os.environ.get("ARTETA_PROMPTS_FILE", os.path.join(REPO_ROOT, "config", "prompts.json")),
```

- [ ] **Step 5: Implement prompt service**

Create `dashboard/api/services/prompt_service.py`:

```python
import json
import logging
import os
import re
import tempfile
from copy import deepcopy
from typing import Dict, List, Optional

from dashboard.api.config import REPO_ROOT, get_settings

logger = logging.getLogger(__name__)

DEFAULT_PROMPTS = [
    {
        "key": "arteta.main",
        "title": "主对话人设",
        "category": "主对话",
        "content": "",
        "variables": [],
        "enabled": True,
        "builtin": True,
    },
    {
        "key": "arteta.dashboard_chat",
        "title": "Dashboard 对话人设",
        "category": "Dashboard 对话",
        "content": "",
        "variables": [],
        "enabled": True,
        "builtin": True,
    },
    {
        "key": "profile.analysis",
        "title": "用户画像分析",
        "category": "画像分析",
        "content": "",
        "variables": ["current_profile", "count", "recent_messages", "nickname", "level", "favorability", "now", "total_count"],
        "enabled": True,
        "builtin": True,
    },
    {
        "key": "daily.summary",
        "title": "每日群聊总结",
        "category": "定时总结",
        "content": "",
        "variables": ["chat_log", "total_msgs", "active_users", "top_users_str"],
        "enabled": True,
        "builtin": True,
    },
    {
        "key": "weekly.report",
        "title": "阿森纳周报",
        "category": "周报",
        "content": "",
        "variables": ["articles"],
        "enabled": True,
        "builtin": True,
    },
    {
        "key": "algo.coach",
        "title": "算法/理科解题",
        "category": "理科解题",
        "content": "",
        "variables": [],
        "enabled": True,
        "builtin": True,
    },
]

_KEY_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
_FIELD_RE = re.compile(r"(?<!{){([a-zA-Z_][a-zA-Z0-9_]*)}(?!})")


def _default_map() -> Dict[str, Dict[str, object]]:
    return {entry["key"]: deepcopy(entry) for entry in DEFAULT_PROMPTS}


class PromptService:
    def __init__(self, prompts_file: str):
        self.prompts_file = prompts_file

    def _load_registry(self) -> Dict[str, object]:
        if not os.path.exists(self.prompts_file):
            return {"version": 1, "entries": []}
        try:
            with open(self.prompts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning("Prompt registry load failed: %s", exc)
            return {"version": 1, "entries": []}
        if not isinstance(data, dict) or not isinstance(data.get("entries", []), list):
            logger.warning("Prompt registry has invalid shape")
            return {"version": 1, "entries": []}
        return {"version": int(data.get("version", 1)), "entries": data.get("entries", [])}

    def _write_registry(self, entries: List[Dict[str, object]]) -> None:
        parent = os.path.dirname(self.prompts_file)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        payload = {"version": 1, "entries": entries}
        fd, temp_path = tempfile.mkstemp(prefix="prompts-", suffix=".json", dir=parent or None, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(temp_path, self.prompts_file)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    def _merged_entries(self) -> List[Dict[str, object]]:
        defaults = _default_map()
        merged = deepcopy(defaults)
        extras = []
        for raw in self._load_registry().get("entries", []):
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("key", "")).strip()
            if not key or not _KEY_RE.match(key):
                continue
            base = merged.get(key, {"key": key, "title": key, "category": "自定义", "content": "", "variables": [], "enabled": True, "builtin": False})
            item = deepcopy(base)
            for field in ["title", "category", "content", "variables", "enabled"]:
                if field in raw:
                    item[field] = raw[field]
            item["builtin"] = bool(base.get("builtin", False))
            if key in merged:
                merged[key] = item
            else:
                extras.append(item)
        result = list(merged.values()) + extras
        return sorted(result, key=lambda item: (str(item.get("category", "")), str(item.get("title", "")), str(item.get("key", ""))))

    def list_entries(self) -> List[Dict[str, object]]:
        return self._merged_entries()

    def _stored_entries(self) -> List[Dict[str, object]]:
        return [deepcopy(entry) for entry in self._merged_entries()]

    def _validate_key(self, key: str) -> str:
        clean = (key or "").strip()
        if not clean or not _KEY_RE.match(clean):
            raise ValueError("invalid prompt key")
        return clean

    def _normalize_patch(self, patch: Dict[str, object], existing: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        item = deepcopy(existing or {})
        for field in ["title", "category", "content"]:
            if field in patch:
                item[field] = str(patch.get(field, "")).strip() if field != "content" else str(patch.get(field, ""))
        if "variables" in patch:
            raw_variables = patch.get("variables") or []
            if not isinstance(raw_variables, list):
                raise ValueError("variables must be a list")
            item["variables"] = [str(value).strip() for value in raw_variables if str(value).strip()]
        if "enabled" in patch:
            item["enabled"] = bool(patch.get("enabled"))
        if not str(item.get("title", "")).strip():
            raise ValueError("title is required")
        if not str(item.get("category", "")).strip():
            raise ValueError("category is required")
        if item.get("enabled", True) and item.get("builtin") and not str(item.get("content", "")).strip():
            raise ValueError("enabled built-in prompt content is required")
        return item

    def _validate_variables(self, entry: Dict[str, object]) -> None:
        declared = set(str(value) for value in entry.get("variables", []))
        used = set(_FIELD_RE.findall(str(entry.get("content", ""))))
        missing = used - declared
        if missing and entry.get("builtin"):
            raise ValueError("undeclared variables: " + ", ".join(sorted(missing)))

    def create_entry(self, payload: Dict[str, object]) -> Dict[str, object]:
        key = self._validate_key(str(payload.get("key", "")))
        entries = self._stored_entries()
        if any(entry["key"] == key for entry in entries):
            raise ValueError("prompt key already exists")
        entry = {
            "key": key,
            "title": str(payload.get("title", key)).strip() or key,
            "category": str(payload.get("category", "自定义")).strip() or "自定义",
            "content": str(payload.get("content", "")),
            "variables": payload.get("variables", []),
            "enabled": bool(payload.get("enabled", True)),
            "builtin": False,
        }
        entry = self._normalize_patch(entry, entry)
        self._validate_variables(entry)
        entries.append(entry)
        self._write_registry(entries)
        return entry

    def update_entry(self, key: str, patch: Dict[str, object]) -> Dict[str, object]:
        clean = self._validate_key(key)
        entries = self._stored_entries()
        for index, entry in enumerate(entries):
            if entry["key"] == clean:
                updated = self._normalize_patch(patch, entry)
                updated["key"] = clean
                updated["builtin"] = bool(entry.get("builtin", False))
                self._validate_variables(updated)
                entries[index] = updated
                self._write_registry(entries)
                return updated
        raise ValueError("prompt key not found")

    def restore_entry(self, key: str) -> Dict[str, object]:
        clean = self._validate_key(key)
        defaults = _default_map()
        if clean not in defaults:
            raise ValueError("prompt key has no default")
        entries = self._stored_entries()
        restored = defaults[clean]
        for index, entry in enumerate(entries):
            if entry["key"] == clean:
                entries[index] = restored
                self._write_registry(entries)
                return restored
        entries.append(restored)
        self._write_registry(entries)
        return restored

    def delete_entry(self, key: str) -> None:
        clean = self._validate_key(key)
        entries = self._stored_entries()
        for entry in entries:
            if entry["key"] == clean and entry.get("builtin"):
                raise ValueError("built-in prompt cannot be deleted")
        next_entries = [entry for entry in entries if entry["key"] != clean]
        if len(next_entries) == len(entries):
            raise ValueError("prompt key not found")
        self._write_registry(next_entries)

    def get_prompt(self, key: str, default: str, variables: Optional[Dict[str, object]] = None) -> str:
        entries = {entry["key"]: entry for entry in self._merged_entries()}
        entry = entries.get(key)
        if not entry or not entry.get("enabled", True):
            template = default
        else:
            content = str(entry.get("content", ""))
            template = content if content.strip() else default
        if variables is None:
            return template
        try:
            return template.format(**variables)
        except Exception as exc:
            logger.warning("Prompt formatting failed for %s: %s", key, exc)
            return default.format(**variables)


def prompt_service() -> PromptService:
    return PromptService(get_settings().prompts_file)


def get_prompt(key: str, default: str, variables: Optional[Dict[str, object]] = None) -> str:
    settings = get_settings()
    return PromptService(settings.prompts_file).get_prompt(key, default, variables)
```

- [ ] **Step 6: Run tests and verify pass**

Run:

```powershell
python -m pytest tests/dashboard/test_dashboard_config.py::test_dashboard_settings_include_prompts_file tests/dashboard/test_prompt_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

If `git` is available, run:

```bash
git add dashboard/api/config.py dashboard/api/services/prompt_service.py tests/dashboard/test_dashboard_config.py tests/dashboard/test_prompt_service.py
git commit -m "feat: add dashboard prompt registry service"
```

---

### Task 2: Prompt API Router

**Files:**
- Create: `dashboard/api/routers/prompts.py`
- Modify: `dashboard/api/main.py`
- Create: `tests/dashboard/test_prompt_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/dashboard/test_prompt_api.py`:

```python
from fastapi.testclient import TestClient

from dashboard.api.main import create_app


def _client(monkeypatch, tmp_path, readonly=False):
    monkeypatch.setenv("ARTETA_PROMPTS_FILE", str(tmp_path / "prompts.json"))
    monkeypatch.setenv("DASHBOARD_READONLY", "true" if readonly else "false")
    monkeypatch.setenv("DASHBOARD_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(tmp_path / "dist"))
    return TestClient(create_app())


def test_prompt_api_lists_builtin_entries(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.get("/api/prompts")

    assert response.status_code == 200
    data = response.json()["data"]
    assert any(entry["key"] == "arteta.main" for entry in data)


def test_prompt_api_updates_builtin_entry(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.put("/api/prompts/arteta.main", json={"content": "新的主教练", "enabled": True})

    assert response.status_code == 200
    assert response.json()["data"]["content"] == "新的主教练"


def test_prompt_api_creates_and_deletes_custom_entry(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    create_response = client.post("/api/prompts", json={
        "key": "custom.note",
        "title": "自定义提醒",
        "category": "自定义",
        "content": "保持紧凑。",
        "variables": [],
        "enabled": True,
    })
    delete_response = client.delete("/api/prompts/custom.note")

    assert create_response.status_code == 200
    assert delete_response.status_code == 200


def test_prompt_api_rejects_builtin_delete(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.delete("/api/prompts/arteta.main")

    assert response.status_code == 400
    assert "built-in" in response.json()["error"]["message"]


def test_prompt_api_blocks_writes_in_readonly(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, readonly=True)

    response = client.put("/api/prompts/arteta.main", json={"content": "readonly", "enabled": True})

    assert response.status_code == 403
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/dashboard/test_prompt_api.py -q
```

Expected: FAIL with 404 for `/api/prompts` or import failure.

- [ ] **Step 3: Implement router**

Create `dashboard/api/routers/prompts.py`:

```python
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.audit_service import AuditService
from dashboard.api.services.prompt_service import PromptService

router = APIRouter(prefix="/api/prompts", tags=["prompts"], dependencies=[Depends(require_auth)])


class PromptEntryRequest(BaseModel):
    key: str = ""
    title: str = ""
    category: str = ""
    content: str = ""
    variables: List[str] = []
    enabled: bool = True


class PromptUpdateRequest(BaseModel):
    title: str = ""
    category: str = ""
    content: str = ""
    variables: List[str] = []
    enabled: bool = True


def _service() -> PromptService:
    return PromptService(get_settings().prompts_file)


def _ensure_writable():
    if get_settings().readonly:
        raise HTTPException(status_code=403, detail="readonly mode")


@router.get("")
def list_prompts():
    return ok(_service().list_entries())


@router.post("")
def create_prompt(request: PromptEntryRequest):
    _ensure_writable()
    settings = get_settings()
    audit = AuditService(settings.audit_log_path)
    try:
        entry = _service().create_entry(request.dict())
    except ValueError as exc:
        audit.record("prompts.create", request.key, "rejected")
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record("prompts.create", entry["key"], "ok")
    return ok(entry)


@router.put("/{key}")
def update_prompt(key: str, request: PromptUpdateRequest):
    _ensure_writable()
    settings = get_settings()
    audit = AuditService(settings.audit_log_path)
    try:
        entry = _service().update_entry(key, request.dict())
    except ValueError as exc:
        audit.record("prompts.update", key, "rejected")
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record("prompts.update", key, "ok")
    return ok(entry)


@router.post("/{key}/restore")
def restore_prompt(key: str):
    _ensure_writable()
    settings = get_settings()
    audit = AuditService(settings.audit_log_path)
    try:
        entry = _service().restore_entry(key)
    except ValueError as exc:
        audit.record("prompts.restore", key, "rejected")
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record("prompts.restore", key, "ok")
    return ok(entry)


@router.delete("/{key}")
def delete_prompt(key: str):
    _ensure_writable()
    settings = get_settings()
    audit = AuditService(settings.audit_log_path)
    try:
        _service().delete_entry(key)
    except ValueError as exc:
        audit.record("prompts.delete", key, "rejected")
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record("prompts.delete", key, "ok")
    return ok({"key": key})
```

- [ ] **Step 4: Mount router**

Modify imports in `dashboard/api/main.py`:

```python
from dashboard.api.routers import auth, bot_chat, config, docs, groups, logs, memories, overview, prompts, verify
```

Add before overview or after memories:

```python
    app.include_router(prompts.router)
```

- [ ] **Step 5: Run API tests**

Run:

```powershell
python -m pytest tests/dashboard/test_prompt_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dashboard/api/main.py dashboard/api/routers/prompts.py tests/dashboard/test_prompt_api.py
git commit -m "feat: expose prompt registry dashboard api"
```

---

### Task 3: Runtime Prompt Integration

**Files:**
- Modify: `dashboard/api/services/bot_chat_service.py`
- Modify: `plugins/arteta_chat.py`
- Modify: `plugins/arteta_daily.py`
- Modify: `plugins/arteta_weekly.py`
- Modify: `tests/dashboard/test_prompt_service.py`

- [ ] **Step 1: Add runtime integration tests for formatted fallback**

Append to `tests/dashboard/test_prompt_service.py`:

```python
def test_get_prompt_formats_valid_override(tmp_path):
    service = PromptService(str(tmp_path / "prompts.json"))
    service.update_entry("weekly.report", {"content": "本周：{articles}", "enabled": True})

    assert service.get_prompt("weekly.report", "默认：{articles}", variables={"articles": "新闻"}) == "本周：新闻"
```

- [ ] **Step 2: Run focused tests**

Run:

```powershell
python -m pytest tests/dashboard/test_prompt_service.py::test_get_prompt_formats_valid_override -q
```

Expected: PASS if Task 1 implementation already supports formatting.

- [ ] **Step 3: Wire Dashboard chat prompt**

In `dashboard/api/services/bot_chat_service.py`, add import:

```python
from dashboard.api.services.prompt_service import get_prompt
```

Keep existing `ARTETA_PROMPT` as the default constant. In `_build_messages`, replace:

```python
        system = (
            f"{ARTETA_PROMPT}\n\n"
            f"【Dashboard 对话调试】：这是开发者后台里的网页对话，不是 QQ 群消息。\n"
            f"当前时间：{current_time}\n群号：{group_id}\n"
            f"当前提问球员：{nickname}，QQ/用户ID：{user_id}，身份：{level}，当前信任度：{favor}。"
        )
```

with:

```python
        persona = get_prompt("arteta.dashboard_chat", ARTETA_PROMPT)
        system = (
            f"{persona}\n\n"
            f"【Dashboard 对话调试】：这是开发者后台里的网页对话，不是 QQ 群消息。\n"
            f"当前时间：{current_time}\n群号：{group_id}\n"
            f"当前提问球员：{nickname}，QQ/用户ID：{user_id}，身份：{level}，当前信任度：{favor}。"
        )
```

In `_reply_algo`, replace the inline `algo_prompt = (` block with:

```python
            default_algo_prompt = (
                "【技术指导】对方提交了技术问题，用教练指导球员口头说话的方式解答。\n"
                "【数学公式硬性规定】短公式/行内公式用单个 $ 包裹（如 $f(x) = x^2$），"
                "长公式/独立公式用双 $$ 包裹（如 $$\\int_a^b f(x)dx$$、$$\\frac{{dy}}{{dx}}$$）。"
                "这是死命令，不遵守会让球员看不懂战术板！\n"
                "【代码硬性规定】如果涉及代码，用 ``` 代码块包裹展示。\n"
                "绝对不要加小标题和列表符：\n"
            )
            algo_prompt = get_prompt("algo.coach", default_algo_prompt) + raw_text
```

- [ ] **Step 4: Wire main chat prompts**

In `plugins/arteta_chat.py`, add import near other dashboard-safe imports:

```python
from dashboard.api.services.prompt_service import get_prompt
```

In `process_chat`, replace:

```python
        f"{ARTETA_PROMPT}\n\n"
```

with:

```python
        f"{get_prompt('arteta.main', ARTETA_PROMPT)}\n\n"
```

In `update_user_profile` where `PROFILE_ANALYSIS_PROMPT.format(...)` is called, replace with:

```python
    prompt = get_prompt(
        "profile.analysis",
        PROFILE_ANALYSIS_PROMPT,
        variables={
            "current_profile": current_profile,
            "count": len(rows),
            "recent_messages": recent_messages,
            "nickname": nickname,
            "level": level,
            "favorability": favorability,
            "now": int(time.time()),
            "total_count": total_count,
        },
    )
```

Use the exact variable names already present in the surrounding function. If a local name differs, map it to the same placeholder value used by the existing `.format(...)` call.

In algorithm handling near `algo_prompt = (`, keep the existing default string in `default_algo_prompt`, then use:

```python
    algo_prompt = get_prompt("algo.coach", default_algo_prompt)
```

- [ ] **Step 5: Wire daily summary**

In `plugins/arteta_daily.py`, add:

```python
from dashboard.api.services.prompt_service import get_prompt
```

Replace:

```python
    prompt = SUMMARY_PROMPT.format(
        chat_log=chat_log[-4000:],
        total_msgs=total_msgs,
        active_users=active_users,
        top_users_str=top_users_str,
    )
```

with:

```python
    prompt = get_prompt(
        "daily.summary",
        SUMMARY_PROMPT,
        variables={
            "chat_log": chat_log[-4000:],
            "total_msgs": total_msgs,
            "active_users": active_users,
            "top_users_str": top_users_str,
        },
    )
```

- [ ] **Step 6: Wire weekly report**

In `plugins/arteta_weekly.py`, add:

```python
from dashboard.api.services.prompt_service import get_prompt
```

Replace:

```python
    prompt = WEEKLY_PROMPT.format(articles=articles_text)
```

with:

```python
    prompt = get_prompt("weekly.report", WEEKLY_PROMPT, variables={"articles": articles_text})
```

- [ ] **Step 7: Run targeted tests**

Run:

```powershell
python -m pytest tests/dashboard/test_prompt_service.py tests/dashboard/test_bot_chat.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add dashboard/api/services/bot_chat_service.py plugins/arteta_chat.py plugins/arteta_daily.py plugins/arteta_weekly.py tests/dashboard/test_prompt_service.py
git commit -m "feat: load bot prompts from registry"
```

---

### Task 4: Default Registry File

**Files:**
- Create: `config/prompts.json`
- Modify: `tests/dashboard/test_prompt_service.py`

- [ ] **Step 1: Create default registry file**

Create `config/prompts.json`:

```json
{
  "version": 1,
  "entries": [
    {
      "key": "arteta.main",
      "title": "主对话人设",
      "category": "主对话",
      "content": "",
      "variables": [],
      "enabled": false,
      "builtin": true
    },
    {
      "key": "arteta.dashboard_chat",
      "title": "Dashboard 对话人设",
      "category": "Dashboard 对话",
      "content": "",
      "variables": [],
      "enabled": false,
      "builtin": true
    },
    {
      "key": "profile.analysis",
      "title": "用户画像分析",
      "category": "画像分析",
      "content": "",
      "variables": ["current_profile", "count", "recent_messages", "nickname", "level", "favorability", "now", "total_count"],
      "enabled": false,
      "builtin": true
    },
    {
      "key": "daily.summary",
      "title": "每日群聊总结",
      "category": "定时总结",
      "content": "",
      "variables": ["chat_log", "total_msgs", "active_users", "top_users_str"],
      "enabled": false,
      "builtin": true
    },
    {
      "key": "weekly.report",
      "title": "阿森纳周报",
      "category": "周报",
      "content": "",
      "variables": ["articles"],
      "enabled": false,
      "builtin": true
    },
    {
      "key": "algo.coach",
      "title": "算法/理科解题",
      "category": "理科解题",
      "content": "",
      "variables": [],
      "enabled": false,
      "builtin": true
    }
  ]
}
```

- [ ] **Step 2: Add test that template is valid JSON**

Append to `tests/dashboard/test_prompt_service.py`:

```python
def test_default_config_prompts_json_is_valid():
    service = PromptService("config/prompts.json")

    keys = {entry["key"] for entry in service.list_entries()}

    assert "arteta.main" in keys
    assert "algo.coach" in keys
```

- [ ] **Step 3: Run test**

Run:

```powershell
python -m pytest tests/dashboard/test_prompt_service.py::test_default_config_prompts_json_is_valid -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add config/prompts.json tests/dashboard/test_prompt_service.py
git commit -m "feat: add default prompt registry template"
```

---

### Task 5: Prompt Frontend Page

**Files:**
- Create: `dashboard/web/src/pages/PromptPage.tsx`
- Modify: `dashboard/web/src/api/client.ts`
- Modify: `dashboard/web/src/App.tsx`
- Modify: `dashboard/web/src/components/Shell.tsx`
- Modify: `dashboard/web/src/styles.css`

- [ ] **Step 1: Add API PUT helper**

Modify `dashboard/web/src/api/client.ts` and add after `apiPost`:

```typescript
export async function apiPut<T>(path: string, payload: unknown, headers: Record<string, string> = {}): Promise<T> {
  const response = await fetch(path, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
      ...headers
    },
    body: JSON.stringify(payload)
  });
  return readApiResponse<T>(response);
}
```

- [ ] **Step 2: Create Prompt page**

Create `dashboard/web/src/pages/PromptPage.tsx`:

```typescript
import { useEffect, useMemo, useState } from 'react';
import { apiDelete, apiGet, apiPost, apiPut } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';

type PromptEntry = {
  key: string;
  title: string;
  category: string;
  content: string;
  variables: string[];
  enabled: boolean;
  builtin: boolean;
};

type PendingAction =
  | { type: 'save' }
  | { type: 'restore' }
  | { type: 'delete' }
  | null;

const emptyDraft: PromptEntry = {
  key: '',
  title: '',
  category: '自定义',
  content: '',
  variables: [],
  enabled: true,
  builtin: false
};

export function PromptPage() {
  const [entries, setEntries] = useState<PromptEntry[]>([]);
  const [selectedKey, setSelectedKey] = useState('');
  const [draft, setDraft] = useState<PromptEntry>(emptyDraft);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState<PendingAction>(null);

  useEffect(() => { void load(); }, []);

  async function load(nextKey?: string) {
    const data = await apiGet<PromptEntry[]>('/api/prompts');
    setEntries(data);
    const key = nextKey || selectedKey || data[0]?.key || '';
    const selected = data.find(entry => entry.key === key) || data[0];
    if (selected) {
      setSelectedKey(selected.key);
      setDraft({ ...selected, variables: [...selected.variables] });
    }
  }

  const categories = useMemo(() => {
    const grouped = new Map<string, PromptEntry[]>();
    for (const entry of entries) {
      const list = grouped.get(entry.category) || [];
      list.push(entry);
      grouped.set(entry.category, list);
    }
    return Array.from(grouped.entries());
  }, [entries]);

  const dirty = useMemo(() => {
    const original = entries.find(entry => entry.key === draft.key);
    return JSON.stringify(original || emptyDraft) !== JSON.stringify(draft);
  }, [draft, entries]);

  function select(entry: PromptEntry) {
    setSelectedKey(entry.key);
    setDraft({ ...entry, variables: [...entry.variables] });
    setMessage('');
    setError('');
  }

  function createNew() {
    setSelectedKey('');
    setDraft({ ...emptyDraft });
    setMessage('');
    setError('');
  }

  async function save() {
    try {
      setError('');
      const payload = {
        key: draft.key,
        title: draft.title,
        category: draft.category,
        content: draft.content,
        variables: draft.variables,
        enabled: draft.enabled
      };
      const saved = draft.builtin || entries.some(entry => entry.key === draft.key)
        ? await apiPut<PromptEntry>(`/api/prompts/${encodeURIComponent(draft.key)}`, payload)
        : await apiPost<PromptEntry>('/api/prompts', payload);
      setMessage(`${saved.title} 已保存`);
      setPending(null);
      await load(saved.key);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
      setPending(null);
    }
  }

  async function restore() {
    try {
      setError('');
      const restored = await apiPost<PromptEntry>(`/api/prompts/${encodeURIComponent(draft.key)}/restore`, {});
      setMessage(`${restored.title} 已恢复默认`);
      setPending(null);
      await load(restored.key);
    } catch (err) {
      setError(err instanceof Error ? err.message : '恢复失败');
      setPending(null);
    }
  }

  async function remove() {
    try {
      setError('');
      await apiDelete<{ key: string }>(`/api/prompts/${encodeURIComponent(draft.key)}`);
      setMessage(`${draft.title || draft.key} 已删除`);
      setPending(null);
      await load('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
      setPending(null);
    }
  }

  const variableText = draft.variables.join(', ');
  const confirmMessage = pending?.type === 'save'
    ? `确定保存 ${draft.title || draft.key} 吗？线上机器人可能在重启后使用这段 prompt。`
    : pending?.type === 'restore'
      ? `确定把 ${draft.title || draft.key} 恢复为代码默认 prompt 吗？`
      : `确定删除 ${draft.title || draft.key} 吗？`;

  return (
    <div className="prompt-layout">
      <section className="panel prompt-sidebar">
        <div className="prompt-sidebar-header">
          <h2>Prompt 人设</h2>
          <button onClick={createNew}>新增</button>
        </div>
        <p className="muted">只有内置 key 会被机器人运行时调用；自定义 key 先作为文本资产保存。</p>
        {categories.map(([category, items]) => (
          <div key={category} className="prompt-category">
            <h3>{category}</h3>
            {items.map(entry => (
              <button key={entry.key} className={entry.key === selectedKey ? 'prompt-item active' : 'prompt-item'} onClick={() => select(entry)}>
                <strong>{entry.title}</strong>
                <small>{entry.key}{entry.enabled ? '' : ' / disabled'}</small>
              </button>
            ))}
          </div>
        ))}
      </section>

      <section className="panel page-panel prompt-editor">
        <div className="prompt-editor-title">
          <div>
            <p className="mission-kicker">PROMPT REGISTRY</p>
            <h2>{draft.key ? draft.title || draft.key : '新增 Prompt'}</h2>
          </div>
          {draft.builtin && <span className="prompt-badge">内置运行时 key</span>}
        </div>
        {message && <p className="status-ok">{message}</p>}
        {error && <p className="status-error">{error}</p>}
        <div className="prompt-form-grid">
          <label>Key<input value={draft.key} disabled={draft.builtin || entries.some(entry => entry.key === draft.key)} onChange={event => setDraft(current => ({ ...current, key: event.target.value }))} /></label>
          <label>标题<input value={draft.title} onChange={event => setDraft(current => ({ ...current, title: event.target.value }))} /></label>
          <label>分组<input value={draft.category} onChange={event => setDraft(current => ({ ...current, category: event.target.value }))} /></label>
          <label>变量<input value={variableText} onChange={event => setDraft(current => ({ ...current, variables: event.target.value.split(',').map(item => item.trim()).filter(Boolean) }))} /></label>
        </div>
        <label className="prompt-enabled"><input type="checkbox" checked={draft.enabled} onChange={event => setDraft(current => ({ ...current, enabled: event.target.checked }))} /> 启用此条目覆盖代码默认 prompt</label>
        <textarea className="prompt-textarea" value={draft.content} onChange={event => setDraft(current => ({ ...current, content: event.target.value }))} placeholder="在这里编辑多行 prompt" />
        <div className="prompt-actions">
          <button disabled={!draft.key || !dirty} onClick={() => setPending({ type: 'save' })}>保存</button>
          <button disabled={!draft.builtin} onClick={() => setPending({ type: 'restore' })}>恢复默认</button>
          <button disabled={draft.builtin || !draft.key} onClick={() => setPending({ type: 'delete' })}>删除</button>
        </div>
      </section>

      {pending && (
        <ConfirmDialog title="确认 Prompt 操作" message={confirmMessage} onCancel={() => setPending(null)} onConfirm={pending.type === 'save' ? save : pending.type === 'restore' ? restore : remove} />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Wire page into app**

In `dashboard/web/src/App.tsx`, add import:

```typescript
import { PromptPage } from './pages/PromptPage';
```

Add render branch:

```tsx
      {page === 'prompts' && <PromptPage />}
```

- [ ] **Step 4: Add navigation item**

In `dashboard/web/src/components/Shell.tsx`, insert before config:

```typescript
  ['prompts', 'Prompt 人设'],
```

- [ ] **Step 5: Add styles**

Append to `dashboard/web/src/styles.css`:

```css
.prompt-layout {
  display: grid;
  grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
  gap: 16px;
}

.prompt-sidebar,
.prompt-editor {
  padding: 18px;
}

.prompt-sidebar-header,
.prompt-editor-title,
.prompt-actions {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.prompt-category {
  margin-top: 18px;
}

.prompt-category h3 {
  margin: 0 0 8px;
  color: #7aa2ff;
  font-size: 13px;
  letter-spacing: 0.18em;
}

.prompt-item {
  display: block;
  width: 100%;
  margin: 6px 0;
  padding: 10px;
  text-align: left;
  color: #f5f7fb;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.16);
  cursor: pointer;
}

.prompt-item.active {
  border-color: #7aa2ff;
  box-shadow: 0 0 18px rgba(122, 162, 255, 0.22);
}

.prompt-item strong,
.prompt-item small {
  display: block;
}

.prompt-item small,
.muted {
  color: #a9b4c9;
}

.prompt-badge {
  padding: 6px 10px;
  color: #37f29b;
  border: 1px solid rgba(55, 242, 155, 0.45);
}

.prompt-form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.prompt-form-grid label,
.prompt-enabled {
  display: grid;
  gap: 6px;
  color: #a9b4c9;
}

.prompt-form-grid input,
.prompt-textarea {
  width: 100%;
  color: #f5f7fb;
  background: rgba(0, 0, 0, 0.28);
  border: 1px solid rgba(255, 255, 255, 0.18);
  padding: 10px;
}

.prompt-textarea {
  min-height: 520px;
  margin-top: 14px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  line-height: 1.55;
  resize: vertical;
}

.prompt-actions {
  justify-content: flex-start;
  margin-top: 12px;
}

@media (max-width: 900px) {
  .prompt-layout {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 6: Build frontend**

Run:

```powershell
npm --prefix dashboard/web run build
```

Expected: build exits 0.

- [ ] **Step 7: Commit**

```bash
git add dashboard/web/src/api/client.ts dashboard/web/src/pages/PromptPage.tsx dashboard/web/src/App.tsx dashboard/web/src/components/Shell.tsx dashboard/web/src/styles.css
git commit -m "feat: add dashboard prompt editor page"
```

---

### Task 6: ECS Deployment Integration

**Files:**
- Modify: `deploy/deploy_ecs.sh`
- Modify: `tests/dashboard/test_deploy_ecs_dashboard.py`

- [ ] **Step 1: Add failing deployment assertions**

Append to `tests/dashboard/test_deploy_ecs_dashboard.py`:

```python
def test_ecs_deploy_script_preserves_prompt_registry():
    script = _script()

    assert "mkdir -p \"$BOT_DIR/config\"" in script
    assert "ARTETA_PROMPTS_FILE=/opt/arteta_bot/config/prompts.json" in script
    assert "config/prompts.json" in script
    assert "if [[ ! -f \"$BOT_DIR/config/prompts.json\" ]]" in script
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
python -m pytest tests/dashboard/test_deploy_ecs_dashboard.py::test_ecs_deploy_script_preserves_prompt_registry -q
```

Expected: FAIL because script lacks prompt registry handling.

- [ ] **Step 3: Update deployment script directories**

In `deploy/deploy_ecs.sh`, after:

```bash
mkdir -p "$BOT_DIR/plugins"
```

add:

```bash
mkdir -p "$BOT_DIR/config"
```

- [ ] **Step 4: Preserve or seed prompt registry**

After Dashboard frontend build block and before `.env.prod` writing, add:

```bash
if [[ ! -f "$BOT_DIR/config/prompts.json" ]]; then
    if [[ -f "$BOT_DIR/config/prompts.json.template" ]]; then
        cp "$BOT_DIR/config/prompts.json.template" "$BOT_DIR/config/prompts.json"
        ok "初始化 Prompt Registry"
    elif [[ -f "config/prompts.json" ]]; then
        cp "config/prompts.json" "$BOT_DIR/config/prompts.json"
        ok "初始化 Prompt Registry"
    else
        cat > "$BOT_DIR/config/prompts.json" << 'PROMPTS_EOF'
{
  "version": 1,
  "entries": []
}
PROMPTS_EOF
        ok "创建空 Prompt Registry"
    fi
else
    ok "保留现有 Prompt Registry"
fi
```

- [ ] **Step 5: Add Supervisor env to bot**

Change bot supervisor environment line from:

```ini
environment=ENVIRONMENT="prod"
```

to:

```ini
environment=ENVIRONMENT="prod",ARTETA_PROMPTS_FILE="/opt/arteta_bot/config/prompts.json"
```

- [ ] **Step 6: Add Supervisor env to dashboard**

In dashboard supervisor `environment=` line, append:

```text
,ARTETA_PROMPTS_FILE=/opt/arteta_bot/config/prompts.json
```

- [ ] **Step 7: Run deployment tests**

Run:

```powershell
python -m pytest tests/dashboard/test_deploy_ecs_dashboard.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add deploy/deploy_ecs.sh tests/dashboard/test_deploy_ecs_dashboard.py
git commit -m "feat: deploy prompt registry to ecs"
```

---

### Task 7: Documentation Updates

**Files:**
- Modify: `docs/dev/developer-dashboard.md`
- Modify: `docs/ops/dashboard-public-deployment.md`

- [ ] **Step 1: Update developer dashboard docs**

In `docs/dev/developer-dashboard.md`, add to 功能模块 list after Bot Chat:

```markdown
- Prompt 人设：按功能分组管理机器人 prompt registry，可编辑主对话、Dashboard 对话、画像分析、每日总结、周报和算法/理科解题 prompt；只有内置 key 会被运行时调用，自定义 key 作为可保存文本资产。
```

Add to ECS env block:

```bash
ARTETA_PROMPTS_FILE=/opt/arteta_bot/config/prompts.json
```

- [ ] **Step 2: Update public deployment docs**

In `docs/ops/dashboard-public-deployment.md`, add `/opt/arteta_bot/config/prompts.json` to production path table:

```markdown
| Prompt Registry | `/opt/arteta_bot/config/prompts.json` |
```

Add `ARTETA_PROMPTS_FILE` to Supervisor environment example:

```text
ARTETA_PROMPTS_FILE="/opt/arteta_bot/config/prompts.json"
```

Add deployment note after upload section:

```markdown
Prompt Registry 部署规则：首次部署可从 `config/prompts.json` 初始化 `/opt/arteta_bot/config/prompts.json`；后续部署默认保留服务器上的现有文件，避免覆盖 Dashboard 中已经编辑过的人设 prompt。
```

- [ ] **Step 3: Commit**

```bash
git add docs/dev/developer-dashboard.md docs/ops/dashboard-public-deployment.md
git commit -m "docs: document dashboard prompt registry"
```

---

### Task 8: Full Verification and Manual Dashboard Check

**Files:**
- No source changes expected.

- [ ] **Step 1: Run dashboard backend tests**

Run:

```powershell
python -m pytest tests/dashboard -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
npm --prefix dashboard/web run build
```

Expected: PASS.

- [ ] **Step 3: Start Dashboard locally**

Run:

```powershell
python -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8765
```

Expected: server starts and logs Uvicorn running on `http://127.0.0.1:8765`.

- [ ] **Step 4: Open Dashboard and verify golden path**

In browser:

1. Open `http://127.0.0.1:8765`.
2. Click `开始`.
3. Open `Prompt 人设`.
4. Select `Dashboard 对话人设`.
5. Change content to a harmless test line.
6. Save and confirm.
7. Refresh page and confirm the saved content persists.
8. Restore default.

Expected: no browser console errors; save and restore both show success messages.

- [ ] **Step 5: Stop local Dashboard server**

Stop the Uvicorn process with Ctrl+C.

- [ ] **Step 6: Final status check**

Run:

```powershell
git status --short
```

Expected: only intentional changes are present, or working tree is clean if all tasks were committed.

---

## Self-Review Notes

Spec coverage:

- Dashboard Prompt 人设 navigation and grouped UI: Task 5.
- File-backed JSON registry: Tasks 1 and 4.
- Backend API and safety rules: Task 2.
- Runtime prompt override with fallback: Task 3.
- ECS deployment and registry preservation: Task 6.
- Tests: Tasks 1, 2, 4, 6, and 8.
- Documentation: Task 7.

No placeholder terms are intentionally left in implementation steps. Type names are consistent: `PromptService`, `PromptEntryRequest`, `PromptUpdateRequest`, `PromptEntry`, and `apiPut`.
