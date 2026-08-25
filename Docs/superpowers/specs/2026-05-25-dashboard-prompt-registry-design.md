# Dashboard Prompt Registry Design

## Goal

Add a Prompt management column to the Developer Dashboard so maintainers can edit Arteta Bot persona and feature prompts directly from the browser, grouped by function, then deploy the same configuration to ECS for the live bot and dashboard chat.

The primary user need is fast prompt iteration without editing Python source files or redeploying code for every wording change.

## Scope

In scope:

- Add a Dashboard navigation item named `Prompt 人设`.
- Store editable prompt entries in a fixed JSON registry file.
- Let the Dashboard list, create, edit, disable, restore, and delete prompt entries where safe.
- Cover the known bot prompt surfaces:
  - main QQ group conversation persona
  - Dashboard bot-chat persona/debug prompt
  - profile analysis prompt
  - daily summary prompt
  - weekly report prompt
  - algorithm/science coaching prompt
- Make runtime code read prompt overrides by key while keeping code defaults as fallback.
- Deploy the prompt registry file and Dashboard changes to ECS.
- Add tests for backend prompt registry behavior and frontend build safety.

Out of scope:

- Full prompt version history UI.
- Multi-user approval workflow.
- Automatic prompt quality scoring.
- Editing arbitrary files from the Dashboard.
- Making newly created prompt keys executable without code binding.

## Chosen Approach

Use a file-based Prompt Registry.

Local default path:

```text
config/prompts.json
```

ECS production path:

```text
/opt/arteta_bot/config/prompts.json
```

Runtime path is configured by:

```text
ARTETA_PROMPTS_FILE=/opt/arteta_bot/config/prompts.json
```

If `ARTETA_PROMPTS_FILE` is absent, the service uses the repository-local `config/prompts.json`.

This approach keeps prompt data separate from code, supports multiline editing naturally, avoids environment-variable abuse, and is simpler than introducing database migrations for this iteration.

## Registry Format

The registry stores an object with a version and entries:

```json
{
  "version": 1,
  "entries": [
    {
      "key": "arteta.main",
      "title": "主对话人设",
      "category": "主对话",
      "content": "...",
      "variables": [],
      "enabled": true,
      "builtin": true
    }
  ]
}
```

Fields:

| Field | Meaning |
| --- | --- |
| `key` | Stable runtime key used by Python code. |
| `title` | Human-readable label in Dashboard. |
| `category` | UI grouping, such as 主对话 or 定时总结. |
| `content` | Multiline prompt text. |
| `variables` | Required `.format(...)` placeholders for prompts that interpolate data. |
| `enabled` | Whether this registry entry may override the code default. |
| `builtin` | Whether the key is a known system prompt. |

Built-in keys for the first version:

| Key | Default source | Category | Variables |
| --- | --- | --- | --- |
| `arteta.main` | `plugins/arteta_chat.py` `ARTETA_PROMPT` | 主对话 | none |
| `arteta.dashboard_chat` | `dashboard/api/services/bot_chat_service.py` dashboard chat prompt | Dashboard 对话 | none |
| `profile.analysis` | `plugins/arteta_chat.py` `PROFILE_ANALYSIS_PROMPT` | 画像分析 | `current_profile`, `count`, `messages` |
| `daily.summary` | `plugins/arteta_daily.py` `SUMMARY_PROMPT` | 定时总结 | existing summary placeholders |
| `weekly.report` | `plugins/arteta_weekly.py` `WEEKLY_PROMPT` | 周报 | `articles` |
| `algo.coach` | algorithm/science prompt in bot and Dashboard chat flows | 理科解题 | none or `raw_text`, depending on final extraction |

New user-created keys can be stored and edited but are informational until code explicitly binds to them.

## Backend Design

Add:

```text
dashboard/api/routers/prompts.py
dashboard/api/services/prompt_service.py
```

The router is mounted under:

```text
/api/prompts
```

Endpoints:

| Endpoint | Behavior |
| --- | --- |
| `GET /api/prompts` | List all registry entries plus default metadata for missing built-ins. |
| `POST /api/prompts` | Create a user-defined entry with a unique key. |
| `PUT /api/prompts/{key}` | Update title, category, content, variables, and enabled state. |
| `POST /api/prompts/{key}/restore` | Restore a built-in entry to the current code default. |
| `DELETE /api/prompts/{key}` | Delete user-defined entries; built-ins are disabled/restored instead of physically deleted. |

Safety rules:

- The service only reads and writes `ARTETA_PROMPTS_FILE`; the API never accepts a filesystem path.
- Writes are blocked when `DASHBOARD_READONLY=true`.
- Every write records an audit entry in `logs/dashboard_audit.log`.
- Built-in keys cannot be physically deleted.
- Empty enabled content is rejected for built-in runtime keys.
- Invalid JSON on disk does not crash the Dashboard; the API returns defaults and records a warning.
- Atomic writes preserve the previous registry if saving fails.

## Frontend Design

Add `Prompt 人设` to `dashboard/web/src/components/Shell.tsx` and render a new `PromptPage` from `App.tsx`.

The page layout:

- Left side: category list and prompt entries.
- Main panel: multiline editor for the selected entry.
- Metadata controls: title, category, enabled toggle, variables list.
- Action buttons: save, restore default, disable, delete where allowed.
- Built-in prompt badge for runtime-bound entries.
- Warning text that only known built-in keys are executed by the bot.

Save behavior:

- Dirty state is visible before saving.
- Saving requires frontend confirmation.
- Backend errors are shown inline.
- Successful saves refresh the entry list from the backend.

Variable behavior:

- Built-in prompts show expected variables.
- If content appears to use `{placeholder}` values not declared for that key, the frontend warns before saving and the backend performs the final validation.

## Runtime Design

Add a shared prompt registry loader that can be used by both bot plugins and Dashboard services.

Runtime lookup contract:

```python
get_prompt(key, default, variables=None) -> str
```

Behavior:

1. Load the registry from `ARTETA_PROMPTS_FILE`.
2. Find the matching key.
3. Use the entry only when it is enabled and content is non-empty.
4. Validate required variables before formatting.
5. Fall back to the code default if the file is missing, JSON is invalid, the key is disabled, content is empty, or variable validation fails.
6. Log a warning when fallback is caused by invalid registry state.

The main conversation prompt still appends dynamic runtime context after the editable persona block. The Dashboard should not expose dynamic state such as current time, group ID, image analysis, Chroma memories, or squad snapshot as freely deletable prompt entries; those remain code-managed context blocks.

## ECS Deployment Design

Production deployment should:

1. Upload changed backend files, frontend source, and built frontend assets.
2. Upload the default prompt registry template to `/opt/arteta_bot/config/prompts.json` if it does not already exist.
3. Avoid overwriting an existing production prompt registry unless explicitly requested.
4. Ensure the directory `/opt/arteta_bot/config` exists and is writable by the runtime user.
5. Add `ARTETA_PROMPTS_FILE=/opt/arteta_bot/config/prompts.json` to both bot and dashboard Supervisor environments.
6. Restart `arteta_dashboard` first.
7. Verify `Prompt 人设` can load and save.
8. Restart `arteta_bot` so QQ runtime reads the same registry.

The deployment script must preserve live prompt edits by default.

## Testing Plan

Backend tests:

- Missing registry returns all built-in defaults.
- Valid registry overrides a built-in prompt.
- Disabled built-in falls back to code default.
- User-defined entries can be created and deleted.
- Built-in entries cannot be physically deleted.
- Read-only mode rejects write operations.
- Invalid JSON does not crash listing.
- Saving performs atomic write.
- Required variables are validated for formatted prompts.

Frontend checks:

```bash
npm --prefix dashboard/web run build
```

Dashboard/backend checks:

```bash
python -m pytest tests/dashboard -v
```

Manual ECS verification:

1. Open the public or restricted Dashboard URL.
2. Enter `Prompt 人设`.
3. Edit a non-critical wording in `arteta.dashboard_chat`.
4. Save and confirm audit logging.
5. Use `机器人对话` to verify the Dashboard chat reflects the change.
6. Edit `arteta.main`, restart `arteta_bot`, and verify QQ conversation reflects the change.
7. Disable a built-in prompt and verify runtime falls back to the code default instead of crashing.

## Documentation Updates

Update:

- `docs/dev/developer-dashboard.md` with the new Prompt module.
- `docs/ops/dashboard-public-deployment.md` with `ARTETA_PROMPTS_FILE` and deployment preservation behavior.
- `CLAUDE.md` only if the development workflow checklist needs to mention prompt registry updates.
