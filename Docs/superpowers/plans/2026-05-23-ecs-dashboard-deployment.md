# ECS Dashboard Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the Arteta Bot dashboard on ECS so group profiles, memories, logs, and config operate directly on live ECS resources instead of local synced copies.

**Architecture:** Keep the existing FastAPI dashboard API as the single backend and serve the built React/Vite app from the same process. Add ECS production configuration for live resource paths, public-mode startup safety, and Supervisor deployment as a separate `arteta_dashboard` process.

**Tech Stack:** Python 3.8, FastAPI, Starlette static files, React/Vite/TypeScript, Supervisor, pytest.

---

## File Structure

- Modify `dashboard/api/config.py`
  - Add `public`, `web_dist`, and configurable `logs_dir` settings.
  - Add a small validation helper for public deployment safety.
- Modify `dashboard/api/security.py`
  - Use the settings validation helper before creating or decoding JWTs.
- Modify `dashboard/api/main.py`
  - Serve `dashboard/web/dist` when configured and present.
  - Add SPA fallback for non-API routes.
- Modify `deploy/deploy_ecs.sh`
  - Install Node/npm and dashboard Python dependencies.
  - Build the dashboard frontend.
  - Write a separate Supervisor program `arteta_dashboard`.
  - Print dashboard access and security-group guidance.
- Modify `docs/dev/developer-dashboard.md`
  - Document ECS-hosted dashboard as the primary operations mode.
  - Mark `start_dashboard.ps1 -EcsSync` as a local troubleshooting fallback.
- Modify `docs/ops/deployment.md`
  - Add ECS Dashboard deployment/start/verify instructions.
- Create `tests/dashboard/test_dashboard_config.py`
  - Verify new settings and public-mode validation.
- Create `tests/dashboard/test_static_frontend.py`
  - Verify frontend static serving and SPA fallback.
- Modify `tests/dashboard/test_logs_service.py`
  - Keep service-level log path behavior covered.
- Modify or create `tests/dashboard/test_deploy_ecs_dashboard.py`
  - Verify deployment script contains dashboard dependencies, build, Supervisor config, and ECS paths.

---

### Task 1: Dashboard runtime settings

**Files:**
- Modify: `dashboard/api/config.py`
- Test: `tests/dashboard/test_dashboard_config.py`

- [ ] **Step 1: Write failing settings tests**

Create `tests/dashboard/test_dashboard_config.py` with:

```python
import os

import pytest

from dashboard.api.config import get_settings, validate_public_settings


def test_dashboard_settings_include_logs_web_dist_and_public(monkeypatch, tmp_path):
    logs_dir = tmp_path / "ecs_logs"
    web_dist = tmp_path / "dist"
    env_file = tmp_path / ".env"

    monkeypatch.setenv("DASHBOARD_LOGS_DIR", str(logs_dir))
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(web_dist))
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))
    monkeypatch.setenv("DASHBOARD_PUBLIC", "true")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "strong-secret")

    settings = get_settings()

    assert settings.logs_dir == str(logs_dir)
    assert settings.web_dist == str(web_dist)
    assert settings.env_file == str(env_file)
    assert settings.public is True


def test_validate_public_settings_rejects_missing_secret(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PUBLIC", "true")
    monkeypatch.delenv("DASHBOARD_SECRET_KEY", raising=False)

    settings = get_settings()

    with pytest.raises(RuntimeError) as exc:
        validate_public_settings(settings)
    assert "DASHBOARD_SECRET_KEY" in str(exc.value)


def test_validate_public_settings_allows_local_dev_without_secret(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PUBLIC", "false")
    monkeypatch.delenv("DASHBOARD_SECRET_KEY", raising=False)

    settings = get_settings()

    validate_public_settings(settings)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/dashboard/test_dashboard_config.py -v
```

Expected: FAIL because `DashboardSettings` has no `web_dist` or `public`, and `validate_public_settings` does not exist.

- [ ] **Step 3: Implement runtime settings**

Modify `dashboard/api/config.py` to this complete content:

```python
import os
from dataclasses import dataclass
from typing import List


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
DEV_SECRET_KEY = "dev-dashboard-insecure-secret"


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


ENV_WHITELIST = [
    "DEEPSEEK_API_KEY",
    "FOOTBALL_API_TOKEN",
    "IMAGE_API_KEY",
    "IMAGE_API_URL",
    "IMAGE_MODEL",
    "VISION_MODEL",
]


def _split_origins(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).lower() == "true"


def get_settings() -> DashboardSettings:
    env_file = os.environ.get("DASHBOARD_ENV_FILE", os.path.join(REPO_ROOT, ".env"))
    return DashboardSettings(
        host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("DASHBOARD_PORT", "8765")),
        admin_password=os.environ.get("DASHBOARD_ADMIN_PASSWORD", ""),
        secret_key=os.environ.get("DASHBOARD_SECRET_KEY", ""),
        allowed_origins=_split_origins(os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "http://localhost:5173")),
        env_file=env_file,
        readonly=_env_bool("DASHBOARD_READONLY"),
        public=_env_bool("DASHBOARD_PUBLIC"),
        db_path=os.environ.get("ARTETA_DB_PATH", os.path.join(REPO_ROOT, "arsenal_data.db")),
        chroma_dir=os.environ.get("ARTETA_CHROMA_DIR", os.path.join(REPO_ROOT, "chroma_db")),
        logs_dir=os.environ.get("DASHBOARD_LOGS_DIR", os.path.join(REPO_ROOT, "logs")),
        docs_roots=[os.path.join(REPO_ROOT, "docs"), os.path.join(REPO_ROOT, "knowledge_base")],
        audit_log_path=os.path.join(REPO_ROOT, "logs", "dashboard_audit.log"),
        sync_status_path=os.environ.get("DASHBOARD_SYNC_STATUS_PATH", os.path.join(REPO_ROOT, "data", "ecs_sync_status.json")),
        web_dist=os.environ.get("DASHBOARD_WEB_DIST", os.path.join(REPO_ROOT, "dashboard", "web", "dist")),
    )


def validate_public_settings(settings: DashboardSettings) -> None:
    if settings.public and not settings.secret_key:
        raise RuntimeError("DASHBOARD_SECRET_KEY is required when DASHBOARD_PUBLIC=true")
    if settings.public and settings.secret_key == DEV_SECRET_KEY:
        raise RuntimeError("DASHBOARD_SECRET_KEY must not use the development fallback when DASHBOARD_PUBLIC=true")
```

- [ ] **Step 4: Run settings tests**

Run:

```bash
python -m pytest tests/dashboard/test_dashboard_config.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/api/config.py tests/dashboard/test_dashboard_config.py
git commit -m "feat: add dashboard ECS runtime settings"
```

---

### Task 2: Public-mode JWT safety

**Files:**
- Modify: `dashboard/api/security.py`
- Modify: `tests/dashboard/test_api_auth.py`

- [ ] **Step 1: Write failing auth safety test**

Append this test to `tests/dashboard/test_api_auth.py`:

```python

def test_public_mode_rejects_missing_jwt_secret(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PUBLIC", "true")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.delenv("DASHBOARD_SECRET_KEY", raising=False)
    client = TestClient(create_app())

    response = client.post("/api/auth/login", json={"password": "secret"})

    assert response.status_code == 500
    assert "DASHBOARD_SECRET_KEY" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/dashboard/test_api_auth.py::test_public_mode_rejects_missing_jwt_secret -v
```

Expected: FAIL because login still succeeds by using the development fallback secret.

- [ ] **Step 3: Implement public-mode JWT safety**

Modify `dashboard/api/security.py` to this complete content:

```python
from datetime import datetime, timedelta
from typing import Dict

from fastapi import Header, HTTPException
from jose import JWTError, jwt

from dashboard.api.config import DEV_SECRET_KEY, get_settings, validate_public_settings

ALGORITHM = "HS256"
TOKEN_TTL_MINUTES = 480


def verify_admin_password(password: str) -> bool:
    settings = get_settings()
    return bool(settings.admin_password) and password == settings.admin_password


def _secret_key() -> str:
    settings = get_settings()
    validate_public_settings(settings)
    return settings.secret_key or DEV_SECRET_KEY


def create_access_token(payload: Dict[str, str]) -> str:
    data = dict(payload)
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES)
    data.update({"exp": expire})
    return jwt.encode(data, _secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> Dict[str, str]:
    return jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])


def require_auth(authorization: str = Header("")) -> Dict[str, str]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[len("Bearer "):]
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("sub") != "admin":
        raise HTTPException(status_code=401, detail="Invalid subject")
    return payload
```

- [ ] **Step 4: Run auth tests**

Run:

```bash
python -m pytest tests/dashboard/test_api_auth.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/api/security.py tests/dashboard/test_api_auth.py
git commit -m "fix: require dashboard JWT secret in public mode"
```

---

### Task 3: Serve built frontend from FastAPI

**Files:**
- Modify: `dashboard/api/main.py`
- Test: `tests/dashboard/test_static_frontend.py`

- [ ] **Step 1: Write failing static frontend tests**

Create `tests/dashboard/test_static_frontend.py` with:

```python
from fastapi.testclient import TestClient

from dashboard.api.main import create_app


def test_serves_dashboard_index_from_configured_dist(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<div id='root'>dashboard</div>", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(dist))

    client = TestClient(create_app())
    response = client.get("/")

    assert response.status_code == 200
    assert "dashboard" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_spa_fallback_does_not_intercept_api(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("dashboard", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(dist))

    client = TestClient(create_app())
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_spa_nested_route_returns_index(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("dashboard nested", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(dist))

    client = TestClient(create_app())
    response = client.get("/groups")

    assert response.status_code == 200
    assert "dashboard nested" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/dashboard/test_static_frontend.py -v
```

Expected: FAIL because `create_app()` does not serve frontend files yet.

- [ ] **Step 3: Implement frontend serving**

Modify `dashboard/api/main.py` to this complete content:

```python
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from dashboard.api.config import get_settings
from dashboard.api.routers import auth, config, docs, groups, logs, memories, overview, verify
from dashboard.api.schemas import ok


def _mount_frontend(app: FastAPI, web_dist: str) -> None:
    index_path = os.path.join(web_dist, "index.html")
    assets_path = os.path.join(web_dist, "assets")
    if os.path.isdir(assets_path):
        app.mount("/assets", StaticFiles(directory=assets_path), name="dashboard-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            return PlainTextResponse("Not Found", status_code=404)
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return PlainTextResponse("Dashboard frontend build not found. Run npm --prefix dashboard/web run build.", status_code=503)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Arteta Developer Mission Control")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(groups.router)
    app.include_router(docs.router)
    app.include_router(config.router)
    app.include_router(logs.router)
    app.include_router(memories.router)
    app.include_router(overview.router)
    app.include_router(verify.router)

    @app.get("/api/health")
    def health():
        return ok({"status": "healthy", "readonly": settings.readonly})

    _mount_frontend(app, settings.web_dist)
    return app


app = create_app()
```

- [ ] **Step 4: Run static frontend tests**

Run:

```bash
python -m pytest tests/dashboard/test_static_frontend.py -v
```

Expected: PASS.

- [ ] **Step 5: Run dashboard API smoke tests**

Run:

```bash
python -m pytest tests/dashboard/test_api_auth.py tests/dashboard/test_overview_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dashboard/api/main.py tests/dashboard/test_static_frontend.py
git commit -m "feat: serve dashboard frontend from FastAPI"
```

---

### Task 4: ECS deployment script for dashboard service

**Files:**
- Modify: `deploy/deploy_ecs.sh`
- Test: `tests/dashboard/test_deploy_ecs_dashboard.py`

- [ ] **Step 1: Write failing deployment script test**

Create `tests/dashboard/test_deploy_ecs_dashboard.py` with:

```python
import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
SCRIPT_PATH = os.path.join(REPO_ROOT, "deploy", "deploy_ecs.sh")


def _script():
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_ecs_deploy_script_configures_dashboard_process():
    script = _script()

    assert "DASHBOARD_ADMIN_PASSWORD" in script
    assert "DASHBOARD_SECRET_KEY" in script
    assert "DASHBOARD_PUBLIC=true" in script
    assert "[program:arteta_dashboard]" in script
    assert "uvicorn dashboard.api.main:app" in script
    assert "ARTETA_DB_PATH=/opt/arteta_bot/arsenal_data.db" in script
    assert "ARTETA_CHROMA_DIR=/opt/arteta_bot/chroma_db" in script
    assert "DASHBOARD_LOGS_DIR=/opt/arteta_bot/logs" in script
    assert "DASHBOARD_WEB_DIST=/opt/arteta_bot/dashboard/web/dist" in script


def test_ecs_deploy_script_builds_dashboard_frontend():
    script = _script()

    assert "apt install -y" in script and "nodejs" in script and "npm" in script
    assert "npm --prefix \"$BOT_DIR/dashboard/web\" install" in script
    assert "npm --prefix \"$BOT_DIR/dashboard/web\" run build" in script
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/dashboard/test_deploy_ecs_dashboard.py -v
```

Expected: FAIL because the deployment script does not configure dashboard deployment yet.

- [ ] **Step 3: Add dashboard deployment variables**

Modify the configuration section near the top of `deploy/deploy_ecs.sh` after `SUPERUSERS=...` to include:

```bash
DASHBOARD_PORT="${DASHBOARD_PORT:-8765}"
DASHBOARD_ADMIN_PASSWORD="${DASHBOARD_ADMIN_PASSWORD:-}"
DASHBOARD_SECRET_KEY="${DASHBOARD_SECRET_KEY:-}"
```

Modify the dependency install line to include Node/npm and Python dashboard dependencies:

```bash
apt install -y python3 python3-pip python3-venv git wget unzip curl supervisor nodejs npm
```

Modify the pip install line to include the current dashboard/runtime dependencies:

```bash
pip install nonebot2 nonebot-adapter-onebot nonebot-plugin-apscheduler httpx aiosqlite pillow pilmoji duckduckgo_search loguru fastapi uvicorn 'python-jose[cryptography]' python-multipart chromadb pysqlite3-binary
```

- [ ] **Step 4: Add frontend build step**

Insert after Python dependency installation:

```bash
if [[ -d "$BOT_DIR/dashboard/web" ]]; then
    info ">>> 构建 Dashboard 前端..."
    npm --prefix "$BOT_DIR/dashboard/web" install
    npm --prefix "$BOT_DIR/dashboard/web" run build
    ok "Dashboard 前端构建完成"
else
    warn "未找到 $BOT_DIR/dashboard/web，跳过 Dashboard 前端构建"
fi
```

- [ ] **Step 5: Add dashboard Supervisor config**

After writing `/etc/supervisor/conf.d/arteta_bot.conf`, add:

```bash
if [[ -z "$DASHBOARD_ADMIN_PASSWORD" ]]; then
    warn "DASHBOARD_ADMIN_PASSWORD 未设置，Dashboard 登录将不可用"
fi
if [[ -z "$DASHBOARD_SECRET_KEY" ]]; then
    warn "DASHBOARD_SECRET_KEY 未设置，Dashboard 公网模式将拒绝签发 JWT"
fi

cat > /etc/supervisor/conf.d/arteta_dashboard.conf << SUPERVISOR_DASHBOARD_EOF
[program:arteta_dashboard]
command=$BOT_DIR/venv/bin/python -m uvicorn dashboard.api.main:app --host 0.0.0.0 --port $DASHBOARD_PORT
directory=$BOT_DIR
user=$BOT_USER
autostart=true
autorestart=true
startretries=3
stderr_logfile=/var/log/arteta_bot/dashboard_error.log
stdout_logfile=/var/log/arteta_bot/dashboard_access.log
environment=ENVIRONMENT="prod",DASHBOARD_PUBLIC="true",DASHBOARD_HOST="0.0.0.0",DASHBOARD_PORT="$DASHBOARD_PORT",DASHBOARD_ADMIN_PASSWORD="$DASHBOARD_ADMIN_PASSWORD",DASHBOARD_SECRET_KEY="$DASHBOARD_SECRET_KEY",ARTETA_DB_PATH=/opt/arteta_bot/arsenal_data.db,ARTETA_CHROMA_DIR=/opt/arteta_bot/chroma_db,DASHBOARD_LOGS_DIR=/opt/arteta_bot/logs,DASHBOARD_ENV_FILE=/opt/arteta_bot/.env,DASHBOARD_WEB_DIST=/opt/arteta_bot/dashboard/web/dist
SUPERVISOR_DASHBOARD_EOF
```

- [ ] **Step 6: Update deployment output**

Add these lines to the final output section before the security-group warning:

```bash
echo -e "${YELLOW}6. Dashboard 管理后台：${NC}"
echo "   supervisorctl status arteta_dashboard"
echo "   supervisorctl restart arteta_dashboard"
echo "   浏览器访问: http://<ECS公网IP>:$DASHBOARD_PORT"
echo "   登录密码来自 DASHBOARD_ADMIN_PASSWORD，JWT 密钥来自 DASHBOARD_SECRET_KEY"
echo ""
echo -e "${YELLOW}⚠  安全组如需公网访问 Dashboard，添加 $DASHBOARD_PORT 端口入方向规则，并使用强密码${NC}"
```

- [ ] **Step 7: Run deployment script tests**

Run:

```bash
python -m pytest tests/dashboard/test_deploy_ecs_dashboard.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add deploy/deploy_ecs.sh tests/dashboard/test_deploy_ecs_dashboard.py
git commit -m "feat: deploy dashboard as ECS supervisor service"
```

---

### Task 5: Dashboard documentation updates

**Files:**
- Modify: `docs/dev/developer-dashboard.md`
- Modify: `docs/ops/deployment.md`

- [ ] **Step 1: Update developer dashboard doc**

Modify `docs/dev/developer-dashboard.md` so the local development section stays, but add this ECS-hosted section after the architecture section:

```markdown
## ECS 生产运行模式

生产推荐将 Dashboard 直接部署在 ECS 上运行，而不是在本地同步 SQLite 副本。ECS 模式下：

- 群聊档案读取和写入 `/opt/arteta_bot/arsenal_data.db`
- 记忆管理读取和删除 `/opt/arteta_bot/chroma_db`
- 实时日志读取 `/opt/arteta_bot/logs`
- 配置密钥读取和更新 `/opt/arteta_bot/.env`
- 前端由 FastAPI 托管 `dashboard/web/dist`

关键环境变量：

```bash
DASHBOARD_PUBLIC=true
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8765
DASHBOARD_ADMIN_PASSWORD=<strong-password>
DASHBOARD_SECRET_KEY=<long-random-secret>
ARTETA_DB_PATH=/opt/arteta_bot/arsenal_data.db
ARTETA_CHROMA_DIR=/opt/arteta_bot/chroma_db
DASHBOARD_LOGS_DIR=/opt/arteta_bot/logs
DASHBOARD_ENV_FILE=/opt/arteta_bot/.env
DASHBOARD_WEB_DIST=/opt/arteta_bot/dashboard/web/dist
```

`DASHBOARD_PUBLIC=true` 时必须配置 `DASHBOARD_SECRET_KEY`，否则登录签发 JWT 会失败。

`start_dashboard.ps1 -EcsSync` 仍可用于本地只读排障，但不再是生产管理主路径。
```

- [ ] **Step 2: Update deployment doc**

Append this section to `docs/ops/deployment.md`:

```markdown
### Dashboard 管理后台（ECS）

Dashboard 作为独立 Supervisor 进程 `arteta_dashboard` 运行，和机器人主进程分开重启。

部署前设置强密码和 JWT 密钥：

```bash
export DASHBOARD_ADMIN_PASSWORD='<strong-password>'
export DASHBOARD_SECRET_KEY='<long-random-secret>'
sudo bash deploy/deploy_ecs.sh
```

检查状态：

```bash
supervisorctl status arteta_dashboard
supervisorctl tail -f arteta_dashboard
```

默认访问地址：

```text
http://<ECS公网IP>:8765
```

如需公网访问，在云安全组放行 `8765` 入方向端口。该模式直接操作 ECS 本机资源：

- `/opt/arteta_bot/arsenal_data.db`
- `/opt/arteta_bot/chroma_db`
- `/opt/arteta_bot/logs`
- `/opt/arteta_bot/.env`

如果只想查看不允许写入，可在 Supervisor 环境中设置：

```bash
DASHBOARD_READONLY=true
```
```

- [ ] **Step 3: Run doc grep checks**

Run:

```bash
python - <<'PY'
from pathlib import Path
for path in ['docs/dev/developer-dashboard.md', 'docs/ops/deployment.md']:
    text = Path(path).read_text(encoding='utf-8')
    assert 'arteta_dashboard' in text or 'ECS 生产运行模式' in text
    assert 'DASHBOARD_SECRET_KEY' in text
print('docs ok')
PY
```

Expected: prints `docs ok`.

- [ ] **Step 4: Commit**

```bash
git add docs/dev/developer-dashboard.md docs/ops/deployment.md
git commit -m "docs: document ECS-hosted dashboard"
```

---

### Task 6: Full verification

**Files:**
- No source changes expected unless tests reveal a defect.

- [ ] **Step 1: Run dashboard test suite**

Run:

```bash
python -m pytest tests/dashboard -v
```

Expected: PASS.

- [ ] **Step 2: Run dashboard frontend build**

Run:

```bash
npm --prefix dashboard/web run build
```

Expected: PASS and Vite writes `dashboard/web/dist`.

- [ ] **Step 3: Run core feature verification**

Run:

```bash
python tools/verify_features.py --suite core
```

Expected: PASS or known skips only.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short
```

Expected: only intentional source/doc/test changes are present. If `dashboard/web/dist` appears and the repo does not normally track it, do not commit it unless already tracked.

- [ ] **Step 5: Final commit if verification fixes were needed**

If Step 1-3 required fixes, commit those fixes:

```bash
git add <changed-files>
git commit -m "fix: stabilize ECS dashboard deployment"
```

---

## Self-Review

- Spec coverage: tasks cover ECS runtime config, public-mode safety, static frontend serving, deployment script, docs, and verification.
- Placeholder scan: no TBD/TODO/implement-later placeholders are present.
- Type consistency: new settings are consistently named `public`, `web_dist`, `DASHBOARD_PUBLIC`, `DASHBOARD_WEB_DIST`, and `DASHBOARD_LOGS_DIR` across tasks.
