# ECS Dashboard Deployment Design

## Goal

Run the Arteta Bot developer dashboard directly on the ECS server so all management pages operate on the live server-side resources instead of local synced copies.

This replaces the current primary workflow of running the dashboard locally with `-EcsSync`. The sync script may remain as a debugging or offline read-only fallback, but it will no longer be the recommended management path.

## Scope

In scope:

- Deploy the existing FastAPI dashboard API on ECS as a separate managed service.
- Build and serve the React/Vite dashboard frontend from ECS.
- Make group profiles, Chroma memories, logs, and config pages read from and write to ECS-local paths.
- Add production path configuration for logs and frontend build output.
- Add startup protection for unsafe public production configuration.
- Update deployment and dashboard documentation.
- Add automated tests for config, static frontend serving, and production safety behavior.

Out of scope:

- Creating a separate remote dashboard agent service.
- Keeping local-to-ECS SQLite sync as the main workflow.
- Adding role-based access control beyond the existing admin login.
- Adding HTTPS or Nginx reverse proxy in this iteration.

## Architecture

The dashboard runs as a new ECS process, separate from the bot process:

```text
Browser
  -> http://ECS_HOST:8765
  -> FastAPI dashboard service
      -> /opt/arteta_bot/arsenal_data.db
      -> /opt/arteta_bot/chroma_db
      -> /opt/arteta_bot/logs
      -> /opt/arteta_bot/.env
      -> dashboard/web/dist
```

The FastAPI app remains the single backend boundary. The browser calls same-origin `/api/*` endpoints and receives the React application from the same service.

## Runtime Configuration

The dashboard service uses environment variables:

| Variable | Purpose | Production value |
| --- | --- | --- |
| `DASHBOARD_HOST` | Bind host | `0.0.0.0` |
| `DASHBOARD_PORT` | Bind port | `8765` |
| `DASHBOARD_ADMIN_PASSWORD` | Login password | Required, strong value |
| `DASHBOARD_SECRET_KEY` | JWT signing key | Required in public mode |
| `DASHBOARD_PUBLIC` | Enables public-mode safety checks | `true` |
| `DASHBOARD_READONLY` | Disable destructive writes | `false` unless intentionally read-only |
| `ARTETA_DB_PATH` | SQLite path | `/opt/arteta_bot/arsenal_data.db` |
| `ARTETA_CHROMA_DIR` | Chroma path | `/opt/arteta_bot/chroma_db` |
| `DASHBOARD_LOGS_DIR` | Logs path | `/opt/arteta_bot/logs` |
| `DASHBOARD_ENV_FILE` | Env file path | `/opt/arteta_bot/.env` |
| `DASHBOARD_WEB_DIST` | Frontend build output | `/opt/arteta_bot/dashboard/web/dist` |

`DASHBOARD_PUBLIC=true` means the app refuses to start if `DASHBOARD_SECRET_KEY` is missing or still using the development fallback. Login already fails when `DASHBOARD_ADMIN_PASSWORD` is empty; that behavior stays.

## Backend Changes

### FastAPI app

`dashboard/api/main.py` will continue to mount the existing routers:

- `/api/auth`
- `/api/groups`
- `/api/memories`
- `/api/verify`
- `/api/docs`
- `/api/logs`
- `/api/config`
- `/api/overview`

It will also serve the built frontend when `DASHBOARD_WEB_DIST` exists:

- Static asset paths are served from the build directory.
- Non-API paths fall back to `index.html` so the React single-page app works on refresh.
- `/api/*` paths are never swallowed by the frontend fallback.

### Settings

`dashboard/api/config.py` will add:

- `public: bool`
- `web_dist: str`
- configurable `logs_dir` via `DASHBOARD_LOGS_DIR`

The existing defaults remain developer-friendly for local use.

### Groups

`/api/groups` already reads from `ARTETA_DB_PATH`. On ECS this points to the live database, so profile edits persist directly to the server database. Existing read-only protection remains available through `DASHBOARD_READONLY=true`.

### Memories

`/api/memories` already reads from `ARTETA_CHROMA_DIR`. On ECS this points to the live ChromaDB directory, so list/search/delete operations reflect the server memory store.

### Logs

`/api/logs` will read from `DASHBOARD_LOGS_DIR`. This avoids the current hard-coded repository-local logs path and lets the ECS dashboard inspect `/opt/arteta_bot/logs`.

### Config

`/api/config` will continue to use `DASHBOARD_ENV_FILE` and the existing whitelist. Updates write directly to the server env file and continue to record audit entries.

## Frontend Changes

The existing React pages remain the source of truth:

- `MissionControlPage`
- `GroupsPage`
- `MemoriesPage`
- `VerifyPage`
- `DocsPage`
- `LogsPage`
- `ConfigPage`

The production frontend is built with:

```bash
npm --prefix dashboard/web install
npm --prefix dashboard/web run build
```

The built files are served by the FastAPI dashboard process. Frontend API calls remain same-origin `/api/*`, so no additional CORS setup is needed for production.

## Deployment Design

Add or extend an ECS deployment path that performs these steps:

1. Upload or update dashboard source files on ECS.
2. Install Python dependencies required by the dashboard.
3. Install frontend dependencies and build `dashboard/web/dist`.
4. Write a Supervisor program named `arteta_dashboard`.
5. Start or restart only `arteta_dashboard`.
6. Leave the bot process managed separately.

Supervisor configuration should set all dashboard env variables explicitly and run:

```bash
python -m uvicorn dashboard.api.main:app --host 0.0.0.0 --port 8765
```

The existing bot Supervisor program should not be coupled to dashboard restarts.

## Security Design

- The dashboard may bind a public port, but it must require login for all `/api/*` management endpoints.
- `DASHBOARD_ADMIN_PASSWORD` is required for access.
- `DASHBOARD_SECRET_KEY` is required when `DASHBOARD_PUBLIC=true`.
- JWT TTL remains 8 hours.
- Destructive operations keep the existing frontend confirmation dialogs.
- Backend write routes continue to honor `DASHBOARD_READONLY=true`.
- Audit logging remains enabled for profile updates, profile deletes, Chroma deletes, and config updates.
- API keys are never returned in plaintext; config endpoints continue to return masked values only.

## Error Handling

- Missing SQLite path: overview shows the database as missing; groups return empty or controlled errors instead of crashing the whole app.
- Missing Chroma path: overview and memories health show unavailable.
- Missing logs directory: logs API returns an empty list.
- Missing frontend dist: API remains available; root route can return a clear dashboard build-missing response.
- Config update failure: the old env file content must remain intact, and the API returns a clear error.
- Unauthorized requests: frontend clears the token and returns to login, preserving existing behavior.

## Testing Plan

Automated tests:

- `dashboard/api/config.py` reads `DASHBOARD_LOGS_DIR`, `DASHBOARD_WEB_DIST`, and `DASHBOARD_PUBLIC`.
- Public mode refuses unsafe missing/default JWT secrets.
- FastAPI serves `index.html` from the configured web dist.
- SPA fallback does not intercept `/api/*` routes.
- Existing groups, memories, logs, config, and overview tests continue to pass.
- Deployment script or generated Supervisor config includes the ECS live paths and dashboard env variables.

Build checks:

```bash
python -m pytest tests/dashboard -v
npm --prefix dashboard/web run build
```

Manual ECS verification:

1. Start `arteta_dashboard` on ECS.
2. Log in through the public dashboard URL.
3. Open group profiles and edit a test user profile.
4. Refresh and verify the edit persists in the ECS SQLite database.
5. Search and delete a test Chroma memory.
6. Tail ECS logs from the logs page.
7. Confirm config keys are masked and updates are audited.
8. Restart the dashboard without restarting the bot process.

## Migration Notes

- `start_dashboard.ps1 -EcsSync` remains useful for local read-only troubleshooting but is no longer the recommended dashboard workflow.
- Documentation should describe the ECS-hosted dashboard as the primary path.
- Existing local dashboard development remains supported with Vite and local FastAPI defaults.
