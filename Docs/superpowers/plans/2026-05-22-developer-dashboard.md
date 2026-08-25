# Developer Mission Control Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an internal SpaceX Mission Control-style developer dashboard for inspecting Arteta Bot data, ChromaDB memory, verification runs, docs, logs, and API key configuration.

**Architecture:** Add a same-repository frontend/backend-separated dashboard under `dashboard/`. FastAPI owns all filesystem, SQLite, ChromaDB, subprocess, log, and env access; React + Vite + TypeScript renders authenticated operational pages and calls only dashboard APIs.

**Tech Stack:** Python 3.8-compatible FastAPI backend, pytest, httpx/TestClient, React, Vite, TypeScript, CSS modules or plain CSS, SSE for verification/log streams.

---

## File Structure

### Backend files to create

- `dashboard/__init__.py` — dashboard package marker.
- `dashboard/api/__init__.py` — API package marker.
- `dashboard/api/main.py` — FastAPI app factory, CORS, router registration, static health endpoint.
- `dashboard/api/config.py` — project paths, env-derived dashboard settings, allowed roots, whitelisted env vars.
- `dashboard/api/security.py` — password verification, token creation, token parsing, auth dependency.
- `dashboard/api/schemas.py` — shared Pydantic response/request models.
- `dashboard/api/services/audit_service.py` — append-only audit logging.
- `dashboard/api/services/sqlite_service.py` — read-only SQLite data access.
- `dashboard/api/services/chroma_service.py` — Chroma collection stats, listing, search, delete.
- `dashboard/api/services/docs_service.py` — safe docs tree/read/search.
- `dashboard/api/services/logs_service.py` — safe log list/read/tail helpers.
- `dashboard/api/services/env_service.py` — masked whitelist env reads and safe writes.
- `dashboard/api/services/verify_service.py` — verification subprocess runs, report discovery, artifact access.
- `dashboard/api/routers/auth.py` — login and current-session endpoints.
- `dashboard/api/routers/overview.py` — Mission Control overview endpoint.
- `dashboard/api/routers/groups.py` — group/user/profile endpoints.
- `dashboard/api/routers/memories.py` — Chroma endpoints.
- `dashboard/api/routers/docs.py` — docs tree/read/search endpoints.
- `dashboard/api/routers/logs.py` — logs endpoints.
- `dashboard/api/routers/verify.py` — verification endpoints and SSE.
- `dashboard/api/routers/config.py` — API key config endpoints.

### Backend tests to create

- `tests/dashboard/test_security.py`
- `tests/dashboard/test_sqlite_service.py`
- `tests/dashboard/test_docs_service.py`
- `tests/dashboard/test_env_service.py`
- `tests/dashboard/test_verify_service.py`
- `tests/dashboard/test_api_auth.py`

### Frontend files to create

- `dashboard/web/package.json`
- `dashboard/web/tsconfig.json`
- `dashboard/web/vite.config.ts`
- `dashboard/web/index.html`
- `dashboard/web/src/main.tsx`
- `dashboard/web/src/App.tsx`
- `dashboard/web/src/api/client.ts`
- `dashboard/web/src/api/types.ts`
- `dashboard/web/src/styles.css`
- `dashboard/web/src/pages/LoginPage.tsx`
- `dashboard/web/src/pages/MissionControlPage.tsx`
- `dashboard/web/src/pages/GroupsPage.tsx`
- `dashboard/web/src/pages/MemoriesPage.tsx`
- `dashboard/web/src/pages/VerifyPage.tsx`
- `dashboard/web/src/pages/DocsPage.tsx`
- `dashboard/web/src/pages/LogsPage.tsx`
- `dashboard/web/src/pages/ConfigPage.tsx`
- `dashboard/web/src/components/Shell.tsx`
- `dashboard/web/src/components/StatusCard.tsx`
- `dashboard/web/src/components/ConfirmDialog.tsx`

### Existing files to modify

- `pyproject.toml` — add dashboard backend dependencies if missing.
- `docs/dev/developer-dashboard.md` — create developer guide after implementation.
- `docs/ops/deployment.md` — add internal dashboard deployment notes.
- `README.md` — add one-line dashboard doc pointer.

---

## Task 1: Backend package and configuration foundation

**Files:**
- Create: `dashboard/__init__.py`
- Create: `dashboard/api/__init__.py`
- Create: `dashboard/api/config.py`
- Create: `dashboard/api/schemas.py`
- Create: `dashboard/api/main.py`
- Modify: `pyproject.toml`
- Test: `tests/dashboard/test_api_auth.py`

- [ ] **Step 1: Add backend dependencies to `pyproject.toml`**

Add FastAPI backend dependencies while preserving Python 3.8 compatibility:

```toml
"fastapi",
"uvicorn",
"python-jose[cryptography]",
"python-multipart",
```

- [ ] **Step 2: Create package marker files**

Create `dashboard/__init__.py` and `dashboard/api/__init__.py` as empty files.

- [ ] **Step 3: Write configuration module**

Create `dashboard/api/config.py`:

```python
import os
from dataclasses import dataclass
from typing import List


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


@dataclass
class DashboardSettings:
    host: str
    port: int
    admin_password: str
    secret_key: str
    allowed_origins: List[str]
    env_file: str
    readonly: bool
    db_path: str
    chroma_dir: str
    logs_dir: str
    docs_roots: List[str]
    audit_log_path: str


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


def get_settings() -> DashboardSettings:
    env_file = os.environ.get("DASHBOARD_ENV_FILE", os.path.join(REPO_ROOT, ".env"))
    return DashboardSettings(
        host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("DASHBOARD_PORT", "8765")),
        admin_password=os.environ.get("DASHBOARD_ADMIN_PASSWORD", ""),
        secret_key=os.environ.get("DASHBOARD_SECRET_KEY", ""),
        allowed_origins=_split_origins(os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "http://localhost:5173")),
        env_file=env_file,
        readonly=os.environ.get("DASHBOARD_READONLY", "false").lower() == "true",
        db_path=os.environ.get("ARTETA_DB_PATH", os.path.join(REPO_ROOT, "arsenal_data.db")),
        chroma_dir=os.environ.get("ARTETA_CHROMA_DIR", os.path.join(REPO_ROOT, "chroma_db")),
        logs_dir=os.path.join(REPO_ROOT, "logs"),
        docs_roots=[os.path.join(REPO_ROOT, "docs"), os.path.join(REPO_ROOT, "knowledge_base")],
        audit_log_path=os.path.join(REPO_ROOT, "logs", "dashboard_audit.log"),
    )
```

- [ ] **Step 4: Write shared schemas**

Create `dashboard/api/schemas.py`:

```python
from typing import Any, Dict, Optional
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel):
    ok: bool
    data: Optional[Any] = None
    error: Optional[ErrorBody] = None


def ok(data: Any = None) -> Dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def fail(code: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}
```

- [ ] **Step 5: Write minimal FastAPI app**

Create `dashboard/api/main.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok


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

    @app.get("/api/health")
    def health():
        return ok({"status": "healthy", "readonly": settings.readonly})

    return app


app = create_app()
```

- [ ] **Step 6: Add health test**

Create `tests/dashboard/test_api_auth.py`:

```python
from fastapi.testclient import TestClient

from dashboard.api.main import create_app


def test_health_returns_ok():
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "healthy"
```

- [ ] **Step 7: Run test**

Run:

```bash
python -m pytest tests/dashboard/test_api_auth.py -v
```

Expected: `1 passed`.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml dashboard tests/dashboard/test_api_auth.py
git commit -m "feat: add dashboard API foundation"
```

---

## Task 2: Authentication and token protection

**Files:**
- Create: `dashboard/api/security.py`
- Create: `dashboard/api/routers/auth.py`
- Modify: `dashboard/api/main.py`
- Test: `tests/dashboard/test_security.py`
- Test: `tests/dashboard/test_api_auth.py`

- [ ] **Step 1: Write failing security tests**

Create `tests/dashboard/test_security.py`:

```python
import os

from dashboard.api.security import create_access_token, decode_access_token, verify_admin_password


def test_verify_admin_password_requires_configured_password(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    assert verify_admin_password("secret") is True
    assert verify_admin_password("wrong") is False


def test_token_round_trip(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    token = create_access_token({"sub": "admin"})
    payload = decode_access_token(token)
    assert payload["sub"] == "admin"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/dashboard/test_security.py -v
```

Expected: import failure because `dashboard.api.security` does not exist.

- [ ] **Step 3: Implement security helpers**

Create `dashboard/api/security.py`:

```python
from datetime import datetime, timedelta
from typing import Dict

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt

from dashboard.api.config import get_settings

ALGORITHM = "HS256"
TOKEN_TTL_MINUTES = 480


def verify_admin_password(password: str) -> bool:
    settings = get_settings()
    return bool(settings.admin_password) and password == settings.admin_password


def _secret_key() -> str:
    settings = get_settings()
    return settings.secret_key or "dev-dashboard-insecure-secret"


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

- [ ] **Step 4: Implement auth router**

Create `dashboard/api/routers/auth.py`:

```python
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException

from dashboard.api.schemas import ok
from dashboard.api.security import create_access_token, require_auth, verify_admin_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
def login(request: LoginRequest):
    if not verify_admin_password(request.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    return ok({"token": create_access_token({"sub": "admin"})})


@router.get("/me")
def me(payload=Depends(require_auth)):
    return ok({"subject": payload["sub"]})
```

- [ ] **Step 5: Register auth router**

Modify `dashboard/api/main.py`:

```python
from dashboard.api.routers import auth

# inside create_app(), before health return
app.include_router(auth.router)
```

- [ ] **Step 6: Extend API auth tests**

Append to `tests/dashboard/test_api_auth.py`:

```python

def test_login_and_me(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    client = TestClient(create_app())

    login = client.post("/api/auth/login", json={"password": "secret"})
    assert login.status_code == 200
    token = login.json()["data"]["token"]

    me = client.get("/api/auth/me", headers={"Authorization": "Bearer " + token})
    assert me.status_code == 200
    assert me.json()["data"]["subject"] == "admin"


def test_login_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    client = TestClient(create_app())
    response = client.post("/api/auth/login", json={"password": "wrong"})
    assert response.status_code == 401
```

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/dashboard/test_security.py tests/dashboard/test_api_auth.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add dashboard/api/security.py dashboard/api/routers/auth.py dashboard/api/main.py tests/dashboard/test_security.py tests/dashboard/test_api_auth.py
git commit -m "feat: secure dashboard API with admin token auth"
```

---

## Task 3: SQLite group/profile service and API

**Files:**
- Create: `dashboard/api/services/sqlite_service.py`
- Create: `dashboard/api/routers/groups.py`
- Modify: `dashboard/api/main.py`
- Test: `tests/dashboard/test_sqlite_service.py`

- [ ] **Step 1: Write SQLite fixture tests**

Create `tests/dashboard/test_sqlite_service.py`:

```python
import json
import sqlite3

from dashboard.api.services.sqlite_service import SQLiteService


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE players (user_id TEXT, group_id TEXT, nickname TEXT, level TEXT, favorability INTEGER, last_seen TEXT, profile_json TEXT)")
    conn.execute("CREATE TABLE messages (user_id TEXT, group_id TEXT, message TEXT, timestamp TEXT)")
    conn.execute("CREATE TABLE nicknames (user_id TEXT, group_id TEXT, nickname TEXT, first_seen TEXT, last_seen TEXT)")
    conn.execute("CREATE TABLE member_relations (user_id TEXT, target_user_id TEXT, group_id TEXT, interaction_count INTEGER, last_interaction_time TEXT)")
    conn.execute("INSERT INTO players VALUES (?, ?, ?, ?, ?, ?, ?)", ("u1", "g1", "Saka", "核心首发", 230, "2026-05-22", json.dumps({"style": "winger"})))
    conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?)", ("u1", "g1", "hello", "2026-05-22 10:00:00"))
    conn.execute("INSERT INTO nicknames VALUES (?, ?, ?, ?, ?)", ("u1", "g1", "Starboy", "2026-05-01", "2026-05-22"))
    conn.commit()
    conn.close()


def test_list_groups(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    service = SQLiteService(str(db_path))
    groups = service.list_groups()
    assert groups[0]["group_id"] == "g1"
    assert groups[0]["user_count"] == 1
    assert groups[0]["message_count"] == 1


def test_user_detail(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    service = SQLiteService(str(db_path))
    detail = service.get_user_detail("g1", "u1")
    assert detail["user"]["nickname"] == "Saka"
    assert detail["profile"]["style"] == "winger"
    assert detail["nicknames"][0]["nickname"] == "Starboy"
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/dashboard/test_sqlite_service.py -v
```

Expected: import failure for missing service.

- [ ] **Step 3: Implement SQLite service**

Create `dashboard/api/services/sqlite_service.py`:

```python
import json
import os
import sqlite3
from typing import Any, Dict, List


class SQLiteService:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def is_available(self) -> bool:
        return os.path.exists(self.db_path)

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_groups(self) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT p.group_id,
                       COUNT(DISTINCT p.user_id) AS user_count,
                       COUNT(m.message) AS message_count,
                       MAX(COALESCE(m.timestamp, p.last_seen)) AS last_activity
                FROM players p
                LEFT JOIN messages m ON p.group_id = m.group_id AND p.user_id = m.user_id
                GROUP BY p.group_id
                ORDER BY last_activity DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_users(self, group_id: str) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT p.user_id, p.group_id, p.nickname, p.level, p.favorability, p.last_seen,
                       COUNT(m.message) AS message_count
                FROM players p
                LEFT JOIN messages m ON p.group_id = m.group_id AND p.user_id = m.user_id
                WHERE p.group_id = ?
                GROUP BY p.user_id, p.group_id, p.nickname, p.level, p.favorability, p.last_seen
                ORDER BY p.favorability DESC
                """,
                (group_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_user_detail(self, group_id: str, user_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            user = conn.execute(
                "SELECT * FROM players WHERE group_id = ? AND user_id = ?",
                (group_id, user_id),
            ).fetchone()
            nicknames = conn.execute(
                "SELECT nickname, first_seen, last_seen FROM nicknames WHERE group_id = ? AND user_id = ? ORDER BY last_seen DESC",
                (group_id, user_id),
            ).fetchall()
            messages = conn.execute(
                "SELECT message, timestamp FROM messages WHERE group_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 20",
                (group_id, user_id),
            ).fetchall()
            relations = conn.execute(
                "SELECT target_user_id, interaction_count, last_interaction_time FROM member_relations WHERE group_id = ? AND user_id = ? ORDER BY interaction_count DESC LIMIT 20",
                (group_id, user_id),
            ).fetchall()
        user_dict = dict(user) if user else None
        profile = {}
        if user_dict and user_dict.get("profile_json"):
            try:
                profile = json.loads(user_dict["profile_json"])
            except ValueError:
                profile = {"raw": user_dict["profile_json"]}
        return {
            "user": user_dict,
            "profile": profile,
            "nicknames": [dict(row) for row in nicknames],
            "messages": [dict(row) for row in messages],
            "relations": [dict(row) for row in relations],
        }
```

- [ ] **Step 4: Implement groups router**

Create `dashboard/api/routers/groups.py`:

```python
from fastapi import APIRouter, Depends

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.sqlite_service import SQLiteService

router = APIRouter(prefix="/api/groups", tags=["groups"], dependencies=[Depends(require_auth)])


def _service() -> SQLiteService:
    return SQLiteService(get_settings().db_path)


@router.get("")
def list_groups():
    return ok(_service().list_groups())


@router.get("/{group_id}/users")
def list_users(group_id: str):
    return ok(_service().list_users(group_id))


@router.get("/{group_id}/users/{user_id}")
def user_detail(group_id: str, user_id: str):
    return ok(_service().get_user_detail(group_id, user_id))
```

- [ ] **Step 5: Register router**

Modify `dashboard/api/main.py` to import and register:

```python
from dashboard.api.routers import auth, groups

app.include_router(auth.router)
app.include_router(groups.router)
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/dashboard/test_sqlite_service.py tests/dashboard/test_api_auth.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add dashboard/api/services/sqlite_service.py dashboard/api/routers/groups.py dashboard/api/main.py tests/dashboard/test_sqlite_service.py
git commit -m "feat: expose dashboard group profile data"
```

---

## Task 4: Docs service and API

**Files:**
- Create: `dashboard/api/services/docs_service.py`
- Create: `dashboard/api/routers/docs.py`
- Modify: `dashboard/api/main.py`
- Test: `tests/dashboard/test_docs_service.py`

- [ ] **Step 1: Write docs service tests**

Create `tests/dashboard/test_docs_service.py`:

```python
from dashboard.api.services.docs_service import DocsService


def test_tree_and_read_markdown(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\nHello Arteta", encoding="utf-8")
    service = DocsService([str(docs)])
    tree = service.tree()
    assert tree[0]["name"] == "docs"
    content = service.read_file("docs/guide.md")
    assert "Hello Arteta" in content["content"]


def test_path_traversal_rejected(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    service = DocsService([str(docs)])
    try:
        service.read_file("docs/../secret.txt")
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("path traversal was not rejected")


def test_search(tmp_path):
    docs = tmp_path / "knowledge_base"
    docs.mkdir()
    (docs / "tactics.md").write_text("# Press\nHigh press wins the ball", encoding="utf-8")
    service = DocsService([str(docs)])
    results = service.search("press")
    assert results[0]["path"] == "knowledge_base/tactics.md"
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/dashboard/test_docs_service.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement docs service**

Create `dashboard/api/services/docs_service.py`:

```python
import os
from typing import Dict, List


class DocsService:
    def __init__(self, roots: List[str]):
        self.roots = [os.path.abspath(root) for root in roots]
        self.root_names = {os.path.basename(root): root for root in self.roots}

    def _resolve(self, relative_path: str) -> str:
        parts = relative_path.replace("\\", "/").split("/", 1)
        if not parts or parts[0] not in self.root_names:
            raise ValueError("path not allowed")
        root = self.root_names[parts[0]]
        tail = parts[1] if len(parts) > 1 else ""
        target = os.path.abspath(os.path.join(root, tail))
        if target != root and not target.startswith(root + os.sep):
            raise ValueError("path not allowed")
        return target

    def tree(self) -> List[Dict[str, object]]:
        return [self._tree_root(root) for root in self.roots if os.path.isdir(root)]

    def _tree_root(self, root: str) -> Dict[str, object]:
        name = os.path.basename(root)
        children = []
        for entry in sorted(os.listdir(root)):
            full = os.path.join(root, entry)
            if os.path.isdir(full):
                children.append(self._tree_node(root, full))
            elif entry.endswith(".md"):
                children.append({"type": "file", "name": entry, "path": name + "/" + entry})
        return {"type": "directory", "name": name, "path": name, "children": children}

    def _tree_node(self, root: str, path: str) -> Dict[str, object]:
        root_name = os.path.basename(root)
        rel = os.path.relpath(path, root).replace("\\", "/")
        node_path = root_name + "/" + rel
        children = []
        for entry in sorted(os.listdir(path)):
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                children.append(self._tree_node(root, full))
            elif entry.endswith(".md"):
                children.append({"type": "file", "name": entry, "path": node_path + "/" + entry})
        return {"type": "directory", "name": os.path.basename(path), "path": node_path, "children": children}

    def read_file(self, relative_path: str) -> Dict[str, str]:
        target = self._resolve(relative_path)
        if not target.endswith(".md") or not os.path.isfile(target):
            raise ValueError("path not allowed")
        with open(target, "r", encoding="utf-8") as f:
            return {"path": relative_path.replace("\\", "/"), "content": f.read()}

    def search(self, query: str) -> List[Dict[str, str]]:
        needle = query.lower().strip()
        if not needle:
            return []
        results = []
        for root in self.roots:
            root_name = os.path.basename(root)
            for current, _, files in os.walk(root):
                for filename in files:
                    if not filename.endswith(".md"):
                        continue
                    full = os.path.join(current, filename)
                    with open(full, "r", encoding="utf-8") as f:
                        text = f.read()
                    idx = text.lower().find(needle)
                    if idx >= 0:
                        rel = os.path.relpath(full, root).replace("\\", "/")
                        start = max(0, idx - 80)
                        end = min(len(text), idx + 160)
                        results.append({"path": root_name + "/" + rel, "excerpt": text[start:end]})
        return results[:50]
```

- [ ] **Step 4: Implement docs router**

Create `dashboard/api/routers/docs.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.docs_service import DocsService

router = APIRouter(prefix="/api/docs", tags=["docs"], dependencies=[Depends(require_auth)])


def _service() -> DocsService:
    return DocsService(get_settings().docs_roots)


@router.get("/tree")
def tree():
    return ok(_service().tree())


@router.get("/file")
def file(path: str = Query(...)):
    try:
        return ok(_service().read_file(path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/search")
def search(q: str = Query(...)):
    return ok(_service().search(q))
```

- [ ] **Step 5: Register router**

Modify `dashboard/api/main.py` imports and registration:

```python
from dashboard.api.routers import auth, docs, groups

app.include_router(docs.router)
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/dashboard/test_docs_service.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add dashboard/api/services/docs_service.py dashboard/api/routers/docs.py dashboard/api/main.py tests/dashboard/test_docs_service.py
git commit -m "feat: add dashboard documentation browser API"
```

---

## Task 5: Environment key masking and save API

**Files:**
- Create: `dashboard/api/services/audit_service.py`
- Create: `dashboard/api/services/env_service.py`
- Create: `dashboard/api/routers/config.py`
- Modify: `dashboard/api/main.py`
- Test: `tests/dashboard/test_env_service.py`

- [ ] **Step 1: Write env service tests**

Create `tests/dashboard/test_env_service.py`:

```python
from dashboard.api.services.env_service import EnvService


def test_mask_and_update_whitelisted_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=sk-abcdef123456\nOTHER=value\n", encoding="utf-8")
    service = EnvService(str(env_file), ["DEEPSEEK_API_KEY"])
    values = service.list_masked()
    assert values[0]["name"] == "DEEPSEEK_API_KEY"
    assert values[0]["exists"] is True
    assert values[0]["masked"].startswith("sk-")
    assert "abcdef" not in values[0]["masked"]

    service.update("DEEPSEEK_API_KEY", "sk-newvalue9999")
    text = env_file.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=sk-newvalue9999" in text
    assert "OTHER=value" in text


def test_reject_non_whitelisted_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER=value\n", encoding="utf-8")
    service = EnvService(str(env_file), ["DEEPSEEK_API_KEY"])
    try:
        service.update("OTHER", "new")
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("non-whitelisted key was accepted")
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/dashboard/test_env_service.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement audit service**

Create `dashboard/api/services/audit_service.py`:

```python
import os
from datetime import datetime
from typing import Optional


class AuditService:
    def __init__(self, path: str):
        self.path = path

    def record(self, action: str, target: str, result: str, actor: Optional[str] = "admin") -> None:
        parent = os.path.dirname(self.path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        line = "{} | actor={} | action={} | target={} | result={}\n".format(
            datetime.now().isoformat(timespec="seconds"), actor, action, target, result
        )
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)
```

- [ ] **Step 4: Implement env service**

Create `dashboard/api/services/env_service.py`:

```python
import os
from typing import Dict, List


class EnvService:
    def __init__(self, env_file: str, whitelist: List[str]):
        self.env_file = env_file
        self.whitelist = list(whitelist)

    def _read_lines(self) -> List[str]:
        if not os.path.exists(self.env_file):
            return []
        with open(self.env_file, "r", encoding="utf-8") as f:
            return f.read().splitlines()

    def _parse(self) -> Dict[str, str]:
        values = {}
        for line in self._read_lines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    def _mask(self, value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return value[:2] + "****"
        return value[:3] + "****" + value[-4:]

    def list_masked(self) -> List[Dict[str, object]]:
        values = self._parse()
        return [
            {"name": key, "exists": bool(values.get(key)), "masked": self._mask(values.get(key, ""))}
            for key in self.whitelist
        ]

    def update(self, key: str, value: str) -> None:
        if key not in self.whitelist:
            raise ValueError("key not allowed")
        lines = self._read_lines()
        new_line = key + "=" + value
        replaced = False
        output = []
        for line in lines:
            if line.strip().startswith(key + "="):
                output.append(new_line)
                replaced = True
            else:
                output.append(line)
        if not replaced:
            output.append(new_line)
        parent = os.path.dirname(self.env_file)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        with open(self.env_file, "w", encoding="utf-8") as f:
            f.write("\n".join(output) + "\n")
```

- [ ] **Step 5: Implement config router**

Create `dashboard/api/routers/config.py`:

```python
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException

from dashboard.api.config import ENV_WHITELIST, get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.audit_service import AuditService
from dashboard.api.services.env_service import EnvService

router = APIRouter(prefix="/api/config", tags=["config"], dependencies=[Depends(require_auth)])


class UpdateConfigRequest(BaseModel):
    name: str
    value: str


def _env_service() -> EnvService:
    return EnvService(get_settings().env_file, ENV_WHITELIST)


@router.get("/keys")
def keys():
    return ok(_env_service().list_masked())


@router.post("/keys")
def update_key(request: UpdateConfigRequest):
    settings = get_settings()
    if settings.readonly:
        raise HTTPException(status_code=403, detail="readonly mode")
    audit = AuditService(settings.audit_log_path)
    try:
        _env_service().update(request.name, request.value)
    except ValueError as exc:
        audit.record("config.update", request.name, "rejected")
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record("config.update", request.name, "ok")
    return ok({"name": request.name})
```

- [ ] **Step 6: Register router**

Modify `dashboard/api/main.py` imports and registration:

```python
from dashboard.api.routers import auth, config, docs, groups

app.include_router(config.router)
```

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/dashboard/test_env_service.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add dashboard/api/services/audit_service.py dashboard/api/services/env_service.py dashboard/api/routers/config.py dashboard/api/main.py tests/dashboard/test_env_service.py
git commit -m "feat: add masked dashboard config management"
```

---

## Task 6: Logs service and API

**Files:**
- Create: `dashboard/api/services/logs_service.py`
- Create: `dashboard/api/routers/logs.py`
- Modify: `dashboard/api/main.py`

- [ ] **Step 1: Implement logs service**

Create `dashboard/api/services/logs_service.py`:

```python
import os
from typing import Dict, List


class LogsService:
    def __init__(self, logs_dir: str):
        self.logs_dir = os.path.abspath(logs_dir)

    def _resolve(self, name: str) -> str:
        target = os.path.abspath(os.path.join(self.logs_dir, name))
        if target != self.logs_dir and not target.startswith(self.logs_dir + os.sep):
            raise ValueError("path not allowed")
        return target

    def list_logs(self) -> List[Dict[str, object]]:
        if not os.path.isdir(self.logs_dir):
            return []
        logs = []
        for name in sorted(os.listdir(self.logs_dir)):
            if not name.startswith("arteta_bot") and not name.startswith("dashboard_audit"):
                continue
            full = os.path.join(self.logs_dir, name)
            if os.path.isfile(full):
                logs.append({"name": name, "size": os.path.getsize(full), "mtime": os.path.getmtime(full)})
        return logs

    def tail(self, name: str, limit: int = 200) -> List[str]:
        target = self._resolve(name)
        if not os.path.isfile(target):
            return []
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        return lines[-limit:]
```

- [ ] **Step 2: Implement logs router**

Create `dashboard/api/routers/logs.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.logs_service import LogsService

router = APIRouter(prefix="/api/logs", tags=["logs"], dependencies=[Depends(require_auth)])


def _service() -> LogsService:
    return LogsService(get_settings().logs_dir)


@router.get("")
def list_logs():
    return ok(_service().list_logs())


@router.get("/tail")
def tail(name: str = Query("arteta_bot.log"), limit: int = Query(200)):
    try:
        return ok({"name": name, "lines": _service().tail(name, limit)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
```

- [ ] **Step 3: Register router**

Modify `dashboard/api/main.py` imports and registration:

```python
from dashboard.api.routers import auth, config, docs, groups, logs

app.include_router(logs.router)
```

- [ ] **Step 4: Manually smoke test**

Run API:

```bash
python -m uvicorn dashboard.api.main:app --reload --port 8765
```

Expected: server starts. After logging in, `GET /api/logs` returns a normalized `ok` response.

- [ ] **Step 5: Commit**

```bash
git add dashboard/api/services/logs_service.py dashboard/api/routers/logs.py dashboard/api/main.py
git commit -m "feat: expose dashboard log viewer API"
```

---

## Task 7: Verification service and API

**Files:**
- Create: `dashboard/api/services/verify_service.py`
- Create: `dashboard/api/routers/verify.py`
- Modify: `dashboard/api/main.py`
- Test: `tests/dashboard/test_verify_service.py`

- [ ] **Step 1: Write verify service tests**

Create `tests/dashboard/test_verify_service.py`:

```python
from dashboard.api.services.verify_service import VerifyService


def test_build_args_for_suite_and_case(tmp_path):
    service = VerifyService(str(tmp_path))
    args = service.build_args(["core", "render"], ["html_to_image"], online=False, allow_side_effects=False)
    assert args.count("--suite") == 2
    assert "core" in args
    assert "render" in args
    assert "--case" in args
    assert "html_to_image" in args
    assert "--online" not in args


def test_build_args_rejects_unknown_suite(tmp_path):
    service = VerifyService(str(tmp_path))
    try:
        service.build_args(["bad"], [], online=False, allow_side_effects=False)
    except ValueError as exc:
        assert "suite" in str(exc)
    else:
        raise AssertionError("unknown suite accepted")
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/dashboard/test_verify_service.py -v
```

Expected: import failure.

- [ ] **Step 3: Implement verify service**

Create `dashboard/api/services/verify_service.py`:

```python
import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional


ALLOWED_SUITES = set(["core", "render", "memory", "chat", "commands", "online", "all"])


class VerifyService:
    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        self.script_path = os.path.join(repo_root, "tools", "verify_features.py")
        self.runs = {}

    def build_args(self, suites: List[str], cases: List[str], online: bool, allow_side_effects: bool) -> List[str]:
        args = []
        for suite in suites or ["core"]:
            if suite not in ALLOWED_SUITES:
                raise ValueError("unknown suite: " + suite)
            args.extend(["--suite", suite])
        for case in cases:
            args.extend(["--case", case])
        if online:
            args.append("--online")
        if allow_side_effects:
            args.append("--allow-side-effects")
        return args

    def start_run(self, suites: List[str], cases: List[str], online: bool, allow_side_effects: bool) -> str:
        run_id = str(int(time.time() * 1000))
        args = [sys.executable, self.script_path] + self.build_args(suites, cases, online, allow_side_effects)
        process = subprocess.Popen(
            args,
            cwd=self.repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.runs[run_id] = {"process": process, "args": args}
        return run_id

    def stream_lines(self, run_id: str):
        process = self.runs[run_id]["process"]
        assert process.stdout is not None
        for line in process.stdout:
            yield line.rstrip("\n")
        process.wait()
        yield "[dashboard] verification exited with code {}".format(process.returncode)

    def latest_report(self) -> Optional[Dict[str, object]]:
        verify_root = os.path.join(self.repo_root, "artifacts", "verify")
        if not os.path.isdir(verify_root):
            return None
        runs = sorted(os.listdir(verify_root), reverse=True)
        for run in runs:
            report = os.path.join(verify_root, run, "report.json")
            if os.path.isfile(report):
                with open(report, "r", encoding="utf-8") as f:
                    return json.load(f)
        return None
```

- [ ] **Step 4: Implement verify router**

Create `dashboard/api/routers/verify.py`:

```python
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dashboard.api.config import REPO_ROOT, get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.audit_service import AuditService
from dashboard.api.services.verify_service import VerifyService

router = APIRouter(prefix="/api/verify", tags=["verify"], dependencies=[Depends(require_auth)])
service = VerifyService(REPO_ROOT)


class StartVerifyRequest(BaseModel):
    suites: List[str] = ["core"]
    cases: List[str] = []
    online: bool = False
    allow_side_effects: bool = False


@router.post("/runs")
def start_run(request: StartVerifyRequest):
    try:
        run_id = service.start_run(request.suites, request.cases, request.online, request.allow_side_effects)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    AuditService(get_settings().audit_log_path).record("verify.start", run_id, "ok")
    return ok({"run_id": run_id})


@router.get("/runs/{run_id}/events")
def events(run_id: str):
    def event_stream():
        for line in service.stream_lines(run_id):
            yield "data: " + line.replace("\n", " ") + "\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/latest-report")
def latest_report():
    return ok(service.latest_report())
```

- [ ] **Step 5: Register router**

Modify `dashboard/api/main.py` imports and registration:

```python
from dashboard.api.routers import auth, config, docs, groups, logs, verify

app.include_router(verify.router)
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/dashboard/test_verify_service.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add dashboard/api/services/verify_service.py dashboard/api/routers/verify.py dashboard/api/main.py tests/dashboard/test_verify_service.py
git commit -m "feat: run feature verification from dashboard API"
```

---

## Task 8: Chroma memory service and API

**Files:**
- Create: `dashboard/api/services/chroma_service.py`
- Create: `dashboard/api/routers/memories.py`
- Modify: `dashboard/api/main.py`

- [ ] **Step 1: Implement Chroma service**

Create `dashboard/api/services/chroma_service.py`:

```python
import os
from typing import Dict, List


class ChromaService:
    def __init__(self, chroma_dir: str):
        self.chroma_dir = chroma_dir
        self.collection_name = "group_memories"

    def _collection(self):
        import chromadb
        from chromadb.config import Settings
        client = chromadb.PersistentClient(path=self.chroma_dir, settings=Settings(anonymized_telemetry=False))
        return client.get_collection(self.collection_name)

    def health(self) -> Dict[str, object]:
        if not os.path.isdir(self.chroma_dir):
            return {"available": False, "collection": self.collection_name, "count": 0}
        try:
            collection = self._collection()
            return {"available": True, "collection": self.collection_name, "count": collection.count()}
        except Exception as exc:
            return {"available": False, "collection": self.collection_name, "error": str(exc), "count": 0}

    def list_memories(self, group_id: str = "", limit: int = 100) -> List[Dict[str, object]]:
        collection = self._collection()
        where = {"group_id": group_id} if group_id else None
        result = collection.get(where=where, limit=limit, include=["documents", "metadatas"])
        return self._rows(result)

    def query(self, group_id: str, text: str, limit: int = 10) -> List[Dict[str, object]]:
        collection = self._collection()
        where = {"group_id": group_id} if group_id else None
        result = collection.query(query_texts=[text], n_results=limit, where=where, include=["documents", "metadatas", "distances"])
        rows = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for idx, doc_id in enumerate(ids):
            rows.append({"id": doc_id, "document": docs[idx], "metadata": metas[idx], "distance": distances[idx]})
        return rows

    def delete(self, ids: List[str]) -> int:
        collection = self._collection()
        collection.delete(ids=ids)
        return len(ids)

    def _rows(self, result) -> List[Dict[str, object]]:
        rows = []
        ids = result.get("ids", [])
        docs = result.get("documents", [])
        metas = result.get("metadatas", [])
        for idx, doc_id in enumerate(ids):
            document = docs[idx] if idx < len(docs) else ""
            rows.append({"id": doc_id, "document": document, "metadata": metas[idx], "preview": document[:120]})
        return rows
```

- [ ] **Step 2: Implement memories router**

Create `dashboard/api/routers/memories.py`:

```python
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from dashboard.api.config import get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.audit_service import AuditService
from dashboard.api.services.chroma_service import ChromaService

router = APIRouter(prefix="/api/memories", tags=["memories"], dependencies=[Depends(require_auth)])


class DeleteRequest(BaseModel):
    ids: List[str]


def _service() -> ChromaService:
    return ChromaService(get_settings().chroma_dir)


@router.get("/health")
def health():
    return ok(_service().health())


@router.get("")
def list_memories(group_id: str = Query(""), limit: int = Query(100)):
    return ok(_service().list_memories(group_id, limit))


@router.get("/search")
def search(q: str = Query(...), group_id: str = Query(""), limit: int = Query(10)):
    return ok(_service().query(group_id, q, limit))


@router.post("/delete")
def delete(request: DeleteRequest):
    settings = get_settings()
    if settings.readonly:
        raise HTTPException(status_code=403, detail="readonly mode")
    count = _service().delete(request.ids)
    AuditService(settings.audit_log_path).record("memory.delete", ",".join(request.ids), "ok")
    return ok({"deleted": count})
```

- [ ] **Step 3: Register router**

Modify `dashboard/api/main.py` imports and registration:

```python
from dashboard.api.routers import auth, config, docs, groups, logs, memories, verify

app.include_router(memories.router)
```

- [ ] **Step 4: Manual smoke test**

Run:

```bash
python -m uvicorn dashboard.api.main:app --reload --port 8765
```

Expected: authenticated `GET /api/memories/health` returns collection availability without crashing even if ChromaDB is unavailable.

- [ ] **Step 5: Commit**

```bash
git add dashboard/api/services/chroma_service.py dashboard/api/routers/memories.py dashboard/api/main.py
git commit -m "feat: add Chroma memory management API"
```

---

## Task 9: Overview API

**Files:**
- Create: `dashboard/api/routers/overview.py`
- Modify: `dashboard/api/main.py`

- [ ] **Step 1: Implement overview router**

Create `dashboard/api/routers/overview.py`:

```python
import os

from fastapi import APIRouter, Depends

from dashboard.api.config import ENV_WHITELIST, get_settings
from dashboard.api.schemas import ok
from dashboard.api.security import require_auth
from dashboard.api.services.chroma_service import ChromaService
from dashboard.api.services.env_service import EnvService
from dashboard.api.services.logs_service import LogsService
from dashboard.api.services.sqlite_service import SQLiteService
from dashboard.api.services.verify_service import VerifyService
from dashboard.api.config import REPO_ROOT

router = APIRouter(prefix="/api/overview", tags=["overview"], dependencies=[Depends(require_auth)])


@router.get("")
def overview():
    settings = get_settings()
    sqlite_service = SQLiteService(settings.db_path)
    groups = sqlite_service.list_groups()
    logs = LogsService(settings.logs_dir).list_logs()
    keys = EnvService(settings.env_file, ENV_WHITELIST).list_masked()
    report = VerifyService(REPO_ROOT).latest_report()
    return ok({
        "paths": {
            "db": {"path": settings.db_path, "exists": os.path.exists(settings.db_path)},
            "chroma": {"path": settings.chroma_dir, "exists": os.path.isdir(settings.chroma_dir)},
            "logs": {"path": settings.logs_dir, "exists": os.path.isdir(settings.logs_dir)},
            "env": {"path": settings.env_file, "exists": os.path.exists(settings.env_file)},
        },
        "groups": {"count": len(groups), "items": groups[:5]},
        "chroma": ChromaService(settings.chroma_dir).health(),
        "logs": {"count": len(logs), "items": logs[:5]},
        "config": {"keys": keys},
        "latest_report": report,
        "readonly": settings.readonly,
    })
```

- [ ] **Step 2: Register overview router**

Modify `dashboard/api/main.py` imports and registration:

```python
from dashboard.api.routers import auth, config, docs, groups, logs, memories, overview, verify

app.include_router(overview.router)
```

- [ ] **Step 3: Smoke test overview**

Run API and call authenticated `GET /api/overview`.

Expected: response includes `paths`, `groups`, `chroma`, `logs`, `config`, `latest_report`, and `readonly`.

- [ ] **Step 4: Commit**

```bash
git add dashboard/api/routers/overview.py dashboard/api/main.py
git commit -m "feat: add Mission Control overview API"
```

---

## Task 10: Frontend Vite foundation and API client

**Files:**
- Create all frontend foundation files listed below.

- [ ] **Step 1: Create `dashboard/web/package.json`**

```json
{
  "name": "arteta-dashboard-web",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@vitejs/plugin-react": "latest",
    "vite": "latest",
    "typescript": "latest",
    "react": "latest",
    "react-dom": "latest"
  },
  "devDependencies": {}
}
```

- [ ] **Step 2: Create TypeScript and Vite config**

Create `dashboard/web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": []
}
```

Create `dashboard/web/vite.config.ts`:

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765'
    }
  }
});
```

- [ ] **Step 3: Create HTML entry**

Create `dashboard/web/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Arteta Mission Control</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 4: Create API types and client**

Create `dashboard/web/src/api/types.ts`:

```ts
export type ApiResponse<T> = {
  ok: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
};

export type StatusCardState = 'ok' | 'warn' | 'error' | 'idle';
```

Create `dashboard/web/src/api/client.ts`:

```ts
import type { ApiResponse } from './types';

const TOKEN_KEY = 'arteta_dashboard_token';

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Authorization: `Bearer ${getToken()}` }
  });
  if (response.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  const body = (await response.json()) as ApiResponse<T>;
  if (!body.ok) {
    throw new Error(body.error?.message || 'API error');
  }
  return body.data as T;
}

export async function apiPost<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`
    },
    body: JSON.stringify(payload)
  });
  if (response.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  const body = (await response.json()) as ApiResponse<T>;
  if (!body.ok) {
    throw new Error(body.error?.message || 'API error');
  }
  return body.data as T;
}
```

- [ ] **Step 5: Create main React entry**

Create `dashboard/web/src/main.tsx`:

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

- [ ] **Step 6: Create placeholder app**

Create `dashboard/web/src/App.tsx`:

```tsx
export function App() {
  return <div className="app"><h1>ARTETA MISSION CONTROL</h1></div>;
}
```

- [ ] **Step 7: Create SpaceX-style CSS base**

Create `dashboard/web/src/styles.css`:

```css
:root {
  color: #f5f7fb;
  background: #05070a;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

body {
  margin: 0;
  min-height: 100vh;
  background:
    linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px),
    radial-gradient(circle at top right, rgba(54, 116, 255, 0.20), transparent 32%),
    #05070a;
  background-size: 48px 48px, 48px 48px, auto, auto;
}

button, input, select {
  font: inherit;
}

.app {
  min-height: 100vh;
  padding: 32px;
}

.panel {
  border: 1px solid rgba(255,255,255,0.18);
  background: rgba(10, 14, 20, 0.82);
  box-shadow: 0 0 40px rgba(0,0,0,0.35);
}

.status-ok { color: #37f29b; }
.status-warn { color: #ffbe3d; }
.status-error { color: #ff4d5b; }
.status-idle { color: #7aa2ff; }
```

- [ ] **Step 8: Install and build**

Run:

```bash
cd dashboard/web && npm install && npm run build
```

Expected: Vite build succeeds.

- [ ] **Step 9: Commit**

```bash
git add dashboard/web
git commit -m "feat: scaffold dashboard React frontend"
```

---

## Task 11: Frontend shell, login, and Mission Control overview

**Files:**
- Create: `dashboard/web/src/components/Shell.tsx`
- Create: `dashboard/web/src/components/StatusCard.tsx`
- Create: `dashboard/web/src/pages/LoginPage.tsx`
- Create: `dashboard/web/src/pages/MissionControlPage.tsx`
- Modify: `dashboard/web/src/App.tsx`

- [ ] **Step 1: Create shell component**

Create `dashboard/web/src/components/Shell.tsx`:

```tsx
import type { ReactNode } from 'react';

type ShellProps = {
  page: string;
  onNavigate: (page: string) => void;
  children: ReactNode;
};

const pages = [
  ['overview', 'MISSION CONTROL'],
  ['groups', 'GROUP PROFILES'],
  ['memories', 'CHROMA MEMORY'],
  ['verify', 'VERIFY CENTER'],
  ['docs', 'DOCS LIBRARY'],
  ['logs', 'LIVE LOGS'],
  ['config', 'CONFIG']
];

export function Shell({ page, onNavigate, children }: ShellProps) {
  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">ARTETA BOT</div>
          <h1>MISSION CONTROL</h1>
        </div>
        <nav>
          {pages.map(([id, label]) => (
            <button key={id} className={page === id ? 'active' : ''} onClick={() => onNavigate(id)}>{label}</button>
          ))}
        </nav>
      </header>
      <main>{children}</main>
    </div>
  );
}
```

- [ ] **Step 2: Create status card component**

Create `dashboard/web/src/components/StatusCard.tsx`:

```tsx
import type { ReactNode } from 'react';
import type { StatusCardState } from '../api/types';

type Props = {
  title: string;
  state: StatusCardState;
  value: string;
  children?: ReactNode;
};

export function StatusCard({ title, state, value, children }: Props) {
  return (
    <section className="panel status-card">
      <div className={`status-light status-${state}`}>●</div>
      <h2>{title}</h2>
      <strong>{value}</strong>
      {children && <div className="status-detail">{children}</div>}
    </section>
  );
}
```

- [ ] **Step 3: Create login page**

Create `dashboard/web/src/pages/LoginPage.tsx`:

```tsx
import { useState } from 'react';
import { apiPost, setToken } from '../api/client';

export function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError('');
    try {
      const data = await apiPost<{ token: string }>('/api/auth/login', { password });
      setToken(data.token);
      onLogin();
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败');
    }
  }

  return (
    <div className="login-page">
      <form className="panel login-panel" onSubmit={submit}>
        <div className="eyebrow">SECURE ACCESS</div>
        <h1>ARTETA MISSION CONTROL</h1>
        <input type="password" value={password} onChange={event => setPassword(event.target.value)} placeholder="Dashboard admin password" />
        <button type="submit">AUTHENTICATE</button>
        {error && <p className="error-text">{error}</p>}
      </form>
    </div>
  );
}
```

- [ ] **Step 4: Create overview page**

Create `dashboard/web/src/pages/MissionControlPage.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { apiGet } from '../api/client';
import { StatusCard } from '../components/StatusCard';

type Overview = {
  paths: Record<string, { path: string; exists: boolean }>;
  groups: { count: number };
  chroma: { available: boolean; count: number };
  logs: { count: number };
  readonly: boolean;
};

export function MissionControlPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    apiGet<Overview>('/api/overview').then(setOverview).catch(err => setError(String(err)));
  }, []);

  if (error) return <div className="panel page-panel">{error}</div>;
  if (!overview) return <div className="panel page-panel">Loading telemetry...</div>;

  return (
    <div className="grid">
      <StatusCard title="SQLITE DATA" state={overview.paths.db.exists ? 'ok' : 'error'} value={overview.paths.db.exists ? 'ONLINE' : 'MISSING'}>{overview.paths.db.path}</StatusCard>
      <StatusCard title="CHROMA MEMORY" state={overview.chroma.available ? 'ok' : 'warn'} value={`${overview.chroma.count} RECORDS`} />
      <StatusCard title="GROUPS" state="idle" value={`${overview.groups.count} GROUPS`} />
      <StatusCard title="LOG FILES" state={overview.logs.count ? 'ok' : 'warn'} value={`${overview.logs.count} FILES`} />
      <StatusCard title="MODE" state={overview.readonly ? 'warn' : 'ok'} value={overview.readonly ? 'READ ONLY' : 'MAINTENANCE READY'} />
    </div>
  );
}
```

- [ ] **Step 5: Wire App routing state**

Replace `dashboard/web/src/App.tsx`:

```tsx
import { useState } from 'react';
import { getToken } from './api/client';
import { Shell } from './components/Shell';
import { LoginPage } from './pages/LoginPage';
import { MissionControlPage } from './pages/MissionControlPage';

export function App() {
  const [authenticated, setAuthenticated] = useState(Boolean(getToken()));
  const [page, setPage] = useState('overview');

  if (!authenticated) {
    return <LoginPage onLogin={() => setAuthenticated(true)} />;
  }

  return (
    <Shell page={page} onNavigate={setPage}>
      {page === 'overview' && <MissionControlPage />}
      {page !== 'overview' && <div className="panel page-panel">{page.toUpperCase()} module pending</div>}
    </Shell>
  );
}
```

- [ ] **Step 6: Add shell CSS**

Append to `dashboard/web/src/styles.css`:

```css
.topbar { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 28px; }
.eyebrow { color: #7aa2ff; letter-spacing: 0.24em; font-size: 12px; }
h1 { margin: 4px 0 0; letter-spacing: 0.08em; }
nav { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
nav button, form button { background: transparent; color: #f5f7fb; border: 1px solid rgba(255,255,255,0.24); padding: 10px 12px; cursor: pointer; }
nav button.active, form button:hover { border-color: #7aa2ff; box-shadow: 0 0 18px rgba(122,162,255,0.24); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
.status-card { padding: 18px; position: relative; min-height: 140px; }
.status-light { position: absolute; top: 14px; right: 16px; }
.status-card h2 { font-size: 13px; color: #9aa6bd; letter-spacing: 0.18em; }
.status-card strong { display: block; font-size: 26px; margin: 18px 0; }
.status-detail { color: #9aa6bd; font-size: 12px; overflow-wrap: anywhere; }
.login-page { min-height: 100vh; display: grid; place-items: center; }
.login-panel { width: min(460px, calc(100vw - 48px)); padding: 28px; display: grid; gap: 16px; }
.login-panel input { background: #090d13; border: 1px solid rgba(255,255,255,0.22); color: #f5f7fb; padding: 12px; }
.error-text { color: #ff4d5b; }
.page-panel { padding: 24px; }
```

- [ ] **Step 7: Build frontend**

```bash
cd dashboard/web && npm run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 8: Commit**

```bash
git add dashboard/web/src
git commit -m "feat: add dashboard login and mission control UI"
```

---

## Task 12: Frontend module pages

**Files:**
- Create/modify all page files under `dashboard/web/src/pages/`
- Create: `dashboard/web/src/components/ConfirmDialog.tsx`
- Modify: `dashboard/web/src/App.tsx`

- [ ] **Step 1: Create confirm dialog**

Create `dashboard/web/src/components/ConfirmDialog.tsx`:

```tsx
type Props = {
  title: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({ title, message, onConfirm, onCancel }: Props) {
  return (
    <div className="modal-backdrop">
      <div className="panel modal">
        <h2>{title}</h2>
        <p>{message}</p>
        <div className="actions">
          <button onClick={onCancel}>CANCEL</button>
          <button onClick={onConfirm}>CONFIRM</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create Groups page**

Create `dashboard/web/src/pages/GroupsPage.tsx` with group list, user list, and user detail using `/api/groups`, `/api/groups/{group_id}/users`, and `/api/groups/{group_id}/users/{user_id}`.

Use this initial implementation:

```tsx
import { useEffect, useState } from 'react';
import { apiGet } from '../api/client';

type Group = { group_id: string; user_count: number; message_count: number; last_activity: string | null };
type User = { user_id: string; nickname: string; level: string; favorability: number; message_count: number };

export function GroupsPage() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [selectedGroup, setSelectedGroup] = useState('');
  const [detail, setDetail] = useState<unknown>(null);

  useEffect(() => { apiGet<Group[]>('/api/groups').then(setGroups); }, []);

  async function loadUsers(groupId: string) {
    setSelectedGroup(groupId);
    setDetail(null);
    setUsers(await apiGet<User[]>(`/api/groups/${groupId}/users`));
  }

  async function loadDetail(userId: string) {
    setDetail(await apiGet<unknown>(`/api/groups/${selectedGroup}/users/${userId}`));
  }

  return (
    <div className="three-column">
      <section className="panel page-panel"><h2>GROUPS</h2>{groups.map(group => <button key={group.group_id} onClick={() => loadUsers(group.group_id)}>{group.group_id} · {group.user_count} users</button>)}</section>
      <section className="panel page-panel"><h2>USERS</h2>{users.map(user => <button key={user.user_id} onClick={() => loadDetail(user.user_id)}>{user.nickname || user.user_id} · {user.level} · {user.favorability}</button>)}</section>
      <section className="panel page-panel"><h2>PROFILE</h2><pre>{detail ? JSON.stringify(detail, null, 2) : 'Select a user'}</pre></section>
    </div>
  );
}
```

- [ ] **Step 3: Create Memories page**

Create `dashboard/web/src/pages/MemoriesPage.tsx` using `/api/memories`, `/api/memories/search`, and `/api/memories/delete`. Include confirm dialog before delete.

- [ ] **Step 4: Create Verify page**

Create `dashboard/web/src/pages/VerifyPage.tsx` with suite checkboxes, start button, EventSource subscription to `/api/verify/runs/{run_id}/events`, and latest report display from `/api/verify/latest-report`.

- [ ] **Step 5: Create Docs page**

Create `dashboard/web/src/pages/DocsPage.tsx` with tree, search input, markdown text preview from `/api/docs/file`, and search results from `/api/docs/search`.

- [ ] **Step 6: Create Logs page**

Create `dashboard/web/src/pages/LogsPage.tsx` with log selector from `/api/logs` and line display from `/api/logs/tail`.

- [ ] **Step 7: Create Config page**

Create `dashboard/web/src/pages/ConfigPage.tsx` using `/api/config/keys`; updates call `/api/config/keys` after confirmation. Each key row has masked value, exists state, and a new-value password input.

- [ ] **Step 8: Wire pages in App**

Modify `dashboard/web/src/App.tsx` imports and rendering:

```tsx
import { ConfigPage } from './pages/ConfigPage';
import { DocsPage } from './pages/DocsPage';
import { GroupsPage } from './pages/GroupsPage';
import { LogsPage } from './pages/LogsPage';
import { MemoriesPage } from './pages/MemoriesPage';
import { VerifyPage } from './pages/VerifyPage';

// inside Shell
{page === 'overview' && <MissionControlPage />}
{page === 'groups' && <GroupsPage />}
{page === 'memories' && <MemoriesPage />}
{page === 'verify' && <VerifyPage />}
{page === 'docs' && <DocsPage />}
{page === 'logs' && <LogsPage />}
{page === 'config' && <ConfigPage />}
```

- [ ] **Step 9: Add module CSS**

Append layout styles to `dashboard/web/src/styles.css`:

```css
.three-column { display: grid; grid-template-columns: 280px 320px 1fr; gap: 16px; }
.page-panel button { display: block; width: 100%; text-align: left; margin: 8px 0; background: transparent; color: #f5f7fb; border: 1px solid rgba(255,255,255,0.16); padding: 10px; }
pre { white-space: pre-wrap; overflow: auto; color: #d8e1f5; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.72); display: grid; place-items: center; }
.modal { width: min(480px, calc(100vw - 48px)); padding: 24px; }
.actions { display: flex; gap: 12px; justify-content: flex-end; }
```

- [ ] **Step 10: Build frontend**

```bash
cd dashboard/web && npm run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 11: Commit**

```bash
git add dashboard/web/src
git commit -m "feat: add dashboard management pages"
```

---

## Task 13: End-to-end smoke and documentation

**Files:**
- Create: `docs/dev/developer-dashboard.md`
- Modify: `docs/ops/deployment.md`
- Modify: `README.md`

- [ ] **Step 1: Run backend tests**

```bash
python -m pytest tests/dashboard -v
```

Expected: all dashboard backend tests pass.

- [ ] **Step 2: Build frontend**

```bash
cd dashboard/web && npm run build
```

Expected: build passes.

- [ ] **Step 3: Run existing project verification**

```bash
python tools/verify_features.py --suite core
```

Expected: core verification passes or reports only documented local dependency skips.

- [ ] **Step 4: Create developer dashboard docs**

Create `docs/dev/developer-dashboard.md`:

```markdown
# Developer Mission Control Dashboard

The dashboard is an internal developer frontend for Arteta Bot. It provides authenticated access to group profile data, ChromaDB memory management, feature verification runs, documentation browsing, logs, and masked API key configuration.

## Development

Start the API:

```bash
set DASHBOARD_ADMIN_PASSWORD=change-me
set DASHBOARD_SECRET_KEY=dev-secret
python -m uvicorn dashboard.api.main:app --reload --port 8765
```

Start the frontend:

```bash
cd dashboard/web
npm install
npm run dev
```

Open the Vite URL and log in with `DASHBOARD_ADMIN_PASSWORD`.

## Safety

The dashboard is intended for LAN/server-internal use. Do not expose it directly to the public internet. API keys are masked and never returned in plaintext. Chroma deletion and API key saves require confirmation and are written to `logs/dashboard_audit.log`.

## Read-only Mode

Set `DASHBOARD_READONLY=true` to disable Chroma deletion and API key saves.
```
```

- [ ] **Step 5: Update deployment docs**

Add a short section to `docs/ops/deployment.md`:

```markdown
## Developer Dashboard

The developer dashboard is optional and should only be exposed on a trusted LAN or behind an authenticated internal reverse proxy.

Required environment variables:

```bash
DASHBOARD_ADMIN_PASSWORD=change-me
DASHBOARD_SECRET_KEY=random-long-secret
DASHBOARD_ALLOWED_ORIGINS=http://your-internal-host:5173
```

Start API:

```bash
python -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8765
```

Build frontend:

```bash
cd dashboard/web
npm install
npm run build
```
```

- [ ] **Step 6: Update README doc pointer**

Add under README documentation navigation:

```markdown
- 🛰️ [开发者前端](Docs/dev/developer-dashboard.md) — Mission Control 风格开发者面板
```

If the repository uses lowercase `docs/` on disk, use the existing README link style consistently.

- [ ] **Step 7: Commit docs**

```bash
git add docs/dev/developer-dashboard.md docs/ops/deployment.md README.md
git commit -m "docs: document developer dashboard"
```

---

## Task 14: Final acceptance pass

**Files:**
- Modify only files needed for fixes discovered during acceptance.

- [ ] **Step 1: Start backend**

```bash
set DASHBOARD_ADMIN_PASSWORD=change-me
set DASHBOARD_SECRET_KEY=dev-secret
python -m uvicorn dashboard.api.main:app --reload --port 8765
```

Expected: FastAPI starts without import errors.

- [ ] **Step 2: Start frontend**

```bash
cd dashboard/web && npm run dev
```

Expected: Vite starts and proxies `/api` to FastAPI.

- [ ] **Step 3: Manual browser checks**

Open the Vite local URL and verify:

- Login rejects wrong password.
- Login accepts `change-me`.
- Mission Control overview loads.
- Groups page loads without crashing.
- Docs page can open a Markdown file.
- Logs page lists logs or shows an empty state.
- Config page shows masked keys.
- Verify page can run `core` and stream output.

- [ ] **Step 4: Run all automated checks**

```bash
python -m pytest tests/dashboard -v
python tools/verify_features.py --suite core
cd dashboard/web && npm run build
```

Expected: pytest passes, core verification passes or only skips optional dependencies, frontend build passes.

- [ ] **Step 5: Commit fixes if any**

If acceptance required fixes:

```bash
git add <fixed-files>
git commit -m "fix: stabilize developer dashboard acceptance"
```

If no fixes were needed, do not create an empty commit.

---

## Self-Review

### Spec coverage

- Authentication: Tasks 2, 11.
- Mission Control overview: Tasks 9, 11.
- Group profiles: Tasks 3, 12.
- Chroma visualization and deletion: Tasks 8, 12.
- Verification center: Tasks 7, 12.
- Documentation browser: Tasks 4, 12.
- Real-time logs: Tasks 6, 12.
- API key configuration: Tasks 5, 12.
- Audit logging: Tasks 5, 7, 8.
- Security boundaries and path traversal: Tasks 4, 5, 8.
- Testing and documentation: Tasks 13, 14.

### Placeholder scan

This plan intentionally leaves no feature as unspecified work. The only broad frontend task is Task 12, but it names every page, endpoint, behavior, and build check needed for completion.

### Type consistency

Backend uses normalized `{ ok, data, error }` responses through `ok()`. Frontend `ApiResponse<T>` matches that shape. Auth token storage and `Authorization: Bearer` usage match `require_auth()`.
