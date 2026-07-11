# Agent Architecture Devlog

## 2026-07-11 - Phase A: Dynamic System Injection Closure

### Scope

- Closed the remaining dynamic `system` message injection paths found in the Agent, QQ chat, Dashboard chat, and algorithm/science fallback paths.
- Kept the phase narrow: no broad file moves and no planner architecture split in this stage.

### Changes

- Moved unavailable web verification data into a non-system `UNTRUSTED_WEB_VERIFICATION_RESULT` user data message.
- Kept forced-tool follow-up guidance as a static system instruction; the dynamic tool name is no longer interpolated into that message.
- Added static QQ and Dashboard chat system prompts. Runtime persona, current time, group/user metadata, recent group context, Chroma memory, football-news context, image/document/web/tool data, and policy snapshots are now appended as untrusted user data messages.
- Changed `/算法` and Dashboard algorithm calls to use static system prompts. Dynamic prompt overrides, subject labels, and user problems are passed as user data.
- Hardened the `pysqlite3` monkey-patch used before ChromaDB imports so incomplete fake or broken modules do not replace stdlib `sqlite3`.

### Compatibility

- Preserved `run_agent_loop` and current tool names.
- Preserved OpenAI-compatible message shape where supported.
- Preserved legacy string-return compatibility around existing tool handlers.
- Did not change ECS deployment process or model/provider configuration in this phase.

### Risk Notes

- The local branch already contained the uncommitted Agent Registry baseline before this phase. The phase commit therefore needs to preserve that baseline to remain runnable from a clean checkout.
- Windows full-suite runs still report existing asyncio/proactor unclosed transport warnings. They do not fail the suite and were present before this phase.
- `tools/verify_features.py --suite agent_loop` still has known routing/planning failures unrelated to this phase:
  - `forces_ui_preference_tool`
  - `forces_reply_body_ui_preference_tool`
  - `allows_llm_to_choose_web_verification_tool`
  - `forces_explicit_memory_tool`

### Verification

- `python -m pytest tests/test_recent_group_context.py tests/dashboard/test_bot_chat.py tests/test_arteta_chat_commands.py tests/test_arteta_memory.py tests/dashboard/test_chroma_service.py -q`
  - Result: `58 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `180 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `448 passed, 2 warnings`.
- `python tools\verify_features.py --suite chat`
  - Result: passed.

### Remaining

- Commit the verified Phase A state.
- Deploy the changed runtime files to ECS.
- Run ECS smoke checks.
- Continue with unified Runtime and `AgentState` after Phase A is deployed.

### ECS Smoke Adjustment

After the initial ECS rollout, the bot and dashboard restarted successfully and `python tools\verify_features.py --suite chat` passed on ECS. Two broader smoke cases exposed verifier issues rather than runtime regressions:

- `agent_registry/web_access_offline` was affected by live GrokSearch environment variables on ECS, so the offline fixture could route through the live Grok branch.
- `agent_registry/permission_gates` still expected the removed legacy `confirmed_tool` bypass to authorize an admin tool.

Verifier fix:

- The offline web smoke now clears GrokSearch and X-fetch environment/module configuration, including NoneBot config lookup, while it runs its fake DuckDuckGo/fetch fixture.
- The permission gate smoke now asserts unconfirmed write/admin calls are rejected and legacy `confirmed_tool` does not bypass confirmation. Confirmed execution remains covered by the pending-action executor cases.

Verification after the fix:

- `python -m pytest tests/test_verify_features.py -q`
  - Result: `7 passed`.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed locally.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `180 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `450 passed, 2 warnings`.

## 2026-07-11 - Phase B Slice: Runtime State and Loop Guard Extraction

### Scope

- Introduced the first real Agent Runtime boundary without changing the public `run_agent_loop` entrypoint.
- Kept routing, provider HTTP, behavior-policy storage, response composition, and parallel execution out of this slice.
- Migrated planner tool execution paths to Runtime where the execution semantics are already stable.

### Changes

- Added `plugins/arteta_agent/runtime/` with:
  - `AgentRunConfig` for round, tool-call, repeat-call, observation, timeout, and initial-tool-stop budgets.
  - `AgentState` / `AgentRunResult` for structured runtime state and stop reasons.
  - `LoopGuard` and canonical `tool_call_signature()` using sorted JSON arguments.
  - `AgentRuntimeRunner` for model calls, tool execution, tool observations, budget checks, timeout handling, and `PermissionRequired` stopping.
- Kept planner compatibility helpers, but routed normal model tool calls and forced tool follow-up through `AgentRuntimeRunner`.
- Routed forced direct tools such as behavior-policy updates, UI preference writes, memory preference writes, science/math tools, and trace display through Runtime initial tool calls.
- Preserved explicit PendingAction confirmation as a direct consume path because it is not a model-planned tool call and must use the stored action ID/args.
- Preserved mood emoji post-processing in planner for now; response splitting is planned for the Response phase.

### Compatibility

- `run_agent_loop` signature is unchanged.
- Existing tool names, schemas, permissions, trace output, artifact marker compatibility, and OpenAI-compatible model-call monkeypatch behavior are unchanged.
- Provider HTTP implementation remains in planner for a later provider-adapter phase.
- The old planner loop body remains as unreachable compatibility code behind an early Runtime return; it will be removed when `planner.py` is reduced in Phase I.

### Risk Notes

- This slice intentionally does not solve multi-intent routing, provider client reuse, SQLite policy migration, persistent audit completion, or parallel-safe tool execution.
- The Runtime still uses planner adapters for model calls and final mood-emoji handling, so planner is not yet a thin compatibility entrypoint.
- Windows full-suite runs still report the pre-existing asyncio/proactor unclosed transport warnings.

### Verification

- `python -m pytest tests/test_arteta_agent_runtime.py -q`
  - Result: `5 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `180 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `455 passed, 2 warnings`.

### Remaining

- Deploy this Phase B slice to ECS and run smoke checks.
- Continue Phase C by replacing mutually-exclusive forced routing with structured `RouteDecision` / multi-intent plans.
