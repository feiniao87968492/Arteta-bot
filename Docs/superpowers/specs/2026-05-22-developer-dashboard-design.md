# Developer Mission Control Dashboard Design

## 1. Goal

Build an internal developer frontend for Arteta Bot: a SpaceX Mission Control-style dashboard that lets maintainers inspect bot data, review and clean ChromaDB memory, run local feature verification, browse documentation, watch logs, and manage API key configuration.

The first version targets LAN/server-internal use, not public internet exposure. It is a read-mostly tool with a small set of guarded write operations.

## 2. Chosen Approach

Use a same-repository, frontend/backend-separated dashboard:

```text
dashboard/
  api/        FastAPI management backend
  web/        React + Vite + TypeScript frontend
```

FastAPI is the only layer that touches local files, SQLite, ChromaDB, logs, environment files, and subprocesses. React only calls authenticated API endpoints.

Development runs the API and frontend separately. Internal deployment can still serve the built frontend through a static server or the FastAPI process if that simplifies operations.

## 3. Visual Direction

The UI follows a SpaceX Mission Control style rather than a conventional admin table-first layout:

- Black background and high-contrast white typography.
- Thin-line grid, panel borders, and telemetry-card composition.
- Red, blue, green, and amber status indicators.
- Dense operational cards on the landing page.
- Module detail pages for deeper inspection and actions.

The landing page is a Mission Control overview. Functional modules are entered from status cards and module panels.

## 4. First-Version Scope

### 4.1 Authentication

- Single administrator password.
- Password configured with `DASHBOARD_ADMIN_PASSWORD`.
- Backend issues a Session/JWT after login.
- All API endpoints require authentication except login and basic health.
- `DASHBOARD_SECRET_KEY` signs tokens.
- Multi-user RBAC is reserved for a later version.

### 4.2 Mission Control Overview

The overview page shows:

- SQLite, ChromaDB, logs, docs, and config path health.
- Latest verification run summary.
- Chroma collection stats: collection name, total records, group count, latest write time when available.
- Group stats: group count, user count, recent message volume.
- Log health: recent warning/error counts and last log timestamp.
- Configuration health: whether required keys exist, never their plaintext values.

### 4.3 Group Profiles

Backed by `arsenal_data.db`:

- List groups by `group_id` with user count, message count, and recent activity.
- List users in a selected group with QQ ID, nickname, favorability, level, message count, and last seen time.
- Show user detail with nickname history, profile JSON, recent messages, and relation data when present.
- First version is read-only for user profiles, favorability, and nicknames.

### 4.4 ChromaDB Memory Management

Backed by the `group_memories` Chroma collection:

- Filter memories by group.
- Search memories by keyword and provide a semantic search entry point.
- Show memory rows with ID, group ID, user ID, timestamp, preview, and document summary.
- Show full document and metadata in a detail panel.
- Support single delete and batch delete.
- Every delete requires frontend confirmation and backend audit logging.

### 4.5 Verification Center

Backed by `tools/verify_features.py`:

- Choose suites and cases: `core`, `render`, `memory`, `chat`, `commands`, `online`, `all`.
- Keep online checks and side-effect allowance as explicit separate switches.
- Start a verification run from the UI.
- Stream stdout/stderr to the frontend while the process runs.
- Use SSE for first-version log streaming because verification output is one-way.
- After completion, parse and display `report.json`, `summary.txt`, and artifact paths from `artifacts/verify/<timestamp>/`.
- Allow browsing text and image artifacts that are inside the run artifact directory.

### 4.6 Documentation Browser

Read-only visualization for:

- `docs/`
- `knowledge_base/`

Features:

- Directory tree navigation.
- Markdown preview.
- Full-text search with file path and excerpt results.
- Visual distinction between developer docs, ops docs, user docs, and knowledge-base content.

Editing, creating, and deleting Markdown files are out of first-version scope.

### 4.7 Real-Time Logs

Backed by project log files:

- Select current log and rotated logs from the allowed log directory.
- Tail the active log in real time.
- Filter by level: DEBUG, INFO, WARNING, ERROR, CRITICAL.
- Search by keyword.
- Expand a log line to inspect full content.

The first version does not restart the bot or manage Supervisor/Docker.

### 4.8 API Key Configuration

Only whitelisted environment variables are manageable, including:

- `DEEPSEEK_API_KEY`
- `FOOTBALL_API_TOKEN`
- `IMAGE_API_KEY`
- `IMAGE_API_URL`
- `IMAGE_MODEL`
- `VISION_MODEL`

Behavior:

- Show existence and masked value only, such as `sk-****abcd`.
- Never return plaintext secrets from the backend.
- Updating a secret requires entering the full new value.
- Save only whitelisted variables in the configured env file.
- Confirm before saving.
- Record every save attempt in the audit log.

No full `.env` free-form editor is included in the first version.

## 5. Backend Structure

```text
dashboard/api/
  main.py
  auth.py
  config.py
  routers/
    auth.py
    overview.py
    groups.py
    memories.py
    docs.py
    logs.py
    verify.py
    config.py
  services/
    sqlite_service.py
    chroma_service.py
    docs_service.py
    logs_service.py
    verify_service.py
    env_service.py
    audit_service.py
```

### 5.1 Service Boundaries

- `sqlite_service.py`: read-only access to `arsenal_data.db` for groups, users, messages, nicknames, profiles, and relations.
- `chroma_service.py`: ChromaDB collection inspection, search, and guarded deletion.
- `docs_service.py`: safe directory tree, Markdown read, and full-text search under allowed docs roots.
- `logs_service.py`: safe log listing, tailing, and filtered reads under allowed log roots.
- `verify_service.py`: subprocess management for `tools/verify_features.py`, SSE event buffering, and report/artifact parsing.
- `env_service.py`: whitelist-based masked config reads and writes.
- `audit_service.py`: append-only audit log for write operations and verification starts.

### 5.2 Router Boundaries

Routers expose resource-oriented endpoints and delegate all filesystem/database logic to services. Routers do not accept arbitrary filesystem paths for sensitive resources. They accept logical IDs or validated relative paths under fixed roots.

## 6. Data Flow

### 6.1 Authentication

1. User submits the administrator password.
2. Backend compares against `DASHBOARD_ADMIN_PASSWORD`.
3. Backend returns a signed token on success.
4. Frontend includes the token on subsequent API requests.
5. Expired or invalid tokens redirect to login.

### 6.2 Verification Run

1. Frontend posts suite/case/options.
2. Backend validates options against the known verification interface.
3. Backend starts `python tools/verify_features.py ...` as a subprocess.
4. Backend streams stdout/stderr events over SSE.
5. Backend records the final exit code and locates the latest run report.
6. Frontend renders live output, final case statuses, and artifacts.

### 6.3 Write Operations

First-version write operations are limited to:

- Chroma memory deletion.
- API key save.
- Verification task start.

Chroma deletion and API key save require:

- Frontend confirmation.
- Authenticated backend request.
- Backend-side validation.
- Audit log entry with timestamp, action, target, and result.

## 7. Security Requirements

- Intended deployment is LAN/server-internal only.
- Do not expose the dashboard directly to the public internet.
- If `DASHBOARD_ADMIN_PASSWORD` is missing, the backend must refuse unsafe operation. It may allow only local health checks.
- Use `DASHBOARD_SECRET_KEY` for token signing.
- API keys are never returned in plaintext.
- Environment editing is whitelist-only.
- Docs and logs access must reject path traversal.
- Artifact browsing must stay within a specific verification run artifact directory.
- Batch Chroma deletion must show the affected count before confirmation.
- `DASHBOARD_READONLY=true` disables Chroma deletion and API key save while preserving read-only inspection and verification viewing.

## 8. Configuration

Dashboard-specific environment variables:

```text
DASHBOARD_HOST
DASHBOARD_PORT
DASHBOARD_ADMIN_PASSWORD
DASHBOARD_SECRET_KEY
DASHBOARD_ALLOWED_ORIGINS
DASHBOARD_ENV_FILE
DASHBOARD_READONLY=false
```

The backend should also honor existing project isolation variables where relevant:

```text
ARTETA_DB_PATH
ARTETA_CHROMA_DIR
ARTETA_SWEARS_FILE
```

## 9. Error Handling

API errors use a consistent shape:

```json
{
  "ok": false,
  "error": {
    "code": "CHROMA_UNAVAILABLE",
    "message": "ChromaDB data directory is unavailable"
  }
}
```

Expected error categories include:

- `UNAUTHORIZED`
- `CONFIG_MISSING`
- `SQLITE_UNAVAILABLE`
- `CHROMA_UNAVAILABLE`
- `LOG_NOT_FOUND`
- `DOC_NOT_FOUND`
- `PATH_NOT_ALLOWED`
- `VERIFY_RUN_FAILED`
- `READONLY_MODE`
- `ENV_WRITE_FAILED`

The frontend should render actionable messages for each category and preserve raw details only where safe.

## 10. Testing and Acceptance

### 10.1 Backend Tests

- Authentication success/failure and token expiry.
- SQLite service against a temporary fixture database.
- Chroma service against an isolated Chroma directory.
- Docs/logs/artifacts path traversal rejection.
- Env service whitelist behavior and masking.
- Verify service command argument construction and report parsing.

### 10.2 Frontend Tests

- TypeScript build passes.
- API client handles success and normalized errors.
- Smoke coverage for login, overview, groups, memories, verification center, docs, logs, and config pages.

### 10.3 Manual Acceptance

- Login gates the dashboard and APIs.
- Mission Control overview shows data source health.
- Group profile pages list groups, users, and user details.
- Chroma page can view, search, single-delete, and batch-delete memories with confirmation.
- Verification center can run selected suites/cases and display live output plus reports.
- Documentation browser previews Markdown and searches docs/knowledge base.
- Logs page tails the current log and filters by level/keyword.
- Config page masks API keys and saves only complete newly entered values.
- Write actions produce audit log entries.

## 11. Version Roadmap

### v1: Developer Mission Control

Deliver the first-version scope above: read-mostly operations, Chroma deletion, API key save, verification runs, docs/logs visibility, and single-admin auth.

### v2: Management Enhancements

- Edit user profiles, favorability, nickname aliases.
- Markdown editor for docs and knowledge base.
- Chroma export/import, time-range cleanup, and backup restore.
- Multi-user RBAC.

### v3: Runtime Operations

- Bot start/stop/restart.
- NapCat connection status.
- Supervisor/Docker status.
- Deployment and backup task management.
- Alerting panel.

### v4: Analytics

- Group activity trends.
- Favorability history charts.
- User relation graph.
- Memory hit analysis.
- Verification result history.

## 12. Out of Scope for v1

- Public internet deployment.
- Multi-user permissions.
- User profile or favorability editing.
- Markdown editing.
- Bot restart or Supervisor/Docker control.
- Arbitrary file browsing.
- Full `.env` editor.
- Returning plaintext API keys.
