# Dashboard Provider Configuration Design

## Goal

Replace Dashboard's per-environment-variable API configuration editor with
independent provider configuration groups. A candidate provider configuration
must be verified with a real, minimal, side-effect-free request before it can
be saved. Applying a verified group atomically updates the group in `.env` and
immediately restarts `arteta_bot`.

The change prevents mixed URL, model, and API key combinations, eliminates
cross-provider credential fallbacks, and makes a failed update recoverable.

## Scope

The Dashboard manages these independent provider groups:

| Provider | Environment fields |
| --- | --- |
| Chat | `DEEPSEEK_API_URL`, `DEEPSEEK_MODEL`, `DEEPSEEK_API_KEY`, `DEEPSEEK_TEMPERATURE` |
| Algorithm solving | `ALGO_API_URL`, `ALGO_MODEL`, `ALGO_API_KEY` |
| Image generation | `IMAGE_API_URL`, `IMAGE_MODEL`, `IMAGE_API_KEY` |
| Vision | `VISION_API_URL`, `VISION_MODEL`, `VISION_API_KEY`, `VISION_TIMEOUT` |
| Football data | `FOOTBALL_API_TOKEN` |
| Grok search | `ARTETA_GROKSEARCH_API_URL`, `ARTETA_GROKSEARCH_MODEL`, `ARTETA_GROKSEARCH_API_KEY`, `ARTETA_GROKSEARCH_TIMEOUT` |
| X Fetch bridge | `ARTETA_X_FETCH_API_URL`, `ARTETA_X_FETCH_API_KEY` |

Only these groups are changed. Other Dashboard configuration remains under its
existing ownership. Existing SiliconFlow credentials remain an internal Vision
fallback and are not mixed with, exposed as, or overwritten by any editable
provider group.

## Provider Boundaries

Each group owns its URL, model where applicable, and secret. A runtime caller
may only use values from its own group:

- Vision reads `VISION_*` only. It must not fall back to `IMAGE_*`.
- Algorithm solving reads `ALGO_*` only. It must not fall back to
  `DEEPSEEK_*`.
- Dashboard Bot Chat and the QQ Bot use the same group boundary rules.
- Image generation continues to read `IMAGE_*`; Chat continues to read
  `DEEPSEEK_*`.

The legacy single-field update endpoint is removed. Agent configuration tools
must reject all provider-group environment fields so no caller can bypass group
validation, atomic persistence, or automatic restart.

## Dashboard UX

The Config page shows one card for each provider. A card includes its current
status, URL/model/token fields appropriate to that provider, a masked key
indicator, validation status, and two commands:

1. **Verify configuration** sends the complete in-memory candidate group to
   the Dashboard API. It never writes `.env`.
2. **Apply and restart bot** is enabled only after verification succeeds. Any
   field edit invalidates the result and disables apply until the candidate is
   verified again.

Keys are never returned in clear text. To apply a group, the operator re-enters
that group's complete secret material; URL and model values may be prefilled
from the saved configuration. The page removes the unrelated global bot restart
command.

## API Contract

The Config router exposes provider-oriented endpoints:

- `GET /api/config/providers` returns all provider groups, their non-secret
  values, masked secrets, and configuration state.
- `POST /api/config/providers/{provider}/validate` accepts one complete
  candidate group and returns a short-lived, one-time validation receipt on
  success.
- `POST /api/config/providers/{provider}/apply` accepts the unchanged
  candidate plus its receipt, atomically writes the group, and restarts
  `arteta_bot`.

The receipt binds an in-memory digest of the normalized candidate and provider
identifier to the authenticated caller. It expires after five minutes and is
consumed by apply. A receipt cannot be reused, used for another provider, or
used after changing any submitted field. It contains no provider secrets.

All requests and responses exclude plaintext keys. Audit records contain only
the provider name, action, success/failure state, and a safe error category;
they do not include credentials, request bodies, or provider response bodies.

## Verification Rules

Validation uses the submitted candidate values and the same URL conventions as
the production caller. It has no persistent business side effects:

- Chat and Algorithm solving call their supplied `chat/completions` endpoint
  with a fixed short prompt and `max_tokens=1`.
- Vision calls the existing Vision transport with an embedded 1x1 PNG and
  bounded output.
- Image generation uses a provider capability/model-list probe and checks the
  configured model when the provider returns a model list; it does not generate
  an image.
- Football data requests the Premier League standings endpoint.
- Grok search performs one fixed minimal search with at most one result.
- X Fetch bridge calls `/fetch` for one fixed public X URL and only checks that
  authentication succeeds and the response is valid JSON.

For URL handling, Chat and Algorithm fields are complete
`/v1/chat/completions` endpoints. Image generation, Vision, Grok search, and X
Fetch are base URLs; their existing transport helpers append the service path.
Timeout, authentication, model, transport, and response-shape failures all
reject validation without changing local state.

## Persistence, Restart, And Recovery

Applying a group follows this sequence:

1. Verify the receipt and candidate digest before any write.
2. Snapshot the current `.env` content.
3. Replace only the selected group's fields using a temporary file and atomic
   rename. Preserve comments and all unrelated variables.
4. Run the fixed command `supervisorctl restart arteta_bot`.
5. If restart succeeds, report the updated provider as active.
6. If restart fails, restore the exact snapshot using the same atomic write
   operation and run `supervisorctl restart arteta_bot` once more to restore
   the old runtime configuration.

The apply response reports whether persistence succeeded, whether the first
restart failed, and whether recovery restart succeeded. It never claims a
configuration is active until the first restart returns success. Read-only
Dashboard mode rejects apply and restart before writing any file.

## Runtime Changes

`EnvService` no longer updates process-wide `os.environ` as a side effect of a
provider edit. The QQ Bot reads the updated `.env` at startup after its restart;
Dashboard paths that need live provider configuration read the target env file
using the same grouped ownership rules.

All direct cross-group defaults are removed from `plugins/arteta_chat.py` and
`dashboard/api/services/bot_chat_service.py`. SiliconFlow is retained only as
the separately configured internal fallback inside `plugins/arteta_vision.py`.

## Test Plan

Automated tests cover:

- registry completeness, field masks, required-field validation, and each
  provider's request URL, headers, payload, and timeout through mocked HTTP
  transports;
- validation failures for credentials, timeouts, unsupported models, and bad
  response shapes with no `.env` mutation;
- validation receipt expiry, one-time use, provider binding, and candidate
  digest mismatch rejection;
- atomic group replacement while preserving unrelated environment entries and
  comments;
- write failure, first restart failure, rollback persistence, and recovery
  restart failure behavior;
- read-only rejection without writes or supervisor calls;
- Vision, Algorithm, and Dashboard Bot Chat regression tests proving no
  cross-group credential fallback;
- Config page grouping, field-change invalidation, verify-before-apply gating,
  and removal of the global restart control.

Verification commands after implementation:

```powershell
python -m pytest tests/dashboard -q
python -m pytest tests/test_arteta_vision_config.py tests/test_arteta_chat_vision.py tests/dashboard/test_bot_chat.py -q
npm --prefix dashboard/web run build
python -m py_compile dashboard/api/routers/config.py dashboard/api/services/env_service.py
```

## Documentation And Deployment

Update `Docs/dev/developer-dashboard.md` with group definitions, URL
conventions, validation behavior, automatic bot restart, and recovery semantics.
Update any affected operational deployment documentation with the new grouped
configuration workflow. Production deployment preserves the remote `.env`
snapshot until the Dashboard applies a verified group; database, Chroma, prompt,
and unrelated runtime files are never overwritten by this feature.

## Acceptance Criteria

1. Each editable external service is represented by exactly one independent
   configuration group.
2. A group cannot be applied until a real verification of that exact candidate
   succeeds.
3. Successful apply atomically persists the entire group and restarts
   `arteta_bot` automatically.
4. A failed verification, write, or restart does not leave a mixed provider
   configuration; restart failure restores the previous group and attempts a
   recovery restart.
5. No bot or Dashboard execution path shares URL, model, or API key values
   across the defined provider groups.
6. Secrets are never returned, logged, audited, or committed.
