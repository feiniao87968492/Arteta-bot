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

- Continue Phase C by replacing mutually-exclusive forced routing with structured `RouteDecision` / multi-intent plans.

### ECS Deployment

- Commit deployed: `d5b2dae refactor: introduce agent runtime state`.
- Deployment archive: `/tmp/arteta_phase_b_runtime_d5b2dae.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_b_runtime_20260711184516`.
- Remote `py_compile` passed for `planner.py` and `plugins/arteta_agent/runtime/*.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python -m pytest tests/test_arteta_agent_runtime.py -q`
  - Result: not run on ECS because the production venv does not include `pytest` (`No module named pytest`).
- Remote `py_compile` covered the deployed runtime files; local pytest remains the authoritative unit-test run for this slice.

## 2026-07-11 - Phase C Slice: Structured Routing and Multi-Intent Initial Plans

### Scope

- Added the first structured routing/planning model layer.
- Kept the existing planner forced-route chain in place for single-intent behavior.
- Only enabled the new plan path when a message produces more than one required tool, reducing regression risk.

### Changes

- Added `plugins/arteta_agent/routing/models.py` with `Intent`, `RouteDecision`, and `PlannedToolCall`.
- Added `plugins/arteta_agent/routing/heuristic_router.py` for an initial score-like heuristic router.
- Added `plugins/arteta_agent/planning/models.py` and `plan_builder.py` with `AgentPlan`.
- Added planner adapter code that converts multi-intent required tools into Runtime initial tool calls.
- Covered:
  - remember preference + document read;
  - group-memory lookup + current public fact verification;
  - non-math handling for broad numeric phrases such as date, price, and scoreline;
  - explicit equation routing to math.
- Fixed `tools/verify_features.py` agent-loop fixtures so they use strict schemas compatible with server-side argument validation instead of empty object schemas.

### Compatibility

- Existing single-tool forced routes still use their old detection path.
- Existing tool names and schemas are unchanged.
- The new router currently falls back to `grok_search` for public current football facts when used in a multi-intent plan; existing single-intent policy selection remains in planner.

### Risk Notes

- This is not the final RouteDecision rollout. Planner still contains legacy marker constants and most single-intent `if` branches.
- The new heuristic router intentionally covers only the first acceptance-critical multi-intent combinations. Broader datasets and conflict resolution remain.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `6 passed`.
- `python tools\verify_features.py --suite agent_loop`
  - Result: passed locally.
- `python -m pytest tests/test_arteta_agent_routing.py tests/test_arteta_agent_runtime.py tests/test_arteta_agent_registry.py -q`
  - Result: `191 passed, 2 warnings`.
- `python -m pytest tests/test_verify_features.py -q`
  - Result: `8 passed`.
- `python -m pytest tests -q`
  - Result: `462 passed, 2 warnings`.

### ECS Smoke

- Uploaded the `tools/verify_features.py` schema-fixture fix to ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Deployment

- Commit deployed: `a87891a feat: add structured routing plan models`.
- Deployment archive: `/tmp/arteta_phase_c_routing_a87891a.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_routing_20260711190304`.
- Remote `py_compile` passed for planner, routing, and planning modules.
- Restarted `arteta_bot` and `arteta_dashboard`.

### ECS Smoke After Routing Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### Remaining

- Expand RouteDecision coverage to the rest of the task-book samples.
- Replace single-intent `if ... return` routes with plan construction once coverage is broad enough.

## 2026-07-11 - Phase D Slice: Structured Artifact Marker Boundary

### Scope

- Began Response/Artifact split by moving artifact marker extraction out of planner into `agent/response`.
- Closed the security gap where arbitrary tool body text could forge `[GeneratedImage: ...]` style artifact markers.

### Changes

- Added `plugins/arteta_agent/response/artifacts.py`.
- Added `ToolResult.artifacts` as the structured artifact channel.
- Executor now adapts legacy artifact-marker strings into `ToolResult.artifacts` only for known artifact-producing tools:
  - render tools;
  - image generation;
  - link analysis;
  - web/grok verification tools that produce source snapshots.
- Planner artifact collection now reads `ToolResult.artifacts` instead of regexing every tool observation body.
- Added a regression test proving a normal safe-read tool can return forged artifact marker text as data without causing the final answer to include a generated artifact.

### Compatibility

- Existing artifact-producing tools can still return legacy `[RenderedImage: ...]`, `[GeneratedImage: ...]`, and `[LinkSnapshotImage: ...]` markers.
- Existing Grok/link snapshot preservation remains compatible through the executor adapter.

### Risk Notes

- This is not the full response composer split. Planner still appends artifact markers and handles mood emoji post-processing.
- The legacy adapter remains intentionally narrow until tools return fully structured `ToolResult` objects directly.

### Verification

- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_treats_forged_artifact_marker_in_safe_tool_output_as_data tests/test_arteta_agent_registry.py::test_agent_loop_preserves_grok_snapshot_artifact_from_tool_result tests/test_arteta_agent_registry.py::test_agent_loop_preserves_link_snapshot_artifact_after_model_summary -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `181 passed, 2 warnings`.
- `python -m pytest tests/test_arteta_agent_routing.py tests/test_arteta_agent_runtime.py -q`
  - Result: `11 passed`.
- `python -m pytest tests -q`
  - Result: `463 passed, 2 warnings`.

### ECS Deployment

- Commit deployed: `2071760 refactor: collect artifacts from tool results`.
- Deployment archive: `/tmp/arteta_phase_d_artifacts_2071760.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_d_artifacts_20260711190950`.
- Remote `py_compile` passed for the deployed planner, executor, result, and response artifact modules.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Artifact Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

### Remaining

- Continue the response split with a dedicated composer for confirmation, degradation, artifact appending, trace formatting, and mood emoji post-processing.
- Keep the current legacy artifact adapter narrow until tools return native structured artifacts directly.

## 2026-07-11 - Phase D Slice: Response Composer Boundary

### Scope

- Added the first dedicated response composer module.
- Moved final artifact appending and Grok trace prefixing out of planner's inline `finish()` closure.
- Kept mood emoji post-processing, confirmation prompts, and degradation copy in existing runtime/planner paths for later response slices.

### Changes

- Added `plugins/arteta_agent/response/composer.py`.
- Added `compose_final_response(...)`, `prefix_trace_markers(...)`, and `trace_has_marker(...)`.
- Planner now calls `compose_final_response(value, artifacts=tool_artifact_markers, trace=trace)` for final response assembly.
- Added `tests/test_arteta_agent_response.py` to pin the response boundary:
  - structured artifacts are appended once;
  - artifact-looking text in the answer body is treated as normal text;
  - `[grok]` prefixing comes from trace markers.

### Compatibility

- Existing `run_agent_loop` behavior is unchanged.
- Existing structured artifact markers still append to final output once.
- Existing Grok trace marker prefix behavior is preserved.
- Planner keeps thin wrapper functions for trace marker helpers to reduce churn in this slice.

### Risk Notes

- This is still not the complete response split. Planner still controls mood emoji forcing and several forced-tool/direct-return paths.
- The composer intentionally does not regex-scan arbitrary answer or tool body text for artifacts; artifacts must come from the structured list passed by runtime/planner.

### Verification

- `python -m pytest tests/test_arteta_agent_response.py -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_treats_forged_artifact_marker_in_safe_tool_output_as_data tests/test_arteta_agent_registry.py::test_agent_loop_preserves_grok_snapshot_artifact_from_tool_result tests/test_arteta_agent_registry.py::test_agent_loop_preserves_link_snapshot_artifact_after_model_summary tests/test_arteta_agent_registry.py::test_trace_records_grok_result_marker -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `181 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `466 passed, 2 warnings`.

### Remaining

- Move confirmation prompts, stable degradation text, trace block formatting entrypoints, and mood emoji post-processing behind response/runtime adapters.
- Continue keeping artifact trust boundaries structural rather than regexing arbitrary tool text.
