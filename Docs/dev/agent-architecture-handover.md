# Arteta Bot Agent Architecture Handover

Date: 2026-07-12

## 1. Final Status

The Arteta Bot Agent architecture refactor is complete against `Docs/tasks/arteta_agent_planner_optimization.md`.

The public compatibility entrypoint is still:

```python
plugins.arteta_agent.planner.run_agent_loop(...)
```

`planner.py` is now only a compatibility wrapper around `AgentRequest` and `run_agent_request(...)`. The active architecture is split across Routing, Planning, Runtime, Provider, Response, Policy, Executor, Audit, and Tool modules.

Latest local commits at handover:

- `ba84ecf docs: record shared client deployment`
- `ace82b8 refactor: reuse shared client in agent tools`
- `2e89e88 docs: record legacy wrapper removal deployment`
- `4a4e210 refactor: remove legacy agent loop wrapper`

The latest code commit deployed to ECS is:

- `ace82b8 refactor: reuse shared client in agent tools`

## 2. What Was Completed

### Safety

- Dynamic external content is no longer placed into dynamic `system` messages.
- Tool results use standard assistant tool-call plus tool-result history where supported.
- Provider fallback for limited tool-history support moves dynamic tool data into user/data messages, not `system`.
- PDF, webpage, group message, attachment, tool result, and exception text are treated as untrusted data.
- Tool arguments are parsed and schema-validated before permission checks and handler execution.
- `confirm_write` and `admin_action` use PendingAction IDs and stored original arguments.
- Legacy `confirmed_tool` bypass is explicitly rejected.
- PendingAction consume is single-use and bound to user, group, tool, and arguments.
- `PermissionRequired` stops the runtime immediately and does not re-enter model planning.
- Tool body text cannot forge PermissionRequired state or artifact output.
- Artifact creation is based on structured `ToolResult.artifacts`, with legacy marker adaptation only for known artifact-producing tools.

### Runtime

- `AgentState`, `AgentRunConfig`, `AgentRuntimeRunner`, `LoopGuard`, and runtime service are implemented under `plugins/arteta_agent/runtime/`.
- Forced tools, required tools, ordinary model tool calls, and follow-up tool calls go through the unified runtime execution path.
- Runtime enforces:
  - max rounds;
  - max tool calls;
  - duplicate same-tool/same-args guard using canonical sorted JSON signatures;
  - observation character budget;
  - total request timeout;
  - stable stop behavior when the final round still returns tool calls.
- Parallel-safe read tools are executed concurrently with a configurable cap, while write/admin/confirmation actions remain serial.

### Routing And Planning

- Structured routing/planning models exist:
  - `Intent`;
  - `RouteDecision`;
  - `PlannedToolCall`;
  - `AgentPlan`.
- Multi-intent plans are supported, including:
  - remember preference plus document analysis;
  - group memory plus current fact verification;
  - document read plus web verification;
  - link analysis plus artifact generation;
  - same-turn independent read tools.
- Current factual football questions route through structured planning and prefer GrokSearch where configured.
- Broad words such as date, price, scoreline, and generic "how is it" no longer act as sufficient math/web force triggers by themselves.

### Provider And HTTP Lifecycle

- `OpenAICompatibleProvider` owns provider request encoding, response parsing, retry policy, capability flags, reasoning content, and tool-history compatibility.
- Main Agent and activation LLM calls reuse the shared async client from `plugins/arteta_agent/providers/http_client.py`.
- Agent web/document/image tools now also use the shared async client lifecycle.
- The only `httpx.AsyncClient` creation inside `plugins/arteta_agent` is the shared client factory.
- Application shutdown closes the shared client through the existing NoneBot shutdown hook.

### Policy

- Behavior Policy uses SQLite store semantics with TTL handling and JSON migration support.
- TTL semantics are fixed by tests:
  - `remaining_turns IS NULL` means permanent;
  - one successful main-agent turn consumes one turn;
  - activation rejection does not consume;
  - multi-tool runtime consumes only one turn;
  - permanent policies do not decrement.
- Policy service owns TTL consumption and emoji enablement decisions.

### Audit

- Persistent audit is connected for confirmation requests, confirmation execution, admin actions, permission denial, validation failure, tool timeout, tool exception, PendingAction consume, duplicate/expired confirmation rejection, and related executor paths.
- Audit details are structured and redacted: request/action/tool identifiers, permission level, argument keys, duration, status, and error code are recorded without raw prompts, full webpages/PDFs, cookies, API keys, or sensitive full arguments.

### Response

- Response composition, trace rendering, artifact marker finalization, and mood emoji post-processing are outside `planner.py`.
- Neutral/debug/math/document/error/permission-confirmation responses do not auto-send mood emoji.
- Emoji send failure does not affect the main response.

## 3. Key Files

Entrypoint:

- `plugins/arteta_agent/planner.py`
- `plugins/arteta_agent/service.py`

Runtime:

- `plugins/arteta_agent/runtime/state.py`
- `plugins/arteta_agent/runtime/runner.py`
- `plugins/arteta_agent/runtime/loop_guard.py`
- `plugins/arteta_agent/runtime/config.py`
- `plugins/arteta_agent/runtime/service.py`

Routing and planning:

- `plugins/arteta_agent/routing/models.py`
- `plugins/arteta_agent/routing/heuristic_router.py`
- `plugins/arteta_agent/routing/contextual_tools.py`
- `plugins/arteta_agent/planning/models.py`
- `plugins/arteta_agent/planning/plan_builder.py`
- `plugins/arteta_agent/planning/execution.py`

Provider and HTTP:

- `plugins/arteta_agent/providers/http_client.py`
- `plugins/arteta_agent/providers/openai_compatible.py`
- `plugins/arteta_agent/providers/chat_completion.py`

Response:

- `plugins/arteta_agent/response/composer.py`
- `plugins/arteta_agent/response/artifacts.py`
- `plugins/arteta_agent/response/mood.py`

Policy:

- `plugins/arteta_agent/behavior_policy.py`
- `plugins/arteta_agent/policy/service.py`

Security and execution:

- `plugins/arteta_agent/executor.py`
- `plugins/arteta_agent/pending.py`
- `plugins/arteta_agent/permissions.py`
- `plugins/arteta_agent/audit.py`
- `plugins/arteta_agent/result.py`
- `plugins/arteta_agent/registry.py`

Devlog:

- `Docs/dev/agent-architecture-devlog.md`

## 4. Verification Evidence

Latest local verification:

```powershell
python -m pytest tests/test_arteta_agent_provider.py -q
# 15 passed

python -m pytest tests/test_arteta_agent_runtime.py tests/test_arteta_agent_provider.py -q
# 30 passed

python -m pytest tests/test_arteta_agent_registry.py -q
# 183 passed, 3 warnings

python tools\verify_features.py --suite agent_loop
# passed

python tools\verify_features.py --suite chat
# passed

python tools\verify_features.py --suite agent_registry --suite agent_permissions
# passed

python -m pytest tests -q
# 537 passed, 1 warning
```

The remaining warning is the known Windows asyncio/proactor cleanup warning family. It predates the final slice and is not a failing test.

Latest static checks:

- No dynamic Agent tool/web/document/image HTTP client creation remains outside `providers/http_client.py`.
- No legacy `_answer_after_unavailable_web_result(...)`.
- No legacy `_answer_from_forced_tool_result(...)`.
- No service `run_legacy_agent_loop(...)`.
- No runtime `inspect.signature(call_llm_with_tools)` compatibility branch.
- Legacy `confirmed_tool` bypass appears only in rejection tests.

## 5. ECS Deployment Evidence

Latest deployed code commit:

- `ace82b8 refactor: reuse shared client in agent tools`

Latest remote backup:

- `/opt/arteta_bot/backups/agent_shared_http_client_20260712103302`

Remote deployment archive:

- `/tmp/arteta_agent_shared_client_ace82b8.tar.gz`

Remote compile check passed for:

- `plugins/arteta_agent/tools/document.py`
- `plugins/arteta_agent/tools/image.py`
- `plugins/arteta_agent/tools/web_access.py`
- `tests/test_arteta_agent_provider.py`
- `tests/test_arteta_agent_registry.py`

Remote service status after restart:

```text
arteta_bot       RUNNING
arteta_dashboard RUNNING
```

ECS smoke tests passed:

```bash
./venv/bin/python tools/verify_features.py --suite chat
./venv/bin/python tools/verify_features.py --suite agent_registry --suite agent_permissions
./venv/bin/python tools/verify_features.py --suite agent_loop
```

## 6. Current Local Working Tree Notes

At handover, local git status still shows unrelated pre-existing local state:

- `.env.dev` modified;
- many untracked historical deployment archives and `.deploy_temp_*` directories;
- local config backup files such as `config/agent_behavior_policy.json`.

These were intentionally not touched or committed during the final refactor closeout.

## 7. Operational Notes

Standard ECS deployment pattern used for the final slices:

```powershell
tar -czf <archive>.tar.gz <changed files>
scp <archive>.tar.gz arteta:/tmp/<archive>.tar.gz
ssh arteta "cd /opt/arteta_bot && mkdir -p /opt/arteta_bot/backups/<name>_$(date +%Y%m%d%H%M%S) && tar -xzf /tmp/<archive>.tar.gz -C /opt/arteta_bot"
ssh arteta "cd /opt/arteta_bot && ./venv/bin/python -m py_compile <changed python files>"
ssh arteta "supervisorctl restart arteta_bot arteta_dashboard && supervisorctl status arteta_bot arteta_dashboard"
```

Post-deploy smoke:

```bash
cd /opt/arteta_bot
./venv/bin/python tools/verify_features.py --suite chat
./venv/bin/python tools/verify_features.py --suite agent_registry --suite agent_permissions
./venv/bin/python tools/verify_features.py --suite agent_loop
```

## 8. Maintenance Guidance

When adding new Agent behavior:

- Add routing tests first when adding a new intent or changing forced routing.
- Add runtime tests first when changing tool execution order, permissions, timeout, or loop termination.
- Keep `planner.py` as compatibility entrypoint only.
- Do not add new `if ... return` forced branches to `planner.py`.
- Do not put external data into `system` messages.
- Do not parse artifacts or permission state from arbitrary tool body text.
- Add new artifact producers through structured `ToolResult.artifacts`.
- Use the shared HTTP client lifecycle for Agent provider/tool HTTP calls.
- Keep write/admin tools serial and permission-checked by the server.
- Keep Behavior Policy changes in the SQLite-backed policy layer.
- Record deployment and smoke evidence in `Docs/dev/agent-architecture-devlog.md`.

## 9. Residual Risks

- The Windows local pytest warning is still present as known environment noise.
- Legacy non-Agent modules outside `plugins/arteta_agent` still contain historical direct HTTP clients. The architecture task acceptance boundary was the Agent stack, Provider, Activation, and Agent tools.
- The local deployment archive clutter should be cleaned separately if desired; it was left untouched to avoid deleting unrelated operator artifacts.

## 10. Completion Decision

The refactor is complete and deployed. The acceptance gates for safety, correctness, architecture, performance, verification, devlog, commit discipline, ECS deployment, and smoke testing have all been satisfied for the Agent architecture task.
